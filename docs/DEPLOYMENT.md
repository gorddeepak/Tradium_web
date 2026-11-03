# Deploying Tradium

Tradium is a mock stock-trading dashboard for NSE equities. This guide takes a
copy of the repository from GitHub to a working public deployment on Render,
backed by a Neon PostgreSQL database.

The deployment is one web service. It builds the React frontend, runs the
FastAPI backend, and serves both from the same origin. Neon hosts the only
database, and all market data comes from Yahoo Finance at runtime.

## 1. Project overview

| Part | What it does |
|---|---|
| Web app | Login, dashboard, holdings, positions, orders, watchlist, charts and the Nova assistant |
| API | Authentication, trading book, portfolio reads, watchlist, quotes and AI routes under `/api` |
| Database | Users, funds, holdings, positions, orders, transactions, watchlists, instruments, latest quotes and portfolio snapshots |
| Background jobs | Market cache refresh, price sync with order fills, daily portfolio snapshot |
| Live feed | Optional Yahoo quote stream pushed to authenticated browsers over WebSockets |

The React build is served by FastAPI in production, so the browser talks to one
origin. The auth cookie and WebSockets work without CORS configuration.

## 2. Technology stack

| Layer | Technology |
|---|---|
| Frontend | React 19, Vite, Tailwind CSS v4 |
| Backend | FastAPI 0.144, Uvicorn, Python 3.13 |
| Database access | SQLAlchemy 2.1 and psycopg 3 |
| Schema migrations | Alembic 1.20 |
| Database | PostgreSQL on Neon |
| Hosting | Render web service |
| Market data | Yahoo Finance REST endpoints and an optional WebSocket stream |
| AI | Google Gemini through pydantic-ai, optional |

## 3. Prerequisites

