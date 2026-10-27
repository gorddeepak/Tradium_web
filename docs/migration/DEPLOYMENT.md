# Deployment runbook — FastAPI + built frontend

**Status:** checked against the implementation in Phase 3C2-E, after the runtime became PostgreSQL-only
(§3Y), the data decision became a clean start (§3Z) and the repository gained a Render Blueprint (§3AA
in [MIGRATION_STATUS.md](./MIGRATION_STATUS.md)). Nothing here has been deployed, and the existing
Express/Render service is untouched.

The target is one service that serves the API and the Vite build from a single origin, exactly as the
Express server does today (one origin means the browser sends the auth cookie with no CORS preflight).

---

## 1. Build

Run from the repository root, before starting the API:

```bash
npm ci
npm run build          # writes dist/ (gitignored)
```

On Render the build command is one line (§7.2). It uses `npm ci --include=dev` because the service sets
`NODE_ENV=production`, which would otherwise make npm omit the devDependencies that Vite needs.

`dist/` is served by FastAPI only when static serving is enabled and `dist/index.html` exists. If the
build is missing, the server logs `Static serving is on but …/dist/index.html is missing; run npm run
build` and keeps serving the API alone (`/dashboard` then returns the JSON 404).

Python dependencies (Python 3.13 was the interpreter used for the migration):

```bash
python -m venv .venv
.venv/bin/pip install -r api/requirements.txt        # runtime
# optional, for the test suite: -r api/requirements-dev.txt (it includes the runtime file)
```

`api/requirements.txt` includes FastAPI 0.144.0, Uvicorn 0.54.0, SQLAlchemy 2.1.6, Alembic 1.20.1,
`psycopg[binary]` 3.3.6 and `pydantic-ai-slim[google]` 2.57.0.

## 2. Database: provision, migrate, then start

### 2.1 The data starts empty

This deployment is a **clean start**. PostgreSQL is the only database the app reads or writes, and it
begins with no trading data:

- Existing MongoDB users, watchlists, snapshots and trading-book rows are **not** imported. There is no
  loader, no dual write and no reconciliation.
- Users sign up fresh after cutover. Each gets an empty book and a zero balance; portfolio history shows
  the live "today" point immediately and gains a stored point each day at 18:00 IST once the snapshot job
  runs (§5).
- MongoDB stays where it is, untouched, as an archive. It is not a runtime dependency of this service.
- Preserving legacy data would be separate migration work; the design for it is
  `POSTGRES_SCHEMA_DESIGN.md` §9, which is explicitly not part of this deployment.

### 2.2 Provisioning

- Any PostgreSQL the app can reach works. The migration was developed and tested against **PostgreSQL
  17.6**; the schema uses standard types, `NUMERIC`, and check constraints (`id ~ '^[0-9a-f]{24}$'`), so an
  older supported major version is plausible but untested.
- One database, one schema. Alembic owns the schema; the app never creates tables.
- `DATABASE_URL` is the connection the running app uses; `DIRECT_DATABASE_URL` is the unpooled
  connection Alembic uses. Against a plain self-hosted PostgreSQL they are normally the same URL. With a
  pooler in front, point `DATABASE_URL` at the pooler and `DIRECT_DATABASE_URL` straight at the database.
- No PostgreSQL extensions or seed data are required: `alembic upgrade head` creates every table in the
  default schema of the database named in the URL. The market universe (53 NSE symbols) is seeded by
  `market_sync`, not by SQL.
- The repository now ships a Render Blueprint that provisions such a database next to the service (§7).
  Any other reachable PostgreSQL still works; `api/.env.example` carries comment-only placeholders.

### 2.3 Migrations (required before the first start)

Run from the repository root, with `DIRECT_DATABASE_URL` set:

```bash
DIRECT_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME' alembic upgrade head
```

- `alembic.ini` already points at `api/migrations` and adds the repo root to `sys.path`, so the command
  needs no paths.
