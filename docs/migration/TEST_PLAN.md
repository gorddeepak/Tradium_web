# Test Plan

**Status convention for every row**

| Status | Meaning |
|---|---|
| `PLANNED` | Written down, not run |
| `IMPLEMENTED` | Test code exists, not executed |
| `ATTEMPTED` | Executed, result not yet judged |
| `PASSED` | Executed and observed correct |
| `FAILED` | Executed and observed incorrect |
| `BLOCKED` | Cannot run; prerequisite missing |
| `DEFERRED` | Intentionally out of scope this phase; a dependency (e.g. a market-data provider) is missing |

**Rules**

1. Do not claim a test passed unless it was executed and the result observed. Record the observation,
   not an intention.
2. Do not run tests against the production database.
3. Do not mutate production data to create fixtures.
4. A test that cannot run because it needs an isolated database is `BLOCKED`, not `PASSED`.

---

## 0. Baseline: what exists today

| Check | Status | Evidence |
|---|---|---|
| Automated test suite in the copied source | **VERIFIED ABSENT** | no test runner in either `package.json`; no `*.test.*` / `*.spec.*` files |
| Lint | available | `npm run lint` |
| Frontend build | available | `npm run build` |
| Manual UI verification | required | no substitute exists |

Consequence: **there is no original test suite to compare against.** Phase 1 parity testing means
comparing Express responses to FastAPI responses directly, using the same seeded data.

---

## 1. Prerequisites

| Item | Needed for | Status |
|---|---|---|
| Isolated MongoDB (local or scratch), never production | every parity test | **AVAILABLE** — local `mongod` on 127.0.0.1:27017; `tradium_fastapi_phase1_test` used and dropped |
| Seeded demo data: ≥2 users, holdings, positions, orders in each status, funds, transactions, snapshots | most tests | **PLANNED** |
| Express reference running on a spare port, pointed at the scratch DB | parity tests | **PLANNED** |
| FastAPI app running against the same scratch DB | Phase 1+ | **PLANNED** |
| Gemini key with quota | AI tests | **BLOCKED** until Phase 3 |
| Recorded resolved npm versions | AI protocol tests | **BLOCKED** until dependencies are installed |

**Fixture policy:** create fixtures only in an isolated database with safe demo configuration. If that
is not available, mark dependent tests `BLOCKED` and record the prerequisite. Never extract production
data as a fixture.

---

## 1A. Phase 1a results — `GET /api/holdings`

Executed 2026-10-18. Fast suite uses `mongomock`; the integration test uses a real local MongoDB at
`mongodb://127.0.0.1:27017/tradium_fastapi_phase1_test`, refuses any database name not ending in
`_test`, and drops it afterwards.

| # | Test | Expected | Status | Evidence |
|---|---|---|---|---|
| 1A.1 | App starts with an injected database | health 200, no real connection | **PASSED** | `test_health.py::test_app_starts_when_database_is_injected` |
| 1A.2 | `/api/health` | 200 `{ ok: true }`, no auth | **PASSED** | `test_health.py::test_health_returns_ok_without_auth` |
| 1A.3 | Unknown route | 404 `{ message: "Route not found" }` | **PASSED** | `test_health.py::test_unknown_route_matches_express_404_shape` |
| 1A.4 | Missing cookie | 401 `{ message: "Not authenticated" }` | **PASSED** | `test_auth.py` (6 tests: missing, empty, wrong secret, expired, malformed, no `id`) |
| 1A.5 | Invalid / expired token | 401 `{ message: "Invalid or expired token" }` | **PASSED** | same file |
| 1A.6 | Valid token, no rows | 200 `[]` | **PASSED** | `test_auth.py`, `test_holdings.py` |
| 1A.7 | User isolation | only the cookie user's rows | **PASSED** | `test_holdings.py::test_returns_only_the_cookie_users_holdings` |
| 1A.8 | Caller-supplied `user`/`userId` ignored | token decides | **PASSED** | `test_holdings.py::test_user_id_from_query_or_body_is_ignored` |
| 1A.9 | Response key set | same 13 keys as Mongoose, incl. `__v` | **PASSED** | `test_holdings.py::test_response_shape_matches_mongoose_serialization` |
| 1A.10 | ObjectId → 24-char hex | no wrapper text | **PASSED** | `test_holdings.py`, `test_serialization.py` |
| 1A.11 | Date → `YYYY-MM-DDTHH:MM:SS.mmmZ` UTC | exactly 3 decimals | **PASSED** | `test_serialization.py` (6 cases incl. IST input) |
| 1A.12 | Malformed ObjectId claim | 500 `{ message: "Something went wrong" }` | **PASSED** | `test_holdings.py::test_malformed_user_id_in_token_returns_server_error` |
| 1A.13 | Database failure | 500, generic message, no leak | **PASSED** | `test_database_errors.py` |
| 1A.14 | Real MongoDB read | same shape/timestamps | **PASSED** | `test_mongo_integration.py` (1 passed) |
| 2A.1 | Live side-by-side vs Express on identical data | byte-identical body | **PENDING** | Express entry point starts cron jobs; a safe reference harness does not exist yet |
| 2A.2 | `Set-Cookie` comparison from login | same attributes | **BLOCKED** | login route is not in Phase 1a |

Suite totals: **23 passed, 1 skipped** without `TEST_MONGO_URL`; **24 passed** with it.

---

## 1B. Phase 1b results — `GET /api/orders` and `GET /api/watchlist`

Executed 2026-10-18. Fast suite uses `mongomock`; the integration test reuses the guarded scratch
database (`tradium_fastapi_phase1_test`, name must end in `_test`, dropped afterwards).

