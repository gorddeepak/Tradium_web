# Migration Status

**Last updated:** 2026-10-19 (Phase 3b)
**Current phase:** **Phase 3b — Nova assistant and insight endpoints**
**Application code modified:** **Yes.** CORS settings and the Nova assistant under `api/`, the frontend
API origin and signup call under `src/`; `server/` and the original repository are untouched.
**Phase 0 docs commit:** `629af4d Phase 0: migration docs and repository guidance`
(`migration/fastapi-backend`, local only — not pushed; see §6.1)

---

## 1. Current state at a glance

| Item | Value |
|---|---|
| Phase | 3b — Nova chat, page insights and dashboard briefing |
| FastAPI application | **started** — the 13 read routes, the 7 write routes, the 4 auth routes and the 3 assistant routes (27 registered operations) |
| Market cache | `marketquotes` populated for **53/53** symbols in `tradium_fastapi_dev`; scheduler **off unless `MARKET_SYNC_ENABLED` is set** |
| Trading jobs | per-minute `priceSync` (fills orders, settles MIS exits) and the daily 18:00 IST snapshot; **off unless `TRADING_JOBS_ENABLED` is set** |
| Express backend | unchanged, retained in-tree as reference |
| Frontend | **switched** to FastAPI on `localhost:8000`; `VITE_API_URL` still overrides |
| CORS | Vite dev origins (5173-5177) with credentials; `CORS_ORIGINS` overrides for deployed origins |
| Development MongoDB | **local** `mongodb://127.0.0.1:27017/tradium_fastapi_dev` via gitignored `api/.env` |
| Test MongoDB | in-memory `mongomock` plus the guarded `*_test` scratch DB; `MONGO_URL` is never used |
| Production MongoDB | never contacted; no data copied |
| New repository path | `D:\deepak\coding\Full Stack Dev\Tradium-FastAPI` |
| Intended GitHub repository | `tradium-fastapi` (private) |
| GitHub push | **BLOCKED** — no `gh` CLI and no authenticated remote |
| Branch for migration work | `migration/fastapi-backend` |
| Source snapshot | `23099b7 single service deployment - Express serves the built frontend` |
| Original repository | `D:\deepak\coding\Full Stack Dev\Zerodha` — untouched |
| Production (Render) | untouched; no service, branch, or env changes |
| Tests executed | **259 passed, 8 skipped** (default); **267 passed** with `TEST_MONGO_URL` — see §5 |
| Express parity check | **run** — cookies, numeric rendering and job side effects compared against the original modules; **no functional difference** (§3K) |
| Browser cutover check | **run** — signup, login, reload, logout and all six dashboard pages against a live FastAPI server (§3L) |
| Nova browser check | **run** — dashboard briefing, a page insight, and chat with one- and two-tool turns against live Gemini (§3M) |

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

## 4. Known issues recorded

These were found during the audit and are documented in `CURRENT_ARCHITECTURE.md` §9. Issues 1–3 and
the SHORT P&L sign were fixed in the FastAPI Nova port during Phase 3b (see §3M), because the tools
were being written from scratch and reproducing known-broken output would bake the defects into the
new backend. The Express reference in `server/` still has the original behaviour. Everything else is
unchanged.

1. ~~Nova `getOrders` returns `quantity` where the schema field is `qty`.~~ **Fixed in FastAPI.**
2. ~~Nova `getOrders` filters lowercase statuses while stored values are uppercase.~~ **Fixed in FastAPI.**
3. ~~Nova `getFunds` reads a non-existent `used` field.~~ **Fixed in FastAPI** (derived
   `usedMargin = blockedInOrders + misMargin`).
4. `POST /api/orders` debits funds before the CNC holdings check and does not refund on rejection.
5. Price sync runs every minute; project documentation says every 5 minutes.
6. `npm start` uses `node`, not nodemon, contrary to project documentation.
7. `DELETE /api/watchlist/:id` returns 204 even when nothing matched.
8. Market-hours logic has no exchange holiday calendar.
9. `settleMisExit` deletes an MIS position unconditionally after a partial fill, so an exit larger than
   the remaining quantity still removes the whole position.
10. ~~Nova `getPositions` reported SHORT P&L with the long-side sign.~~ **Fixed in FastAPI.**

Items 4–9 are still reproduced as-is; fix separately with approval (AD-9).

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

---

## 6. Blockers

### 6.1 GitHub publication — BLOCKED

- `gh` is **not installed** on this machine (command not found).
- No authenticated GitHub CLI session exists.
- No remote is configured in the new repository.

Nothing was worked around through the original repository, and no credentials were handled. The local
repository is fully initialized and safe to push once a remote exists.

**Manual steps (run from `D:\deepak\coding\Full Stack Dev\Tradium-FastAPI`):**