- **`DIRECT_DATABASE_URL` is mandatory for Alembic.** It is not derived from `DATABASE_URL`: without it
  the command stops with `RuntimeError: DIRECT_DATABASE_URL is not set. Alembic needs the direct
  (non-pooled) PostgreSQL connection string.` (verified, Phase 3C2-D).
- A fresh database ends with `alembic_version = 0001` and the 10 application tables (`users`, `funds`,
  `holdings`, `positions`, `orders`, `transactions`, `watchlists`, `instruments`, `latest_quotes`,
  `portfolio_snapshots`) plus `alembic_version` (verified on a disposable 17.6 database).
- Re-run the same command for later deploys; it is idempotent up to `head`.
- On Render this is the Blueprint's `preDeployCommand`, which runs automatically after the build and
  before the new instance receives traffic (§7.4).

### 2.4 Start

```bash
uvicorn api.main:app --host 0.0.0.0 --port "$PORT"
```

- `PORT` is provided by the platform; Uvicorn reads the `--port` flag, not the environment.
- Run a **single** instance per database. The trading and market jobs are opt-in (§5); multiple stateless
  API instances are safe only while both switches are unset.
- The app opens no database connection during startup. PostgreSQL connects lazily on the first request
  that needs it, so a start with a wrong `DATABASE_URL` looks healthy until the first query.
- Health check: `GET /api/health` → `200 {"ok": true}`. It does no database, Yahoo or AI work, so it is a
  **liveness** probe only. For readiness, probe an authenticated data route — an unauthenticated request
  returns `401` regardless of the database, so it must carry a token.
- Behind a reverse proxy, make sure Uvicorn trusts its `X-Forwarded-For` (it honours the header but by
  default trusts only `127.0.0.1`/`::1`). Signup and login are rate-limited per client IP — 20 requests
  per 15 minutes — using the socket peer address, so an untrusted proxy would make every user share one
  budget. Render's Python runtime sets `FORWARDED_ALLOW_IPS=*`; the Blueprint also passes
  `--forwarded-allow-ips='*'` explicitly (§7.2).

## 3. Environment variables

Copy the shape from `api/.env.example`. The deployment environment supplies these; `api/.env` is local
development only and is never committed.

| Variable | Required | Purpose |
|---|---|---|
| `DATABASE_URL` | **yes** | PostgreSQL connection string for every read and write. Both `postgresql://…` and `postgresql+psycopg://…` work with the installed psycopg 3 driver. Missing means the first data request fails with `RuntimeError: DATABASE_URL is not set` |
| `DIRECT_DATABASE_URL` | **yes, for Alembic** | Unpooled connection used by `alembic upgrade head` only; never read by the running app |
| `JWT_SECRET` | **yes** | Signs the auth cookie's JWT. Use at least 32 bytes: PyJWT logs `InsecureKeyLengthWarning` below that. Keep it stable — changing it logs every user out |
| `NODE_ENV` | recommended | `production` is the only value that changes behaviour: sets `Secure` on the auth cookie **and** turns on static serving (matching Express) |
| `SERVE_STATIC` | optional | Explicit override for static serving. Defaults to `NODE_ENV=production`, so a local run can serve the real build without the `Secure` cookie |
| `GOOGLE_GENERATIVE_AI_API_KEY` | for Nova | Gemini key for chat, page insights and the briefing. When absent the three assistant routes answer `503` and everything else works |
| `GEMINI_MODEL` | optional | Overrides the default `gemini-3.5-flash-lite` (the model Express uses) |
| `CORS_ORIGINS` | only if split | Comma-separated browser origins allowed with credentials. **Not needed** when this service serves the frontend; set it only when the frontend is on a different origin |
| `PORT` | platform | Port passed to `uvicorn --port` |
| `MARKET_SYNC_ENABLED` | optional | Market-cache refresh owner. **Off by default**; at most one process (§5) |
| `TRADING_JOBS_ENABLED` | optional | Price sync (fills orders, moves funds) + daily snapshot owner. **Off by default**; exactly one process (§5) |

