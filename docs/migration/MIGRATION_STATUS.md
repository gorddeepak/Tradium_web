# Migration Status

**Last updated:** 2026-10-27 (Phase 3C-F)
**Current phase:** **Phase 3C-F — legacy Express/MongoDB cleanup**
**Application code modified:** **Yes, up to Phase 3C-F** (3C2-D changed documentation only; 3C-E added
deployment configuration, `.python-version` and documentation; 3C-F removed the unused Express backend,
its parity harness, the `pymongo` dependency and other verified-unused code).
Phase 3B1 moved authentication to PostgreSQL; Phase 3B2 moved the market cache there and made
`price_sync` a dual writer; Phase 3B3 moved watchlists there and made the daily snapshot enumerate users
from PostgreSQL; Phase 3B3.1 moved price sync and Nova's watchlist tool onto the same table; Phase 3C1
moved the snapshot rows and the historical half of `/api/portfolio/history` there; Phase 3C2 moved the
whole trading book (funds, holdings, positions, orders, transactions) and tied the write flows to it;
Phase 3C2-B moved the last book readers (the live history point, the snapshot job, Nova's five book tools);
Phase 3C2-C merged the watchlist WebSocket branch and deleted the MongoDB runtime. Every FastAPI surface
is now PostgreSQL-backed, the runtime needs no MongoDB, the 3C2-D decision is a clean start on
an empty database (§3Z), 3C-E adds the Render Blueprint that deploys it (§3AA), and 3C-F removes the
unused Express reference and MongoDB dependency from the active repository (§3AB). The original
repository remains untouched.
**Phase 0 docs commit:** `629af4d Phase 0: migration docs and repository guidance`
(`migration/fastapi-backend`, local only — not pushed; see §6.1)

---

## 1. Current state at a glance

| Item | Value |
|---|---|
| Phase | 3C-F — legacy cleanup: Express backend and parity harness removed, MongoDB dependency dropped |
| FastAPI application | **started** — the 13 read routes, the 7 write routes, the 4 auth routes and the 3 assistant routes (27 registered operations), plus the optional static mount and SPA fallback |
| PostgreSQL schema | **created by Alembic** — `api/migrations/versions/0001_initial_schema.py` creates all 10 tables (`users`, `funds`, `holdings`, `positions`, `orders`, `transactions`, `watchlists`, `instruments`, `latest_quotes`, `portfolio_snapshots`) plus `alembic_version`; verified by `alembic upgrade head` on a disposable PostgreSQL 17.6 cluster |
| PostgreSQL-backed surfaces | **authentication** (`users`, Phase 3B1), the **market cache** (`instruments`/`latest_quotes`, Phase 3B2), **watchlists** (Phase 3B3), **price sync's watchlist symbols** (Phase 3B3.1), **Nova's `getWatchlist`** (Phase 3B3.1), **portfolio snapshots** (`portfolio_snapshots`, Phase 3C1), the **whole trading book** (`funds`, `holdings`, `positions`, `orders`, `transactions`, Phase 3C2) and its **remaining readers** — the live portfolio point, the daily snapshot's book read and Nova's five book tools (Phase 3C2-B) |
| MongoDB-backed surfaces | **none — the FastAPI runtime no longer touches MongoDB at all.** Phase 3C2-C removed `api/db.py`, the `db.connect()`/`db.close()` startup wiring, `app.state.db`, the unused scheduler `db` parameters and the insight/briefing `db` dependencies; `MONGO_URL` is no longer a setting. Phase 3C-F removed the Express reference (`server/`), the parity harness and the `pymongo` dependency, so no tracked code uses MongoDB |
| Market cache | `instruments` + `latest_quotes` in PostgreSQL; market sync seeds the **53-symbol universe**; scheduler **off unless `MARKET_SYNC_ENABLED` is set** |
| Trading jobs | per-minute `price_sync` (fills orders, settles MIS exits, upserts the canonical PostgreSQL quote and reads watchlist symbols from PostgreSQL) and the daily 18:00 IST snapshot, which enumerates users from PostgreSQL, reads holdings/positions from PostgreSQL and upserts `portfolio_snapshots` in PostgreSQL; **off unless `TRADING_JOBS_ENABLED` is set** |
| Legacy data decision | **clean start (Phase 3C-D).** PostgreSQL begins empty: existing MongoDB users, watchlists, snapshots and trading-book records do **not** carry over, users create fresh accounts, and the MongoDB data stays in place as an untouched archive. No loader, dual write or reconciliation is planned; preserving legacy data would be separate, later migration work. Portfolio history therefore shows the live "today" point from day one and gains stored points only after cutover |
| Express backend | **removed from the active tree (Phase 3C-F)** — `server/` and `tools/express-parity/` deleted; Git history keeps the reference. The deployed Express/Render service is untouched |
| Frontend | **switched** to FastAPI on `localhost:8000`; a production build is now **served by FastAPI** (SPA fallback) when `SERVE_STATIC`/`NODE_ENV=production`; `VITE_API_URL` still overrides |
| CORS | Vite dev origins (5173-5177) with credentials; `CORS_ORIGINS` overrides for deployed origins; a same-origin production build needs neither |
| Development MongoDB | **not used.** The gitignored `api/.env` has no `MONGO_URL` setting, and Phase 3C-F removed the last code that read one |
| Development PostgreSQL | whatever `DATABASE_URL` names — a local database such as `tradium`; `DIRECT_DATABASE_URL` is read only by Alembic |
| Test MongoDB | **none.** Phase 3C-F removed `test_mongo_integration.py`'s MongoDB half (the PostgreSQL tests live on as `test_postgres_integration.py`) and the `pymongo` dependency |
| Test PostgreSQL | a guarded disposable `*_test` database named by `TEST_DATABASE_URL`; the suite runs `alembic upgrade head` and skips when it is unset |
| Production MongoDB | never contacted; no data copied |
| Production PostgreSQL | never contacted; no data copied, no data loader written |
| New repository path | `D:\deepak\coding\Full Stack Dev\Tradium-FastAPI` |
| Intended GitHub repository | `tradium-fastapi` (private) |
| GitHub push | **BLOCKED** — no `gh` CLI and no authenticated remote |
| Branch for migration work | `migration/fastapi-backend` (base); the release candidate is `phase3c2-final-cutover`, local only |
| Source snapshot | `23099b7 single service deployment - Express serves the built frontend` |
| Original repository | `D:\deepak\coding\Full Stack Dev\Zerodha` — untouched |
| Production (Render) | untouched; the Blueprint is prepared but **not applied**, and no service, branch or environment variable was changed |
| Render deployment config | `render.yaml` (one Python web service + one PostgreSQL database, same region) and `.python-version`; pre-deploy `alembic upgrade head`, same-origin static serving, schedulers off, secrets generated or entered in the dashboard (§3AA) |
| Tests executed | **403 passed, 0 skipped** with only `TEST_DATABASE_URL` (2026-10-27, Phase 3C-F). The MongoDB-only tests and the unused stream decoder's 17 tests were removed with their code; `test_postgres_integration.py` now runs in the normal suite — see §5 |
| PostgreSQL test instance | PostgreSQL 17.6, local cluster on `127.0.0.1:5433`, database `tradium_final_cutover_test`; scoped to this run and outside the repository |
| Express parity check | **run (Phase 2e)** — cookies, numeric rendering and the non-snapshot job side effects; **no functional difference** (§3K). The harness itself was removed in Phase 3C-F |
| Read-route parity check | **run (Phase 4b)** — byte-identical for the Mongo-backed read routes at the time; **not rerun since the PostgreSQL moves** (§3Q). The harness itself was removed in Phase 3C-F |
| Repository secret scan | **clean (Phase 4b/3B2)** — no credentials, API keys, private keys or `.env` files in tracked files; the PostgreSQL docs contain placeholders only |
| Browser cutover check | **run** — signup, login, reload, logout and all six dashboard pages against a live FastAPI server (§3L) |
| Nova browser check | **run** — dashboard briefing, a page insight, and chat with one- and two-tool turns against live Gemini (§3M) |
| Production static check | **run** — the built SPA served by FastAPI: deep links, refresh, assets, login, same-origin API, Nova, and the `Secure` cookie (§3N) |

---

## 2. Repository isolation — what was done

1. Verified the original repository before copying:
   - root: `D:/deepak/coding/Full Stack Dev/Zerodha`
   - branch: `main`
   - HEAD: `23099b7 single service deployment - Express serves the built frontend`
   - remote: `origin https://github.com/gorddeepak/Tradium.git` (fetch and push)
   - working tree: clean; 177 tracked files
   - the only untracked file of consequence was `server/.env` (real secrets, deliberately excluded)
2. Created the sibling directory `Tradium-FastAPI` (it did not exist).
3. Exported the committed snapshot with `git archive ... HEAD`, which excludes `.git`, untracked
   files, `node_modules`, and build output by construction.
4. Verified the copy contains exactly 177 files and only `server/.env.example` among env files.
5. Scanned tracked files for secret patterns: **none found**.
6. `git init -b main`, then committed the snapshot as the baseline:

   ```
   1979884 Initial snapshot of Tradium source at 23099b7
   ```

7. Created `migration/fastapi-backend` from that commit.
8. No remote was added. **The new repository has no connection to the original.**

### Deliberately not copied

| Excluded | Why |
|---|---|
| `.git/` | the new project must have an independent history |
| `server/.env` | contains real secrets |
| `node_modules/`, `dist/` | generated artifacts |

### `CLAUDE.md` and `.gitignore`

The copied `.gitignore` ignores `CLAUDE.md` (the original project chose not to ship it). Photo-copying
that rule would silently exclude the required `CLAUDE.md` deliverable, so it must be staged with
`git add -f CLAUDE.md` and that exception documented here. The ignore rule itself was **not** modified
— changing it is a separate decision.

---

## 3. Documents created in Phase 0

| File | Purpose |
|---|---|
| `CLAUDE.md` | instructions for future sessions in this repository |
| `docs/migration/MIGRATION_PLAN.md` | phases, gates, acceptance criteria, rollback |
| `docs/migration/CURRENT_ARCHITECTURE.md` | verified description of the Express/Mongo/React system |
| `docs/migration/API_CONTRACTS.md` | every endpoint, field names, status codes, side effects |
| `docs/migration/ARCHITECTURE_DECISIONS.md` | approved directions + validation flags + open questions |
| `docs/migration/TEST_PLAN.md` | what must be verified, with honest status values |
| `docs/migration/AI_INTEGRATION_PLAN.md` | Nova/Gemini/Vercel AI SDK details and Python plan |
| `docs/migration/MARKET_DATA_PLAN.md` | every market-data consumer and the `yfinance` investigation |
| `docs/migration/MIGRATION_STATUS.md` | this file |

No existing source file was edited, added to, or removed beyond these documents.

---

## 3A. Phase 1a — files created

New files only; nothing below `server/` or `src/` was edited.

| File | Purpose |
|---|---|
| `api/main.py` | app factory, lifespan, Express-shaped error envelope, routers |
| `api/config.py` | env-backed settings (`MONGO_URL`, `JWT_SECRET`, `HOST`, `PORT`) |
| `api/db.py` | one PyMongo client, database injection for tests |
| `api/auth.py` | `token` cookie → `jwt.decode` (HS256) → user id |
| `api/serialization.py` | ObjectId → hex, datetime → `...mmmZ` UTC |
| `api/routes/health.py` | `GET /api/health` → `{ ok: true }` |
| `api/routes/holdings.py` | `GET /api/holdings`, filtered by the token's user |
| `api/requirements.txt`, `api/requirements-dev.txt` | runtime and test dependencies |
| `api/.env.example` | required variables, with a dedicated-test-DB note |
| `api/tests/` | `conftest.py` plus 5 test modules |
| `pytest.ini` | `testpaths = api/tests`, `pythonpath = .` |

Dependencies: `fastapi 0.144.0`, `uvicorn 0.54.0`, `pymongo 4.19.0`, `PyJWT 2.15.1`,
`python-dotenv 1.2.4`; dev: `pytest 9.1.1`, `httpx 0.28.1`, `mongomock 4.3.0`.
Installed in a repository-local `.venv` (gitignored), not system-wide.

Absent at the end of Phase 1a: orders, funds, jobs, Yahoo/market data, Nova, any route beyond health
and holdings, any frontend change, any deployment change. No scheduled job was enabled.

---

## 3B. Phase 1b — files created

| File | Purpose |
|---|---|
| `api/routes/orders.py` | `GET /api/orders`: `find({user})` then `sort({createdAt: -1})` |
| `api/routes/watchlist.py` | `GET /api/watchlist`: `find({user})`, natural order |
| `api/tests/test_orders.py` | isolation, newest-first ordering, 20-key shape, empty list |
| `api/tests/test_watchlist.py` | isolation, 10-key shape, empty list |
| `api/main.py` (edited) | registers the two new routers |
| `api/tests/conftest.py` (edited) | adds `orders_factory`, `watchlist_factory` |
| `api/tests/test_mongo_integration.py` (edited) | real-MongoDB read of `orders` and `watchlists` |

Collections queried: `orders` and `watchlists`, both confirmed present in the local database's
collection metadata before the code was written.

Still absent: the order write routes (`POST /api/orders`, `POST /api/orders/exits`,
`DELETE /api/orders/:id`), the watchlist write routes, funds, positions, jobs, Yahoo/market data,
Nova, and any frontend or deployment change.

---

## 3C. Phase 1c — local development database and positions/funds reads

### Development database

| Item | Value |
|---|---|
| Development connection string | `mongodb://127.0.0.1:27017/tradium_fastapi_dev` |
| Effective database name | **`tradium_fastapi_dev`** |
| Where it is configured | gitignored `api/.env` (`MONGO_URL`), loaded explicitly by `api/config.py` |
| Connection mode | local `mongod` on `127.0.0.1:27017` |
| Test database | `mongomock` (fast suite) and `tradium_fastapi_phase1_test` (guarded integration suite) |

`api/config.py` now loads `api/.env` by absolute path instead of relying on python-dotenv's
caller-directory search, which silently searched the working directory in some launch modes.
`override=False` keeps real environment variables (a deployment's) ahead of the file. There is no
Atlas or other remote fallback: without `MONGO_URL` the app still raises `RuntimeError`.

The URI carries the database name, so there is no separate database-name setting to adapt.

### Files

| File | Purpose |
|---|---|
| `api/routes/positions.py` | `GET /api/positions`: `find({user})`, natural order |
| `api/routes/funds.py` | `GET /api/funds`: `derivedFunds` port (creates an empty funds row on first read) |
| `api/tests/test_positions.py` | isolation, 13-key shape, empty list |
| `api/tests/test_funds.py` | derived maths, first-read creation, isolation |
| `api/config.py` (edited) | explicit `api/.env` load |
| `api/.env.example` (edited) | documents the local dev URI and the test-database rule |
| `api/main.py` (edited) | registers the two new routers |
| `api/tests/conftest.py` (edited) | adds `positions_factory` |
| `api/tests/test_mongo_integration.py` (edited) | real-MongoDB read for positions + funds |

Collections queried: `positions`, `funds`, `orders`, `transactions` (funds reads four). All were
already present in the local collection metadata.

Not ported at the time: `GET /api/funds/transactions` (the other funds read), all write routes, jobs,
market data, and Nova. `GET /api/funds/transactions` was ported in Phase 1d (§3D).

---

## 3D. Phase 1d — remaining read endpoints

All new code is under `api/`; `server/`, `src/`, and the original repository are untouched.

| File | Purpose |
|---|---|
| `api/routes/funds.py` (edited) | adds `GET /api/funds/transactions`: `find({user}).sort({createdAt: -1})` |
| `api/routes/portfolio.py` | `GET /api/portfolio/history`: snapshot window, IST labels, MIS live point |
| `api/routes/instruments.py` | `GET /api/instruments/search`: regex over the local quote cache |
| `api/routes/market.py` | `GET /api/market/overview`: cached indices + stocks + `asOf` |
| `api/tests/test_funds.py` (edited) | transaction ordering, isolation, shape, empty list |
| `api/tests/test_portfolio.py` | live point, ascending snapshots, legacy `invested: null`, today overwrite, range fallback |
| `api/tests/test_instruments.py` | symbol/name match, renamed keys, empty query, limit 10 + literal regex |
| `api/tests/test_market.py` | index order, cold cache, `asOf`, row key set |
| `api/main.py` (edited) | registers the three new routers |
| `api/tests/conftest.py` (edited) | adds `market_quote_factory` |
| `api/tests/test_mongo_integration.py` (edited) | real-MongoDB read of `portfoliosnapshots`, `marketquotes`, `transactions` |

Collections queried: `transactions`, `portfoliosnapshots`, `holdings`, `positions`, `marketquotes`.
All were already present in the local collection metadata.

**Decision (labels):** `GET /api/portfolio/history` formats its `label` field with the IST calendar
day (`UTC+05:30`). The Express code used `toLocaleDateString("en-CA")`, i.e. the server's local zone;
`API_CONTRACTS` §0.5 states business-day logic uses IST and the snapshot job stores IST days at UTC
midnight. IST reproduces the Express output for the intended environment and is deterministic.

**Deferred (not ported):** the live-Yahoo instrument routes `GET /api/instruments/lookup/:symbol`,
`GET /api/instruments/:symbol`, and `GET /api/instruments/:symbol/candles`. They require a market-data
provider (Yahoo Finance), which is a separate phase (see `MARKET_DATA_PLAN.md`). `GET /api/portfolio`
also has no other read route — `/history` is the only one. Write routes, order execution, jobs, and
Nova remain out of scope.

---

## 3E. Phase 1e — write endpoints

All new code is under `api/`; `server/`, `src/`, and the original repository are untouched. The Express
business rules are ported as-is: ownership checks, order states, cash blocks, the atomic merge of a
second fill, refunds on cancel, the OCO cancellation of sibling exits, and the exact error strings.

### Routes ported

| Method | Route | Express source |
|---|---|---|
| `POST` | `/api/watchlist` | `watchlistRoutes.js` — symbol regex, duplicate guard, create |
| `DELETE` | `/api/watchlist/:id` | `watchlistRoutes.js` — always 204 |
| `POST` | `/api/funds/transactions` | `fundsRoutes.js` — deposit upsert / atomic withdrawal guard |
| `POST` | `/api/orders` | `ordersRoutes.js` — validation, cash block, holdings check, create |
| `POST` | `/api/orders/exits` | `ordersRoutes.js` — resolve the book, replace the old pair |
| `DELETE` | `/api/orders/:id` | `ordersRoutes.js` — claim-and-cancel with refund |
| `POST` | `/api/positions/:id/square-off` | `positionsRoutes.js` — live/`ltp` exit, release, ledger, closing order |

### Files

| File | Purpose |
|---|---|
| `api/routes/watchlist.py` (edited) | adds `POST /api/watchlist` and `DELETE /api/watchlist/:id` |
| `api/routes/funds.py` (edited) | adds `POST /api/funds/transactions` |
| `api/routes/orders.py` (edited) | adds `POST /api/orders`, `POST /api/orders/exits`, `DELETE /api/orders/:id` |
| `api/routes/positions.py` (edited) | adds `POST /api/positions/:id/square-off` |
| `api/order_engine.py` | port of `server/utils/executeOrder.js`: `apply_fill`, `create_exit_pair`, `spawn_bracket_exits`, `cancel_sibling_exits` (the atomic `$set` pipeline merge for a second fill) |
| `api/market_data.py` | the provider seam (`fetch_quote`); the market-data phase fills it in |
| `api/documents.py` | `new_document` (Mongoose `createdAt`/`updatedAt`/`__v`) and `inc_funds` (upserted `$inc`) |
| `api/js_compat.py` | JavaScript number rules: `Number()` coercion, `Number(x) || 0`, Indian money grouping |
| `api/tests/test_watchlist.py`, `test_funds.py`, `test_orders.py`, `test_positions.py` (edited) | the focused write tests |
| `api/tests/conftest.py` (edited) | adds `funds_factory` |
| `api/tests/test_mongo_integration.py` (edited) | one real-MongoDB write flow incl. the merge pipeline |

### Deferred dependency: the market-data provider

`market_data.fetch_quote` returns `None` because Yahoo Finance (`server/jobs/priceSync.js`) is a
separate phase. That is exactly the "provider returned no price" branch the Express code already
handles, so it is ported rather than faked:

- `POST /api/orders` with `type: "MARKET"` answers 503
  `"No live price available for <symbol>, try again in a moment"` — no order, no debit. LIMIT/SL/SL-M
  placement is independent of the provider and works now.
- `POST /api/positions/:id/square-off` falls back to the stored `ltp`, which is the documented Express
  fallback when `quote()` fails.

No price is fabricated, and no external trading or brokerage side effect is invoked anywhere. The
identical `apply_fill` logic *is* ported (it is required by `POST /api/orders/exits` and by a filling
MARKET order) and is exercised in tests by injecting a quote through the seam.

*Updated in Phase 2a (§3G):* `fetch_quote` still returns `None`, so all of the above is unchanged.
Only `fetch_candles` was added to the module, so historical candles no longer wait on this phase —
the quote-dependent behaviour above still does.

### Behaviour notes

- **Mongoose validators are not re-implemented.** The routes perform the same *explicit* checks Express
  performs and return the same 400/404/409/503 messages. Mongoose-only failures (a missing `name`, a
  non-`NSE` `exchange` enum, a non-String value on a String path) would be a 500 in Express; here a
  non-string `symbol` is accepted and stored as given. The React client always sends the typed fields.
- **Numeric rendering. Resolved in Phase 2e (§3K).** JavaScript has one number type and
  `JSON.stringify(2500.0)` is `"2500"`, so a whole float renders as `2500` in Express and as `2500.0`
  here. Measured on the same stored document: `JSON.parse` maps both to the same IEEE-754 double, so no
  client can observe the difference. **Cosmetic; `to_json_value` left unchanged.** The one behavioural
  edge — a non-finite value renders as `null` in Express but raises in Starlette — is unreachable
  through any write path (see §3K).
- Known issue #4 in §4 (debit before a holdings check) is reproduced, not fixed.

---

## 3F. Phase 1f — authentication

All new code is under `api/`; `server/`, `src/`, and the original repository are untouched. The Express
request/response contracts, password verification, JWT payload, cookie attributes and error envelopes
are preserved as-is.

### Routes ported

| Method | Route | Express source |
|---|---|---|
| `POST` | `/api/auth/signup` | `authController.js` — ordered validation, duplicate checks, bcrypt hash, 201 |
| `POST` | `/api/auth/login` | `authController.js` — `comparePassword`, one 401 message for both failure modes |
| `POST` | `/api/auth/logout` | `authController.js` — `clearCookie`, 200 |
| `GET` | `/api/auth/me` | `authController.js` — `findById(id).select("-password")`, 404 when gone |

### Files

| File | Purpose |
|---|---|
| `api/routes/auth.py` | the four endpoints; `COOKIE_*` options; the controller's own 500 envelope |
| `api/auth.py` (edited) | adds `create_token` (HS256 `{ id, iat, exp }`, 7 days), `hash_password`, `verify_password` beside `require_user` |
| `api/rate_limit.py` | `FixedWindowLimiter` + `AuthRateLimitMiddleware`, port of the express-rate-limit mount |
| `api/config.py` (edited) | adds `node_env` (`NODE_ENV`), which drives the cookie's `Secure` flag |
| `api/main.py` (edited) | registers the auth router, adds the rate-limit middleware, passes `HTTPException` headers through the error envelope |
| `api/requirements.txt` (edited) | adds `bcrypt==5.0.0` |
| `api/tests/test_auth_routes.py` | 25 focused tests for the four endpoints, bcrypt and the limiter |
| `api/tests/test_mongo_integration.py` (edited) | real-MongoDB signup → cookie → login → `/me` round-trip |

Collection used: `users` (already present in the local collection metadata).

### Behaviour notes

- **Passwords.** `bcrypt` at cost 10, the same cost as the User model's pre-save hook, and the same
  `$2b$` format. Cross-implementation verification was **run**, not assumed: a hash generated by the
  npm `bcrypt` package verifies in Python, and a Python-generated hash verifies in Node. The password
  is truncated to bcrypt's 72-byte input limit, which is what Node's `bcrypt` does silently.
- **Tokens.** `{ id, iat, exp }` signed HS256 with `JWT_SECRET`, `exp - iat = 604800` — the same
  payload `jsonwebtoken` produces for `expiresIn: "7d"`. Tokens issued here satisfy the existing
  `require_user` dependency, which is proved by taking a signup cookie through `GET /api/holdings`.
- **Cookie.** `HttpOnly`, `SameSite=Strict`, `Path=/`, `Max-Age=604800`, `Secure` only when
  `NODE_ENV=production`; logout clears it with `Max-Age=0`. Attribute *ordering* and the case of the
  `SameSite` value differ from Express's serializer, which RFC 6265 makes meaningless.
- **Rate limiting.** 20 requests per 15 minutes per client IP on signup and login only — one shared
  limiter, as in Express — with draft-7 `RateLimit-Policy`/`RateLimit` headers, `Retry-After` on the
  429, and the same body text. Implemented as ASGI middleware because Express sets those headers on
  every guarded response, including the 400s, while a FastAPI dependency's `Response` is discarded
  when a handler raises.
- **The auth 500 envelope.** The controller catches its own errors and answers
  `{ message: "Server error", error: <raw> }`, which differs from the central handler's
  `{ message: "Something went wrong" }`. Reproduced for all three handlers that had a `catch`. The
  `error` *text* is driver-specific (Mongoose's CastError sentence vs bson's `InvalidId` sentence).
- **`NODE_ENV` drives the cookie's `Secure` flag** through `get_settings()` at request time. Express
  reads it once at import; since the variable does not change during a process the observable behaviour
  is the same, and reading it per request makes the production branch directly testable.

### Not done in this phase

- No CORS middleware. Express enables credentialed CORS for `localhost:5173–5177`; here the frontend
  is still not pointed at FastAPI, so the browser integration is deliberately deferred with it.
- No frontend change. A pre-existing frontend defect was found and **not** fixed: `Signup.jsx` calls
  `signup(form.name, form.email, form.password)` while `AuthContext.signup(formData)` accepts a single
  argument, and the form field is `name` rather than the API's `username`. The FastAPI route preserves
  the Express contract (`username`, `email`, `password`); the frontend signup path is broken against
  both backends and is out of scope for this phase.
- No Nova/Gemini work, no market data, no jobs.

---

## 3G. Phase 2a — historical candles

**Goal:** port `GET /api/instruments/:symbol/candles` and nothing else. No WebSocket work, no quote
cache, no lookup/detail routes, no change to any quote-dependent trading path.

### Provider decision

`yfinance` was evaluated first, as `MARKET_DATA_PLAN.md` §3.1 planned. It works — all eight ranges
return data for both an Indian equity (`RELIANCE.NS`) and an index (`^NSEI`) — but for five of the
eight ranges it returns a **different series** from the one Express serves:

| `range` | interval | divergence |
|---|---|---|
| `1D` / `5D` / `6M` | `1m` / `5m` / `60m` | none — identical bars and values |
| `SPARK` / `1Y` | `1d` | `time` shifted by 33,300 s: yfinance labels a daily bar at exchange midnight, Yahoo at the session open |
| `1M` | `30m` | timestamps 900 s earlier *and* different OHLC — different bucketing, not a relabelling |
| `5Y` / `ALL` | `1wk` / `1mo` | one bar short — the in-progress final period is dropped |

Both symbols showed every divergence. Because the daily shift would move the candle chart's x-axis
onto the previous day and `1M` prices would simply differ, using yfinance would have meant
post-processing its output to reconstruct Yahoo's own bar boundaries. Measured results are in
`MARKET_DATA_PLAN.md` §3.1.

**Decision:** call the endpoint that `yahoo-finance2`'s `chart()` reads, directly, with `requests`.
Same endpoint and same parameters as Express, so the bars match by construction; no pandas, no numpy.
`requests==2.34.2` is the only new runtime dependency.

### Routes ported

| Route | Notes |
|---|---|
| `GET /api/instruments/{symbol}/candles` | query `range` (default `1M`); `exchange` is accepted and ignored, as Express does |

### Files

- `api/market_data.py` — **extended.** `fetch_candles`, `ticker_for`, `CANDLE_RANGES`,
  `_request_chart`, `_candles_from_payload`, and the `MarketDataError` type. `fetch_quote` still
  returns `None`, so MARKET orders and square-off behave exactly as in Phase 1e.
- `api/routes/instruments.py` — the candles route added; `GET /api/instruments/search` untouched.
- `api/tests/test_instrument_candles.py` — **new**, 23 tests, none of which touch the network.
- `api/requirements.txt` — added `requests==2.34.2`.
- `docs/migration/MARKET_DATA_PLAN.md` — §3.1 rewritten with the decision and the measurements.
- `docs/migration/TEST_PLAN.md` — §1G.
- `docs/migration/MIGRATION_STATUS.md` — this section.

### Behaviour notes

- **The request parameters are the library's, not the route's.** `instrumentRoutes.js` passes only
  `period1` and `interval`, so `yahoo-finance2`'s defaults supply the rest:
  `includePrePost=true`, `useYfid=true`, `events=div|split|earn`, `lang=en-US`. `includePrePost=true`
  is load-bearing — with `false`, the `^NSEI` intraday series came back one bar longer than the
  library's. Reproducing the library's exact query made all 16 comparisons agree.
- **`time` is the bar's UTC epoch + 19800.** `meta.gmtoffset` is 19800 for these symbols, so Express's
  fixed +5:30 shift is the bar's IST wall-clock. Unchanged.
- **A range with no bars is `200 []`, not a 404** — that is what `res.json([])` produces. A provider
  error object, a missing result, a non-2xx response and a non-JSON body all become the single
  `404 {"message": "Could not fetch candle data"}` Express uses for every failure, an unknown symbol
  included.
- **Two additions Express does not have**, neither of which changes the bars: a browser
  `User-Agent` (Yahoo rejects some clients without one) and a 20 s request timeout (Express has none
  and would hold the request open).
- **Yahoo's intraday retention is inherited, not corrected.** `1D` asks for 3 days of 1-minute bars
  and receives one session; `5D` asks for 5 and receives three. Express behaves the same way.
- **No caching**, matching Express: every request is a live call.
- **The known numeric-rendering item is now reachable here too.** A whole float — a close of `1209.0`,
  for instance — is rendered `1209.0` where JS `JSON.stringify` writes `1209`. Closed in §3K: both parse
  to the same double, so it is cosmetic.

### Verification

- `yahoo-finance2` was installed in a scratch directory **outside this repository**, its outgoing
  chart URL was captured by wrapping `fetch`, and its `chart()` result was mapped with the exact code
  from `server/routes/instrumentRoutes.js`. Compared against `api.market_data.fetch_candles`:
  **16 / 16 identical** — 2 symbols × 8 ranges, matching bar count, first and last `time`, and first
  and last OHLC.
- A live smoke run through the real application (real network, real route, `mongomock` database)
  returned 246 bars for `RELIANCE 1M`, 375 for `^NSEI 1D` and 5 for `^NSEI SPARK`; an unknown symbol
  returned 404 `{"message": "Could not fetch candle data"}` and a missing cookie returned 401.
- The evaluated dependency was then uninstalled and the suite re-run, so `requirements.txt` is
  demonstrably sufficient: `pip check` reports no broken requirements and all tests pass without
  yfinance, pandas or numpy present.

### Not done in this phase

- No WebSocket or streaming work in this phase; streaming was evaluated separately in §3H.
- No `marketquotes` sync job, so `GET /api/instruments/search` and `GET /api/market/overview` still
  return nothing against the live dev database.
- `GET /api/instruments/lookup/:symbol` and `GET /api/instruments/:symbol` remain **DEFERRED**.
  *(Superseded by §3I.)*
- `fetch_quote` still returns `None`: MARKET orders still answer the documented 503 and square-off
  still falls back to the stored `ltp`. *(Superseded by §3I.)*
- No CORS middleware, no frontend change, no response caching for candles.

---

## 3H. Phase 2b — WebSocket streaming proof of concept

**Goal:** find out whether Yahoo's stream can feed live prices, before any of it is designed in. No
cache sync, no `fetch_quote`, no lookup/detail routes, no trading changes.

### Verdict

**The stream is real and works for Indian symbols, but it cannot replace the polling jobs, and
adopting it now would add a stateful always-on connection for no visible benefit. Keep REST polling.**
Full measurements in `MARKET_DATA_PLAN.md` §3.2.

Tested live on Monday 2026-10-19, 13:57–14:11 IST, with the NSE open.

### Files

- `api/yahoo_stream.py` — **new.** A decoder for the wire format only: `decode_frame`, `quote_time`,
  `StreamDecodeError`. Standard library, no network, not wired into any route or job.
- `api/tests/test_yahoo_stream.py` — **new**, 17 tests.
- `api/tests/fixtures/yahoo_stream_frames.json` — **new**, 9 real frames captured from the live
  streamer, used as fixtures.
- `docs/migration/MARKET_DATA_PLAN.md` — §3.2 rewritten with the results and the decision.
- `docs/migration/TEST_PLAN.md` — §1H.

### What was verified

| Check | Result |
|---|---|
| Endpoint | `wss://streamer.finance.yahoo.com/?version=2`; no auth, crumb or cookie |
| `.NS` equities stream | yes — `RELIANCE`, `INFY`, `TCS`, `HDFCBANK` |
| `^` indices stream | yes — `^NSEI`, `^NSEBANK` |
| Update rate | ~1/s/symbol; 190–242 frames per symbol per 240 s; worst gap 6.0 s |
| Fields | `id`, `price`, `time`, `exchange`, `change`, `change_percent`, `quote_type`, `market_hours`; stocks add `day_volume`, `last_size`, `price_hint` |
| Price agreement with the Phase 2a REST path | `RELIANCE` Δ0.4, `INFY` Δ0.0, `^NSEI` Δ0.3 |
| Reconnect after an abrupt transport abort | handshake 1.77 s, first frame 2.40 s |
| Unsubscribe | frames stop after one in-flight message |
| Concurrent connections from one host | 3/3 streamed |
| `yfinance.live.AsyncWebSocket` | works, run rather than read |

Prices were live, not stale: `^NSEI` sent `price=22889.05, change=-257.10`, and
`price - change = 23146.15`, exactly the previous session's close.

### The two findings that decide this

1. **`marketCap` and `sector` are never streamed.** `marketSync` writes nine fields; the stream
   covers `ltp`, `dayChange`, `dayChangePct`, `volume` (stocks only) and a derivable `prevClose`. The
   Markets page's `marketCap` column and the sector heatmap (`SectorHeatmap.jsx` filters
   `marketCap > 0`) would go blank. The 5-minute REST batch must keep running for those two fields
   regardless — which removes most of the reason to add a second data path.
2. **Unsupported symbols fail silently.** Subscribing to `NOTAREALSYMBOL.NS` and `ZZZZ.NS` produced no
   frames, no error and no rejection. Absence is the only signal, so a dead symbol is
   indistinguishable from a closed market. Any future adoption must detect per-symbol staleness.

### The timestamp trap

`pricing.proto` declares `sint64 time = 3` and `sint64 day_volume = 9`; protobuf encodes `sint64` as
a **zigzag** varint. Read as a plain varint, `time` decodes to a date in **2083** with no error
raised. `api/yahoo_stream.py` decodes zigzag explicitly and a test pins it against captured frames.

### Why not `yfinance`'s client

It works, but it decodes via `MessageToDict`, which renders `int64`/`sint64` as **strings**
(`time` arrives as `"1792399388000"`), and its `listen()` reconnect path can re-enter its loop without
a fresh connection because `_connect()` returns early while `self._ws` is set. The decoder here is
standard library, ~150 lines, and tested against real frames.

### Dependencies

**None added.** `websockets` was already present through `uvicorn[standard]`; `yfinance`, pandas and
numpy were installed only to run the evaluation and were removed again afterwards. `pip check` is
clean and the full suite passes without them.

### Not verified

- A **full trading session** — the soak was ~14 minutes, not 09:15–15:30. Behaviour at the close and
  over hours is unknown.
- **Market open/close** transitions, and a **holiday or weekend**.
- **Network failures other than an abrupt local abort** (DNS loss, a proxy dropping long-lived
  connections).
- **Provider terms** for this use — still open (§7.5), unchanged by these results.

---

## 3I. Phase 2c — REST market data and live quotes

**Goal:** port `marketSync` (all nine quote fields), implement a real `fetch_quote`, and migrate the two
deferred instrument routes.

### Provider decision: cookie + crumb handshake

`/v7/finance/quote` is **not** open the way the chart endpoint is. A bare request answers:

```json
{"finance":{"result":null,"error":{"code":"Unauthorized","description":"Invalid Crumb", ...}}}
```

`yahoo-finance2` hides a two-step handshake. Reproduced and measured:

| Step | Request | Result |
|---|---|---|
| 1 | `GET https://fc.yahoo.com` | `404` by design, sets the `A3` cookie |
| 2 | `GET https://query1.finance.yahoo.com/v1/test/getcrumb` | plain-text crumb |
| 3 | `GET https://query2.finance.yahoo.com/v7/finance/quote?symbols=…&crumb=…` | `200` rows |

The first attempt used `https://finance.yahoo.com/quote/AAPL` as the bootstrap, which is what
`yahoo-finance2` does. **It returns a 301 with no `Set-Cookie` when called through `requests`,** so the
crumb step then fails. `fc.yahoo.com` is the step that actually works from Python. Recorded in
`MARKET_DATA_PLAN.md` §3.3 so the next reader does not repeat the dead end.

The session and crumb are cached process-wide behind a `threading.Lock`. A `401` triggers **one**
forced refresh (cookie *and* crumb — retrying with only a new crumb still answers 401) before the call
fails for real.

### Routes ported

| Route | Behaviour |
|---|---|
| `GET /api/instruments/lookup/{symbol}` | one quote; `symbol` uppercased, `name` from `longName \|\| shortName \|\| <path param>` |
| `GET /api/instruments/{symbol}` | the same plus open/high/low/prevClose/volume/52-week range |

Both answer **404 `"Instrument not found"`** for an unknown symbol, a zero price, **and a provider
failure** — Express wraps the whole handler in `try { … } catch { 404 }`, and that is preserved rather
than "improved" into a 503. Keys with no value are **omitted**, because `JSON.stringify` drops
`undefined`; they are not sent as `null`.

### `fetch_quote` is now real

`fetch_quote` returns `{"ltp", "dayChangePct"}` from a live quote, or `None`. `None` means "no usable
price", which is the branch both callers already had: a MARKET order answers the documented 503 and a
square-off falls back to the stored `ltp`.

Provider errors are **swallowed inside `fetch_quote`**, matching `fetchQuote`'s own `try/catch`. This was
a real bug in the previous phase's seam: it raised `MarketDataError`, which would have surfaced as a 500
instead of the 503 an order placement owes the client.

### Files

- `api/data/nifty50.py` — **new.** Port of `server/data/nifty50.js`: 50 stocks + 3 indices.
- `api/jobs/market_sync.py` — **new.** `sync_quotes`, `backfill_sectors`, `market_sync`.
- `api/market_hours.py` — **new.** Port of `server/utils/marketHours.js`.
- `api/scheduler.py` — **new.** The five-minute tick **and the ownership switch**.
- `api/market_data.py` — quote/crumb/sector provider plus `fetch_quote_row`; candle code untouched.
- `api/routes/instruments.py` — the two routes added.
- `api/main.py` — starts the scheduler only when enabled and only for a real (non-injected) database.
- `api/tests/test_market_sync.py` — **new**, 56 tests.
- `api/tests/test_instrument_quotes.py` — **new**, 13 tests.
- `api/tests/test_mongo_integration.py` — one new real-Mongo test for the bulk upsert.
- `api/.env.example` — documents `MARKET_SYNC_ENABLED`.
- `api/tests/test_orders.py`, `api/tests/test_positions.py` — three tests patched to keep the
  "no live quote" branch explicit now that `fetch_quote` really calls out.

### Update behaviour, observed rather than assumed

The exact command Mongoose sends for `bulkWrite` + `upsert` was captured with `mongoose.set("debug")`
against a throwaway `*_test` database:

```json
{"$setOnInsert": {"createdAt": …, "sector": "", "__v": 0},
 "$set": {…eight quote fields…, "updatedAt": …}}
```

Two consequences, both reproduced:

- **`sector` lives in `$setOnInsert` only.** A price cycle therefore cannot blank a sector the backfill
  has already resolved.
- **`backfillSectors` uses `doc.save()`,** which refreshes `updatedAt` and leaves `__v` at `0` (a no-op
  save writes nothing at all).

`sync_quotes` sends the same shape as one `bulk_write`. `backfill_sectors` writes one
`update_one({_id}, {"$set": {"sector", "updatedAt"}})` per resolved symbol, capped at
`SECTORS_PER_RUN = 10`, matching `if (!sector) continue`.

### Single owner for the sync

Express starts the cron unconditionally on connect. Two services doing that against one collection would
double the Yahoo traffic and race on the same documents, so ownership is explicit:

- `MARKET_SYNC_ENABLED` gates the scheduler and **defaults to off**.
- `create_app(database=…)` never starts it, so the test suite cannot reach the network.
- `market_sync` uses a non-blocking `threading.Lock` (the `isSyncing` equivalent); a tick that arrives
  while one is running returns immediately.
- The job keeps the **last good cache** on a provider failure: stale prices beat an empty Markets page.
- The gate syncs while the market is open **or when the cache is empty**, so a cold start still populates
  the page.

**Caveat, documented rather than hidden:** the lock is per process. Running more than one uvicorn worker
with the switch on would start one scheduler per worker. Exactly one process may set the flag; see
`api/scheduler.py` and `MARKET_DATA_PLAN.md` §3.4.

### Staleness — a deliberate non-change

`regularMarketTime` was measured at 15:31 IST, one minute after the close:

| Symbol | Age of last price |
|---|---|
| `^NSEI` | 1 s |
| `RELIANCE` | 106 s |
| `^BSESN` | **903 s** |

A five-minute cutoff would have rejected a legitimately-current quote. Express has no staleness check,
and adding one would silently convert valid MARKET fills into 503s — a financial-behaviour change made
unilaterally. **Missing, non-numeric, zero and negative prices are rejected; age is not.** This is
recorded as a known gap in `MARKET_DATA_PLAN.md` §5, not as parity that was achieved.

### Verification

| Check | Result |
|---|---|
| Batch quote from Python | **53/53** tickers, `missing: []` |
| Field-for-field vs `yahoo-finance2` | **identical** for `RELIANCE`, `^NSEI`, `^NSEBANK`, `^BSESN`, `M&M` on price/change/pct/prevClose/volume/marketCap/longName |
| `M&M.NS` (ampersand) | resolves and quotes correctly |
| Indices | `marketCap` absent → written as `0`; `volume` `0` |
| `fetch_sector` | `RELIANCE` → `Energy` via `assetProfile`; `^NSEI` → `""` (404) |
| Sync against `tradium_fastapi_dev` | **53 rows** written — 50 stocks + 3 indices, all nine fields present |
| Sector backfill against the dev DB | 10 resolved per run, as capped |
| `GET /api/instruments/search?q=REL` | `200`, row with renamed `price`/`changePct` |
| `GET /api/market/overview` | `200`, indices in seed order, 50 stocks, real `asOf` |
| `GET /api/instruments/lookup/RELIANCE` | `200`, `symbol: "RELIANCE"`, live price |
| `GET /api/instruments/RELIANCE` | `200`, all detail keys |
| Unknown symbol / no cookie | `404 "Instrument not found"` / `401` |

### Not done in this phase

- No `priceSync` (including `settleMisExit`), no `portfolioSnapshot`, no holiday calendar.
- No WebSocket, no streaming, no change to the frontend.
- No Express-vs-FastAPI HTTP-level parity run in this phase — the rate limiter, cookies and numeric
  rendering were compared later in §3K.
- The scheduler is not enabled by default, and nothing was enabled against any deployment.

---

## 3J. Phase 2d — remaining scheduled jobs

**Goal:** port the three behaviours Express runs on timers — `priceSync` (including `settleMisExit`)
and `portfolioSnapshot` — with the existing market-hours gate and single-owner rule.

### What was ported

| Express | FastAPI | Schedule |
|---|---|---|
| `syncPrices()` → `runSync()` | `sync_prices()` → `run_sync()` | every minute, plus once on startup |
| `settleMisExit(order)` | `settle_mis_exit(db, order)` | called by `run_sync` for filled MIS exits |
| `recordDailySnapshot()` | `record_daily_snapshot(db)` | 18:00 IST daily, **no** run on startup |

`run_sync` reads **all** holdings, positions, watchlists and OPEN orders, dedupes them by
`symbol-exchange`, quotes each distinct symbol once (sequentially, as Express does), updates the three
price-bearing collections, backfills a missing holding sector, then fills the crossed OPEN orders.

### Behaviour preserved, including the odd parts

- **No fill outside market hours.** `sync_prices` returns before quoting, so an OPEN limit order waits
  for the next session. Express has no separate gate around the fill loop.
- **The claim is the race guard.** An order fills only if
  `find_one_and_update({_id, status: "OPEN"})` still matches. A cancel that lands after the quote fetch
  wins.
- **SL-M fills at the live price**, not the trigger, and the blocked cash is corrected by
  `(order.price - fill_price) * qty` — only for a non-exit BUY or any MIS order. Exits never take that
  adjustment.
- **MIS exits settle, everything else applies a fill.** `settle_mis_exit` releases
  `entry * qty + pnl` (with `pnl` signed by LONG/SHORT), writes a `SETTLEMENT` ledger row
  (`` `SYMBOL MIS exit` ``), then deletes the position. A missing position **cancels** the order; a
  failed `$gte` guard **rejects** it. Both paths cancel the sibling legs.
- **OCO.** Every filled exit calls `cancel_sibling_exits`; a cancelled CNC BUY sibling is refunded.
- **One bad order does not stop the rest** — the loop logs and continues.
- **Snapshot every user**, including someone who sold everything: `users` → holdings → open MIS legs.
  Rerunning on the same IST day updates the same row instead of inserting a duplicate.
- **Snapshot date** is the IST calendar day stored at **UTC midnight**, exactly as
  `new Date(Date.now() + 5.5h)` then a UTC midnight produces.

Two behaviours are bugs in the original and were preserved deliberately (recorded in §4):

1. `settleMisExit` deletes the position unconditionally at the end, so its earlier
   `if (updated.qty <= 0) delete` is redundant: a partial exit releases cash for the open quantity and
   still removes the whole position.
2. The snapshot job has no catch-up: a process restarted after 18:00 waits until tomorrow.

### Schedule and ownership

`MARKET_SYNC_ENABLED` keeps gating only the shared market cache. The jobs that **move money** have a
separate switch, `TRADING_JOBS_ENABLED`, so enabling order fills can never happen as a side effect of
populating the Markets page:

| Switch | Starts | Default |
|---|---|---|
| `MARKET_SYNC_ENABLED` | `MarketSyncScheduler` (5 min + cold start) | off |
| `TRADING_JOBS_ENABLED` | `PriceSyncScheduler` (1 min + startup) and `PortfolioSnapshotScheduler` (18:00 IST) | off |

Both are read per startup, and `create_app(database=…)` never starts either, so the test suite cannot
reach the network or change financial state. Exactly one process may set each switch; during the
migration that process must not be running alongside Express's cron against the same database.

**Caveat, unchanged from §3I:** both guards are per process. More than one uvicorn worker with a switch
on starts one scheduler per worker.

### Writes, observed rather than assumed

The exact commands were captured with `mongoose.set("debug")` against a throwaway `*_test` database:

| Operation | Command |
|---|---|
| `holding.save()` / `position.save()` / `watchlist.save()` | `updateOne({_id}, {"$set": {…changed fields, updatedAt}})` — **`__v` untouched** |
| order claim | `findOneAndUpdate({_id, status:"OPEN"}, {"$set": {status, filled, price, updatedAt}})` |
| snapshot upsert | `$set` the four numbers plus `updatedAt`; `$setOnInsert` `createdAt` and `__v: 0` |

`run_sync` reproduces those shapes with `update_one` / `find_one_and_update` plus
`documents.utcnow()`. One known numeric nuance carries over from §3E: `settle_mis_exit` passes its
ledger amount through `js_number`, matching the existing `apply_fill` and square-off paths, so a whole
rupee P&L is stored as an integer rather than a BSON double. JSON output is unaffected.

### Files

- `api/jobs/price_sync.py` — **new.** `sync_prices`, `run_sync`, single-flight lock.
- `api/jobs/portfolio_snapshot.py` — **new.** `snapshot_date`, `record_daily_snapshot`.
- `api/portfolio_math.py` — **new.** Shared `mis_components`; the history route and the job now use it.
- `api/order_engine.py` — `settle_mis_exit` added next to `apply_fill`/`cancel_sibling_exits`.
- `api/scheduler.py` — `TRADING_JOBS_ENABLED`, `PriceSyncScheduler`, `PortfolioSnapshotScheduler`,
  `seconds_until_snapshot`.
- `api/main.py` — starts/stops both trading jobs under the switch.
- `api/routes/portfolio.py` — imports the shared `mis_components` (no behaviour change).
- `api/.env.example` — documents `TRADING_JOBS_ENABLED`.
- `api/tests/test_price_sync.py` — **new**, 27 tests.
- `api/tests/test_portfolio_snapshot.py` — **new**, 13 tests.
- `api/tests/test_mongo_integration.py` — one new real-Mongo job test.

### Verification

| Check | Result |
|---|---|
| Full suite (default) | **242 passed, 8 skipped** |
| Full suite with `TEST_MONGO_URL` | **250 passed** |
| Real-Mongo job run | holdings/position prices refreshed, sector filled, MIS exit settled, snapshot upserted; scratch DB dropped |
| Mongoose `save()` / claim / snapshot shapes | **observed** with `mongoose.set("debug")`; reproduced |
| Market gate | closed → no provider call, no write |
| Single-flight | lock held → tick returns without work; lock always released |
| Order matching | LIMIT at its limit, SL-M at the live price, no cross → still OPEN |
| MIS settlement | LONG and SHORT signs, funds release, ledger row, sibling cancel, missing position → CANCELLED |
| Partial exit | releases only the open quantity; position removed (Express behaviour preserved) |
| Snapshot date | 23:59 IST → same day; 00:00 IST → next day; month boundary |
| Snapshot idempotence | second run keeps `_id`/`createdAt`, updates `value`/`updatedAt`, one row |
| Scheduler default | both switches off; injected test DB never starts either job |
| Live startup wiring | **verified** — with `TRADING_JOBS_ENABLED=true`, `create_app()` starts the price and snapshot schedulers, `MARKET_SYNC_ENABLED` stays off, and the closed-market tick changed no document count in `tradium_fastapi_dev` |
| Yahoo calls during tests | **none** — provider patched at `api.jobs.price_sync` |
| `tradium_fastapi_dev` | untouched in this phase (still only the 53 Phase 2c `marketquotes` rows) |

### Not done in this phase

- No Express-vs-FastAPI HTTP or timing parity run — the focused check in §3K covers the job *side
  effects* and the snapshot/auth surfaces only; the remaining HTTP comparison rows are still
  **PENDING**.
- No holiday calendar, no auto square-off of open MIS positions at the close (Express has neither).
- No change to the frontend, no deployment, and no switch enabled anywhere.
- No scheduler dependency added; the three loops remain plain threads.

---

## 3K. Phase 2e — focused Express parity check

**Goal:** settle the three parity uncertainties that were still `PENDING` — the auth `Set-Cookie`
header, whole-float JSON rendering, and the database side effects of the three scheduled jobs — without
starting the Express application and without touching the original repository or any real data.

### Method

The harness lives in `tools/express-parity/` and is read-only.

- **`server/index.js` is never loaded.** It is the only file that registers cron jobs, so the harness
  imports the smallest modules instead: `routes/authRoutes`, `routes/holdingsRoutes`,
  `jobs/priceSync`, `jobs/portfolioSnapshot`.
- **The two provider seams are stubbed before `priceSync` is required**, by intercepting
  `Module._load`: `yahoo-finance2` becomes a fake class driven by `scenario.json`, and
  `utils/marketHours.isMarketOpen` returns `true`. No Yahoo request is made.
- **Every run uses a scratch database** (`tradium_parity_*`), dropped before and after. The dev
  database `tradium_fastapi_dev` and the `zerodha` database are never opened.
- **The original checkout is read-only** (`ZERODHA_SERVER`). This repository's `server/` copy has no
  `node_modules`, so the harness loads the original tree's installed dependencies; all 38 `server/`
  source files were confirmed identical to this repository's copies apart from line endings first.
- **Both sides build the same documents.** `scenario.json` is the single shared input: two users, three
  holdings, two MIS positions (LONG and SHORT), two watchlist rows, six OPEN orders, one funds row,
  four quotes and a sector map.
- The FastAPI side runs `create_app(database=<scratch>)`, so no scheduler is started either.
- The Node files are `.cjs` because the repository root `package.json` sets `"type": "module"`.

### 1. Authentication cookies (real routes, same request sequence)

| Step | Express | FastAPI | Verdict |
|---|---|---|---|
| signup | 201, `token=<jwt>; Max-Age=604800; Path=/; Expires=<+7d>; HttpOnly; SameSite=Strict` | 201, same except **no `Expires`** and `SameSite=strict` | equivalent |
| login | 200, same cookie | 200, same cookie | equivalent |
| `GET /me` | 200 `{"user":{_id,username,email,createdAt,updatedAt,__v}}` | identical once id/timestamps are normalised | equivalent |
| logout | 200, `token=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT; HttpOnly; SameSite=Strict` | 200, `token=""; Max-Age=0; Expires=<now>; Path=/; HttpOnly; SameSite=strict` | equivalent (both delete) |
| `GET /me` after logout | 401 `Not authenticated` | 401 `Not authenticated` | equivalent |
| `GET /me` with no cookie | 401 | 401 | equivalent |
| login, wrong password | 401 `Invalid credentials` | 401 `Invalid credentials` | equivalent |

JWT payloads are identical in shape: HS256, `{id, iat, exp}`, `exp - iat = 604800`, 171 characters.

Measured differences, none observable by a client:

- **`Expires` on the signup/login cookie.** Express converts `maxAge` into both `Max-Age` and `Expires`;
  Starlette sends only `Max-Age`. `Max-Age` wins in every current browser.
- **Logout mechanism.** Express clears with `Expires` in the past (Express 5's `clearCookie` deletes
  `maxAge`); Starlette sends `Max-Age=0` *and* `Expires=<now>`. Both are deletion per RFC 6265 §5.3,
  which gives `Max-Age` precedence. *(Express 4 would have kept the cookie alive — that is not what the
  installed Express 5.2.1 does.)*
- **Empty-value quoting.** `http.cookies` emits `token=""`; Express emits `token=`. A browser parses
  both as the empty string, which `require_user` treats as "not authenticated".
- **Attribute order and `SameSite=strict` casing.** Parsed case- and order-insensitively per RFC 6265.

### 2. Whole-float JSON rendering (real `GET /api/holdings`, same stored document)

| Stored BSON value | Express body | FastAPI body |
|---|---|---|
| double `2500.0` | `2500` | `2500.0` |
| double `0.0` | `0` | `0.0` |
| double `-0.0` | `0` | `-0.0` |
| double `0.30000000000000004` | `0.30000000000000004` | `0.30000000000000004` |
| double `1e21` | `1e+21` | `1e+21` |
| int32 `0`, `100` | `0`, `100` | `0`, `100` |
| ObjectId, `Date`, `__v` | hex string, ISO-8601 ms, `0` | identical |

`JSON.parse` maps `2500` and `2500.0` to the same IEEE-754 double, so no client can distinguish them;
the React app reads these fields as numbers and formats them itself. **Cosmetic, left unchanged** —
`to_json_value` stays as it is.

One case is behavioural rather than cosmetic, and was measured rather than assumed: a **non-finite**
value. `JSON.stringify(NaN)` is `null`, while Starlette's `JSONResponse` uses `allow_nan=False` and
raises `ValueError` (→ 500 through the central handler). No write path can store one: provider quotes
are finite-checked in `fetch_quote`; `qty` and `price` pass through `js_number` and are then rejected by
`is_falsy_number` (NaN is falsy in JS); `triggerPrice`/`slTrigger`/`tpPrice` pass through
`js_number_or_zero`, which turns NaN into `0` exactly as `Number(x) || 0` does. Recorded as a residual
edge case, not fixed.

### 3. Background jobs (equivalent input → compared collection by collection, BSON types included)

The scenario exercises every branch that was ported. Both sides produced **the same document multiset**
in `holdings`, `positions`, `watchlists`, `orders`, `funds`, `users` and `transactions`:

| Behaviour | Observed identically on both sides |
|---|---|
| price refresh | `RELIANCE` → `ltp 2510.25`, `dayChangePct 1.5`; `INFY` → `1500.75 / 0.75`; position `INFY` → `1500.75`; watchlist `INFY` → `1500.75 / 0.75` |
| missing quote | `TATAMOTORS` untouched; no provider value invented |
| sector backfill | `RELIANCE` `""` → `"Energy"`; a symbol with no profile stays `""`; a known sector is not overwritten |
| LIMIT BUY into an existing holding | `qty 10 → 12`, `avgPrice 2420.4166666666665` (server-side `$divide` pipeline) |
| LIMIT SELL all of a holding | row deleted, funds `+7451.25`, ledger `INFY sell` `-51.25` |
| SL-M exit fill | filled at the live price `810.5`, not the trigger `795`; no blocked-cash adjustment for an exit |
| MIS settlement | SHORT position deleted, funds `+3158`, ledger `SBIN MIS exit` `-42` stored as **int32** |
| OCO | sibling exit `CANCELLED`; the uncrossed SELL stays `OPEN` |
| bracket spawn | new `WIPRO` holding (`qty 3`, `avgPrice/ltp 400`, `dayChangePct 0`, `sector ""`) plus an `SL-M` and a `LIMIT` exit leg, both `OPEN` |
| uncrossed order | stays `OPEN`, nothing written |
| final funds | `110609.75` (identical double) |
| snapshot | one row per user; `value 33123.5`, `invested 32045.5`, `misValue 7503.75`, `misInvested 7500`; a user with no rows gets `0/0/0/0`; `date` is the same IST day at UTC midnight |

The **only** divergence anywhere in the job surface is the BSON numeric type of the two snapshot MIS
fields:

| Field | Express | FastAPI | Why |
|---|---|---|---|
| `misInvested` | `int32` | `double` | `misComponents` starts at `0` in JS and `0.0` in `api/portfolio_math.py` |
| `misValue` | `int32` when integral (`0`, `7500`), `double` otherwise | always `double` | same |

The values are numerically identical, no query or index reads those fields, and the history route
returns them as numbers. **Recorded, not changed**: applying `js_number` in `mis_components` would close
it, but it would also change the live `/api/portfolio/history` output for no client-visible reason.
Noted as a candidate if strict BSON-type parity is ever required.

### Verification

| Check | Result |
|---|---|
| `compare.py` verdict | **equivalent - no functional difference observed** |
| Auth steps compared | 7 (signup, me, login, logout, me-after-logout, anonymous me, bad login) |
| Documents compared per collection | `users` 2, `holdings` 3, `positions` 1, `orders` 8, `funds` 1, `transactions` 2, `snapshots` 2 |
| Provider calls | **none** (both seams stubbed) |
| Schedulers started | **none** on either side |
| Express entry point loaded | **no** (`server/index.js` never required) |
| Scratch databases | dropped; `tradium_fastapi_dev` and `zerodha` untouched |
| Original repository | read-only; no file, branch, remote or history change |

### Files

- `tools/express-parity/` — **new**, 11 files: three Node harnesses (`.cjs`), the three FastAPI
  equivalents, the shared `scenario.json`, `harness_env.py`, `compare.py`, a README and a `.gitignore`
  for the captures.

### Not done in this phase

- No Express *server* was started, so CORS, the static frontend mount and the central error handler were
  not exercised.
- Orders, watchlist, positions, funds, portfolio history and the market routes were **not** compared at
  the HTTP level; only their post-job documents were (for the write paths) and their stored-shape
  rendering is already covered by the route tests. Those rows stay `PENDING` in `TEST_PLAN.md`.
- Job *scheduling* was compared by reading both sources, not by waiting for a cron tick.
- No behaviour was changed and no dependency was added.

---

## 3L. Phase 3a — CORS and frontend cutover

**Goal:** let the React app in this repository talk to FastAPI with cookie authentication, fix the
known signup mismatch, and verify the auth lifecycle and main pages in a browser.

### Changes

| File | Change |
|---|---|
| `api/config.py` | `VITE_DEV_ORIGINS` (5173-5177) and `get_cors_origins()`; `CORS_ORIGINS` is a comma-separated override, defaulting to the Vite origins |
| `api/main.py` | `CORSMiddleware` with the resolved origins, `allow_credentials=True`, all methods and headers |
| `api/.env.example` | documents `CORS_ORIGINS` and its production use |
| `src/services/api.js` | development `BASE_URL` is now `http://localhost:8000/api`; `VITE_API_URL` still wins, production stays same-origin `/api` |
| `src/features/auth/pages/Signup.jsx` | calls `signup({ username: form.name.trim(), email, password })` instead of three positional arguments |
| `api/tests/test_cors.py` | **new**, four tests: each Vite port, credentialed preflight, rejected origin, environment override |

The signup route was **not** changed: it already accepts `username`, `email`, `password`, matching the
Express contract. Only the frontend caller was wrong, in two ways at once (argument shape and the
`name`/`username` field name).

### Verification against a live server

Run with `uvicorn api.main:app` on `127.0.0.1:8000`, `MONGO_URL` pointing at the scratch database
`tradium_fastapi_phase3a_test`, and Vite on `localhost:5173`. The browser used `http://localhost:5173`
so the request origin exercised the default CORS list.

| Check | Observed |
|---|---|
| Preflight `OPTIONS /api/auth/login` from `http://localhost:5173` | 200, `Access-Control-Allow-Origin: http://localhost:5173`, `Access-Control-Allow-Credentials: true` |
| Signup through the UI | `POST /api/auth/signup` 201, cookie set, redirect to `/dashboard` |
| Signup payload | the created user's `username` is the full name typed into the form |
| Session restoration | page reload issued `GET /api/auth/me` 200 and stayed on the dashboard |
| Login through the UI | `POST /api/auth/login` 200, redirect to `/dashboard` |
| Logout through the user menu | `POST /api/auth/logout` 200, redirect to `/login`; `/api/auth/me` then 401 |
| Protected route after logout | `/dashboard` redirected to `/login` |
| Holdings, positions, orders, watchlist, funds, markets | each page rendered its expected empty state; every data request returned 200 |
| Wrong password / duplicate signup | 401 `Invalid credentials` / 400 `User already exists` |
| Stale-session calls before signup | two `GET /api/auth/me` 401 responses, the expected logged-out state |
| Nova calls | `POST /api/assistant/*` 404; `PageInsight` shows "Insight unavailable right now." and the rest of the page still works |

No CORS error appeared in the browser console. The only failed requests were the deferred Nova
endpoints.

### Files and checks

- `npm run lint`: **pass**.
- `npm run build`: **pass** (Vite 8.1.5, 3521 modules; only the existing chunk-size advisory).
- `.venv/Scripts/python.exe -m pytest -q`: **246 passed, 8 skipped**.
- Scratch database `tradium_fastapi_phase3a_test`: **dropped** after the run.
- `tradium_fastapi_dev` was not written to in this phase; `zerodha` still has its 9 collections.

### Not done in this phase

- No production deployment, static serving change, or Render change. FastAPI still does **not** mount
  `dist/`; a production cutover needs either that mount (planned for Phase 4) or a separately deployed
  frontend whose origin is listed in `CORS_ORIGINS`.
- No Nova/Gemini work. The assistant routes remain 404 until that phase.
- No change to `server/`, the original `Zerodha` repository, or its deployment.
- The HTTP-level parity rows for orders, watchlist, positions, funds, portfolio history and market
  routes remain `PENDING` in `TEST_PLAN.md`; this phase exercised the browser paths, not a byte-level
  comparison.

---

## 3M. Phase 3b — Nova assistant, insights and briefing

**Goal:** port the Express assistant to FastAPI with the existing routes, prompts, tools and streaming
protocols, then verify it from the unmodified React UI.

### Implementation

| File | Change |
|---|---|
| `api/assistant.py` | **new** — verbatim chat/insight/briefing prompts, `NovaDeps`, `get_ai_model()`, six tool snapshot functions, module-level `chat_agent`/`plain_agent`, `stream_text` |
| `api/routes/assistant.py` | **new** — `POST /api/assistant/chat` (Vercel UI Message Stream), `POST /api/assistant/insight` and `POST /api/assistant/briefing` (plain text) |
| `api/portfolio_math.py` | added `calculate_portfolio_summary()` and `day_change_rupees()` shared with the tool layer |
| `api/config.py` | `AISettings` / `get_ai_settings()` reading `GOOGLE_GENERATIVE_AI_API_KEY` and optional `GEMINI_MODEL` |
| `api/main.py` | registers `assistant.router` |
| `api/requirements.txt` | `pydantic-ai-slim[google]==2.57.0` |
| `api/.env.example` | documents the Gemini key and model override |
| `api/tests/test_assistant.py` | **new** — 13 tests: auth, payload validation, missing configuration, text/tool SSE, insight/briefing text, tool data parity, SHORT P&L, cross-user isolation, date serialization |

### Decisions

- **Protocol:** PydanticAI `VercelAIAdapter` with `sdk_version=7`, matching the installed frontend
  (`ai@7.0.58`, `@ai-sdk/react@4.0.61`). The adapter emits the message-part SSE frames the panel
  already understands; no custom format was invented.
- **Payload validation:** the chat body is checked manually so a non-array `messages` returns the
  Express-compatible `400 {"error":"Invalid messages payload"}` instead of FastAPI's 422 shape.
- **Step cap:** Express `stepCountIs(5)` became `UsageLimits(request_limit=5)`.
- **Insight/briefing:** plain-text `StreamingResponse` using the original `pageContext` descriptions,
  `FORMAT_RULES`, the 25-word insight limit and the dashboard-only briefing prompt.
- **Configuration:** key from `GOOGLE_GENERATIVE_AI_API_KEY`; model defaults to
  `gemini-3.5-flash-lite`, overridable with `GEMINI_MODEL`. Missing key → `503` from the route, not an
  import-time crash. No key or model string is hardcoded in the controller.
- **Failure handling:** insight/briefing use one generator entered and iterated in the same task
  (PydanticAI requirement) and yield `Insight unavailable right now.` if the provider fails after
  headers are sent. Chat maps `ModelAPIError` to `502` and other exceptions to `500`.
- **Tool defects (intentional, tested divergence from Express):**
  - `getOrders` reads `qty` rather than the non-existent `quantity`.
  - `getOrders` status matching is case-insensitive against uppercase stored values.
  - `getFunds` derives `usedMargin = blockedInOrders + misMargin` instead of reading `funds.used`.
  - `getPositions` flips the P&L sign for SHORT positions.

### Verification against a live server

Run with `uvicorn api.main:app` on `127.0.0.1:8000`, `MONGO_URL` pointing at the scratch database
`tradium_fastapi_phase3b_test`, Vite on `localhost:5173`, and a real Gemini key injected into the
process environment only (never written to a tracked file). The scratch DB held two holdings
(RELIANCE, INFY), long and short MIS positions, OPEN/EXECUTED/CANCELLED orders, a watchlist row and
₹50,000 available funds.

| Check | Observed |
|---|---|
| Dashboard briefing | `POST /api/assistant/briefing` 200 `text/plain`; card showed a 2–3 sentence briefing with real P&L, e.g. day P&L ₹204 / 0.64% |
| Holdings page insight | `POST /api/assistant/insight` 200; "RELIANCE drove today's gains of ₹204, offsetting INFY's 1.50% drop to bring total portfolio value to ₹31,900." |
| Chat, single tool | `POST /api/assistant/chat` 200 SSE; `getHoldings` card, answer named RELIANCE 10 @ ₹2,500 and INFY 5 @ ₹1,380, total ₹31,900 |
| Chat, two tools | `getFunds` + `getOrders` cards; answer reported ₹50,000 available, ₹4,900 blocked and the single pending RELIANCE limit buy of 3 @ ₹2,450 |
| Tool card rendering | unmodified `AssistantPanel.jsx` rendered `getHoldings`, `getFunds` and `getOrders` as completed tool cards |
| Unauthenticated chat | 401 (test) |
| Non-array `messages` / missing key | 400 `{"error":"Invalid messages payload"}` / 503 (test) |

The two-tool turn also confirms the three Express tool defects are fixed: the orders tool returned a
quantity and matched the uppercase `OPEN` status, and the funds tool reported a derived blocked margin
rather than failing on the missing `used` field.

### Files and checks

- `.venv/Scripts/python.exe -m pytest -q`: **259 passed, 8 skipped**.
- Scratch database `tradium_fastapi_phase3b_test`: **dropped** after the run.
- `tradium_fastapi_dev` and `zerodha` were not written to in this phase.

### Not done in this phase

- No static serving of `dist/`, no production deployment and no Render change. FastAPI still does not
  mount the frontend build.
- No retry policy for provider 429/5xx; errors surface as described above.
- The five-step cap is configured but was not probed adversarially; the HTTP-level parity rows in
  `TEST_PLAN.md` remain pending except where this phase added direct tests.

---

## 3N. Phase 4a — production static serving and deployment preparation

**Goal:** serve the Vite production build from FastAPI with correct SPA fallback and API isolation,
document the production configuration, and verify the built app locally.

### Changes

| File | Change |
|---|---|
| `api/main.py` | `DIST_DIR`, `_serve_frontend()` (optional `/assets` mount + `GET /{full_path:path}` SPA fallback), wired in after the routers so it can never shadow `/api` |
| `api/config.py` | `serve_static_enabled()` — `SERVE_STATIC` override, else `NODE_ENV=production` (Express parity) |
| `api/.env.example` | documents `SERVE_STATIC` and its relationship to `NODE_ENV` |
| `api/tests/test_static.py` | **new** — 10 tests over a throwaway `dist/`: root/deep-link shell, assets, root files, known-API passthrough, unknown-API JSON 404, bare `/api`, default-off, missing build, production-mode default, flag precedence |
| `docs/DEPLOYMENT.md` | **new** - build/start commands, env-var table, cookie/CORS notes, scheduler ownership, static behaviour, local production run, rollback |

No change was made to `src/`; the production build already calls the API at the relative `/api` path
(Phase 3a), which is what makes same-origin serving work.

### Behaviour

- Static serving is **off by default**; it turns on with `SERVE_STATIC=true` or `NODE_ENV=production`.
  The separate switch lets a local run serve the real build without also forcing the `Secure` cookie.
- `/assets/*` is served by a `StaticFiles` mount; other real files in `dist/` (e.g. `/favicon.svg`) are
  returned directly; every other non-`/api` path gets `dist/index.html`.
- `/api` and `/api/*` always reach FastAPI. A known route is untouched; an unknown one returns the JSON
  `{"message": "Route not found"}`, never the app shell.
- A missing `dist/index.html` logs a warning and leaves the API running (no crash).
- **Deliberate divergence:** a missing file under `/assets/` returns the JSON 404, whereas Express's
  fallback would return `index.html`. Missing assets should not resolve to HTML.

### Verification against a live server

Build first: `npm run build` produced `dist/` (Vite 8.1.5, 59 assets). Then `uvicorn api.main:app` on
`127.0.0.1:8000` with `NODE_ENV=production`, `SERVE_STATIC=true`, a scratch database
`tradium_fastapi_phase4a_test`, and a runtime-injected Gemini key. Browser origin `http://localhost:8000`.

| Check | Observed |
|---|---|
| `GET /` | 200 `text/html`; the SPA boots with no console errors |
| `GET /dashboard`, `/login`, `/dashboard/holdings` (deep links) | 200 `text/html` (app shell) |
| Refresh on `/dashboard/positions` | 200, dashboard and data reload |
| `GET /assets/index-*.js` | 200 `text/javascript`, full size; `/favicon.svg` 200 `image/svg+xml` |
| `GET /api/health` | 200 `{"ok":true}` (not shadowed) |
| `GET /api/nope`, `GET /api` | 404 `application/json` `{"message":"Route not found"}` |
| Browser network | only the expected logged-out `/api/auth/me` 401; all assets and data requests 200 |
| Login through the UI, `NODE_ENV=production` | 200; cookie stored over `http://localhost`; app reached `/dashboard` |
| `Set-Cookie` (production) | `token=…; HttpOnly; Max-Age=604800; Path=/; SameSite=strict; Secure` |
| Same-origin API | data requests to `/api/holdings`, `/api/positions`, `/api/orders`, `/api/watchlist`, `/api/funds`, `/api/portfolio/history` all 200 with no CORS preflight |
| Dashboard briefing | rendered with real numbers (net worth ₹1,13,150, day P&L +₹503.57) |
| Holdings page insight | "RELIANCE led today's gains with a 1.25% increase, offsetting INFY's 1.5% drop…" |
| Nova chat | `getFunds` tool card + grounded answer (₹50,000 available, ₹7,350 blocked) |
| Missing AI key | `/`, `/dashboard`, `/api/health` still 200/`ok`; briefing/insight 503 `{"message":"AI is not configured"}`, chat 503 `{"error":"AI is not configured"}` |
| Scheduler ownership | startup log shows the app only; no market-sync or trading-job line (both switches unset) |

### Files and checks

- `.venv/Scripts/python.exe -m pytest -q`: **269 passed, 8 skipped**; **277 passed** with `TEST_MONGO_URL`.
- `npm run lint`: **pass**; `npm run build`: **pass**.
- Scratch database `tradium_fastapi_phase4a_test`: **dropped** after the run.
- `tradium_fastapi_dev` and `zerodha` were not written to in this phase.

### Not done in this phase

- **No deployment.** No Render service was created, modified, or repointed; the existing Express service
  and the original repository are untouched, and no Git remote was configured.
- Multiple API instances would need a single-instance constraint unless both job switches stay unset;
  that is documented, not enforced in code.
- No HTTPS termination, reverse proxy, or `TrustedHost`/proxy-header configuration; the production
  cookie is `Secure`, so a non-localhost deployment needs HTTPS in front of it.

---

## 3O. Phase 4b — final pre-deployment readiness review

**Goal:** resolve the remaining `PENDING`/`PARTIAL` test rows that touch auth, trading, data integrity
or frontend integration; scan tracked files for secrets; and confirm the deployment guide matches the
implementation. No application code was changed.

### Read-route parity (closes rows 1D.16, 2B.1, 2C.1)

The Phase 2e harness compared cookies, numeric rendering and job side effects but left the HTTP bodies of
the ordinary read routes unchecked. Phase 4b extends it:

| File | Change |
|---|---|
| `tools/express-parity/routes_scenario.json` | **new** — synthetic fixture: two users, holdings, MIS/CNC positions, watchlist rows, orders in several states, funds, SETTLEMENT/DEPOSIT transactions, snapshots (one legacy `invested: 0`) and `marketquotes` |
| `tools/express-parity/express_routes.cjs` | **new** — boots only the orders/watchlist/positions/funds/portfolio/market/instrument routers on an ephemeral port and captures each GET body; `server/index.js` is never required |
| `tools/express-parity/fastapi_routes.py` | **new** — the same requests through `create_app(database=...)` |
| `tools/express-parity/compare.py` | `compare_routes()` — structural JSON comparison (keys, values, list order) and a `read routes` section |

Run: `node express_routes.cjs`, `python fastapi_routes.py`, `python compare.py`. Result: **`identical`**
— no functional difference and no number-spelling difference either.

| Route | Observed (both sides) |
|---|---|
| `GET /api/orders` | 200, newest first, full Mongoose key set incl. `__v` |
| `GET /api/watchlist` | 200, both rows |
| `GET /api/positions` | 200, LONG/SHORT MIS + a CNC leg |
| `GET /api/funds` | 200, `usedMargin 16940 = blockedInOrders 6240 + misMargin 10700`, `realizedPnl 1200.5` |
| `GET /api/funds/transactions` | 200, newest first |
| `GET /api/portfolio/history?range=1Y` | 200, two snapshots (one `invested: null`) then today's live point |
| `GET /api/market/overview` | 200, `asOf` = freshest `updatedAt`, indices in `nifty50` order |
| `GET /api/instruments/search?q=IN` | 200, renamed `price`/`changePct` |
| `GET /api/instruments/search?q=` | 200, `[]` |

The Yahoo-backed instrument routes (`/lookup/:symbol`, `/:symbol`, `/:symbol/candles`) are deliberately
not called, so the harness stays offline; row 1I.36 stays `NOT RUN` (it needs the provider). The cron
**schedule** and the central error handler remain outside the harness (rows 1J.33 and 8.13 stay
`PARTIAL`).

### Security and repository readiness

- **No committed secrets.** A scan of every tracked file found no Google API key (`AIza…`), no AWS key,
  no private key block, no credentials embedded in a `mongodb://`/`mongodb+srv://` URL, and no JWT. The
  only matches for `JWT_SECRET=`/`API_KEY=` were the two `.env.example` placeholders and fake
  `test-…`/`parity-…` values. The original repository's real `GOOGLE_GENERATIVE_AI_API_KEY`, `JWT_SECRET`
  and `MONGO_URL` values appear in **none** of the tracked files; `.env` has never been committed.
- **`.env` files**: only `api/.env.example` and `server/.env.example` are tracked (a scan of all history
  for `.env`/`api/.env`/`server/.env` found nothing).
- **Local artifacts untracked.** `CLAUDE.md` (already listed in `.gitignore`) and `.claude/launch.json`
  were tracked anyway; both are now `git rm --cached`'d (the files remain on disk) and `.claude/` was
  added to `.gitignore`. They are per-developer agent/editor files, not project files.
- **Larger tracked files** are legitimate: the frontend screenshots (`src/assets/screenshots/*.png`,
  ~3 MB total) and `package-lock.json`. No binary or archive is tracked accidentally.
- **Dependency pinning**: `api/requirements.txt` pins all runtime packages (FastAPI, Uvicorn, PyMongo,
  PyJWT, python-dotenv, bcrypt, requests, `pydantic-ai-slim[google]`). `api/requirements-dev.txt`
  (already present) pins the test-only deps (`pytest`, `httpx`, `mongomock`) and pulls in the runtime
  file with `-r requirements.txt`, so a fresh clone can install and run the suite.

### Deployment readiness

`docs/DEPLOYMENT.md` was cross-checked against the code; the build/start commands, env-var
names, `/api/health` endpoint, `Secure`-cookie behaviour, static-serving switch and the two scheduler
switches all match. Notes added or confirmed:

- **Python 3.13** is the interpreter the migration was built and tested on; the platform must provide a
  compatible version (`pydantic-ai-slim==2.57.0`, FastAPI, Uvicorn).
- **Mongo is connected lazily.** The app starts and `/api/health` answers `200` even when MongoDB is
  unreachable; the failure surfaces on the first data request. Liveness therefore passes while a
  database outage is invisible to the health check — an operational limitation, not a code defect.
- **HTTPS is required** for any non-localhost host because the production auth cookie is `Secure`.
- **Single scheduler owner**: leave `MARKET_SYNC_ENABLED` and `TRADING_JOBS_ENABLED` unset while Express
  still runs; enable each on exactly one process at a deliberate cutover.

### Not done in this phase

- **No deployment** and no Render/GitHub changes; the branch is still local-only (no remote).
- No application code changed, so the test suite was not rerun (`269 passed, 8 skipped` stands).
- The `PARTIAL` AI rows (five-step cap, live provider 429/5xx) and the Express-defect rows 4–9 were left
  as recorded; none is a publication or deployment blocker.

---

## 3P. Phase 3B1 — PostgreSQL schema foundation and authentication

**Goal:** put the approved relational schema under Alembic and move exactly one surface — user identity —
from MongoDB to PostgreSQL. Every other route keeps reading MongoDB.

> **Naming.** `Phase 3B1` and `Phase 3B2` label the PostgreSQL workstream. §3L and §3M keep their
> historical labels (`Phase 3a` — CORS/frontend cutover, `Phase 3b` — Nova) because earlier documents
> already refer to them that way. The two schemes are unrelated.

### Schema

| File | Purpose |
|---|---|
| `alembic.ini` | `script_location = api/migrations`; `sqlalchemy.url` is deliberately empty |
| `api/migrations/env.py` | reads `DIRECT_DATABASE_URL`; migrations never use the pooled URL |
| `api/migrations/versions/0001_initial_schema.py` | revision `0001`, the only revision so far |
| `api/postgres/base.py` | declarative base and the shared 24-hex id pattern |
| `api/postgres/models.py` | the ten tables |
| `api/postgres/session.py` | lazily created engine and session factory |

`alembic upgrade head` creates `users`, `funds`, `holdings`, `positions`, `orders`, `transactions`,
`watchlists`, `instruments`, `latest_quotes`, `portfolio_snapshots` and `alembic_version`. The tables
carry the checks, unique keys, foreign keys and indexes from `POSTGRES_SCHEMA_DESIGN.md`, including
24-hex id checks, `exchange = 'NSE'`, `timestamptz(3)` and `numeric` columns. Alembic owns schema
creation; nothing calls `create_all()` at application startup.

### Authentication

- `POST /api/auth/signup`, `POST /api/auth/login` and `GET /api/auth/me` read and write `users` in
  PostgreSQL. `POST /api/auth/logout` is unchanged — it only clears the cookie.
- Response bodies, the `{ message }` / `{ message, error }` envelopes, status codes, the rate limiter,
  the cookie flags and the JWT claims are unchanged.
- Ids are `secrets.token_hex(12)` — 24 lowercase hex characters, the same external shape as an
  `ObjectId`. Book rows still key on `ObjectId(user_id)`, so a PostgreSQL id still opens the
  Mongo-backed routes; a test goes signup → cookie → `GET /api/holdings` to prove it.
- Duplicate signup is still rejected by pre-checks, but the `users` unique constraints close the race
  between two concurrent requests: an `IntegrityError` maps to the same 400 `"User already exists"`.
- bcrypt hashes stay compatible in both directions — a Node-generated hash logs in, and a Python hash
  verifies under the npm package.
- `/me` with a malformed id is a 404, not a 500.
- `DATABASE_URL` is read on first use. Importing the app and calling `/api/health` need no PostgreSQL;
  the failure surfaces on the first request that needs it. With the variable unset, the auth routes
  answer their own 500 body and the two market routes answer the central
  `{"message": "Something went wrong"}`.

### What did not change

- Only `users` is PostgreSQL-backed. `funds`, `holdings`, `positions`, `orders`, `transactions`,
  `watchlists`, `portfolio_snapshots` and every Nova tool still use MongoDB.
- No data was copied. There is no loader, so a user that exists only in MongoDB cannot log in, and a
  user created after 3B1 exists only in PostgreSQL (§4).
- The `users` table starts empty; signup is the only way a row appears.

---

## 3Q. Phase 3B2 — market cache moved to PostgreSQL

**Goal:** move the quote cache behind `/api/market/overview`, `/api/instruments/search` and both sync
jobs from MongoDB's `marketquotes` collection to `instruments` + `latest_quotes`, without touching the
book tables. Runtime rules and field ownership: `MARKET_DATA_PLAN.md` §3.6.

### Tables and ownership

| Writer | Writes |
|---|---|
| `api/jobs/market_sync.py` | all **53 universe** instruments (3 indices + 50 stocks) with full quotes; owns `in_market_universe = true` |
| `api/jobs/price_sync.py` | `ltp`, `day_change_pct`, `updated_at`, `source_time` for held/watched/open-order symbols; inserts book-only instruments (`in_market_universe = false`) |

- `persist_market_quotes` upserts every universe symbol even when the provider returned nothing for it,
  so `instruments` can hold 53 rows while `latest_quotes` holds only usable prices. That seeding is
  deliberate and separately tested (`test_missing_provider_rows_still_seed_the_53_symbol_universe`).
- The quote upsert never writes `sector` and never moves `instruments.updated_at`. The sector backfill
  owns `sector`, is capped at 10 symbols per run and leaves `latest_quotes.updated_at` alone.
- `price_sync` writes only the four price fields, so a one-minute tick cannot blank `day_change`,
  `prev_close`, `volume`, `market_cap`, the instrument's name/kind or its universe membership.
- `price_sync` derives both writes from one provider batch. A PostgreSQL failure is logged and does not
  stop the MongoDB price update, the order fill or the MIS settlement.

### Stale quotes

`latest_quotes` keeps two timestamps apart: `updated_at` is when this service persisted the quote (the
legacy `updatedAt`, and the source of `asOf`); `source_time` is the provider's `regularMarketTime`, or
`NULL`.

- An incoming row whose `source_time` is **older** than the stored one is dropped, so a late provider
  response cannot overwrite a newer price.
- A row with **no** `source_time` is applied and clears the stored `source_time`: the price is the
  newest poll result but cannot be tied to a provider timestamp.
- A missing, zero, negative or non-numeric price never creates or overwrites a quote. A provider
  failure leaves the last good cache in place, so stale prices survive instead of blanking the Markets
  page.

### Reads and one approved ordering change

- Both routes join `instruments` to `latest_quotes` and filter `in_market_universe = true`; a seeded
  instrument with no quote stays invisible, which is what the Mongo cache did implicitly.
- The wire shape is unchanged: `_id`, `symbol`, `name`, `kind`, `sector`, `ltp`, `dayChange`,
  `dayChangePct`, `prevClose`, `volume`, `marketCap`, `createdAt`, `updatedAt`, `__v`.
- **Visible change:** overview now returns indices in `^NSEI`, `^NSEBANK`, `^BSESN` order (any unknown
  index first) and stocks by `symbol ASC`. Express returned MongoDB natural order, which happened to
  follow the seed list. This is the approved decision in `POSTGRES_SCHEMA_DESIGN.md` §2.10 and §4.13,
  because PostgreSQL has no natural order.
- Search keeps the relevance order — exact symbol, symbol prefix, name prefix, substring, then
  `symbol ASC`, limit 10 — and escapes `%` and `_` so the term is literal.

### Verification and limits

- Targeted phase suites: **163 passed** (`test_postgres_migration`, `test_postgres_models`,
  `test_auth_routes`, `test_market`, `test_instruments`, `test_market_sync`).
- Full suite: **358 passed, 7 skipped** with `TEST_DATABASE_URL`; **365 passed, 0 skipped** with
  `TEST_MONGO_URL` as well. The 7 skips are the optional real-MongoDB tests.
- The Express-vs-FastAPI **read-route parity check was not rerun** for the two market routes after the
  backend switch, so the new ordering has not been compared side by side with Express. The Phase 4b
  result in §3O describes the Mongo-backed implementation.
- While Express remains runnable, its jobs still write `marketquotes`; the two caches are independent
  and can diverge. The one-scheduler-owner rule already covers this.
- If `DATABASE_URL` is unset or unreachable, the failure is logged and `price_sync` continues on
  MongoDB: prices still update and orders still fill, but the canonical quote and the sector backfill
  are skipped.
- No loader and no `marketquotes` removal. The MongoDB cache is left in place, untouched.

---

## 3R. Phase 3B3 — PostgreSQL snapshot identity and watchlists

**Goal:** give the daily snapshot the canonical PostgreSQL user list and move the watchlist API off
MongoDB, without touching holdings, positions, orders, funds, transactions or financial workflows.

### Snapshot identity

- `record_daily_snapshot(db, session_factory=None)` enumerates ids from the PostgreSQL `users` table.
  The snapshot rows themselves are still MongoDB `portfoliosnapshots` documents, keyed by
  `ObjectId(user_id)` like every other Mongo book row.
- `PortfolioSnapshotScheduler` passes its session factory; tests can inject one. If PostgreSQL is
  unavailable, the tick logs and writes nothing.
- A user that exists only in MongoDB is no longer snapshotted. A PostgreSQL user with no holdings or
  positions still gets a zero-valued row.

### Watchlists

- `GET`, `POST` and `DELETE /api/watchlist` now use the `watchlists` table through `get_session`.
- The read keeps the ten-key document shape and orders by `created_at ASC, id ASC`. `ltp` and
  `dayChangePct` come from `latest_quotes` through `instruments`, with `0` when either is missing.
- `POST` keeps the `201` / `409` / `400` contracts, falls back `name` to `symbol`, and accepts only
  `exchange: "NSE"` (design D21/F13). The unique `(user_id, symbol)` key closes the duplicate race.
- `DELETE` stays always-`204`, including missing, non-owned and malformed ids.
- Every query is scoped to the token user; the same symbol may be watched by different users.

### Verification and limits

- Full suite: **367 passed, 7 skipped** with `TEST_DATABASE_URL`; **374 passed, 0 skipped** with
  `TEST_MONGO_URL` as well.
- The existing Mongo holdings, positions, orders, funds, transactions, snapshot-persistence,
  market-cache and price-sync suites passed unchanged.
- No loader was added, so existing MongoDB users and watchlists do not appear in PostgreSQL.

---

## 3S. Phase 3B3.1 — the remaining watchlist consumers

**Goal:** make the two code paths that still read MongoDB watchlists use the same PostgreSQL table.
No other collection or tool moved.

- `run_sync` reads watchlist symbols from `watchlists` whenever it receives a session factory, and no
  longer writes the mirrored `ltp`/`dayChangePct` onto MongoDB rows. Holdings, positions, open orders,
  quote batching, fills and MIS settlement are untouched. The MongoDB read/write remains only when no
  factory is supplied, which is the Express-parity harness path.
- A failed PostgreSQL watchlist read is logged and the run continues with holdings, positions and
  orders, so an unreadable watchlist cannot block a fill.
- Nova's `watchlist_snapshot` queries `watchlists` scoped to the token user, joins `instruments` and
  `latest_quotes`, orders by `created_at ASC, id ASC`, and reports `0` for a missing quote. Its output
  (`symbol`, `ltp`, `dayChangePct`) and summary are unchanged.
- Focused tests cover the PostgreSQL source, the untouched book path, a watchlist read failure, Nova
  ordering/isolation and empty or quote-less watchlists.

### Verification and limits

- Full suite: **373 passed, 7 skipped** with `TEST_DATABASE_URL`; **380 passed, 0 skipped** with
  `TEST_MONGO_URL` as well (6 new tests).
- There is still no automatic MongoDB → PostgreSQL loader for users or watchlists.

---

## 3T. Phase 3B4 — trading-book dependency audit (no code change)

**Goal:** find the smallest next migration slice among the remaining MongoDB-backed book data without
creating a split source of truth. The audit read the routes, `order_engine.py`, both jobs, the snapshot
math, Nova's tools, the tests and the Express-parity harness. Nothing was migrated.

### Coupling found

The five book collections form one write graph. Every collection is written by a flow that also writes
at least one other:

| Collection | Written by | Also writes |
|---|---|---|
| `funds` | placement debit, cancel refund, fill/settlement credit, sibling refund, square-off, deposit/withdrawal, first `GET /funds` | `orders`, `holdings`/`positions`, `transactions` |
| `holdings` | CNC fills, `price_sync` price refresh | `funds`, `transactions`, `orders` (on a failed sell) |
| `positions` | MIS fills, MIS exit settlement, square-off, `price_sync` price refresh | `funds`, `transactions`, `orders` |
| `orders` | placement, fills, exits, cancel, set-exits, square-off, `price_sync` claim | `funds`, `holdings`, `positions`, `transactions` |
| `transactions` | deposit/withdrawal, CNC sell, MIS exit, square-off | `funds`, `holdings`/`positions`, `orders` |

`portfoliosnapshots` is the exception: the daily job is its only writer, it is derived only from
holdings and positions, and the history route is its only reader. No trading flow reads it.

### Conclusion

There is **no safe subset** of `funds`, `holdings`, `positions`, `orders`, `transactions`. Moving any one
of them would make a single fill, cancel or square-off write across MongoDB and PostgreSQL with no shared
transaction, which is exactly the inconsistency this migration must avoid. A dual write is not a fix;
`POSTGRES_SCHEMA_DESIGN.md` §9.1 already rules it out.

**Recommended next slice — Phase 3C1: snapshot persistence.** Move `portfoliosnapshots` to
`portfolio_snapshots` and read history from PostgreSQL while the live point still comes from MongoDB.
It is one-way derived data, so a failure or rollback cannot corrupt cash, holdings or orders. It also
completes the Phase 3B3 identity work, because the job already enumerates PostgreSQL users.

**Then Phase 3C2: the whole trading book in one cutover.** `funds`, `holdings`, `positions`, `orders`
and `transactions` must move together, behind the transaction boundaries in
`POSTGRES_SCHEMA_DESIGN.md` §6.2–§6.10 and the one-shot loader in §9.

---

## 3U. Phase 3C1 — portfolio snapshots on PostgreSQL

**Goal:** move daily snapshot persistence and the historical half of `/api/portfolio/history` to the
existing `portfolio_snapshots` table, leaving the trading book on MongoDB. No migration was needed:
`0001_initial_schema.py` already had the table, the `(user_id, snapshot_date)` unique key and the
`numeric(20,4)` columns.

### Data sources after this phase

| Surface | Source |
|---|---|
| Snapshot user list | PostgreSQL `users` (unchanged from Phase 3B3) |
| Snapshot values (`value`, `invested`, `mis_value`, `mis_invested`) | MongoDB `holdings` and open MIS `positions`, using the existing formulas |
| Snapshot rows | PostgreSQL `portfolio_snapshots`, one row per user per IST day |
| `/api/portfolio/history` historical points | PostgreSQL `portfolio_snapshots`, `snapshot_date ASC` |
| `/api/portfolio/history` today point | MongoDB `holdings` + open MIS `positions`, still live |
| Old `portfoliosnapshots` documents | untouched, no longer written or read; rollback archive only |

### What changed

- `api/jobs/portfolio_snapshot.py` uses PostgreSQL `INSERT ... ON CONFLICT (user_id, snapshot_date)
  DO UPDATE`. A re-run on the same IST day updates the four numbers and `updated_at`, keeps the
  original `id`, `created_at` and `version`, and creates no duplicate. Users are enumerated in
  `created_at ASC, id ASC` order so a failure test is deterministic.
- Each user is committed in its own transaction. The surrounding `try` still stops the run on the
  first error, matching Express, but earlier users stay committed.
- `snapshot_date()` still returns the IST calendar day as a UTC-midnight datetime for the existing
  date tests; the column stores `snapshot_date().date()`.
- `api/routes/portfolio.py` reads history through `get_session`, filters on the IST calendar-day
  window (`days` points ending today) and renders `label` with `date.isoformat()`. `value` is
  `value + mis_value`; `invested` is `invested + mis_invested`, or `null` when `invested` is zero, so
  legacy rows keep their chart gap. The live today point is appended, or overwrites today's snapshot
  row, exactly as before. `float()` is applied to the `Decimal` columns so the JSON numbers match the
  old Mongo response.
- `api/tests/test_portfolio_snapshot.py`, `test_portfolio.py` and the relevant
  `test_mongo_integration.py` cases now use a real disposable PostgreSQL database; MongoDB remains
  `mongomock` except in the optional integration module.
- `tools/express-parity/` no longer runs `record_daily_snapshot()` (it would write to the configured
  PostgreSQL database) and no longer compares `portfoliosnapshots` or `portfolio/history`, because the
  two implementations no longer share a database for those surfaces.

### Historical cutover consequence

**PostgreSQL history starts empty.** Existing MongoDB snapshots are deliberately not loaded and are
not dual-written, so `/api/portfolio/history` shows only snapshots created by the job after this
phase, plus the live today point. A user with months of MongoDB history will see a chart that begins
on their first post-3C1 trading day. This is expected for this phase, not a bug; loading the archive
is a separate decision. The MongoDB collection is left in place so a rollback can still use it.

### Verification and limits

- Focused suites: **25 passed** (`test_portfolio_snapshot.py`, `test_portfolio.py`,
  `test_mongo_integration.py`) against disposable PostgreSQL and a real scratch MongoDB.
- Full suite: **373 passed, 7 skipped** with `TEST_DATABASE_URL` only (the 7 are the optional
  real-MongoDB tests); **380 passed, 0 skipped** with `TEST_MONGO_URL` as well.
- No loader, no dual write and no change to holdings, positions, orders, funds, transactions or Nova's
  other tools. No schema migration was added.
- The Express parity harness is not a PostgreSQL harness; snapshot and history parity must be covered
  by the pytest suite until a PostgreSQL-aware harness exists.

### Next

**Phase 3C2 — the whole trading book in one cutover**, as recommended in §3T. It is recorded in
§3V below; the five book collections form one write graph, so they moved together behind shared
transaction boundaries.

---

## 3V. Phase 3C2 — trading book on PostgreSQL

**The `funds`, `holdings`, `positions`, `orders` and `transactions` write paths now run on
PostgreSQL.** This is a write cutover plus the reads those routes own. The remaining portfolio
read consumers and Nova's other tools still read MongoDB and are the next stage.

### What moved

- **New shared module `api/trading_book.py`.** One place for the documented quantizers (`CASH` 2 dp,
  `PRICE` 4 dp, `AVERAGE` 6 dp, `ROUND_HALF_UP`, no intermediate per-share rounding), 24-hex ids,
  millisecond timestamps, the per-user advisory lock, the single cash-block predicate, guarded fund
  helpers and the Mongoose-shaped response serializers.
- **`api/order_engine.py`** ports `server/utils/executeOrder.js`: validation before mutation,
  weighted holdings/position merges, bracket spawning, MIS settlement, SL-M cash adjustment, status
  transitions, sibling cancellation and refunds. Business rejections raise `FillRejected`, so the
  order's stored `filled`/`price` stay untouched and the caller books `REJECTED` plus one refund.
- **`api/routes/orders.py`, `funds.py`, `holdings.py`, `positions.py`** read and write PostgreSQL.
  `holdings`/`positions` join `instruments`/`latest_quotes` for `ltp`, `dayChangePct` and `sector`
  instead of storing a second copy of the price.
- **`api/jobs/price_sync.py`** refreshes the canonical quote cache and fills OPEN orders from it.
  `api/scheduler.py` now passes only the session factory to `sync_prices`.
- **`api/market_data.fetch_quote`** carries the provider `regularMarketTime` as `sourceTime`.
- **`api/documents.py`** keeps only `utcnow()`; `new_document`/`inc_funds` had no remaining callers.

### Transaction and money rules

- Every financial flow is one database transaction: `get_session`, then
  `pg_advisory_xact_lock(hashtextextended(user_id, 0))`, then `SELECT ... FOR UPDATE` on the rows it
  moves. A failed fill cannot leave a partial debit, position, order status or ledger row.
- Status changes are conditional (`UPDATE ... WHERE status = 'OPEN' RETURNING`). A fill or cancel
  that loses the race matches no row, so proceeds and refunds are booked at most once. The second
  scheduled tick sees no OPEN order for an executed one.
- Placement validates before debit. Orders that block cash are debited once; cancellation refunds
  exactly `(qty - filled) * price`; a rejected fill is refunded once. A rejected order is adjusted
  for SL-M only after it settles, never before.
- MIS exits release the entry notional for the exited quantity plus/minus realised P&L. A full exit
  deletes the position row because the `qty > 0` check constraint forbids writing zero; a partial
  exit keeps the remaining quantity.
- OCO sibling cancellation runs only when an **exit** fills. A bracket entry anchors its group and
  spawns exits, which must stay OPEN.

### API-visible changes (intentional)

1. **The book is NSE-only**, matching the PostgreSQL check constraints. An order or exit request with
   any other `exchange` is rejected with **400 `"Unsupported exchange"`**; omitting it defaults to
   `NSE`.
2. **A MARKET order needs a fresh provider time.** If the quote is missing, has no
   `regularMarketTime`, is older than 10 minutes, or is more than 2 minutes in the future, placement
   returns **503** rather than filling from a stale price. Scheduled fills likewise leave the order
   OPEN until a trustworthy quote arrives.
3. **An oversized MIS exit is rejected, not capped.** The position, funds and ledger are left
   untouched. Legacy Express released `min(position.qty, order.qty)` and then deleted the whole
   position; both behaviours are fixed (known issues 4 and 9).
4. **A repeated or raced square-off returns 404 `"Position not found"`** once the first call has
   deleted the row, instead of a race-specific 409. The delete and its cash/settlement/order writes
   are one transaction.
5. **`fetch_quote` now includes `sourceTime`.** Callers that compared the exact dict shape were
   updated; the legacy keys are unchanged.
6. **The response envelopes and field names are unchanged** (`{message}` errors, Mongoose-shaped
   `_id`/`user`/`__v`, camelCase book fields), so the frontend needs no change.

### Verification and limits

- Focused trading-book suites: **108 passed** (`test_holdings.py`, `test_positions.py`,
  `test_orders.py`, `test_funds.py`, `test_order_fills.py`, `test_price_sync.py`) against a
  disposable PostgreSQL database.
- Full suite: **401 passed, 7 skipped** with `TEST_DATABASE_URL` only (the 7 are the optional
  real-MongoDB tests); **408 passed, 0 skipped** with `TEST_MONGO_URL` as well.
- No Express `server/` change, no MongoDB loader, no dual write, no Redis/WebSockets, and no new
  schema migration: the existing book tables and constraints were sufficient.
- Still on MongoDB by design: the live portfolio point and daily snapshot book read, Nova's
  holdings/positions/orders/funds tools, and any other portfolio-history consumer. Search/watchlist
  and market data remain on their Phase 3B PostgreSQL paths.
- The optional Express parity harness is not a PostgreSQL harness, so these flows are covered by
  pytest until a PostgreSQL-aware harness exists.

### Next

Migrate the remaining portfolio read consumers and Nova's book-backed tools, then retire the
MongoDB book collections once no reader remains.

---

## 3W. Phase 3C2-B — the remaining trading-book readers on PostgreSQL

The live portfolio point, the daily snapshot's book read and Nova's five book tools
(`getPortfolioSummary`, `getHoldings`, `getPositions`, `getFunds`, `getOrders`) now read
PostgreSQL. They were the last FastAPI readers of the MongoDB book collections.

### What changed

- `api/trading_book.py` gained three shared read helpers — `holding_rows()`, `position_rows()`
  and `portfolio_totals()` — that return Mongoose-named dicts with `Decimal` values and join
  `latest_quotes` for `ltp`/`dayChangePct` (`0` when a symbol has no quote). The chart, the
  snapshot job and Nova all call them, so the three cannot drift apart.
- `GET /api/portfolio/history`'s live today point and `api/jobs/portfolio_snapshot.py` both call
  `portfolio_totals(session, user_id)`. The route still returns plain JSON numbers, an empty book
  still yields zeros, and the today label is still the IST day.
- Nova's `*_snapshot()` helpers take `(user_id, session_factory=None)` like `watchlist_snapshot`,
  `NovaDeps` is now only `user_id`, and the chat route no longer needs a Mongo `db`, so a chat
  turn without a tool call does not open PostgreSQL.
- `api/portfolio_math.py`'s `mis_components()` now does `Decimal` arithmetic, because its inputs
  are `Numeric` columns; the values it returns are unchanged.
- `record_daily_snapshot()` and `PortfolioSnapshotScheduler` dropped their unused `db` parameter.

### Verification and limits

- Focused: **18 passed** (`test_portfolio.py`, `test_portfolio_snapshot.py`) after the
  portfolio/snapshot batch, then **17 passed** (`test_assistant.py`,
  `test_assistant_trading_book.py`) after the Nova batch.
- Full suite: **405 passed, 7 skipped** with `TEST_DATABASE_URL` only (the 7 are the optional
  real-MongoDB tests); **412 passed, 0 skipped** with `TEST_MONGO_URL` too.
  `python -m compileall -q api` is clean.
- No FastAPI code reads a MongoDB book collection any more: searching `api/` outside the tests
  and migrations for `get_collection`, `db[` and `portfoliosnapshots` finds nothing.
- Still on MongoDB, deliberately: the `db.connect()` startup wiring and `app.state.db` (a missing
  `MONGO_URL` still stops startup), the unused `db` parameters on `MarketSyncScheduler`,
  `PriceSyncScheduler` and the insight/briefing routes, and the Express reference in `server/`.
- `test_mongo_integration.py` kept its `TEST_MONGO_URL` gate even though it no longer reads book
  collections, so the PostgreSQL-only skip count stays at 7.

### Next

Nothing in FastAPI still reads the MongoDB book, and the `db` plumbing was removed in Phase 3C2-C
(§3Y). The remaining collections are archived data only: Phase 3C-D decided on a clean PostgreSQL start,
so no loader, reconciliation or collection retirement is required before deployment (§3Z).

---

## 3X. Phase 3C2 — live watchlist quotes over WebSockets

A push channel beside the existing watchlist REST API, so the page can show a price change
without waiting for the 30-second poll.

`GET /api/watchlist/stream` upgrades to a WebSocket. The handshake reuses the `token` cookie
through `user_from_token`, which is the body of the existing HTTP guard; a missing or invalid
token is accepted and then closed with `1008`, because a browser cannot read a close code from
a rejected handshake and would otherwise retry forever.

Each socket is registered against the JWT's user id, and every publish rebuilds its frames from
that user's `watchlists` rows joined to `instruments`/`latest_quotes`. Add and remove therefore
apply while a socket is open, and one user's symbols never reach another user's socket.
`price_sync` calls `publish_persisted_quotes` only after its quote transaction commits, so a
frame never carries a price that is not in `latest_quotes`; a failed read is logged and dropped
so live delivery cannot fail the job that also fills orders.

The frontend keeps `GET /api/watchlist` for the first paint and the existing poll as a fallback.
`useWatchlistStream` opens after the first load, merges frames by watchlist row id, reuses the
existing flash animation, retries with a 5–30 s backoff and treats `1008` as terminal; unmount
closes the socket and clears the retry timer.

Focused tests: **59 passed** (`test_watchlist_stream.py`, `test_watchlist.py`,
`test_price_sync.py`) against a disposable PostgreSQL database. The full suite is **410 passed,
7 skipped** with `TEST_DATABASE_URL` only and **417 passed, 0 skipped** with `TEST_MONGO_URL` too;
`python -m compileall -q api`, `npm run lint` and `npm run build` pass (the build keeps its
pre-existing >500 kB chunk warning). Details: `docs/migration/WATCHLIST_WEBSOCKETS.md`.

---

## 3Y. Phase 3C2-C — the WebSocket branch merged, and a PostgreSQL-only runtime

Phase 3C2-B and `phase3c2-ws-watchlist` were merged on `phase3c2-final-cutover`. The only conflict was
this file, where §3W and §3X were both kept. The merge changed no runtime behaviour: WebSocket
authentication still uses the `token` cookie, each socket still sees only its own user's watchlist rows,
and frames are still published only after `price_sync`'s PostgreSQL commit.

MongoDB is no longer part of the FastAPI runtime. `api/db.py` is deleted, `create_app()` takes no
`database` argument, startup opens no MongoDB connection, shutdown closes none, and `app.state.db` is
gone. `Settings` no longer reads `MONGO_URL`; `MarketSyncScheduler` and `PriceSyncScheduler` take only a
PostgreSQL session factory; and the insight/briefing routes no longer declare an unused `Database`
dependency. `test_health.py` now proves startup with `MONGO_URL` unset, and the two "injected database"
tests became real startup-wiring tests that assert each scheduler starts and stops under its switch.
`mongomock` left `api/requirements-dev.txt`; `pymongo` stays because `api/serialization.py` serialises
with `bson.ObjectId`, and the `TEST_MONGO_URL` integration suite stays as the compatibility check that
the retired collections are untouched.

The app was run twice against one disposable PostgreSQL database — once with `MONGO_URL` unset and once
pointing at an unreachable port (`mongodb://127.0.0.1:1/...`). Both runs served `/api/health`, signup,
`/api/auth/me`, funds, holdings, positions, orders, portfolio history, watchlist, `/api/market/overview`
and an authenticated `/api/watchlist/stream` handshake with `2xx` responses and a clean shutdown;
`app.state` had no `db` and `pymongo` was never imported.

Focused integration: **192 passed** (watchlist stream, watchlist, price sync, auth, auth routes,
portfolio, portfolio snapshot, assistant, Nova trading book, market sync). Focused MongoDB-removal run:
**222 passed** (the same set plus health, CORS, static, database errors, market, instruments). Full suite
**414 passed, 7 skipped** with `TEST_DATABASE_URL` only and **421 passed, 0 skipped** with `TEST_MONGO_URL`
too; `python -m compileall -q api` passes. No frontend file changed in this phase, so lint/build were not
rerun. `server/` (Express) is untouched. Nothing was pushed or deployed.

---

## 3Z. Phase 3C-D — release readiness and the clean-start decision

**Decision: PostgreSQL starts empty.** The existing MongoDB trading-book data is inconsistent and
disposable, so it is **not** migrated. No loader, dual write or reconciliation process is built, and the
MongoDB databases are left in place, untouched, as an archive rather than a runtime dependency. In
practice:

- Existing MongoDB users, watchlists, snapshots and trading-book rows (funds, holdings, positions,
  orders, transactions) will **not** appear in PostgreSQL.
- Users create fresh PostgreSQL accounts after cutover; each starts with an empty book, a zero balance and
  a portfolio history that shows the live "today" point from day one and stores a daily point from the
  first snapshot the job writes.
- MongoDB remains available read-only as an archive, and is not read or written by the FastAPI runtime
  (§3Y). Nothing was deleted.
- If legacy data ever needs to be preserved, that is separate migration work, and the loader and
  reconciliation gates designed in `POSTGRES_SCHEMA_DESIGN.md` §9 are the starting point.

The documents that still framed this as open were corrected: the status table and §7 item 11 in this file,
the §3W "Next" note, the §8 WebSocket bullet (superseded by §3X), and the header plus §9 note in
`POSTGRES_SCHEMA_DESIGN.md`. `DEPLOYMENT.md` was rewritten for a PostgreSQL-only service — environment
variables, `DIRECT_DATABASE_URL` and `alembic upgrade head`, the start command, cookie/CORS/HTTPS
requirements, the scheduler switches and the liveness-only health check.

Both documented commands were validated against a disposable PostgreSQL 17.6 database
(`tradium_release_check_test`, created and dropped for this check):

- `alembic upgrade head` with only `DIRECT_DATABASE_URL` set created the schema and stamped
  `alembic_version = 0001` (11 tables). Without `DIRECT_DATABASE_URL` it stops with
  `RuntimeError: DIRECT_DATABASE_URL is not set` — there is no fallback to `DATABASE_URL`.
- `uvicorn api.main:app --host 127.0.0.1 --port 8011` with `DATABASE_URL`, `JWT_SECRET` and
  `NODE_ENV=production`, no `MONGO_URL` and no `dist/` build: `/api/health` returned `200`, signup returned
  `201` with `token` set as `HttpOnly; Secure; SameSite=strict; Path=/; Max-Age=604800`, and `/api/auth/me`,
  `/api/funds`, `/api/holdings`, `/api/orders`, `/api/portfolio/history`, `/api/watchlist` and
  `/api/market/overview` all returned `200`. `/dashboard` returned the JSON 404 because the build was
  absent, with the expected "run `npm run build`" warning in the log.

No application code changed in this phase, so the suite was not rerun; the Phase 3C2-C totals
(**414 passed, 7 skipped** and **421 passed, 0 skipped**) still describe the branch.

---

## 3AA. Phase 3C-E — Render deployment configuration

**The deployment is now described in the repository.** `render.yaml` at the root defines one Python web
service (`tradium-fastapi`) and one PostgreSQL database (`tradium-postgres`) in the same region, wired
together through the database's internal `connectionString`; `.python-version` pins Python 3.13, the
version the migration was developed on.

- **Build:** `npm ci --include=dev && npm run build && pip install -r api/requirements.txt`.
  `--include=dev` is required because the service sets `NODE_ENV=production`, and `npm ci` would
  otherwise omit Vite and the other devDependencies.
- **Pre-deploy:** `alembic upgrade head`, with `DIRECT_DATABASE_URL` supplied explicitly from the
  database. Pre-deploy commands require a paid instance type.
- **Start:** `uvicorn api.main:app --host 0.0.0.0 --port $PORT --proxy-headers
  --forwarded-allow-ips='*'`. Render's Python runtime already sets `FORWARDED_ALLOW_IPS=*`; the explicit
  flag keeps the rate-limiter requirement visible. The service is a `0.5c-512mb` instance so there is no
  idle spin-down and one scheduler owner.
- **Health check:** `/api/health` (liveness only, as before).
- **Secrets:** `JWT_SECRET` uses Render's `generateValue`; `GOOGLE_GENERATIVE_AI_API_KEY` uses
  `sync: false`, so it is entered privately in the dashboard. No secret is committed.
- **Jobs:** `MARKET_SYNC_ENABLED` and `TRADING_JOBS_ENABLED` are explicitly `"false"`, matching the code
  default. `numInstances: 1` keeps one owner when they are enabled later.
- **Frontend:** `NODE_ENV=production` turns on static serving, and `SERVE_STATIC=true` states it
  explicitly. One origin means the `Secure` cookie and the `/api/watchlist/stream` WebSocket need no
  CORS; `CORS_ORIGINS` stays unset.

Validated locally against the disposable `tradium_render_check` database (created and dropped for this
check), using Render-shaped plain `postgresql://` URLs:

- `alembic upgrade head` created the schema (`alembic_version = 0001`, 11 tables) and a second run was a
  no-op. This also confirmed that SQLAlchemy 2.1.6 resolves the plain scheme Render supplies to the
  installed psycopg 3 driver.
- `npm ci --include=dev` and `npm run build` succeeded with `NODE_ENV=production`, producing
  `dist/index.html` and the hashed `/assets/*` files.
- `uvicorn` with the Blueprint's environment (including the proxy flags) served `/` and `/dashboard` as
  the SPA shell, `/favicon.svg` and a hashed asset with `200`s, returned the JSON 404 for an unknown
  `/api` path, accepted signup (`201`, `HttpOnly; Secure; SameSite=strict; Path=/; Max-Age=604800`),
  served authenticated funds and watchlist routes, accepted the watchlist WebSocket with the token cookie
  and closed it with `1008` without one.
- With `--forwarded-allow-ips='*'`, 21 rate-limited signup requests carrying distinct `X-Forwarded-For`
  values were all rejected as `400` and none as `429`; the 21st request from one address got `429`.
- `python -m compileall -q api` passed. The local server process used about 120 MB after startup, well
  inside the 512 MB plan; watch for exit 137 under Nova load.

`render.yaml` was checked locally against Render's published Blueprint fields, plan IDs and regions.
The Render CLI is not installed, so `render blueprints validate` was not run, and nothing was deployed.

---

## 3AB. Phase 3C-F — legacy Express/MongoDB cleanup

**The active tree now matches the intended architecture.** With every FastAPI surface on PostgreSQL, the
unused Express reference and the MongoDB dependency were removed rather than kept for history.

- **Removed `server/`** (38 files): the Express app, routers, controllers, Mongoose models, jobs, seed and
  backfill scripts, and its `package.json`/lockfile. Nothing imported it: the React build, `scripts/`,
  `render.yaml` and the FastAPI runtime all use `api/`. Its cron jobs were never started by the parity
  harness, and the deployed Express service is a separate Render resource that this repository does not
  manage.
- **Removed `tools/express-parity/`** (14 files): the Phase 2e/4b harness loaded the Express modules and
  `pymongo` directly, so it could not run after the Express removal. Its results stay recorded in §3K and
  `TEST_PLAN.md`.
- **Removed the MongoDB Python dependency:** `pymongo==4.19.0` left `api/requirements.txt`,
  `api/serialization.py` lost its `bson.ObjectId` branch (PostgreSQL ids are already 24-hex strings), and
  the test suite lost its `bson` imports and unused Mongoose-shaped fixtures.
- **`test_mongo_integration.py` became `test_postgres_integration.py`:** the real-PostgreSQL book reads,
  write routes, scheduled fill/snapshot and auth round-trip tests are preserved; the scratch MongoDB
  fixture and the "Mongo stays untouched" assertions were removed with the dependency.
- **Removed `api/yahoo_stream.py`, its 17 tests and the captured-frame fixture:** a Phase 2b decoder proof
  of concept with no runtime consumer; the REST quote path is the shipped implementation.
- **Documentation:** `README.md`, `AGENTS.md`, `api/.env.example` and `DEPLOYMENT.md` now describe only the
  FastAPI/PostgreSQL setup. The MongoDB archive itself, the clean-start decision (§3Z) and the historical
  phase records are unchanged; the deployed Express service was not touched.

Verification: the full backend suite with only `TEST_DATABASE_URL`, `python -m compileall -q api`,
`npm run lint`, `npm run build`, and a FastAPI start with no `MONGO_URL` and no MongoDB client installed.

---

## 4. Known issues recorded

These were found during the audit and are documented in `CURRENT_ARCHITECTURE.md` §9. Issues 1–3 and
the SHORT P&L sign were fixed in the FastAPI Nova port during Phase 3b (see §3M), because the tools
were being written from scratch and reproducing known-broken output would bake the defects into the
new backend. The Express reference (removed in Phase 3C-F; Git history keeps it) still had the original
behaviour. Everything else is
unchanged.

1. ~~Nova `getOrders` returns `quantity` where the schema field is `qty`.~~ **Fixed in FastAPI.**
2. ~~Nova `getOrders` filters lowercase statuses while stored values are uppercase.~~ **Fixed in FastAPI.**
3. ~~Nova `getFunds` reads a non-existent `used` field.~~ **Fixed in FastAPI** (derived
   `usedMargin = blockedInOrders + misMargin`).
4. ~~`POST /api/orders` debits funds before the CNC holdings check and does not refund on rejection.~~
   **Fixed in Phase 3C2** (validation before debit; a rejected fill refunds once).
5. Price sync runs every minute; project documentation says every 5 minutes.
6. `npm start` uses `node`, not nodemon, contrary to project documentation.
7. `DELETE /api/watchlist/:id` returns 204 even when nothing matched.
8. Market-hours logic has no exchange holiday calendar.
9. ~~`settleMisExit` deletes an MIS position unconditionally after a partial fill, so an exit larger
   than the remaining quantity still removes the whole position.~~ **Fixed in Phase 3C2** (oversized
   exits are rejected; partial exits keep the remainder).
10. ~~Nova `getPositions` reported SHORT P&L with the long-side sign.~~ **Fixed in FastAPI.**

Items 5–8 are still reproduced as-is; fix separately with approval (AD-9).

### Introduced or exposed by the move to PostgreSQL

11. **Identity is split across two databases.** `record_daily_snapshot` now enumerates the PostgreSQL
    `users` table (Phase 3B3), so a user created after Phase 3B1 does receive snapshots. The remaining
    gap is data: a user that exists only in MongoDB cannot log in (authentication reads PostgreSQL), and
    a MongoDB-only watchlist is invisible to `GET /api/watchlist`. There is no loader in either
    direction. This must be closed before any deployment that expects existing accounts and watchlists
    to keep working.
12. **Two market caches exist while Express is runnable.** `server/jobs/marketSync.js` still writes
    `marketquotes`; the FastAPI jobs write `instruments`/`latest_quotes`. They are independent. The
    single-scheduler-owner rule keeps both from refreshing at once, but a dormant cache will go stale and
    must not be read by anything.
13. ~~Nova's watchlist tool read the wrong collection (`db["watchlist"]`; the real one is
    `watchlists`).~~ **Fixed in Phase 3B3.1.** The tool now reads PostgreSQL `watchlists` joined to
    `instruments`/`latest_quotes`, scoped to the token user. It is recorded in `POSTGRES_AUDIT.md`
    §5 issue 5.