- A GitHub account with the repository pushed to it.
- A [Neon](https://neon.tech) account.
- A [Render](https://render.com) account connected to GitHub.
- Node.js 18 or newer.
- Python 3.12 or newer. The repository pins 3.13 in `.python-version`, which
  Render reads automatically.
- Git, and a local clone if you want to run migrations by hand.
- Optional: a Google Gemini API key for Nova.

The build expects `package-lock.json` to be committed, because it uses
`npm ci`.

## 4. Neon PostgreSQL setup

1. Sign in to Neon and create a project. Pick the region closest to your Render
   region; Oregon is the default in `render.yaml`.
2. Create a database and role, or use the ones Neon creates with the project.
3. Open **Connection Details** and copy both connection strings.
4. Keep the `?sslmode=require` suffix on both URLs.

| String | Host | Used by |
|---|---|---|
| Pooled | Contains `-pooler` | The FastAPI app for all normal reads and writes |
| Direct | No `-pooler` | Alembic, for `alembic upgrade head` |

Both strings look like this:

```text
postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require
```

`DATABASE_URL` takes the pooled string and `DIRECT_DATABASE_URL` takes the
direct one. Migrations must not run through the pooler. The app reads
`DATABASE_URL` lazily, so nothing connects until the first request that needs
the database.

## 5. Render deployment

The repository contains `render.yaml`, a Render Blueprint that describes the
service. Render reads it from the branch you deploy.

| Setting | Value |
|---|---|
| Service name | `tradium-fastapi` |
| Runtime | Python |
| Region | `oregon` |
| Plan | `0.5c-512mb` |
| Instances | 1 |
| Health check | `/api/health` |

The service runs three commands:

```bash
# Build
npm ci --include=dev && npm run build && pip install -r api/requirements.txt

# Pre-deploy
alembic upgrade head

# Start
uvicorn api.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips='*'
```

- `--include=dev` keeps Vite installed even though `NODE_ENV=production` is set.
- The pre-deploy command creates or updates the database schema before the new
  instance receives traffic. If it fails, the deploy is cancelled and the
  previous version keeps running.
- The start command binds to the port Render provides and trusts Render's proxy
  headers, so rate limiting sees the real client IP.
- A paid instance is required for pre-deploy commands. It also avoids idle
  spin-down, which would stop the schedulers and drop WebSocket connections.

To deploy:

1. Push the repository to GitHub, with `main` containing `render.yaml`.
2. In Render, choose **New > Blueprint** and select the repository.
3. Review the service and confirm the region before the first deploy. The
   region cannot be changed later.
4. Enter the values listed in section 6 when prompted.
5. Click **Deploy Blueprint**.

Keep `numInstances: 1`. The background jobs and the live quote feed assume a
single process owns them.

## 6. Environment variables

`render.yaml` sets the non-secret values. Render prompts for the rest during
the first deploy and stores them outside Git.

| Variable | Source | Purpose |
|---|---|---|
| `DATABASE_URL` | You, from Neon | Pooled connection used by the app. Required |
| `DIRECT_DATABASE_URL` | You, from Neon | Direct connection used by Alembic. Required for migrations |
| `JWT_SECRET` | Render | Signs the auth cookie. Render generates it; changing it logs everyone out |
| `GOOGLE_GENERATIVE_AI_API_KEY` | You, optional | Enables Nova and the insight cards. Without it those routes return `503` and the rest of the app works |
| `NODE_ENV` | Blueprint | `production`. Sets `Secure` on the auth cookie |
| `SERVE_STATIC` | Blueprint | `true`. Serves the Vite build from `dist/` |
| `LIVE_QUOTES_ENABLED` | Blueprint | `true`. Opens the Yahoo quote stream |
| `LIVE_QUOTES_FLUSH_SECONDS` | Blueprint | `5`. How often live ticks are written to PostgreSQL |
| `LIVE_QUOTES_STALE_SECONDS` | Blueprint | `60`. Age at which a quote is marked stale |
| `MARKET_SYNC_ENABLED` | Blueprint | `true`. Owns the market cache refresh |
| `TRADING_JOBS_ENABLED` | Blueprint | `true`. Owns the price sync and daily snapshot |

Two settings are optional and normally left unset:

- `GEMINI_MODEL` overrides the default model `gemini-3.5-flash-lite`.
- `CORS_ORIGINS` is only needed if the frontend is served from a different
  origin. The bundled deployment does not need it.

Locally, the backend reads `api/.env`. Copy `api/.env.example`, fill in the
values, and never commit that file.

## 7. Database setup and Alembic migrations

A new Neon database is empty. Alembic creates the entire schema:

```bash
alembic upgrade head
```

On Render this runs automatically as the pre-deploy command. To run it by hand
from your machine:

```bash
DIRECT_DATABASE_URL='postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require' \
  alembic upgrade head
```

Use the direct Neon URL, not the pooled one. Alembic reads only
`DIRECT_DATABASE_URL` and stops with a clear error if it is missing.

The first migration creates:

```text
users  funds  holdings  positions  orders  transactions
watchlists  instruments  latest_quotes  portfolio_snapshots
```

It also creates `alembic_version`, which records the current revision. Running
the command again is safe; a database already at `head` is left unchanged.

After the first deploy, a new database has the schema but no users. Sign up
through the app to create an account with an empty book and a zero balance.

Two rules:

- Never place `alembic upgrade head` in the start command. It would run on
  every restart.
- Never point Alembic at the pooled URL. Some poolers cannot run the DDL a
  migration needs.

## 8. Background jobs and live market prices

Three jobs run inside the web process, each guarded by a switch.

| Job | Schedule | Switch | Work |
|---|---|---|---|
| Market sync | At startup, then every 5 minutes | `MARKET_SYNC_ENABLED` | Refreshes the 53-symbol NIFTY universe and its quotes. Seeds a new database |
| Price sync | At startup, then every minute | `TRADING_JOBS_ENABLED` | Refreshes quotes, fills crossed limit and stop orders, settles intraday exits, moves funds. Runs only during market hours |
| Portfolio snapshot | Daily at 18:00 IST | `TRADING_JOBS_ENABLED` | Stores one portfolio value point per user |

Market hours are 09:15 to 15:30 IST on weekdays. There is no holiday calendar;
outside those hours Yahoo returns the last close.

Both switches are `true` in `render.yaml`. They belong to one process, so the
service must stay at one instance. Two instances would fetch the same quotes
twice, race on the same rows, and try to fill the same orders.

The live quote feed is also owned by that one process:

- `LIVE_QUOTES_ENABLED=true` opens one Yahoo WebSocket for the 53 tracked
  symbols.
- Ticks reach the browser immediately on `/api/quotes/stream`. Pending ticks
  are written to `latest_quotes` every `LIVE_QUOTES_FLUSH_SECONDS`.
- A quote older than `LIVE_QUOTES_STALE_SECONDS` is shown as stale, and an
  older tick is rejected.
- The watchlist page uses `/api/watchlist/stream` for the same data. Both
  sockets authenticate with the `token` cookie during the handshake.
- When the stream is unavailable or disabled, prices still update through the
  scheduled REST sync.

Yahoo's streamer is an unofficial endpoint. Treat it as best-effort and follow
the provider note in
[LIVE_MARKET_PRICES.md](./migration/LIVE_MARKET_PRICES.md) before relying on it
publicly.

## 9. Domain and HTTPS

Render serves the app on `https://<service-name>.onrender.com` with a valid
certificate. To use your own domain:

1. Open the service in Render and go to **Settings > Custom Domains**.
2. Add the domain and copy the CNAME record Render shows.
3. Create that record at your DNS provider.
4. Wait for Render to issue the certificate. HTTPS is enabled automatically.

No application setting changes. The frontend calls relative `/api` paths, and
the WebSockets derive `wss://` from the page origin. Because `NODE_ENV` is
`production`, the auth cookie is `Secure` and `SameSite=strict`, so the app must
be reached over HTTPS outside `localhost`.

## 10. Deployment verification

Work through this list after the first deploy and after any change that touches
configuration.

| Check | Expected result |
|---|---|
| `https://<service>/api/health` | `{"ok":true}` |
| Deploy log | Build, pre-deploy migration and start all succeeded |
| Root URL | The landing page loads |
| Sign up | A new account is created and the dashboard opens |
| Holdings, positions, orders | Pages load with an empty book and zero balance |
| Markets page | Instruments and quotes appear within a few minutes |
| Watchlist | Updates without a full page reload, and the stream connects |
| Live prices | The header shows a live indicator during market hours |
| Nova | Chat and insight cards work when the Gemini key is set |
| Restart | The service restarts and the same account can still log in |

`/api/health` is a liveness check only. It does not touch the database, Yahoo
or Gemini, so also open a data page to confirm the database connection.

Check the deploy log if the app loads but data is missing. The application logs
a warning when a job switch is unset or the frontend build is missing.

## 11. Troubleshooting and rollback

| Symptom | Likely cause | Fix |
|---|---|---|
| Pre-deploy fails with `DIRECT_DATABASE_URL is not set` | The variable is missing | Add the direct Neon URL in Render and redeploy |
| First data request fails, health still returns OK | Wrong `DATABASE_URL` or the database is unreachable | Re-copy the pooled URL, keep `?sslmode=require` |
| Pooler errors about prepared statements | The pooler rejects the statement cache | Use the direct Neon URL for `DATABASE_URL`, or keep the app on one instance |
| Pages return JSON 404 | The frontend build was not produced or static serving is off | Check for `dist/index.html` in the build log and confirm `SERVE_STATIC=true` |
| Markets page stays empty | The market cache was never seeded | Confirm `MARKET_SYNC_ENABLED=true`, then check the job log |
| Orders never fill | Price sync is not running or the market is closed | Confirm `TRADING_JOBS_ENABLED=true` and check the time in IST |
| Live prices never arrive | The optional feed is off or the vendor is unreachable | Check `LIVE_QUOTES_ENABLED`; the REST sync still updates prices |
| Nova answers `503` | No Gemini key | Add `GOOGLE_GENERATIVE_AI_API_KEY` and redeploy |
| Login fails only in production | The cookie is `Secure` but the app is on HTTP | Use the HTTPS URL, including for custom domains |
| Signup or login returns `429` | More than 20 attempts in 15 minutes from one IP | Wait for the window to reset |
| Everyone is logged out after a deploy | `JWT_SECRET` changed | Keep the generated value stable |

To roll back:

1. In Render, open the service and redeploy the previous successful deploy, or
   revert the offending commit on `main` and let Render rebuild.
2. Keep the instance count at one during and after the rollback.
3. Do not edit or delete applied migrations. Alembic migrations run forward
   only; if a migration must be undone, add a new revision that reverses it.
4. If data is damaged, restore a Neon branch or backup, then redeploy the code
   version that matches that schema.

A failed pre-deploy never replaces the running version, so most configuration
mistakes only need a corrected environment variable and another deploy.
