# Deployment runbook — FastAPI + built frontend

**Status:** Phase 4a prepared this runbook and the code it describes; Phase 4b re-checked every claim
here against the implementation and added the operational notes below. Nothing here has been deployed,
and the existing Express/Render service is untouched. See
[MIGRATION_STATUS.md](./MIGRATION_STATUS.md) §3N and §3O for what was actually verified.

The target is one service that serves the API and the Vite build from a single origin, exactly as the
Express server does today (one origin means the browser sends the auth cookie with no CORS preflight).

---

## 1. Build

Run from the repository root, before starting the API:

```bash
npm ci
npm run build          # writes dist/ (gitignored)
```

`dist/` is served by FastAPI only when static serving is enabled and `dist/index.html` exists. If the
build is missing, the server logs a warning and keeps serving the API alone.

## 2. Start

```bash
uvicorn api.main:app --host 0.0.0.0 --port "$PORT"
```

- `PORT` is provided by the platform (defaults to `8000` for local runs).
- Install Python dependencies into a virtualenv first. Runtime: `pip install -r api/requirements.txt`.
  For the test suite as well: `pip install -r api/requirements-dev.txt` (it includes the runtime file).
- **Python 3.13** is the interpreter the migration was built and tested on (`pydantic-ai-slim==2.57.0`,
  FastAPI 0.144.0, Uvicorn 0.54.0). The platform must provide a compatible modern interpreter.
- Run a **single** instance per database. Trading and market jobs are opt-in (§4), so multiple
  stateless API instances are safe **only while both job switches are unset**.
- Health check: `GET /api/health` → `200 {"ok": true}`. It does no database or Yahoo work.
- **Mongo is connected lazily.** The app starts and the health check answers `200` even when MongoDB is
  unreachable; the failure appears on the first data request. Use a data-touching readiness probe (for
  example a request to an authenticated route) if a database outage must fail the check.

## 3. Environment variables

Copy the shape from `api/.env.example`. The deployment environment supplies these; `api/.env` is for
local development and is never committed.

| Variable | Required | Purpose |
|---|---|---|
| `MONGO_URL` | **yes** | MongoDB connection string; the server cannot serve data without it |
| `JWT_SECRET` | **yes** | Signs the auth cookie's JWT. Must match the value the currently deployed service uses so existing login cookies stay valid during the cutover |
| `NODE_ENV` | recommended | `production` is the only value that changes behaviour: sets `Secure` on the auth cookie **and** turns on static serving (matching Express) |
| `SERVE_STATIC` | optional | Explicit override for static serving. Defaults to `NODE_ENV=production`. Lets a local run serve the real build without the `Secure` cookie |
| `GOOGLE_GENERATIVE_AI_API_KEY` | for Nova | Gemini key for chat, page insights and the briefing. When absent, the three assistant routes answer `503` and the rest of the app works |
| `GEMINI_MODEL` | optional | Overrides the default `gemini-3.5-flash-lite` (the model Express uses) |
| `CORS_ORIGINS` | only if split | Comma-separated browser origins allowed with credentials. **Not needed** when this service serves the frontend itself; set it only when the frontend is on a different origin |
| `PORT` | platform | Port for the server |
| `MARKET_SYNC_ENABLED` | optional | Market-cache refresh owner. **Off by default**; at most one process |
| `TRADING_JOBS_ENABLED` | optional | Price sync (fills orders, moves funds) + daily snapshot owner. **Off by default**; exactly one process |

### Production cookie and same-origin behaviour

- With `NODE_ENV=production`, `Set-Cookie` includes `Secure; HttpOnly; SameSite=strict; Path=/;
  Max-Age=604800`. Over a real HTTPS deployment the browser stores and returns it normally.
- The built frontend calls the API with a relative `/api` path (`src/services/api.js`), so requests are
  same-origin and no CORS headers are involved.
- `Secure` requires HTTPS in a browser. Browsers treat `http://localhost` as trustworthy, so the
  production cookie was verified in a browser locally; a non-localhost http:// deployment would lose
  the cookie until HTTPS is in front of it.

## 4. Scheduler ownership

The three Express crons are ported but **opt-in**, and default to **off**:

- `MARKET_SYNC_ENABLED=true` — market-cache refresh (startup + every 5 minutes).
- `TRADING_JOBS_ENABLED=true` — `priceSync` (startup + every minute; fills crossed OPEN orders, settles
  MIS exits, moves funds) **and** the daily 18:00 IST portfolio snapshot.

Exactly **one** process may set each, because two owners would double the Yahoo traffic, both try to
fill the same orders, and write duplicate work against the same collections.

**Cutover rule:** while the Express service is still deployed, leave both switches unset on the new
service; Express remains the single owner. Enable them on the FastAPI service only when Express is
stopped (or its crons are disabled), and only deliberately.

## 5. Static serving behaviour

- Enabled by `SERVE_STATIC`, or by `NODE_ENV=production` when it is unset.
- `/assets/*` is served from `dist/assets/`; root files such as `/favicon.svg` are served as-is.
- Any other non-`/api` path returns `dist/index.html`, so client-side routes (`/dashboard`,
  `/dashboard/holdings/<symbol>`, `/login`, …) work on direct navigation and refresh.
- `/api` and `/api/*` are never served the app shell. A known route reaches FastAPI; an unknown one
  returns the JSON 404 `{"message": "Route not found"}`.
- A missing file under `/assets/` returns the JSON 404 rather than `index.html` (a deliberate, minor
  divergence from Express, which would return the shell).

## 6. Local production-shaped run

```bash
npm run build
# api/.env: MONGO_URL, JWT_SECRET, GOOGLE_GENERATIVE_AI_API_KEY
SERVE_STATIC=true uvicorn api.main:app --host 127.0.0.1 --port 8000
# open http://localhost:8000
```

Add `NODE_ENV=production` to also exercise the `Secure` cookie (works on `http://localhost`; use HTTPS
elsewhere).

## 7. Rollback

The Express/Render service is not modified by this migration. To roll back, stop the FastAPI service
and point DNS/traffic back at the existing service; if the FastAPI service had been made the scheduler
owner, turn its switches off and re-enable Express first so job ownership is never lost.

## 8. Known blockers and limitations

- No deployment has been performed: this is documentation and locally verified code only.
- The repository still has no Git remote and `gh` is not installed, so the branch is local-only (see
  [MIGRATION_STATUS.md](./MIGRATION_STATUS.md) §6.1 for the publication steps).
- HTTPS is required before any non-localhost deployment, because the production auth cookie is
  `Secure`.
- The health check is liveness only: it passes while MongoDB is unreachable (§2). It is not a
  readiness probe.
- A missing file under `/assets/` returns a JSON 404 instead of the app shell — a deliberate, minor
  divergence from Express (§5).
- Multiple API instances must not each run the schedulers: at most one process may set each of
  `MARKET_SYNC_ENABLED` and `TRADING_JOBS_ENABLED` (§4).
