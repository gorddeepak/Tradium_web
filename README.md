# Tradium

A mock Indian-stock-trading dashboard in the style of Zerodha's Kite — paper
trading on NSE-listed equities, with live prices, an intraday/delivery order
ticket, and a Gemini-powered portfolio assistant ("Nova"). No real money, no
real orders: a full-stack playground for MERN + AI tool-calling.

## Stack

- **Frontend** — React 19, Vite, Tailwind CSS v4, a hand-rolled SVG chart
  library (`src/components/charts/`)
- **Backend** — Express 5, MongoDB (Mongoose), JWT auth in httpOnly cookies
- **AI** — Google Gemini via the Vercel AI SDK, used for Nova (chat + tools)
  and per-page insight cards
- **Live data** — yahoo-finance2 for quotes and candles; prices sync to the DB
  every 5 minutes

## Getting started

Requires Node.js >= 18 and a running MongoDB instance.

```bash
# 1. Backend
cd server
npm install
cp .env.example .env    # then fill in MONGO_URL, JWT_SECRET, GOOGLE_GENERATIVE_AI_API_KEY
npm run seed            # optional: demo account (demo@tradium.local) with sample data
npm start               # API on http://localhost:3002

# 2. Frontend (in a second terminal, from the repo root)
npm install
npm run dev             # app on http://localhost:5173
```

Then open http://localhost:5173, sign up (or log in as the demo account), and
you're trading paper money.

### Environment

The backend reads everything from `server/.env` — see `server/.env.example`:

| Variable | Required | Purpose |
|---|---|---|
| `MONGO_URL` | yes | MongoDB connection string (server exits without it) |
| `JWT_SECRET` | yes | Signs the auth cookie's JWT |
| `GOOGLE_GENERATIVE_AI_API_KEY` | for Nova + insight cards | Gemini API key |
| `PORT` | no | API port (default 3002) |

The frontend needs no env file for local dev. Set `VITE_API_URL` only when
pointing a production build at a deployed backend.

## Scripts

| Where | Command | What it does |
|---|---|---|
| root | `npm run dev` | Vite dev server (port 5173) |
| root | `npm run build` | production build |
| root | `npm run lint` | ESLint |
| server | `npm start` | backend with nodemon (port 3002) |
| server | `npm run seed` | reset/create the demo account |
| server | `npm run backfill` | backfill portfolio history snapshots |

## How trading works here

- **Products:** `CNC` (delivery) and `MIS` (intraday, squared off by day end)
- **Order types:** MARKET fills at the server-side Yahoo price; LIMIT / SL /
  SL-M rest as OPEN until the 5-minute price sync crosses them
- **Funds and shares are enforced atomically** — a buy debit, a sell share
  check, and a square-off all use guarded MongoDB writes so two racing
  requests can't double-spend
- **Bracket exits:** stop-loss / target orders attach to a position; settling
  one cancels its sibling automatically

## Layout

```
src/
  features/        one folder per feature (assistant, auth, dashboard, marketing)
  components/      shared UI (shadcn primitives + the chart library)
  utils/           formatters and portfolio math
server/
  routes/          one Express router per resource
  controllers/     auth, assistant (AI tools), insights
  models/          one Mongoose model per file
  jobs/            price sync (5 min) + daily portfolio snapshot (6pm IST)
  utils/           executeOrder (the trading core), portfolio math
```

`AGENTS.md` covers the same ground for AI coding assistants (conventions,
gotchas, rate-limit constraints).

## Notes

- Gemini free tier is ~500 requests/day — the app deliberately fires AI calls
  only on page visits and chat, never in polling loops
- Everything is a mock: charges shown in the order ticket are estimates
  modelled on Zerodha's published schedule, not debited anywhere