```bash
# 1. Create a private repository named tradium-fastapi in the GitHub UI (do not initialise it
#    with a README, .gitignore, or licence).

# 2. Add it as the only remote.
git remote add origin https://github.com/<your-account>/tradium-fastapi.git

# 3. Confirm the remote and branch before pushing.
git remote -v
git branch --show-current          # expect: migration/fastapi-backend
git log --oneline -1

# 4. Push the baseline and the migration branch.
git push -u origin main
git push -u origin migration/fastapi-backend
```

Before pushing, confirm `git remote -v` shows exactly one URL and that it points at the **new** empty
repository — not `gorddeepak/Tradium`.

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
  not refresh prices or fill orders on its own yet.
- No exchange holiday calendar, no staleness cutoff on quotes (deliberate — see §3I), and no auto
  square-off of open MIS positions at the close (Express has none).
- No WebSocket, streaming, or push channel **in the application**: no socket is opened at runtime and
  no streamed data reaches the database. Phase 2b evaluated the stream offline and added only a
  decoder module plus its tests.
- CORS is limited to the default Vite origins plus whatever `CORS_ORIGINS` names; there is no wildcard
  and no origin reflection.
- No write to the `zerodha` database and no production data copied into `tradium_fastapi_dev`.
- **No Express *server* was started.** The Phase 2e harness imports individual Express modules on an
  ephemeral port against scratch databases; `server/index.js`, its cron registrations and its static
  frontend mount were never executed.
- No AI model *generation* beyond the three Nova routes; no agentic features, background AI jobs,
  embeddings, or vector store. Insight and briefing fire only on page visit/data change.
- No production frontend deployment, no FastAPI static `dist/` mount, and no deployed CORS origin.
- No change to `server/` or the original repository; `src/` changed only for the API origin and the
  signup call (§3L).
- No database migration, schema change, or write to the application database.
- No Render service created, modified, or deployed.
- No change to the original repository's history, branch, remotes, or working tree.
- No merge of `migration/fastapi-backend` into `main`.
- No secret rotation, and no attempt to remove anything from the original Git history.

---

## 9. Immediate next step

**Phase 3b complete (Nova assistant, insights and briefing). Awaiting review.** The React app now runs
end-to-end against FastAPI in local development, including the assistant. Nothing further will be
implemented without approval.

Open items:

0. **Nova is ported and verified** (§3M): chat, insight and briefing routes stream with the same
   protocols as Express, the six tools return request-scoped data, and four Express tool defects were
   fixed deliberately with tests. The step cap is configured but not adversarially probed, and there
   is no provider retry policy.

1. **The harness blocker is gone for module-level comparisons.** `tools/express-parity/` now compares
   auth cookies, `GET /api/holdings` JSON and the three jobs against the real Express modules without
   booting the app or touching real data (§3K). The remaining `PENDING` rows are the *HTTP-level*
   comparisons for orders, watchlist, positions, funds, portfolio history and the market routes; the
   same harness can host them.
2. **Quotes are not age-checked.** Missing, non-numeric, zero and negative prices are rejected; a
   quote that is minutes old is accepted, because a cutoff would have rejected a legitimately current
   `^BSESN` quote (§3I). Whether to add one — and at what threshold — is a decision, not a bug fix.
3. **Nothing is scheduled by default.** Enabling the cache is `MARKET_SYNC_ENABLED=true`; enabling
   order filling and the daily snapshot is `TRADING_JOBS_ENABLED=true`, each on exactly one process.
   Until then prices only move through the write routes and the cache only fills by calling
   `market_sync` manually.
4. **Numeric rendering is closed** (§3E, §3K): whole floats differ only in their JSON spelling and no
   client can observe it. The residual `int32` vs `double` type difference on the two snapshot MIS
   fields is recorded, not fixed.
5. **Cookie parity is closed** (§3K): identical `Max-Age`, `Path`, `HttpOnly`, `SameSite`, `Secure`,
   deletion on logout and JWT claims; only `Expires` presence, attribute order and the empty-value
   quoting differ. Cross-app cookie validation still needs the same `JWT_SECRET` as Express.
6. **The local cutover is complete** (§3L): CORS works with credentials, signup/login/reload/logout and
   all six dashboard pages were exercised in a browser against a live FastAPI process, and the signup
   caller now sends `{ username, email, password }`.
7. Remaining before a production cutover: FastAPI does not serve `dist/` yet. Either add the static
   mount (planned for Phase 4) or deploy the frontend separately and list its origin in `CORS_ORIGINS`.
8. Recommended next, in order:
   1. The remaining HTTP-level parity rows, if wanted, using the committed harness.
   2. FastAPI static `dist/` serving, as the first production-cutover item.
   3. A step-cap probe and a live provider-error probe to close the two `PARTIAL` rows in
      `AI_INTEGRATION_PLAN.md` §11, if wanted.
   4. Any remaining Express-defect decisions (orders debit/refund, `settleMisExit` partial fill).