| # | Test | Expected | Status | Evidence |
|---|---|---|---|---|
| 1B.1 | `GET /api/orders` returns only the cookie user's orders | other user's rows absent | **PASSED** | `test_orders.py::test_returns_only_the_cookie_users_orders` |
| 1B.2 | Orders newest first | `createdAt` descending | **PASSED** | `test_orders.py::test_orders_are_newest_first` |
| 1B.3 | Order response key set | the 20 Mongoose keys incl. `__v` | **PASSED** | `test_orders.py::test_response_shape_matches_mongoose_serialization` |
| 1B.4 | No orders | 200 `[]` | **PASSED** | `test_orders.py::test_empty_orders_returns_empty_list` |
| 1B.5 | `GET /api/watchlist` returns only the cookie user's rows | other user's rows absent | **PASSED** | `test_watchlist.py::test_returns_only_the_cookie_users_watchlist` |
| 1B.6 | Watchlist response key set | the 10 Mongoose keys incl. `__v` | **PASSED** | `test_watchlist.py::test_response_shape_matches_mongoose_serialization` |
| 1B.7 | No watchlist rows | 200 `[]` | **PASSED** | `test_watchlist.py::test_empty_watchlist_returns_empty_list` |
| 1B.8 | Real MongoDB read of `orders` + `watchlists` | correct rows, BSON dates to the ms | **PASSED** | `test_mongo_integration.py::test_orders_and_watchlist_read_real_mongo_documents` |
| 2B.1 | Live side-by-side vs Express on identical data | byte-identical body | **PENDING** | Express entry point starts cron jobs; no safe reference harness yet |

Suite totals: **30 passed, 2 skipped** without `TEST_MONGO_URL`; **32 passed** with it.

Auth rejection, token-claim isolation, malformed-claim 500 and database-failure 500 are shared with
the holdings suite through the same `require_user` dependency and error handlers, so they are not
re-tested per route.

Not verified for these routes: no live Express comparison; `POST`/`DELETE` behaviour is out of scope
(not ported); nothing deployed.

---

## 1C. Phase 1c results — local dev database, `GET /api/positions`, `GET /api/funds`

Executed 2026-10-18.

### Development database configuration

| # | Check | Expected | Status | Evidence |
|---|---|---|---|---|
| 1C.0a | `api/.env` load | `MONGO_URL` resolves at import | **PASSED** | `import api.config` → db name `tradium_fastapi_dev` |
| 1C.0b | Local `mongod` reachable | admin `ping` ok | **PASSED** | `db.connect()` then `admin.command("ping")` |
| 1C.0c | Normal startup selects the dev DB | `app.state.db.name == "tradium_fastapi_dev"` | **PASSED** | `create_app()` + lifespan, no injected database |
| 1C.0d | Server is local | host `127.0.0.1:27017` | **PASSED** | `client.address` |
| 1C.0e | Test DB stays separate | `_test`-suffixed guard intact | **PASSED** | integration fixture refuses non-`_test` names |
| 1C.0f | `zerodha` untouched | same 9 collections | **PASSED** | `list_collection_names()` |

### Endpoints

| # | Test | Expected | Status | Evidence |
|---|---|---|---|---|
| 1C.1 | `GET /api/positions` returns only the cookie user's rows | other user's rows absent | **PASSED** | `test_positions.py::test_returns_only_the_cookie_users_positions` |
| 1C.2 | Position response key set | the 13 Mongoose keys incl. `__v` | **PASSED** | `test_positions.py::test_response_shape_matches_mongoose_serialization` |
| 1C.3 | No positions | 200 `[]` | **PASSED** | `test_positions.py::test_empty_positions_returns_empty_list` |
| 1C.4 | `GET /api/funds` derived maths | `usedMargin = blockedInOrders + misMargin`; correct `realizedPnl` | **PASSED** | `test_funds.py::test_derived_margins_and_realized_pnl` |
| 1C.5 | First read creates an empty funds row | `available: 0`, row persisted | **PASSED** | `test_funds.py::test_creates_an_empty_funds_row_on_first_read` |
| 1C.6 | Real MongoDB read of positions + funds | correct rows, BSON dates, maths | **PASSED** | `test_mongo_integration.py::test_positions_and_funds_read_real_mongo_documents` |
| 2C.1 | Live side-by-side vs Express on identical data | byte-identical body | **PENDING** | no safe reference harness |

Suite totals: **35 passed, 3 skipped** without `TEST_MONGO_URL`; **38 passed** with it.

Not verified: no live Express comparison; `GET /api/funds/transactions` and all write routes are not
ported; nothing deployed.

---

## 1D. Phase 1d results — transactions, portfolio history, instrument search, market overview

Executed 2026-10-18. Fast suite uses `mongomock`; the integration test reuses the guarded scratch
database (`tradium_fastapi_phase1_test`, name must end in `_test`, dropped afterwards).

### Funds transactions

| # | Test | Expected | Status | Evidence |
|---|---|---|---|---|
| 1D.1 | `GET /api/funds/transactions` returns only the cookie user's rows | other user's rows absent | **PASSED** | `test_funds.py::test_transactions_are_newest_first_and_user_scoped` |
| 1D.2 | Transactions newest first | `createdAt` descending | **PASSED** | same test |
| 1D.3 | Transaction shape and empty list | 10 Mongoose keys incl. `__v`; `[]` when none | **PASSED** | `test_funds.py::test_transactions_shape_and_empty` |

### Portfolio history

| # | Test | Expected | Status | Evidence |
|---|---|---|---|---|
| 1D.4 | No snapshots | today's live point only (holdings + MIS) | **PASSED** | `test_portfolio.py::test_live_point_only_when_no_snapshots` |
| 1D.5 | Snapshots ascending, legacy rows | `label` `YYYY-MM-DD`; `invested: null` for pre-`invested` rows | **PASSED** | `test_portfolio.py::test_snapshots_ascending_with_null_invested_for_legacy_rows` |
| 1D.6 | Duplicate today point | overwritten, not duplicated | **PASSED** | `test_portfolio.py::test_todays_snapshot_is_overwritten_not_duplicated` |
| 1D.7 | Range fallbacks | unknown range behaves as 30 days | **PASSED** | `test_portfolio.py::test_unknown_range_falls_back_to_thirty_days` |

