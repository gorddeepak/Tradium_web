# Tradium

A mock Indian-stock-trading dashboard in the style of Zerodha's Kite — paper
trading on NSE-listed equities, with live prices, an intraday/delivery order
ticket, and a Gemini-powered portfolio assistant ("Nova"). No real money, no
real orders: a full-stack playground for trading UIs and AI tool-calling.

## Stack

- **Frontend** — React 19, Vite, Tailwind CSS v4, a hand-rolled SVG chart
  library (`src/components/charts/`)
- **Backend** — FastAPI, SQLAlchemy and PostgreSQL, JWT auth in httpOnly cookies
- **AI** — Google Gemini via pydantic-ai, used for Nova (chat + tools)
  and per-page insight cards
- **Live data** — Yahoo Finance quotes and candles; prices sync to PostgreSQL
  every minute

## Getting started

Requires Node.js >= 18, Python 3.12+ and a running PostgreSQL database.

```bash
# 1. Backend (from the repo root)
cp api/.env.example api/.env   # then fill in DATABASE_URL, DIRECT_DATABASE_URL, JWT_SECRET
alembic upgrade head
.venv/Scripts/python.exe -m uvicorn api.main:app --reload --port 8000

# 2. Frontend (in a second terminal)
npm install
npm run dev             # app on http://localhost:5173
```

Set `MARKET_SYNC_ENABLED=true` in `api/.env` for local development. The
scheduler runs `market_sync` once at startup, which seeds the 53-symbol NIFTY
universe and its quotes; without it the Markets page and instrument search stay
empty until that job runs.

Then open http://localhost:5173 and sign up — you're trading paper money.

### Environment

The backend reads everything from `api/.env` — see `api/.env.example`:

| Variable | Required | Purpose |
|---|---|---|
| `DATABASE_URL` | yes | PostgreSQL connection string for the app |
| `DIRECT_DATABASE_URL` | for migrations | direct connection used by `alembic` |
| `JWT_SECRET` | yes | Signs the auth cookie's JWT |
| `GOOGLE_GENERATIVE_AI_API_KEY` | for Nova + insight cards | Gemini API key |
| `MARKET_SYNC_ENABLED` | no | Own the market-cache sync (seed + every 5 min) |
| `TRADING_JOBS_ENABLED` | no | Own price sync (every minute) + daily snapshot |
| `PORT` | no | API port (default 8000) |

The frontend needs no env file for local dev. Set `VITE_API_URL` only when
pointing a production build at a deployed backend.

## Scripts

| Where | Command | What it does |
|---|---|---|
| root | `npm run dev` | Vite dev server (port 5173) |
| root | `npm run build` | production build |
| root | `npm run lint` | ESLint |
| root | `npm run screens` | capture landing-page screenshots (needs the app running) |
| root | `alembic upgrade head` | apply PostgreSQL migrations |
| root | `python -m pytest -q` | backend tests (needs `TEST_DATABASE_URL`) |

## How trading works here

- **Products:** `CNC` (delivery) and `MIS` (intraday, squared off by day end)
- **Order types:** MARKET fills at the server-side Yahoo price; LIMIT / SL /
  SL-M rest as OPEN until the price sync crosses them
- **Funds and shares are enforced atomically** — a buy debit, a sell share
  check, and a square-off all run in one PostgreSQL transaction, so two racing
  requests can't double-spend
- **Bracket exits:** stop-loss / target orders attach to a position; settling
  one cancels its sibling automatically

## Layout

```
src/
  features/        one folder per feature (assistant, auth, dashboard, marketing)
  components/      shared UI (shadcn primitives + the chart library)
  utils/           formatters and portfolio math
api/
  routes/          one FastAPI router per resource
  postgres/        SQLAlchemy models and the session factory
  migrations/      Alembic history
  jobs/            market sync (5 min), price sync (1 min), daily snapshot (6pm IST)
  trading_book.py  the trading core (orders, positions, funds)
  assistant.py     Nova's agent, tools and Gemini model
```

`AGENTS.md` covers the same ground for AI coding assistants (conventions,
gotchas, rate-limit constraints).

## Notes

- Gemini free tier is ~500 requests/day — the app deliberately fires AI calls
  only on page visits and chat, never in polling loops
- Everything is a mock: charges shown in the order ticket are estimates
  modelled on Zerodha's published schedule, not debited anywhere