14. ~~`price_sync` sourced watchlist symbols from MongoDB.~~ **Fixed in Phase 3B3.1.** With a session
    factory it reads the PostgreSQL `watchlists` table and leaves the MongoDB mirror alone; the MongoDB
    read/write remains only for the Express-parity harness path, which has no session factory.
15. **`DEPLOYMENT.md` is stale.** Its environment table does not list `DATABASE_URL`, does not mention
    `DIRECT_DATABASE_URL`/`alembic upgrade head`, and still implies MongoDB alone is sufficient. The code
    is correct; the deployment guide was outside this slice.
16. **The MongoDB snapshot archive is not loaded.** Since Phase 3C1 the job writes only PostgreSQL
    `portfolio_snapshots`. Existing MongoDB `portfoliosnapshots` documents are untouched but invisible
    to `/api/portfolio/history`, so every user's PostgreSQL history starts at their first post-3C1
    snapshot (plus the live point). See §3U.

---

## 5. Checks actually run

| Check | Result |
|---|---|
| Original repository `git status --short` | clean |
| Original repository HEAD / branch / remote | recorded in §2 |
| New directory pre-existence check | absent before creation |
| `git archive` file count | 177 |
| Env-file presence in the copy | only `server/.env.example` |
| Secret-pattern scan of tracked files | no matches |
| New repo `git log` | one commit, baseline snapshot |
| New repo `git remote -v` | **empty** |
| Pre-commit secret scan of all 9 staged files | no credential patterns matched |
| Staged file set | 9 Markdown files only; no application file touched (2,683 insertions, 0 deletions) |
| Application tests (Phase 1f) | **run:** 91 passed, 6 skipped; 97 passed with `TEST_MONGO_URL` |
| Registered routes (Phase 1f) | **verified** — 21 operations: the 10 reads, the 7 writes, and the 4 auth routes (`POST` signup/login/logout, `GET /me`) |
| Application tests (Phase 2a) | **run:** 114 passed, 6 skipped; 120 passed with `TEST_MONGO_URL` |
| Application tests (Phase 2b) | **run:** 131 passed, 6 skipped; 137 passed with `TEST_MONGO_URL` |
| Application tests (Phase 2c) | **run:** 197 passed, 7 skipped; 204 passed with `TEST_MONGO_URL` |
| Application tests (Phase 2d) | **run:** 242 passed, 8 skipped; 250 passed with `TEST_MONGO_URL` |
| Mongoose `save()` / order-claim / snapshot-upsert shapes (Phase 2d) | **observed** — `mongoose.set("debug")` against a scratch `*_test` DB; `save()` sets changed fields plus `updatedAt` and leaves `__v`; the snapshot upsert uses `$setOnInsert` for `createdAt`/`__v: 0` |
| Job settlement and snapshot against a real MongoDB (Phase 2d) | **verified** — price refresh, sector backfill, MIS exit settlement (funds/ledger/position delete) and the daily snapshot upsert all run on real BSON types; scratch DB dropped afterwards |
| Trading-job scheduler default (Phase 2d) | **verified** — off unless `TRADING_JOBS_ENABLED` is truthy; never started for an injected test database; price sync still honours the market-hours gate |
| Live startup wiring (Phase 2d) | **verified** — `create_app()` with `TRADING_JOBS_ENABLED=true` starts the price and snapshot schedulers while `MARKET_SYNC_ENABLED` remains off; the closed-market startup tick left every dev-DB collection count unchanged |
| Registered routes (Phase 2c) | **verified** — 24 operations: the 13 reads, the 7 writes and the 4 auth routes; the new ones are `GET /api/instruments/lookup/{symbol}` and `GET /api/instruments/{symbol}` |
| Yahoo quote handshake | **verified** — `fc.yahoo.com` → `getcrumb` → `/v7/finance/quote`; the `finance.yahoo.com/quote/AAPL` bootstrap used by `yahoo-finance2` returns no cookie to `requests` |
| Batch quote from Python | **verified** — 53/53 tickers in one request, `missing: []` |
| Quote field parity vs `yahoo-finance2` | **verified** — identical for `RELIANCE`, `^NSEI`, `^NSEBANK`, `^BSESN`, `M&M` across price, change, pct, prevClose, volume, marketCap and longName |
| Mongoose bulkWrite document shape | **observed** — `mongoose.set("debug")` against a scratch `*_test` DB; `$setOnInsert` carries `createdAt`/`sector:""`/`__v:0`, `$set` carries the eight quote fields plus `updatedAt` |
| Mongoose `save()` on sector backfill | **observed** — refreshes `updatedAt`, leaves `__v` at 0; a no-op save writes nothing |
| `marketSync` against `tradium_fastapi_dev` | **verified** — 53 rows (50 stocks + 3 indices), all nine fields present, `^NSEI` marketCap 0, indices' volume 0 |
| Sector cap per run | **verified** — 10 resolved on the first run, 10 more on the second |
| Cache-backed routes after the sync | **verified** — `/api/instruments/search` and `/api/market/overview` return real rows instead of `[]` |
| Live quote routes through the real app | **verified** — lookup and detail return 200 with live prices; unknown symbol → 404 `"Instrument not found"`; no cookie → 401 |
| Staleness evidence | **measured** — `regularMarketTime` ages 1 s / 106 s / 903 s at 15:31 IST; a 5-minute cutoff would reject a current quote |
| Scheduler default | **verified** — off unless `MARKET_SYNC_ENABLED` is truthy; never started for an injected test database |
| Yahoo streamer reachable for `.NS` symbols | **verified** — live session, 2026-10-19 13:57–14:11 IST; equities and `^` indices both streamed |
| Stream vs REST price agreement | **verified** — Δ0.4 / Δ0.0 / Δ0.3 for `RELIANCE` / `INFY` / `^NSEI` |
| Streamer reconnect after an abrupt abort | **verified** — handshake 1.77 s, first frame 2.40 s |
| Streamer silently ignores unknown symbols | **verified** — no frames, no error, for `NOTAREALSYMBOL.NS` and `ZZZZ.NS` |
| Evaluated streaming stack removed | **verified** — `pip check` clean, 137 tests pass without yfinance/pandas/numpy; no new dependency added |
| Registered routes (Phase 2a) | **verified** — 22 operations: the 11 reads, the 7 writes and the 4 auth routes; the new one is `GET /api/instruments/{symbol}/candles` |
| Candle parity vs `yahoo-finance2` | **verified** — 16/16 identical for `RELIANCE` and `^NSEI` across all eight ranges, against a scratch `yahoo-finance2` reference built outside this repository |
| Candles through the real app over the live network | **verified** — 246 bars (`RELIANCE`/`1M`), 375 (`^NSEI`/`1D`), 5 (`^NSEI`/`SPARK`); unknown symbol → 404 with the Express message; no cookie → 401 |
| `yfinance` and its pandas/numpy stack removed | **verified** — `pip check` reports no broken requirements and the suite still passes, so `requirements.txt` is sufficient |
| Write flow against a real MongoDB | **verified** — deposit, watchlist add/delete, two MARKET fills into one merged position, square-off, LIMIT place + cancel; scratch DB dropped afterwards |
| Auth round-trip against a real MongoDB | **verified** — signup → cookie → login → `/me` with the `users` collection; scratch DB dropped afterwards |
| bcrypt cross-implementation | **verified** — an npm `bcrypt` hash verifies in Python and a Python hash verifies in the npm package (Node v22, out-of-tree) |
| Rate limiter | **verified** — the 21st guarded attempt is a 429 with the documented body; logout and `/me` are never limited |
| Write residue in `tradium_fastapi_dev` | **marketquotes cache only** — 53 rows written by the Phase 2c sync against the local dev DB; the Phase 2d jobs ran only on mongomock and `*_test` scratch DBs, so no orders, funds, holdings, positions or snapshots were created in the dev DB |
| Local `mongod` reachability | **verified** — admin `ping` ok on `127.0.0.1:27017` |
| Effective dev database name | **verified** — `tradium_fastapi_dev`, from a normal `create_app()` startup |
| `zerodha` database | untouched — same 9 collections, no writes |
| Lint / build in the new repo (Phase 3a) | **pass** — `npm run lint` clean; `npm run build` produced the Vite 8.1.5 bundle |
| Repository root / branch / remotes before writing | verified: `Tradium-FastAPI`, `migration/fastapi-backend`, **no remote** |
| Scratch database after the integration run | absent from `list_database_names()`; `zerodha` untouched |
| Express reference harness (Phase 2e) | **run** — module-level only (`server/index.js` never loaded): 7 auth steps, the real `GET /api/holdings` body, and `syncPrices` + `settleMisExit` + `recordDailySnapshot` side effects compared on identical input; **no functional difference** (§3K) |
| Job side effects vs Express (Phase 2e) | **verified** — 7 collections identical including BSON numeric types; the only divergence is `int32` vs `double` on the two snapshot MIS fields (values equal) |
| Auth cookies vs Express (Phase 2e) | **verified** — `Max-Age`, `Path`, `HttpOnly`, `SameSite`, `Secure`, deletion on logout and the JWT claims all equivalent; header differences are informational only |
| Numeric rendering vs Express (Phase 2e) | **verified** — whole floats render `2500` vs `2500.0`; identical after `JSON.parse`; dates, ObjectIds and integers identical |
| Application tests (Phase 3a) | **run:** 246 passed, 8 skipped; the four new CORS tests cover all five Vite ports, credentials, rejection and the env override |
| Live CORS preflight (Phase 3a) | **verified** — 200 with the exact `http://localhost:5173` origin and `Access-Control-Allow-Credentials: true` |
| Browser signup/login/reload/logout (Phase 3a) | **verified** — UI signup 201 → dashboard, reload restored the session via `/me` 200, UI login 200, logout 200 → `/login`, then `/dashboard` redirected to `/login` |
| Main pages against FastAPI (Phase 3a) | **verified** — holdings, positions, orders, watchlist, funds and markets rendered their empty states with all data requests 200; no CORS console errors |
| Deferred Nova endpoints (Phase 3a) | **observed** — `/api/assistant/briefing` and `/insight` 404; the insight card degrades to "Insight unavailable right now." |
| Scratch database after Phase 3a | **dropped** — `tradium_fastapi_phase3a_test` absent; `tradium_fastapi_dev` untouched; `zerodha` still 9 collections |
| Application tests (Phase 3b) | **run:** 259 passed, 8 skipped; the 13 new assistant tests cover auth, payload validation, missing configuration, text and tool SSE, insight/briefing text, tool parity, SHORT P&L, cross-user isolation and date serialization |
| PydanticAI stream protocol (Phase 3b) | **verified** — `VercelAIAdapter(sdk_version=7)` emits `start`, `start-step`, `tool-input-start`, `tool-input-available`, `tool-output-available`, text deltas and `finish` frames |
| Live Gemini from the FastAPI app (Phase 3b) | **verified** — chat returned grounded `getHoldings` output; insight and briefing returned `text/plain` with correct ₹ formatting |
| Browser Nova chat (Phase 3b) | **verified** — one-tool and two-tool turns rendered as tool cards plus a grounded answer in the unmodified panel |
| Browser briefing and insight (Phase 3b) | **verified** — dashboard briefing and Holdings insight showed real portfolio numbers |
| Tool-defect fixes (Phase 3b) | **verified** — `qty`, case-insensitive uppercase status and derived blocked margin all showed in the live two-tool answer |
| Missing-key behaviour (Phase 3b) | **verified** — all three routes return 503 when `GOOGLE_GENERATIVE_AI_API_KEY` is unset |
| Scratch database after Phase 3b | **dropped** — `tradium_fastapi_phase3b_test` absent; `tradium_fastapi_dev` and `zerodha` untouched |
| Application tests (Phase 4a) | **run:** 269 passed, 8 skipped; 277 passed with `TEST_MONGO_URL`; the 10 new static tests cover deep links, assets, API passthrough, JSON 404s, default-off and missing-build handling |
| Frontend build (Phase 4a) | **pass** — `npm run lint` clean and `npm run build` produced `dist/` (Vite 8.1.5, 59 assets) |
| Static serving over HTTP (Phase 4a) | **verified** — `/` and deep links (`/dashboard`, `/login`, `/dashboard/holdings`) return the app shell; `/assets/*` and `/favicon.svg` return their files; `NODE_ENV=production` alone enables it |
| API isolation (Phase 4a) | **verified** — `/api/health` returns `{"ok":true}`; `/api` and unknown `/api/*` return the JSON 404, never the SPA shell |
| Production cookie (Phase 4a) | **verified** — `NODE_ENV=production` sets `Secure; HttpOnly; SameSite=strict; Path=/; Max-Age=604800`, and the browser kept the session over `http://localhost` |
| Same-origin production browser flow (Phase 4a) | **verified** — login, all six dashboard pages, briefing, a page insight and a Nova tool call against the FastAPI-served build with no CORS |
| Missing AI key while serving static (Phase 4a) | **verified** — static and API stay up; the three assistant routes return 503 |
| Scheduler ownership at startup (Phase 4a) | **verified** — with both switches unset the startup log shows no job line; jobs stay opt-in |
| Scratch database after Phase 4a | **dropped** — `tradium_fastapi_phase4a_test` absent; `tradium_fastapi_dev` and `zerodha` untouched |
| Read-route parity (Phase 4b) | **verified** — 9 GET routes compared live against Express over one seeded fixture; `compare.py` reported `identical` (closes rows 1D.16, 2B.1, 2C.1) |
| Route-harness isolation (Phase 4b) | **verified** — `server/index.js` never required, no Yahoo call, scratch `tradium_parity_*` databases dropped; none left behind |
| Secret scan (Phase 4b) | **clean** — no API keys, private keys, credential URLs or JWTs in tracked files; the original `.env` values are absent; `.env` has never been committed |
| Repository hygiene (Phase 4b) | **fixed** — `CLAUDE.md` and `.claude/launch.json` untracked (files kept on disk), `.claude/` added to `.gitignore` |
| Application tests (Phase 4b) | **not rerun** — no application code changed, so `269 passed, 8 skipped` / `277` with `TEST_MONGO_URL` from Phase 4a stands |
| Alembic migration (Phase 3B1) | **verified** — `alembic upgrade head` on an empty PostgreSQL 17.6 database created all 10 tables plus `alembic_version`; `alembic current` reported `0001 (head)`; the upgrade is repeatable |
| Schema tests (Phase 3B1) | **run** — `test_postgres_migration.py` and `test_postgres_models.py` cover table/column types, checks, uniques, FKs, partial and descending indexes, id formats and the quote cascade |
| Authentication against PostgreSQL (Phase 3B1) | **verified** — signup, login and `/me` read `users` in PostgreSQL; duplicate signup and the unique-constraint race return 400; a PostgreSQL 24-hex id still opens Mongo-backed routes; malformed id → 404; bcrypt hashes work both ways |
| Market cache against PostgreSQL (Phase 3B2) | **verified** — 53 universe instruments seeded, usable quotes upserted, repeated syncs neither duplicate nor blank metadata, book-only instruments do not join the universe |
| Stale-quote handling (Phase 3B2) | **verified** — an older `source_time` does not overwrite a newer quote; a missing one is applied and clears the stored value; an unusable price never creates or overwrites a row |
| Price sync dual-write (Phase 3B2) | **verified** — one provider batch updates the Mongo `ltp`/`dayChangePct` and upserts the PostgreSQL quote; a PostgreSQL failure is logged and the Mongo fill path still completes |
| Application tests with no database configured (Phase 3B1/3B2) | **run:** 282 passed, 83 skipped — `TEST_DATABASE_URL` unset, so every PostgreSQL-dependent test skips instead of failing |
| Targeted phase suites (Phase 3B1/3B2) | **run:** 163 passed — `test_postgres_migration`, `test_postgres_models`, `test_auth_routes`, `test_market`, `test_instruments`, `test_market_sync` |
| Application tests (Phase 3B1/3B2) | **run:** 358 passed, 7 skipped with `TEST_DATABASE_URL` only (the 7 are the optional real-MongoDB tests); 365 passed, 0 skipped with `TEST_MONGO_URL` too |
| Test PostgreSQL instance (Phase 3B1/3B2) | disposable local PostgreSQL **17.6** cluster on `127.0.0.1:5433`, database `tradium_phase3b_wrapup_test`; `initdb` trust auth; outside the repository |
| Scratch databases after Phase 3B2 | **dropped** — `tradium_fastapi_phase3b_test` absent from MongoDB; `tradium_fastapi_dev` and `zerodha` untouched |
| Snapshot user enumeration (Phase 3B3) | **verified** — `record_daily_snapshot` reads ids from the PostgreSQL `users` table; a PostgreSQL-only user gets a zero-valued row; a MongoDB-only user is not snapshotted |
| Watchlist API on PostgreSQL (Phase 3B3) | **verified** — GET/POST/DELETE use the `watchlists` table; ten-key document shape, `created_at ASC, id ASC` ordering, `ltp`/`dayChangePct` from `latest_quotes`, `0` when missing |
| Watchlist contracts (Phase 3B3) | **verified** — `201` on create, `409` on duplicate, `400` on invalid body, always-`204` delete, `name` falls back to `symbol`, per-user isolation |
| Application tests (Phase 3B3) | **run:** 367 passed, 7 skipped with `TEST_DATABASE_URL` only (the 7 are the optional real-MongoDB tests); 374 passed, 0 skipped with `TEST_MONGO_URL` too |
| Test PostgreSQL instance (Phase 3B3) | disposable local PostgreSQL **17.6** cluster on `127.0.0.1:5433`, database `tradium_phase3b_wrapup_test`; `initdb` trust auth; outside the repository |
| Price-sync watchlist source (Phase 3B3.1) | **verified** — with a session factory the job quotes PostgreSQL `watchlists` symbols, leaves the MongoDB mirror untouched, and still fills open limit orders; holdings and positions are unchanged |
| Watchlist read failure (Phase 3B3.1) | **verified** — a failing PostgreSQL watchlist query is logged and the book refresh still runs |
| Nova watchlist tool (Phase 3B3.1) | **verified** — reads the token user's PostgreSQL rows in `created_at`/`id` order, joins quotes, reports `0` for missing quotes, and returns an empty list for a user with none |
| Application tests (Phase 3B3.1) | **run:** 373 passed, 7 skipped with `TEST_DATABASE_URL` only; 380 passed, 0 skipped with `TEST_MONGO_URL` too (6 new tests) |
| Snapshot persistence on PostgreSQL (Phase 3C1) | **verified** — the job inserts one `portfolio_snapshots` row per PostgreSQL user; a second run updates the same `id`/`created_at` instead of inserting; a zero-holding user still gets a zero row |
| Snapshot failure behaviour (Phase 3C1) | **verified** — a bad holding aborts the remaining users without raising, and users already processed stay committed; a failing PostgreSQL enumeration logs and writes nothing |
| Portfolio history mixed source (Phase 3C1) | **verified** — historical points come from `portfolio_snapshots` in ascending order with IST day labels; `invested` is `null` for a zero/legacy row; the live today point still comes from real MongoDB holdings/positions, and an existing today row is overwritten |
| Application tests (Phase 3C1) | **run:** 373 passed, 7 skipped with `TEST_DATABASE_URL` only; 380 passed, 0 skipped with `TEST_MONGO_URL` too; focused snapshot/portfolio/integration run **25 passed** |
| Test PostgreSQL instance (Phase 3C1) | disposable local PostgreSQL **17.6** cluster on `127.0.0.1:5433`, database `tradium_phase3c1_test`; `initdb` trust auth; outside the repository; dropped after the run |
| Express parity harness after the snapshot move (Phase 3C1) | **updated, not rerun** — `recordDailySnapshot`/`record_daily_snapshot` and the `portfoliosnapshots` dump were removed, and `portfolio/history` was removed from the route list, because FastAPI now uses PostgreSQL for both |
| Application tests (Phase 3C2-B) | **run:** 405 passed, 7 skipped with `TEST_DATABASE_URL` only; 412 passed, 0 skipped with `TEST_MONGO_URL` too; focused runs **18 passed** (portfolio + snapshot) and **17 passed** (assistant + Nova book tools) |
| MongoDB book readers after Phase 3C2-B | **none** — searching `api/` outside tests and migrations for `get_collection`, `db[` and `portfoliosnapshots` returns nothing; the live portfolio point, snapshot job and Nova's five tools all read PostgreSQL |
| Test PostgreSQL instance (Phase 3C2-B) | local PostgreSQL **17.6** cluster on `127.0.0.1:5433`, database `tradium_phase3c2b_test`; `initdb` trust auth; outside the repository |
| Application tests (Phase 3C2-C) | **run:** 414 passed, 7 skipped with `TEST_DATABASE_URL` only; 421 passed, 0 skipped with `TEST_MONGO_URL` too; focused **192 passed** (integration) and **222 passed** (MongoDB removal); `python -m compileall -q api` passes; frontend untouched |
| FastAPI MongoDB runtime after Phase 3C2-C | **none** — `api/db.py` deleted, no `MONGO_URL` setting, no `app.state.db`, no scheduler or route `db` parameter; `python` runs with `MONGO_URL` unset and with it pointed at a dead port, and `pymongo` is not imported at runtime |
| Test PostgreSQL instance (Phase 3C2-C) | local PostgreSQL **17.6** cluster on `127.0.0.1:5433`, database `tradium_final_cutover_test`; outside the repository |
| Application tests (Phase 3C2-D) | **not rerun** — documentation only, no application code changed; the Phase 3C2-C totals (**414**/**421**) stand. Validated instead on a disposable `tradium_release_check_test`: `alembic upgrade head` through `DIRECT_DATABASE_URL`, and a live `uvicorn` run with `NODE_ENV=production`, no `MONGO_URL` and no `dist/` build (§3Z) |
| Render configuration (Phase 3C-E) | **not rerun** — no application code changed; the Phase 3C2-C totals still stand. Validated instead on a disposable `tradium_render_check` database: the Blueprint's plain `postgresql://` URLs migrate to `0001` (11 tables, second run a no-op), `npm ci --include=dev && npm run build` succeeds with `NODE_ENV=production`, and the Blueprint's `uvicorn` command serves the SPA, hashed assets, signup with the production cookie, authenticated routes and the watchlist WebSocket, with per-IP rate limiting through the proxy headers; `python -m compileall -q api` passes (§3AA) |
| Test PostgreSQL instance (Phase 3C-E) | disposable local PostgreSQL **17.6** cluster on `127.0.0.1:5433`, database `tradium_render_check`; created and dropped around the check; outside the repository |

---

## 6. Blockers

### 6.1 GitHub publication — BLOCKED (unchanged in Phase 4b)

- `gh` is **not installed** on this machine (command not found).
- No authenticated GitHub CLI session exists.
- No remote is configured in the new repository (`git remote -v` is empty).

Nothing was worked around through the original repository, and no credentials were handled. The local
repository is fully initialized and safe to push once a remote exists. Phase 4b confirmed the working
tree contains no secrets and untracked the two local artifacts (`CLAUDE.md`, `.claude/launch.json`).

**Manual steps (run from `D:\deepak\coding\Full Stack Dev\Tradium-FastAPI`):**

```bash
# 1. Create a private repository named tradium-fastapi in the GitHub UI (do not initialise it
#    with a README, .gitignore, or licence).

# 2. Add it as the only remote.
git remote add origin https://github.com/<your-account>/tradium-fastapi.git

# 3. Confirm the remote, the branches and a clean tree before pushing.
git remote -v                      # exactly one URL, the NEW empty repo
git branch -a                      # main and migration/fastapi-backend
git branch --show-current          # expect: migration/fastapi-backend
git status --short                 # expect: empty
git log --oneline -1               # expect: the latest Phase 3B1/3B2 commit

# 4. Push the baseline and the migration branch.
git push -u origin main
git push -u origin migration/fastapi-backend
```

Before pushing, confirm `git remote -v` shows exactly one URL and that it points at the **new** empty
repository — not `gorddeepak/Tradium`. The repository is private; do not add the original
repository as a remote or push to it.

### 6.2 Nothing else is blocking Phase 1

Phase 1 still needs an isolated MongoDB and seeded demo data, but that is a Phase 1 prerequisite, not a
Phase 0 blocker.

---

## 7. Unresolved decisions

From `ARCHITECTURE_DECISIONS.md`:

1. ~~Exact MongoDB collection names~~ — **resolved**: confirmed read-only against the local database
   metadata (`orders`, `watchlists`, `positions`, `funds`, `transactions`, `holdings`, …).
2. Whether PydanticAI's `VercelAIAdapter` matches `@ai-sdk/react` 4.0.61.
3. ~~Whether Yahoo streaming delivers messages for exact `.NS` symbols~~ — **resolved (Phase 2b)**: it
   does, for equities and indices, but it is **not adopted** because it cannot supply `marketCap` or
   `sector` and is not needed at the frontend's 30 s poll interval; see §3H.
4. ~~Which candle intervals/ranges `yfinance` returns identically~~ — **resolved (Phase 2a)**: three
   of eight. `yfinance` was rejected for candles and Yahoo's chart endpoint is called directly; see
   §3G and `MARKET_DATA_PLAN.md` §3.1.
5. Whether Yahoo data is permitted for the intended display and deployment.
6. The approved fallback if streaming fails.
7. Current Render build/start configuration (not in the repository).
8. Whether the FastAPI service replaces the existing Render service or is added alongside it.
9. Whether the two job switches — `MARKET_SYNC_ENABLED` for the cache and `TRADING_JOBS_ENABLED` for
   order filling and snapshots — should ever both be set in one production process, and which service
   owns them once Express is retired.
10. Where PostgreSQL runs, whether connections are pooled (PgBouncer/Neon-style) and what the pool
    limits are. `DATABASE_URL` is pooled, `DIRECT_DATABASE_URL` is direct; no host has been chosen.
11. ~~**How existing data reaches PostgreSQL, and in what order.**~~ — **resolved (Phase 3C-D): it does
    not.** The deployment starts on an empty PostgreSQL database, the MongoDB data is kept as an
    untouched archive, and no loader, dual write or reconciliation is built. See §3Z.
12. When Express's `marketquotes` cache is retired. It is still written by the Express jobs and must not
    be read once the FastAPI service is the only backend.

---

## 8. Explicitly not approved / not done

- No route beyond the twenty-seven ported operations: the 13 reads (`GET /api/health`, `GET /api/holdings`,
  `GET /api/orders`, `GET /api/watchlist`, `GET /api/positions`, `GET /api/funds`,
  `GET /api/funds/transactions`, `GET /api/portfolio/history`, `GET /api/instruments/search`,
  `GET /api/instruments/lookup/{symbol}`, `GET /api/instruments/{symbol}`,
  `GET /api/instruments/{symbol}/candles`, `GET /api/market/overview`), the 7 writes (`POST`/`DELETE
  /api/watchlist`, `POST /api/funds/transactions`, `POST`/`DELETE /api/orders`, `POST /api/orders/exits`,
  `POST /api/positions/:id/square-off`), the 4 auth routes (`POST /api/auth/signup`,
  `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`) and the 3 assistant routes
  (`POST /api/assistant/chat`, `POST /api/assistant/insight`, `POST /api/assistant/briefing`).
- The per-minute `priceSync`, `settleMisExit` and the daily `portfolioSnapshot` **are ported**, but both
  schedulers are **off by default**; neither was enabled against any deployment, so the FastAPI app does
  not refresh prices or fill orders on its own yet. `price_sync` now also upserts the PostgreSQL quote,
  and both schedulers fall back to `DATABASE_URL` at tick time rather than at startup.
- No exchange holiday calendar, no staleness cutoff on quotes (deliberate — see §3I), and no auto
  square-off of open MIS positions at the close (Express has none).
- ~~No WebSocket, streaming, or push channel **in the application**~~ — **superseded (Phase 3C2):** the
  watchlist streams over `GET /api/watchlist/stream` (§3X). The Yahoo market-data stream is still not
  used: Phase 2b evaluated it offline and kept only a decoder module plus its tests.
- CORS is limited to the default Vite origins plus whatever `CORS_ORIGINS` names; there is no wildcard
  and no origin reflection.
- No write to the `zerodha` database and no production data copied into `tradium_fastapi_dev`.
- **No Express *server* was started.** The Phase 2e harness imports individual Express modules on an
  ephemeral port against scratch databases; `server/index.js`, its cron registrations and its static
  frontend mount were never executed.
- No AI model *generation* beyond the three Nova routes; no agentic features, background AI jobs,
  embeddings, or vector store. Insight and briefing fire only on page visit/data change.
- No production frontend deployment and no deployed CORS origin; FastAPI now **can** serve `dist/`
  with an SPA fallback (Phase 4a), but no service was deployed.
- No change to `server/` or the original repository; `src/` changed only for the API origin and the
  signup call (§3L).
- **Schema created on a disposable test cluster only.** `alembic upgrade head` was applied to
  `tradium_phase3b_wrapup_test` on a local PostgreSQL 17.6 instance. No production database was
  contacted, no developer PostgreSQL database was written, and no data was copied from MongoDB.
- No PostgreSQL reads or writes for `funds`, `holdings`, `positions`, `orders`, `transactions`,
  `watchlists` or `portfolio_snapshots`, even though the tables exist. Those routes and the Nova tools
  remain MongoDB-only.
- No one-shot data loader and no dual-read/dual-write for book data. Users and the market cache are the
  only PostgreSQL-backed surfaces.
- No `marketquotes` backfill, drop or retirement, and no Express scheduler change. Express remains
  runnable and still writes its own cache.
- No parity rerun for the two PostgreSQL-backed read routes (`/api/market/overview`,
  `/api/instruments/search`) after the move; their new ordering is approved but not compared live
  against Express.
- No Render service created, modified, or deployed.
- No change to the original repository's history, branch, remotes, or working tree.
- No merge of `migration/fastapi-backend` into `main`.
- No secret rotation, and no attempt to remove anything from the original Git history.

---

## 9. Immediate next step

**Phases 3B1-3C-F are complete and awaiting review.** Authentication, the market cache, watchlists
(including the live WebSocket stream), price-sync watchlist symbols, Nova's `getWatchlist`, portfolio
snapshots and the whole trading book — including its last readers — are PostgreSQL-backed, and the
FastAPI runtime no longer needs MongoDB at all, and Phase 3C-F removed the Express reference, the parity
harness and the last MongoDB dependency. The suite reports **403 passed, 0 skipped** with
`TEST_DATABASE_URL` alone. The branch is still local-only; nothing was deployed.

**The deployment is described in the repository; applying it is a dashboard step.** `render.yaml` (§3AA)
provisions one Python web service and one PostgreSQL database in the same region, and runs
`alembic upgrade head` as the pre-deploy command with `DIRECT_DATABASE_URL` supplied explicitly. To use it:
push the branch to a Git provider, create a Render Blueprint from the repository, enter
`GOOGLE_GENERATIVE_AI_API_KEY` when prompted, and deploy. The Blueprint uses paid plans on purpose — the
free web plan cannot run a pre-deploy command and spins down after 15 idle minutes (stopping the
schedulers and dropping WebSockets), and free Postgres expires after 30 days. Both scheduler switches stay
`"false"` until the Express crons are stopped; see §3J for ownership and `DEPLOYMENT.md` §5 and §7.6 for
the switch-on sequence. The exact steps, verified commands and limitations are in
[`DEPLOYMENT.md`](../DEPLOYMENT.md) §7.

No data migration is required or planned: users sign up fresh, and MongoDB stays untouched as an archive
(§3Z). Nothing is left to reconcile before this deployment; the loader and reconciliation design in
`POSTGRES_SCHEMA_DESIGN.md` §9 applies only if a later decision preserves legacy data.

Deferred, unchanged: an exchange holiday calendar, a quote-age cutoff, the remaining Express-defect
fixes (orders debit/refund, `settleMisExit` partial fill), and publication to a remote (§6.1).