### Instruments and market (cache-backed)

| # | Test | Expected | Status | Evidence |
|---|---|---|---|---|
| 1D.8 | Search matches symbol or name | case-insensitive; renamed keys `price`/`changePct` | **PASSED** | `test_instruments.py::test_matches_symbol_or_name_case_insensitively`, `::test_renames_fields_for_the_client` |
| 1D.9 | Search regex characters | treated literally | **PASSED** | `test_instruments.py::test_limits_to_ten_and_treats_regex_characters_literally` |
| 1D.10 | Search empty / whitespace `q` | `[]` | **PASSED** | `test_instruments.py::test_empty_query_returns_empty_list` |
| 1D.11 | Search cap | at most 10 rows | **PASSED** | `test_instruments.py::test_limits_to_ten_and_treats_regex_characters_literally` |
| 1D.12 | Overview cold cache | `asOf: null`, empty arrays | **PASSED** | `test_market.py::test_cold_cache_returns_nulls_and_empty_lists` |
| 1D.13 | Overview index ordering | order from `data/nifty50.js`; `stocks` only `kind: "stock"` | **PASSED** | `test_market.py::test_indices_follow_seed_order_and_stocks_are_split_out` |
| 1D.14 | Overview `asOf` + row keys | freshest `updatedAt`; Mongoose key set preserved | **PASSED** | `test_market.py::test_as_of_is_the_freshest_row_and_rows_keep_mongoose_keys` |
| 1D.15 | Real MongoDB read | `portfoliosnapshots`, `marketquotes`, `transactions` resolve | **PASSED** | `test_mongo_integration.py::test_portfolio_market_search_and_transactions_read_real_mongo_documents` |
| 1D.16 | Live side-by-side vs Express on identical data | byte-identical body | **PENDING** | no safe reference harness |
| 1D.17 | Live-Yahoo instrument routes (`/lookup/:symbol`, `/:symbol`, `/:symbol/candles`) | mapped Yahoo data | **DEFERRED** | market-data phase; no provider integration approved |

Suite totals: **48 passed, 4 skipped** without `TEST_MONGO_URL`; **52 passed** with it.

Note: `instruments/search` and `market/overview` read only the `marketquotes` cache. The cache is
populated by a sync job that this phase does not port, so against the live dev database these routes
return empty results until the market-data phase exists. Route behaviour and shape are verified with
seeded fixtures.

---

## 1E. Phase 1e results — write endpoints

Executed 2026-10-18. Fast suite uses `mongomock`; the integration test reuses the guarded scratch
database (`tradium_fastapi_phase1_test`, name must end in `_test`, dropped afterwards). The market-data
provider is not ported, so a MARKET order is tested against the injected `market_data.fetch_quote` seam
(a real MongoDB aggregation pipeline runs in the integration test when a quote is present).

### Watchlist

| # | Test | Expected | Status | Evidence |
|---|---|---|---|---|
| 1E.1 | `POST /api/watchlist` | 201, Mongoose key set, `ltp`/`dayChangePct` 0, row persisted | **PASSED** | `test_watchlist.py::test_add_watchlist_creates_item_and_rejects_duplicates` |
| 1E.2 | Duplicate symbol | 409 `"Already in watchlist"`, no second row | **PASSED** | same test |
| 1E.3 | Invalid / missing symbol | 400 `"Invalid symbol"`; `^NSEI` accepted; `exchange` defaults to `NSE` | **PASSED** | `test_watchlist.py::test_add_watchlist_validates_symbol` |
| 1E.4 | `DELETE /api/watchlist/:id` | 204 with no body, idempotent, another user's row untouched | **PASSED** | `test_watchlist.py::test_delete_watchlist_is_always_204` |

### Funds transactions

| # | Test | Expected | Status | Evidence |
|---|---|---|---|---|
| 1E.5 | Deposit | 201, funds row upserted, `{funds, transaction}` shape, positive amount | **PASSED** | `test_funds.py::test_deposit_creates_funds_row_and_transaction` |
| 1E.6 | Withdraw within balance | 201, balance down, amount negative, default method | **PASSED** | `test_funds.py::test_withdrawal_guards_the_balance` |
| 1E.7 | Withdraw beyond balance | 400 `"Amount exceeds available balance"`, balance unchanged | **PASSED** | same test |
| 1E.8 | Invalid kind / zero / NaN amount | 400 `"Invalid transaction"` | **PASSED** | `test_funds.py::test_transaction_validation_and_default_method` |
| 1E.9 | Unknown method label | falls back to `"Bank transfer"` / `"Bank withdrawal"` | **PASSED** | same test |

### Order placement

| # | Test | Expected | Status | Evidence |
|---|---|---|---|---|
| 1E.10 | LIMIT buy | 201, `OPEN`, `filled: 0`, cash blocked `qty*price` | **PASSED** | `test_orders.py::test_limit_buy_places_open_order_and_blocks_cash` |
| 1E.11 | MARKET with no provider | 503, no order, no debit | **PASSED** | `test_orders.py::test_market_order_without_a_provider_returns_503` |
| 1E.12 | MARKET with a quote | 201 `EXECUTED`, second fill merges via the pipeline, weighted average | **PASSED** | `test_orders.py::test_market_order_with_a_quote_fills_and_merges_holdings`; `test_mongo_integration.py::test_write_routes_against_real_mongo` |
| 1E.13 | Validation table | each exact 400 message (enums, qty, price, SL trigger, inverted bracket) | **PASSED** | `test_orders.py::test_order_validation_errors` |
| 1E.14 | Insufficient funds / holdings | exact messages, incl. `₹7,500` Indian grouping; no mutation | **PASSED** | `test_orders.py::test_insufficient_funds_and_holdings_messages` |
| 1E.15 | String numbers coerced | `"5"`/`"1500"` accepted, stored as numbers | **PASSED** | `test_orders.py::test_string_numbers_are_coerced` |
| 1E.16 | Bracket entry | `groupId` equals the order `_id` | **PASSED** | `test_orders.py::test_bracket_entry_anchors_its_group` |