`MONGO_URL` is **not** read by this service. `TEST_MONGO_URL` is a test-only variable for the optional
real-MongoDB suite and has no place in a deployment.

### Market data provider

Quotes and candles come from Yahoo Finance's public endpoints (`query2.finance.yahoo.com` chart and quote
APIs, plus the `fc.yahoo.com` cookie and `getcrumb` handshake), the same provider the Express app uses.
**No market-data environment variable or API key exists** — only the optional `MARKET_SYNC_ENABLED`
switch. NSE symbols are mapped to Yahoo tickers by appending `.NS`; indices keep their `^` symbol.

### Frontend origin, cookies, CORS and HTTPS

- The built frontend calls a relative `/api` path (`src/services/api.js`), so requests are same-origin and
  no CORS headers are involved. `VITE_API_URL` is a **build-time** override only, for a split deployment.
- With `NODE_ENV=production` the auth cookie is `token=…; HttpOnly; Secure; SameSite=strict; Path=/;
  Max-Age=604800`, so it lasts 7 days.
- `Secure` requires **HTTPS** in a browser. Browsers treat `http://localhost` as trustworthy, so a local
  production-shaped run works; any non-localhost http:// deployment would silently lose the cookie.
- The live watchlist uses a WebSocket on `/api/watchlist/stream`. It authenticates with the same `token`
  cookie during the handshake, so a reverse proxy must forward WebSocket upgrades for that path and keep
  the cookie on the same origin.

## 4. Static serving behaviour

- Enabled by `SERVE_STATIC`, or by `NODE_ENV=production` when it is unset.
- `/assets/*` is served from `dist/assets/`; root files such as `/favicon.svg` are served as-is.
- Any other non-`/api` path returns `dist/index.html`, so client-side routes (`/dashboard`,
  `/dashboard/holdings/<symbol>`, `/login`, …) work on direct navigation and refresh.
- `/api` and `/api/*` are never served the app shell. A known route reaches FastAPI; an unknown one
  returns the JSON 404 `{"message": "Route not found"}`.
- A missing file under `/assets/` returns the JSON 404 rather than `index.html` (a deliberate, minor
  divergence from Express, which would return the shell).

## 5. Scheduler ownership

The three Express crons are ported but **opt-in**, and default to **off**:

- `MARKET_SYNC_ENABLED=true` — market-cache refresh (startup + every 5 minutes).
- `TRADING_JOBS_ENABLED=true` — `price_sync` (startup + every minute; fills crossed OPEN orders, settles
  MIS exits, moves funds) **and** the daily 18:00 IST portfolio snapshot.

Exactly **one** process may set each, because two owners would double the Yahoo traffic, both try to fill
the same orders, and duplicate work against the same tables.

**Cutover rule:** while the Express service is still deployed, leave both switches unset on the new
service; Express remains the single owner. Enable them on the FastAPI service only when Express is
stopped (or its crons are disabled), and only deliberately. After a clean-start cutover there is no data
hand-over — only who owns each job.

## 6. Local production-shaped run

```bash
npm run build
# api/.env: DATABASE_URL, JWT_SECRET, GOOGLE_GENERATIVE_AI_API_KEY
DIRECT_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:5432/tradium alembic upgrade head
SERVE_STATIC=true uvicorn api.main:app --host 127.0.0.1 --port 8000
# open http://localhost:8000
```

Add `NODE_ENV=production` to also exercise the `Secure` cookie (works on `http://localhost`; use HTTPS
elsewhere). Phase 3C2-D verified this shape with `NODE_ENV=production`, no `MONGO_URL` and no `dist/`:
health, signup, funds, holdings, orders, portfolio history, watchlist and market overview all answered
`200`. Phase 3C2-E repeated it with a real `dist/`, the Render start flags and a plain `postgresql://`
URL, and also exercised `/dashboard`, a hashed asset and the watchlist WebSocket (§3AA in the status
document).

## 7. Render deployment (`render.yaml`)

