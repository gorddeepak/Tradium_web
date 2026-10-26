# Express parity harness (read-only)

Focused, isolated harnesses that compare the **original Express backend** with this FastAPI port.
They were built for the focused parity check described in `docs/migration/MIGRATION_STATUS.md` §3K and
`docs/migration/TEST_PLAN.md` §1K.

## What makes this safe

- **`server/index.js` is never loaded**, so no cron job, market sync, AI call or scheduler is started.
  Only the smallest modules are imported (`routes/authRoutes`, `routes/holdingsRoutes`,
  `jobs/priceSync`, `jobs/portfolioSnapshot`), and the two provider seams `priceSync` reaches for
  (`yahoo-finance2` and `utils/marketHours`) are replaced in the module loader before it is required.
- **Only scratch databases are touched** (`tradium_parity_*`), each dropped before and after the run.
  No production database and no development database is read or written.
- **The original checkout is read-only.** These scripts `require` files from it and never write.

## Requirements

- Node.js >= 18 and the dependency tree of the **original** checkout: this repository's `server/`
  copy has no `node_modules`, so point `ZERODHA_SERVER` at the original `server/` directory
  (default: `../../Zerodha/server` relative to this repository).
- A local MongoDB on `127.0.0.1:27017` (override with `PARITY_MONGO`).
- The FastAPI virtualenv, so `api` imports resolve.

> These scripts are inert unless run by hand, and they must never be pointed at a running
> production server. Set `ZERODHA_SERVER` explicitly; do not rely on the default in CI.

## Run

Run every command from this directory (`tools/express-parity`). Captures go to `out/` by default.

```bash
# 0. configuration (PowerShell: $env:NAME="value")
export PARITY_MONGO=mongodb://127.0.0.1:27017
export ZERODHA_SERVER=../../Zerodha/server          # the ORIGINAL checkout, read-only

# 1. authentication: cookie attributes, logout clearing, JWT payload
node express_auth.cjs
python fastapi_auth.py

# 2. numeric serialization through the real GET /api/holdings route
node express_numbers.cjs
python fastapi_numbers.py

# 3. background jobs: priceSync side effects
node express_jobs.cjs
python fastapi_jobs.py

# 4. read-route bodies: orders, watchlist, positions, funds, funds/transactions,
#    market/overview, instruments/search
node express_routes.cjs
python fastapi_routes.py

# 5. diff the results
python compare.py
```

`python` means the repository's virtualenv (`.venv\Scripts\python.exe` on Windows), so that `api`
imports resolve. Set `PARITY_OUT_DIR` only to redirect the captures.

`compare.py` prints, per collection, the documents that exist on only one side, and a per-field BSON
type map. `RESULT: equivalent - no functional difference observed` means the two implementations
produced the same documents with the same values; `[informational]` lines are differences no client can
observe (a JSON number spelling, a header attribute).

## Files

| File | Purpose |
|---|---|
| `scenario.json` | the shared synthetic input for the job run (users, holdings, positions, watchlists, orders, funds, quotes, sectors) |
| `express_auth.cjs` | boots only `routes/authRoutes` on an ephemeral port and records every `Set-Cookie` |
| `fastapi_auth.py` | the same request sequence against `create_app(database=...)` |
| `express_numbers.cjs` | serves the real `GET /api/holdings` and captures the raw JSON body |
| `fastapi_numbers.py` | the same, over the real FastAPI route |
| `express_jobs.cjs` | seeds `scenario.json`, runs `syncPrices()`, dumps every collection with BSON types preserved |
| `fastapi_jobs.py` | the same, through `sync_prices()` |
| `routes_scenario.json` | the shared synthetic input for the read-route run (users, holdings, positions, watchlists, orders, funds, transactions, snapshots, quotes) |
| `express_routes.cjs` | serves the real orders/watchlist/positions/funds/market/instrument routers on an ephemeral port and captures each GET body |
| `fastapi_routes.py` | the same requests against `create_app(database=...)` |
| `compare.py` | diffs the job dumps, the auth/number captures and the read-route bodies |

## Notes

- The Node harnesses are `.cjs` because the repository root `package.json` sets `"type": "module"`;
  they are CommonJS by design (they `require` the original checkout's modules).
- BSON numeric **types** are compared, not just values: whole-valued numbers are `int32` when a
  JavaScript `number` is written but `double` when a Python `float` is. That is the class of
  difference this harness exists to find.
- `createdAt`/`updatedAt` are normalised away (they are wall-clock), and ObjectIds that were not
  seeded are normalised to `<oid>`. Seeded ids are kept, so cross-collection references are compared.
- `_id` and `__v` are **not** normalised away, so the write shapes are still checked.
- The route harness deliberately does **not** call the Yahoo-backed instrument routes
  (`/lookup/:symbol`, `/:symbol`, `/:symbol/candles`), so the whole run stays offline.
- **Portfolio snapshots are no longer compared.** Since Phase 3C1 the daily snapshot writes PostgreSQL
  `portfolio_snapshots`, so `record_daily_snapshot()` is not run here (it would write to the configured
  PostgreSQL database) and `/api/portfolio/history` is not in the route list (its historical points now
  come from PostgreSQL, not the scratch MongoDB). Both are covered by `api/tests/test_portfolio_snapshot.py`
  and `api/tests/test_portfolio.py`.