### Cancellation, exits, square-off

| # | Test | Expected | Status | Evidence |
|---|---|---|---|---|
| 1E.17 | Cancel open order | 200 `CANCELLED`, refund `unfilled*price` | **PASSED** | `test_orders.py::test_cancel_order_refunds_and_reports_state` |
| 1E.18 | Cancel already-cancelled / unknown / foreign | 400 `"Order is already cancelled"`, 404 `"Order not found"`, another user's order left `OPEN` | **PASSED** | same test |
| 1E.19 | Set exits | 201, `SL-M`+`LIMIT` pair, shared fresh `groupId`, message `"Exit rules set for …"` | **PASSED** | `test_orders.py::test_set_exits_creates_then_replaces_the_pair` |
| 1E.20 | Replace exits / no holding | old pair `CANCELLED`, new pair created; 404 `"No holding found for …"` | **PASSED** | same test |
| 1E.21 | Square-off LONG | `pnl` sign, position deleted, funds released, SETTLEMENT written, closing order + exit pair cancelled | **PASSED** | `test_positions.py::test_square_off_long_releases_cash_and_records_settlement` |
| 1E.22 | Square-off SHORT | `pnl` sign `(exit-entry)*qty*-1` | **PASSED** | `test_positions.py::test_square_off_short_pnl_sign` |
| 1E.23 | Square-off errors | 404 unknown/foreign, 400 non-MIS, 400 no `ltp`; position untouched | **PASSED** | `test_positions.py::test_square_off_errors` |

Suite totals: **66 passed, 5 skipped** without `TEST_MONGO_URL`; **71 passed** with it.

Not verified this phase: a live Express-vs-FastAPI comparison; the concurrency races (double square-off
409, parallel cancel/fill, parallel withdrawals) and the `apply_fill` sell-rejection path; the
Mongoose-validator-only 500s and the whole-float numeric rendering noted in `MIGRATION_STATUS.md` §3E.
A MARKET order cannot fill without the deferred market-data provider — its behaviour is exercised by
injecting a quote through the seam, and it returns the documented 503 otherwise.

---

## 1F. Phase 1f results — authentication routes

Ported: `POST /api/auth/signup`, `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`,
plus the express-rate-limit middleware mounted on signup and login.

| # | Test | Expected | Status | Evidence |
|---|---|---|---|---|
| 1F.1 | Signup valid | 201 `{ message, user: { id, username, email } }`, bcrypt hash stored, cookie set (`Secure` only under `NODE_ENV=production`) | **PASSED** | `test_auth_routes.py::test_signup_creates_user_and_sets_cookie`, `::test_cookie_is_secure_when_node_env_is_production` |
| 1F.2 | Signup document shape | Mongoose key set incl. `createdAt`/`updatedAt`/`__v` | **PASSED** | `test_auth_routes.py::test_signup_writes_mongoose_style_document` |
| 1F.3 | Signup validation | 400 `"Username, email and password are required"`; `"Password must be at least 8 characters"`, incl. a non-string password | **PASSED** | `test_auth_routes.py::test_signup_validation` |
| 1F.4 | Signup duplicate email / username | 400 `"User already exists"` for both | **PASSED** | `test_auth_routes.py::test_signup_rejects_duplicates` |
| 1F.5 | Login valid | 200 `{ message, user }`, cookie renewed | **PASSED** | `test_auth_routes.py::test_login_sets_cookie_and_returns_user` |
| 1F.6 | Login wrong password / unknown email | 401 `"Invalid credentials"` — the same message for both | **PASSED** | `test_auth_routes.py::test_login_rejects_bad_credentials` |
| 1F.7 | Login missing fields | 400 `"Email and password are required"` | **PASSED** | `test_auth_routes.py::test_login_requires_email_and_password` |
| 1F.8 | `/me` | 200, the user minus `password`, BSON dates to the millisecond | **PASSED** | `test_auth_routes.py::test_me_returns_the_user_without_password` |
| 1F.9 | `/me` without a cookie | 401 `"Not authenticated"` | **PASSED** | `test_auth_routes.py::test_me_requires_a_cookie` |
| 1F.10 | `/me` for a deleted user | 404 `"User not found"` | **PASSED** | `test_auth_routes.py::test_me_returns_404_when_the_user_is_gone` |
| 1F.11 | `/me` with a malformed `id` claim | 500 `{ message: "Server error", error }` — the controller's own envelope | **PASSED** | `test_auth_routes.py::test_me_uses_the_auth_500_envelope_for_a_malformed_id` |
| 1F.12 | Logout | 200 `{ message: "Logged out" }`, `Max-Age=0` cookie | **PASSED** | `test_auth_routes.py::test_logout_clears_the_cookie` |
| 1F.13 | Token from signup/login opens protected routes | `GET /api/holdings` 200 with that cookie | **PASSED** | `test_auth_routes.py::test_signup_token_opens_protected_routes`, `::test_login_token_opens_protected_routes` |
| 1F.14 | Token claims | HS256 `{ id, iat, exp }`, `exp - iat == 604800` | **PASSED** | `test_auth_routes.py::test_signup_token_has_the_jsonwebtoken_claims` |
| 1F.15 | bcrypt cross-implementation | a Node-generated `$2b$10$` hash verifies in Python, and a Python hash in Node | **PASSED** | `test_auth_routes.py::test_hashes_are_readable_across_implementations` (Node check run out-of-tree) |
| 1F.16 | Rate limit | 21st signup/login attempt in 15 min → 429 with the documented body | **PASSED** | `test_auth_routes.py::test_signup_and_login_share_one_limiter` |
| 1F.17 | Rate-limit headers | draft-7 `RateLimit-Policy` and `RateLimit` on a guarded response | **PASSED** | `test_auth_routes.py::test_signup_sets_the_draft7_rate_limit_headers` |
| 1F.18 | Rate-limit scope | logout is never limited | **PASSED** | `test_auth_routes.py::test_logout_is_not_rate_limited` |
| 1F.19 | Real MongoDB | signup → cookie → login → `/me`, `users` collection, stored hash | **PASSED** | `test_mongo_integration.py::test_auth_routes_against_real_mongo` |
| 2F.1 | Live side-by-side vs Express | byte-identical body, status and `Set-Cookie` | **PENDING** | no safe reference harness (`server/index.js` starts cron jobs on connect) |