The repository root now carries a Render Blueprint. Build, migration and start commands live in Git
instead of the dashboard, and one Python service plus one PostgreSQL database are defined together.

### 7.1 What the Blueprint creates

| Resource | Settings | Why |
|---|---|---|
| Web service `tradium-fastapi` | Python runtime, `0.5c-512mb`, `oregon`, one instance | Paid instance so `preDeployCommand` is available; no idle spin-down, which would stop the schedulers and drop WebSocket connections |
| Database `tradium-postgres` | `0.1c-256mb`, PostgreSQL 17, `oregon`, database `tradium` | Same region as the service, so the private-network URL works; paid so it does not expire after 30 days |

Both resource names are new. **Do not reuse the existing Express service's name**: Render applies a
Blueprint to an existing resource with the same name instead of creating a second one, which would
reconfigure the live Express service.

`region: oregon` is Render's default. Change both entries together before the first deploy if a
different region is wanted; a region cannot be changed after creation.

### 7.2 Build, migrate, start

| Step | Command |
|---|---|
| Build | `npm ci --include=dev && npm run build && pip install -r api/requirements.txt` |
| Pre-deploy | `alembic upgrade head` |
| Start | `uvicorn api.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips='*'` |
| Health check | `/api/health` |

- `--include=dev` is required: the service sets `NODE_ENV=production`, and `npm ci` otherwise omits
  devDependencies, including Vite.
- The build runs from the repository root, so `dist/` exists in the deploy image and the same service
  serves it (§7.5).
- `preDeployCommand` runs after the build and before the new instance receives traffic; a failure cancels
  the deploy and the previous version keeps serving. It requires a **paid** instance type.
