# Architecture

Tradium is a single-origin web application. FastAPI serves the JSON API and, in
production, the built React frontend. PostgreSQL is the only database. Yahoo
Finance supplies market data, and Google Gemini powers Nova and the page
insights.

```
Browser
  |  HTTP /api/*, WebSocket /api/*/stream
  v
FastAPI (one process)
  |-- React build (dist/)
  |-- routers, trading book, background jobs
  |-- PostgreSQL (SQLAlchemy + Alembic)
  |-- Yahoo Finance REST + optional live stream
  `-- Gemini (Nova chat, insights, briefing)
```

## Frontend

The React app is organised by feature under `src/features/`:

- `auth/` — login, signup and the auth context.
- `dashboard/` — dashboard shell, pages, tables, hooks and the quote store.
- `assistant/` — Nova's chat panel and per-page insight cards.
- `marketing/` — the public landing page.

Shared UI primitives live in `src/components/ui/`, charts in
`src/components/charts/`, formatters and portfolio helpers in
`src/utils/tradiumUtils.jsx`, and every API call in `src/services/api.js`.
`BASE_URL` and the WebSocket URLs are exported there so no component hardcodes
an origin.

Pages read REST data on mount. Live quotes then overlay the cached rows through
`src/features/dashboard/quotes/QuoteContext.jsx`, which owns one browser socket
per dashboard and merges prices by provider time. REST polling remains the
fallback when the live feed is disabled or disconnected.

## Backend

`api/main.py` creates the app, mounts one router per resource under `/api`,
starts the enabled schedulers in the lifespan, serves the React build with an
SPA fallback, and reproduces the JSON error envelope the frontend expects.

| Module | Responsibility |
|---|---|
| `api/routes/` | Auth, holdings, positions, orders, funds, portfolio, watchlist, instruments, market, quotes and assistant endpoints |
| `api/trading_book.py` | Funds, holdings, positions, orders and transactions in PostgreSQL |
| `api/order_engine.py` | Fills, exits, bracket orders and square-off |
| `api/portfolio_math.py` | Shared portfolio summary and day-change math |
| `api/market_data.py` | Yahoo quotes, candles, profiles and provider backoff |
| `api/market_store.py` | Instrument and quote persistence and reads |
| `api/jobs/` | Market sync, price sync and the daily portfolio snapshot |
| `api/assistant.py` | Nova's agent, tools and Gemini model |
| `api/postgres/` | SQLAlchemy models and the session factory |

## Database

Alembic migrations under `api/migrations/` are the schema source of truth. The
tables are:

| Table | Contents |
|---|---|
| `users` | Accounts and password hashes |
| `funds` | Per-user cash balance |
| `holdings` | Delivery positions |
| `positions` | Open intraday positions |
| `orders` | Open, filled, cancelled and rejected orders |
| `transactions` | Funds ledger |
| `watchlists` | Per-user symbols |
| `instruments` | Symbol, name, exchange, kind, sector and universe membership |
| `latest_quotes` | Latest persisted price and provider time per instrument |
| `portfolio_snapshots` | One portfolio total per user per IST day |

Financial writes run in PostgreSQL transactions with a per-user advisory lock
and row locks. A buy debit, sell share check, fill, refund and square-off
cannot partially apply or double-book.

## Authentication

Signup and login issue a JWT in an `HttpOnly`, `SameSite=Strict` cookie. Every
protected route resolves the user from that cookie. Passwords use bcrypt, auth
routes are rate-limited in process, and the cookie is marked `Secure` in
production.

## Market data

- `market_sync` runs at startup and every five minutes. It seeds the 53-symbol
  NIFTY universe independently of the provider, then refreshes quotes.
- `price_sync` runs every minute, updates holding, position and watchlist
  prices, and fills crossed orders only when the provider time is fresh.
- `latest_quotes` is the canonical cache. A provider failure keeps the last
  good quote; missing prices stay missing rather than becoming zero.
- Yahoo `429` responses start a shared cooldown that backs off from one minute
  to fifteen minutes and honours `Retry-After`.
- The optional live feed streams the same universe over
  `/api/quotes/stream`; see [LIVE_MARKET_PRICES.md](./LIVE_MARKET_PRICES.md).

## Tests

Backend tests use `pytest` and need `TEST_DATABASE_URL` pointing at a
disposable PostgreSQL database. Frontend quote-merge rules run with
`npm run test:quotes`; the rest of the frontend is verified with `npm run lint`
and `npm run build`. Deployment is covered in [DEPLOYMENT.md](./DEPLOYMENT.md).