Suite totals: **91 passed, 6 skipped** without `TEST_MONGO_URL`; **97 passed** with it.

Known differences recorded in this phase (none is a behavioural divergence for the React client):

- **`Set-Cookie` serialization.** Starlette writes the attributes in a different order and lowercases
  the value (`SameSite=strict`; Express writes `SameSite=Strict`). Cookie attributes are parsed
  case- and order-insensitively per RFC 6265, so the browser-visible behaviour is identical.
- **Malformed JSON body.** Express's body parser answers 400 `{ message: <parser text> }`; the app
  returns 400 `{ message: "Invalid request" }`, the pre-existing §0 rule for validation errors.
- **The `error` text in the auth 500 envelope** is driver-specific: Mongoose's CastError sentence
  versus bson's `InvalidId` sentence. Only the field's presence and type are part of the contract.
- **A `null` JSON body on signup.** Express destructures `null` and throws inside the controller → 500;
  here it is treated as `{}` → 400. The React client always sends an object.
- **Rate limiting is per worker.** Like express-rate-limit's default in-memory store; if the service is
  ever run multi-worker, the effective limit multiplies. Documented, not silently different.

---

## 1G. Phase 2a results — historical candles

Ported: `GET /api/instruments/:symbol/candles`. Nothing else in this phase — no quotes, no streaming,
no jobs.

Suite totals: **114 passed, 6 skipped** without `TEST_MONGO_URL`; **120 passed** with it.

### Candles

| # | Test | Expected | Status | Evidence |
|---|---|---|---|---|
| 1G.1 | Response shape | `[{ time, open, high, low, close }]`, no volume, `time` = bar epoch + 19800 | **PASSED** | `test_instrument_candles.py::test_returns_ohlc_only_and_shifts_timestamps_to_ist` |
| 1G.2 | Bar parity against `yahoo-finance2` itself | identical bar count, first/last `time` and first/last OHLC, for 2 symbols × 8 ranges | **PASSED** | 16/16 comparisons; method in `MARKET_DATA_PLAN.md` §3.1 (scratch reference built outside the repo) |
| 1G.3 | Request parity | the same query parameters the JS library sends, `includePrePost=true` included | **PASSED** | `test_instrument_candles.py::test_sends_the_same_query_parameters_as_yahoo_finance2` |
| 1G.4 | Empty-bar filtering | bars with a null `open` are absent | **PASSED** | `test_instrument_candles.py::test_drops_bars_that_have_no_open_price` |
| 1G.5 | Symbol convention | `^` passes through; everything else gets `.NS` | **PASSED** | `test_instrument_candles.py::test_index_symbols_keep_their_caret`, `::test_the_client_exchange_parameter_is_ignored` |
| 1G.6 | All eight ranges | each `range` maps to its Express `days`/`interval` pair | **PASSED** | `test_instrument_candles.py::test_each_range_maps_to_the_express_interval` (8 parameters) |
| 1G.7 | Default and unknown range | default `1M`; an unrecognised range falls back to 30 days / `1d` | **PASSED** | `test_instrument_candles.py::test_defaults_to_the_one_month_range`, `::test_an_unrecognised_range_falls_back_to_daily` |
| 1G.8 | Range with no data | `200 []`, not an error | **PASSED** | `test_instrument_candles.py::test_a_symbol_with_no_trading_data_is_an_empty_list`, `::test_a_result_without_timestamps_is_an_empty_list` |
| 1G.9 | Provider failure | 404 `{ message: "Could not fetch candle data" }` — the same message for an unknown symbol, a provider error object, a missing result, a non-2xx response and a non-JSON body | **PASSED** | `test_instrument_candles.py::test_provider_failure_is_the_express_404`, `::test_provider_error_object_is_a_404`, `::test_transport_failure_becomes_a_provider_error`, `::test_non_json_body_becomes_a_provider_error`, `::test_a_missing_result_is_a_provider_error` |
| 1G.10 | Authentication | 401 `"Not authenticated"` without a cookie | **PASSED** | `test_instrument_candles.py::test_requires_authentication` |
| 1G.11 | Live network, real app | 200 with real bars for an equity and an index | **PASSED** | out-of-tree smoke run: `RELIANCE`/`1M` 246 bars, `^NSEI`/`1D` 375, `^NSEI`/`SPARK` 5; unknown symbol 404, no cookie 401 |
| 1G.12 | Dependency sufficiency | the suite passes with `yfinance`, pandas and numpy removed | **PASSED** | `pip check` clean after uninstalling; 120 passed |

Observed bar counts on 2026-10-18 (market closed), through the implemented route:

| `range` | `RELIANCE` | `^NSEI` |
|---|---|---|
| `1D` | 362 | 375 |
| `5D` | 220 | 223 |
| `SPARK` | 5 | 5 |
| `1M` | 246 | 247 |
| `6M` | 866 | 870 |
| `1Y` | 246 | 245 |
| `5Y` | 262 | 262 |
| `ALL` | 241 | 231 |