- The start command binds to `$PORT` (Render's default is `10000`). Uvicorn reads the flag, not the
  environment.
- Render's Python runtime sets `FORWARDED_ALLOW_IPS=*`; the explicit flag keeps the requirement visible
  in the Blueprint and is what makes the auth limiter see real client IPs (§2.4).

### 7.3 Database and connection strings

- `DATABASE_URL` and `DIRECT_DATABASE_URL` both reference the database's `connectionString`: the
  **internal** URL, `postgresql://USER:PASSWORD@INTERNAL_HOST:PORT/DATABASE`. It is reachable only from a
  Render service in the same account and region, which is why both resources share `oregon`.
- `connectionString` is the direct connection; `connectionPoolString` is the pooled one. Pooling is not
  enabled, so both variables point at the same direct URL and Alembic never runs through a pooler.
- The URL uses the plain `postgresql://` scheme. SQLAlchemy 2.1.6 resolves that to the installed
  **psycopg 3** driver, so no `+psycopg` suffix is needed (verified against a disposable database with
  both Alembic and the running app). A hand-written `postgresql+psycopg://` URL is equivalent.
- The app connects lazily, so the first request after a deploy is the first database connection. A wrong
  URL therefore looks healthy until then (§2.4).

### 7.4 Migrations

- On the paid instance the Blueprint runs `alembic upgrade head` before each deploy. It is idempotent
  (revision `0001` is the only one) and the deploy is cancelled if it fails.
- `DIRECT_DATABASE_URL` is supplied explicitly from the database; it is never derived from
  `DATABASE_URL` (§2.3).
- Do **not** put `alembic upgrade head` in `startCommand`: it would run on every restart, and a second
  instance could race the first.
- On the **free** plan `preDeployCommand` is unsupported. Run the migration manually from a machine that
  can reach the database's **external** URL, then deploy:

  ```bash
  DIRECT_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@EXTERNAL_HOST:5432/tradium?sslmode=require' \
    alembic upgrade head
  ```

  Repeat before every deploy that contains a migration. Free Postgres also expires 30 days after
  creation, has no backups and is capped at 1 GB of storage, so it is a demo target only.

### 7.5 Frontend, HTTPS, cookies and WebSockets

- The same service serves the SPA. `NODE_ENV=production` (and the explicit `SERVE_STATIC=true`) turns on
  the static mount, and `dist/index.html` exists after the build. `/` and client routes such as
  `/dashboard` return the shell; `/assets/*` returns the hashed files (§4).
- Render terminates TLS and redirects HTTP to HTTPS, so the `Secure` auth cookie and `SameSite=strict`
  work. The frontend calls the relative `/api` path, so the cookie and the API share one origin and no
  CORS headers are involved.
- The watchlist WebSocket connects to `wss://<service-host>/api/watchlist/stream` (derived from the page
  origin), carrying the same `token` cookie on the handshake. Render proxies WebSocket upgrades on the
  service's single port with no extra configuration and imposes no fixed connection timeout.
- `CORS_ORIGINS` stays unset. It is only needed if the frontend moves to a different origin, in which
  case `VITE_API_URL` must also be set at build time (§3).

### 7.6 Schedulers

The Blueprint sets `MARKET_SYNC_ENABLED` and `TRADING_JOBS_ENABLED` to `"false"`, matching the code
default (§5). `numInstances: 1` keeps one owner when they are turned on, but a zero-downtime deploy
briefly runs the old and new instances together. Enable each switch deliberately, and keep the instance
count at one.

### 7.7 Manual dashboard steps

1. Push the branch to a Git provider (the repository still has no remote) and grant Render access to it.
2. In Render: **New > Blueprint**, choose the repository, then the branch that contains `render.yaml`.
3. Review the two resources. Change `region` in both entries before the first deploy if needed; it cannot
   be changed afterwards.
4. Enter `GOOGLE_GENERATIVE_AI_API_KEY` when prompted. Leaving it empty is allowed; Nova then answers
   `503` while the rest of the app works.
5. Click **Deploy Blueprint**. The first deploy runs the build, then the migration, then the start
   command.
6. Open `https://<service>.onrender.com/api/health` (expect `{"ok":true}`), then the root URL, and sign up
   with a fresh account — legacy MongoDB users do not exist here (§2.1).
7. Optional custom domain: **Settings > Custom Domains**, add the domain, create the CNAME it shows and
   wait for Render's certificate. No application setting changes: the frontend is same-origin and the
   WebSocket derives `wss://` from the page.
8. To enable the jobs, wait until the Express crons are stopped, set the switches in the dashboard (or in
   `render.yaml`) and redeploy (§5).

## 8. Rollback

The Express/Render service and the MongoDB archive are not modified by this migration. To roll back,
stop the FastAPI service and point traffic back at the existing Express service; if the FastAPI service
had been made the scheduler owner, turn its switches off and re-enable Express first so job ownership is
never lost. PostgreSQL data written after the cutover is not copied back to MongoDB — it is simply
abandoned.

## 9. Known blockers and limitations

- No deployment has been performed: this is documentation and locally verified code only.
- The Blueprint is ready but unapplied. The repository still has no Git remote, so the branch and
  `render.yaml` are local-only (see [MIGRATION_STATUS.md](./MIGRATION_STATUS.md) §6.1).
- `render.yaml` was checked locally against Render's published Blueprint fields and plan IDs; it was not
  checked with the Render CLI, which is not installed here and needs a Render account.
- The selected plan is paid (`0.5c-512mb`). The free plan cannot run `preDeployCommand`, spins down after
  15 idle minutes and expires its Postgres after 30 days, so it is only a demo path (§7.4).
- HTTPS is required before any non-localhost deployment, because the production auth cookie is `Secure`.
  Render supplies it, but a custom domain must have its certificate issued first.
- The health check is liveness only: it passes while PostgreSQL is unreachable. It is not a readiness
  probe.
- Auth rate limiting (20 signup/login attempts per 15 minutes) lives in process memory, so it is per
  worker and resets on restart — it is not shared across instances (§2.4).
- The app is a single writer per database once either scheduler switch is on (§5, §7.6).
- A missing file under `/assets/` returns a JSON 404 instead of the app shell — a deliberate, minor
  divergence from Express (§4).
- Legacy MongoDB data stays an archive; nobody will see their old rows after cutover (§2.1).