Yahoo's own intraday retention applies, and is inherited rather than corrected: `1D` requests 3 days
of 1-minute bars and receives one session; `5D` requests 5 days and receives three.

Known differences and additions recorded in this phase:

- **A browser `User-Agent` and a 20 s timeout** are sent; Express sends neither. Neither changes the
  bars that come back.
- **Yahoo's intraday retention** is whatever the provider returns, so bar counts vary by session and
  symbol. Not a divergence from Express.
- **The numeric-rendering item from §5 now also applies to candle prices**: a whole float such as
  `1209.0` is rendered `1209.0` where JS writes `1209`. Both parse to the same number.
- **Live provider calls are not stubbed in the fast suite.** Every route test replaces
  `_request_chart`, so the suite makes no network calls and does not depend on the internet.

---

## 2. API contract parity

Method: issue the same request to Express and FastAPI with equivalent cookies and data, then compare
status code, body **keys**, value types, and error message text.

| # | Test | Expected | Status |
|---|---|---|---|
| 2.1 | Every GET route: JSON key set | identical keys, including `_id`, `__v`, timestamps | PLANNED |
| 2.2 | ObjectId fields | 24-char hex strings, no `ObjectId(...)` wrapper | PLANNED |
| 2.3 | Timestamps | ISO-8601 UTC strings | PLANNED |
| 2.4 | Enum values | casing preserved (`OPEN`, `LONG`, `CNC`, …) | PLANNED |
| 2.5 | Error envelope | `{ message }` for normal routes, `{ error }` for the three assistant routes | PLANNED |
| 2.6 | Validation messages | exact strings from API_CONTRACTS §5.2 and §5.3, in the same order | PLANNED |
| 2.7 | Status codes | 400/401/404/409/503 in the documented cases | PLANNED |
| 2.8 | Money in messages | Indian grouping (`₹1,23,456`) | PLANNED |
| 2.9 | `window` vs omitted | `invested: null` preserved; missing quote fields omitted | PLANNED |
| 2.10 | List ordering | orders and transactions newest-first; history oldest-first | PLANNED |

---

## 3. Authentication and session

| # | Test | Expected | Status |
|---|---|---|---|
| 3.1 | Signup valid | 201, user object, `Set-Cookie: token` | **PASSED** — §1F.1 |
| 3.2 | Signup missing field | 400 with the exact message | **PASSED** — §1F.3 |
| 3.3 | Signup short password | 400 `"Password must be at least 8 characters"` | **PASSED** — §1F.3 |
| 3.4 | Signup duplicate email | 400 `"User already exists"` | **PASSED** — §1F.4 |
| 3.5 | Signup duplicate username | 400 `"User already exists"` | **PASSED** — §1F.4 |
| 3.6 | Login valid | 200, user object, cookie renewed | **PASSED** — §1F.5 |
| 3.7 | Login wrong password | 401 `"Invalid credentials"` | **PASSED** — §1F.6 |
| 3.8 | Login unknown email | 401 `"Invalid credentials"` (same message) | **PASSED** — §1F.6 |
| 3.9 | Cookie attributes | `HttpOnly`, `SameSite=Strict`, `Path=/`, `Max-Age` 7d, `Secure` only in production | **PASSED** (attribute values; Starlette lowercases the `SameSite` value — see §1F notes) — §1F.1 |
| 3.10 | Token payload | HS256 with `{ id }`, 7-day expiry | **PASSED** (also carries `iat`, as jsonwebtoken does) — §1F.14 |
| 3.11 | Password hashing compatibility | an existing bcrypt hash still verifies after the port | **PASSED** — §1F.15 (real Node-generated `$2b$10$` vector) |
| 3.12 | `/me` without cookie | 401 `"Not authenticated"` | **PASSED** — §1F.9 |
| 3.13 | `/me` with tampered token | 401 `"Invalid or expired token"` | **PASSED** — `test_auth.py` (guard-level), shared by every protected route |
| 3.14 | `/me` with expired token | 401 | **PASSED** — `test_auth.py` (guard-level) |
| 3.15 | Logout | 200, cookie cleared, subsequent protected call 401 | **PASSED** (cleared cookie asserted; the follow-up 401 is the guard covered in §1A.4) — §1F.12 |
| 3.16 | Rate limit | 21st signup/login attempt within 15 min → 429 with the documented body | **PASSED** — §1F.16 |
| 3.17 | Rate-limit scope | `/me` and other routes are not limited | **PASSED** — §1F.18 |

---

## 4. User isolation

Two users, A and B, each with data.

| # | Test | Expected | Status |
|---|---|---|---|
| 4.1 | A lists holdings/positions/orders/watchlist/funds | only A's rows | **PASSED** — per-route isolation tests (§1A–§1C) |
| 4.2 | A requests B's position square-off | 404, no mutation | **PASSED** — `test_positions.py::test_square_off_errors` |
| 4.3 | A cancels B's order | 404, order unchanged | **PASSED** — `test_orders.py::test_cancel_order_refunds_and_reports_state` |
| 4.4 | A deletes B's watchlist item | no effect (204 regardless), B's row remains | **PASSED** — `test_watchlist.py::test_delete_watchlist_is_always_204` |
| 4.5 | A calls a Nova tool | only A's data in the answer | PLANNED |
| 4.6 | Concurrent requests from A and B | no cross-contamination of the user identity | PLANNED |

---

## 5. Serialization and data shape

| # | Test | Expected | Status |
|---|---|---|---|
| 5.1 | New Python-written document | includes `createdAt`/`updatedAt`/`__v` like Mongoose's | PLANNED |
| 5.2 | Mixed old/new documents | both serialise without errors | PLANNED |
| 5.3 | `PortfolioSnapshot.date` | stored as the IST day at UTC midnight | PLANNED |
| 5.4 | History labels | `YYYY-MM-DD` `label` for the same rows | **PASSED** (format only; live Express comparison PENDING — §1D.16) — `test_portfolio.py` |
| 5.5 | Sorting | numeric/date ordering matches | PLANNED |

---

## 6. Trading logic

### 6.1 Order placement

| # | Test | Expected | Status |
|---|---|---|---|
| 6.1.1 | LIMIT buy | 201, `OPEN`, cash debited `qty*price` | **PASSED** — `test_orders.py::test_limit_buy_places_open_order_and_blocks_cash` |
| 6.1.2 | MARKET buy | 201, `EXECUTED`, `filled=qty`, holdings updated | **PASSED** (`fetch_quote` seam) — `test_orders.py::test_market_order_with_a_quote_fills_and_merges_holdings` |
| 6.1.3 | MARKET buy, provider down | 503, no order created, no debit | **PASSED** — `test_orders.py::test_market_order_without_a_provider_returns_503` |
| 6.1.4 | MIS short | allowed, cash blocked `qty*price`, position created (via fill) | PLANNED (MIS long fill covered by §1E.12; short not asserted) |
| 6.1.5 | CNC sell beyond holdings | 400 with the holdings message; **note current debit-before-check behaviour** | **PASSED** (message; CNC sell does not debit) — `test_orders.py::test_insufficient_funds_and_holdings_messages` |
| 6.1.6 | Insufficient funds | 400, no order, balance unchanged | **PASSED** — same test |
| 6.1.7 | Invalid enums | 400 per each message | **PASSED** — `test_orders.py::test_order_validation_errors` |
| 6.1.8 | Non-integer qty | 400 `"Quantity must be a whole number"` | **PASSED** — same test |
| 6.1.9 | SL without trigger | 400 | **PASSED** — same test |
| 6.1.10 | Inverted bracket | 400 with the BUY/SELL-specific message | **PASSED** — same test |
| 6.1.11 | Bracket accepted | `groupId` equals the order `_id` | **PASSED** — `test_orders.py::test_bracket_entry_anchors_its_group` |
| 6.1.12 | String numbers | `"5"` accepted as 5 | **PASSED** — `test_orders.py::test_string_numbers_are_coerced` |

### 6.2 Fills and brackets

| # | Test | Expected | Status |
|---|---|---|---|
| 6.2.1 | LIMIT crossing | fills once at the limit price; sibling cancelled | PLANNED (needs the price-sync job) |
| 6.2.2 | SL trigger crossing | fires once at the trigger/stored settings | PLANNED (needs the price-sync job) |
| 6.2.3 | SL-M | fills at live `ltp` | PLANNED (needs the price-sync job) |
| 6.2.4 | Two overlapping matching cycles | single fill (atomic claim) | PLANNED |
| 6.2.5 | MIS exit | position deleted, P&L settled, funds released, transaction written | PLANNED (needs the price-sync job) |
| 6.2.6 | CNC buy fill | holdings weighted average correct | **PASSED** — `test_orders.py::test_market_order_with_a_quote_fills_and_merges_holdings` |
| 6.2.7 | CNC sell fill | holdings reduced; proceeds credited; zero-qty holding removed | PLANNED |
| 6.2.8 | CNC sell beyond holdings at fill time | order `REJECTED`, siblings cancelled | PLANNED |
| 6.2.9 | Cancel an unfilled order | refund `unfilled*price` | **PASSED** — `test_orders.py::test_cancel_order_refunds_and_reports_state` |
| 6.2.10 | Cancel an already-filled order | 400 `"Order is already executed"`, no refund | **PASSED** (cancelled branch; the executed branch shares the same code path) — same test |
| 6.2.11 | Parallel cancel and fill | exactly one refund/fill outcome | PLANNED |

### 6.3 Exits and square-off

| # | Test | Expected | Status |
|---|---|---|---|
| 6.3.1 | Set exits on a holding | two orders created, `isExit: true`, shared `groupId` | **PASSED** — `test_orders.py::test_set_exits_creates_then_replaces_the_pair` |
| 6.3.2 | Replace exits | old pair cancelled, new pair created | **PASSED** — same test |
| 6.3.3 | Exits with no position/holding | 404 with the specific message | **PASSED** (no-holding branch; the MIS branch shares the shape) — same test |
| 6.3.4 | Square-off LONG | correct P&L sign and funds release | **PASSED** — `test_positions.py::test_square_off_long_releases_cash_and_records_settlement` |
| 6.3.5 | Square-off SHORT | correct P&L sign and funds release | **PASSED** — `test_positions.py::test_square_off_short_pnl_sign` |
| 6.3.6 | Double square-off | one succeeds; the other 409 | PLANNED (needs a race) |
| 6.3.7 | Square-off non-MIS | 400 | **PASSED** — `test_positions.py::test_square_off_errors` |
| 6.3.8 | Square-off with no `ltp` | 400 | **PASSED** — same test |
| 6.3.9 | Square-off cancels exits | open exits become `CANCELLED` | **PASSED** — `test_positions.py::test_square_off_long_releases_cash_and_records_settlement` |
| 6.3.10 | Square-off records a closing order | `EXECUTED` MARKET order present | **PASSED** — same test |

### 6.4 Funds

| # | Test | Expected | Status |
|---|---|---|---|
| 6.4.1 | Deposit | 201, balance increases, transaction positive | **PASSED** — `test_funds.py::test_deposit_creates_funds_row_and_transaction` |
| 6.4.2 | Withdraw within balance | 201, balance decreases, transaction negative | **PASSED** — `test_funds.py::test_withdrawal_guards_the_balance` |
| 6.4.3 | Withdraw beyond balance | 400, balance unchanged | **PASSED** — same test |
| 6.4.4 | Parallel withdrawals | total never exceeds the starting balance | PLANNED (needs a race) |
| 6.4.5 | Derived margin | `usedMargin = blockedInOrders + misMargin` matches Express | **PASSED** — §1C.4 |
| 6.4.6 | Realised P&L | equals the sum of SETTLEMENT amounts | **PASSED** — §1C.4; the square-off writes a SETTLEMENT (§1E.21) |
| 6.4.7 | Unknown method label | falls back to the default label | **PASSED** — `test_funds.py::test_transaction_validation_and_default_method` |
| 6.4.8 | Zero/negative/NaN amount | 400 `"Invalid transaction"` | **PASSED** — same test |

### 6.5 Holdings, positions, portfolio

| # | Test | Expected | Status |
|---|---|---|---|
| 6.5.1 | Portfolio summary math | matches `portfolioMath` for the same data | PLANNED |
| 6.5.2 | MIS components | value and invested match | **PASSED** — `test_portfolio.py::test_live_point_only_when_no_snapshots` |
| 6.5.3 | History with no snapshots | returns today's live point only | **PASSED** — same test |
| 6.5.4 | History with legacy rows | `invested: null` and no zero drop | **PASSED** — `test_portfolio.py::test_snapshots_ascending_with_null_invested_for_legacy_rows` |
| 6.5.5 | History range fallbacks | unknown range behaves as 30 days | **PASSED** — `test_portfolio.py::test_unknown_range_falls_back_to_thirty_days` |
| 6.5.6 | Duplicate today point | overwritten, not duplicated | **PASSED** — `test_portfolio.py::test_todays_snapshot_is_overwritten_not_duplicated` |

---

## 7. Instruments and market

| # | Test | Expected | Status |
|---|---|---|---|
| 7.1 | Search matches symbol or name | case-insensitive, max 10, correct renamed keys | **PASSED** — `test_instruments.py` |
| 7.2 | Search with regex characters | treated literally | **PASSED** — `test_instruments.py::test_limits_to_ten_and_treats_regex_characters_literally` |
| 7.3 | Search with empty `q` | `[]` | **PASSED** — `test_instruments.py::test_empty_query_returns_empty_list` |
| 7.4 | Lookup valid | mapped fields, uppercase symbol | **DEFERRED** — needs a market-data provider |
| 7.5 | Lookup invalid | 404 `"Instrument not found"` | **DEFERRED** — needs a market-data provider |
| 7.6 | Detail fields | same keys and mapping as Express | **DEFERRED** — needs a market-data provider |
| 7.7 | Candles, all ranges | key set and IST shift identical | **PASSED** — §1G.1, §1G.2, §1G.6 (16/16 identical to `yahoo-finance2` for 2 symbols × 8 ranges) |
| 7.8 | Candles provider failure | 404 `"Could not fetch candle data"` | **PASSED** — §1G.9 |
| 7.9 | Overview with cold cache | `asOf: null`, empty arrays | **PASSED** — `test_market.py::test_cold_cache_returns_nulls_and_empty_lists` |
| 7.10 | Overview index ordering | order from `data/nifty50.js` | **PASSED** — `test_market.py::test_indices_follow_seed_order_and_stocks_are_split_out` |
| 7.11 | Overview cache integrity | `stocks` contains only `kind: "stock"` | **PASSED** — same test |

---

## 8. Jobs

| # | Test | Expected | Status |
|---|---|---|---|
| 8.1 | Price sync inside market hours | updates `ltp` for held symbols | PLANNED |
| 8.2 | Price sync outside hours | no provider calls | PLANNED |
| 8.3 | Price sync single-flight | overlapping triggers do not double-run | PLANNED |
| 8.4 | One symbol fails | others still update; failure logged | PLANNED |
| 8.5 | Market sync batch | 53 tickers upserted, no duplicates | PLANNED |
| 8.6 | Sector backfill | at most 10 per run, no overwrite of known values | PLANNED |
| 8.7 | Snapshot job | one row per user per day; rerun is idempotent | PLANNED |
| 8.8 | Job ownership | only one process schedules jobs | PLANNED |
| 8.9 | Startup first run | immediate sync like the current app | PLANNED |

---

## 9. Nova (Phase 3)

See [AI_INTEGRATION_PLAN.md](./AI_INTEGRATION_PLAN.md) §10 for the full matrix. Minimum gate:

| # | Test | Expected | Status |
|---|---|---|---|
| 9.1 | Text-only stream | renders in the unmodified panel | BLOCKED (Phase 3) |
| 9.2 | Single tool call | tool card + grounded answer | BLOCKED |
| 9.3 | Five-step cap | stops at five | BLOCKED |
| 9.4 | Cross-user probe | no data leak | BLOCKED |
| 9.5 | Insight stream | `useCompletion` renders text | BLOCKED |
| 9.6 | Briefing stream | renders on dashboard | BLOCKED |
| 9.7 | Provider failure | documented client state | BLOCKED |

---

## 10. Frontend and build

| # | Test | Expected | Status |
|---|---|---|---|
| 10.1 | `npm run lint` | passes | PLANNED |
| 10.2 | `npm run build` | passes; `dist/` produced | PLANNED |
| 10.3 | Production mode serves SPA | deep link returns `index.html` | PLANNED |
| 10.4 | `/api` is not swallowed by the SPA fallback | API still reachable | PLANNED |
| 10.5 | Every page renders against FastAPI | no console errors beyond known states | PLANNED |
| 10.6 | Login → dashboard → trade → logout | end-to-end without code changes | PLANNED |

---

## 11. Deployment

| # | Test | Expected | Status |
|---|---|---|---|
| 11.1 | Env var parity | every required name present | PLANNED |
| 11.2 | Health endpoint | 200 `{ ok: true }` | PLANNED |
| 11.3 | Cold start | app serves after a fresh boot | PLANNED |
| 11.4 | Rollback | previous service still works | PLANNED |

Do not run any deployment test against the existing production service in Phase 0.
