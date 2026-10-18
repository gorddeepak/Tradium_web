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
| Isolated MongoDB (local or scratch), never production | every parity test | **PLANNED** |
| Seeded demo data: ≥2 users, holdings, positions, orders in each status, funds, transactions, snapshots | most tests | **PLANNED** |
| Express reference running on a spare port, pointed at the scratch DB | parity tests | **PLANNED** |
| FastAPI app running against the same scratch DB | Phase 1+ | **PLANNED** |
| Gemini key with quota | AI tests | **BLOCKED** until Phase 3 |
| Recorded resolved npm versions | AI protocol tests | **BLOCKED** until dependencies are installed |

**Fixture policy:** create fixtures only in an isolated database with safe demo configuration. If that
is not available, mark dependent tests `BLOCKED` and record the prerequisite. Never extract production
data as a fixture.

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
| 3.1 | Signup valid | 201, user object, `Set-Cookie: token` | PLANNED |
| 3.2 | Signup missing field | 400 with the exact message | PLANNED |
| 3.3 | Signup short password | 400 `"Password must be at least 8 characters"` | PLANNED |
| 3.4 | Signup duplicate email | 400 `"User already exists"` | PLANNED |
| 3.5 | Signup duplicate username | 400 `"User already exists"` | PLANNED |
| 3.6 | Login valid | 200, user object, cookie renewed | PLANNED |
| 3.7 | Login wrong password | 401 `"Invalid credentials"` | PLANNED |
| 3.8 | Login unknown email | 401 `"Invalid credentials"` (same message) | PLANNED |
| 3.9 | Cookie attributes | `HttpOnly`, `SameSite=Strict`, `Path=/`, `Max-Age` 7d, `Secure` only in production | PLANNED |
| 3.10 | Token payload | HS256 with `{ id }`, 7-day expiry | PLANNED |
| 3.11 | Password hashing compatibility | an existing bcrypt hash still verifies after the port | PLANNED |
| 3.12 | `/me` without cookie | 401 `"Not authenticated"` | PLANNED |
| 3.13 | `/me` with tampered token | 401 `"Invalid or expired token"` | PLANNED |
| 3.14 | `/me` with expired token | 401 | PLANNED |
| 3.15 | Logout | 200, cookie cleared, subsequent protected call 401 | PLANNED |
| 3.16 | Rate limit | 21st signup/login attempt within 15 min → 429 with the documented body | PLANNED |
| 3.17 | Rate-limit scope | `/me` and other routes are not limited | PLANNED |

---

## 4. User isolation

Two users, A and B, each with data.

| # | Test | Expected | Status |
|---|---|---|---|
| 4.1 | A lists holdings/positions/orders/watchlist/funds | only A's rows | PLANNED |
| 4.2 | A requests B's position square-off | 404, no mutation | PLANNED |
| 4.3 | A cancels B's order | 404, order unchanged | PLANNED |
| 4.4 | A deletes B's watchlist item | no effect (204 regardless), B's row remains | PLANNED |
| 4.5 | A calls a Nova tool | only A's data in the answer | PLANNED |
| 4.6 | Concurrent requests from A and B | no cross-contamination of the user identity | PLANNED |

---

## 5. Serialization and data shape

| # | Test | Expected | Status |
|---|---|---|---|
| 5.1 | New Python-written document | includes `createdAt`/`updatedAt`/`__v` like Mongoose's | PLANNED |
| 5.2 | Mixed old/new documents | both serialise without errors | PLANNED |
| 5.3 | `PortfolioSnapshot.date` | stored as the IST day at UTC midnight | PLANNED |
| 5.4 | History labels | `YYYY-MM-DD` matching the Express output for the same rows | PLANNED |
| 5.5 | Sorting | numeric/date ordering matches | PLANNED |

---

## 6. Trading logic

### 6.1 Order placement

| # | Test | Expected | Status |
|---|---|---|---|
| 6.1.1 | LIMIT buy | 201, `OPEN`, cash debited `qty*price` | PLANNED |
| 6.1.2 | MARKET buy | 201, `EXECUTED`, `filled=qty`, holdings updated | PLANNED |
| 6.1.3 | MARKET buy, provider down | 503, no order created, no debit | PLANNED |
| 6.1.4 | MIS short | allowed, cash blocked `qty*price`, position created (via fill) | PLANNED |
| 6.1.5 | CNC sell beyond holdings | 400 with the holdings message; **note current debit-before-check behaviour** | PLANNED |
| 6.1.6 | Insufficient funds | 400, no order, balance unchanged | PLANNED |
| 6.1.7 | Invalid enums | 400 per each message | PLANNED |
| 6.1.8 | Non-integer qty | 400 `"Quantity must be a whole number"` | PLANNED |
| 6.1.9 | SL without trigger | 400 | PLANNED |
| 6.1.10 | Inverted bracket | 400 with the BUY/SELL-specific message | PLANNED |
| 6.1.11 | Bracket accepted | `groupId` equals the order `_id` | PLANNED |
| 6.1.12 | String numbers | `"5"` accepted as 5 | PLANNED |

### 6.2 Fills and brackets

| # | Test | Expected | Status |
|---|---|---|---|
| 6.2.1 | LIMIT crossing | fills once at the limit price; sibling cancelled | PLANNED |
| 6.2.2 | SL trigger crossing | fires once at the trigger/stored settings | PLANNED |
| 6.2.3 | SL-M | fills at live `ltp` | PLANNED |
| 6.2.4 | Two overlapping matching cycles | single fill (atomic claim) | PLANNED |
| 6.2.5 | MIS exit | position deleted, P&L settled, funds released, transaction written | PLANNED |
| 6.2.6 | CNC buy fill | holdings weighted average correct | PLANNED |
| 6.2.7 | CNC sell fill | holdings reduced; proceeds credited; zero-qty holding removed | PLANNED |
| 6.2.8 | CNC sell beyond holdings at fill time | order `REJECTED`, siblings cancelled | PLANNED |
| 6.2.9 | Cancel an unfilled order | refund `unfilled*price` | PLANNED |
| 6.2.10 | Cancel an already-filled order | 400 `"Order is already executed"`, no refund | PLANNED |
| 6.2.11 | Parallel cancel and fill | exactly one refund/fill outcome | PLANNED |

### 6.3 Exits and square-off

| # | Test | Expected | Status |
|---|---|---|---|
| 6.3.1 | Set exits on a holding | two orders created, `isExit: true`, shared `groupId` | PLANNED |
| 6.3.2 | Replace exits | old pair cancelled, new pair created | PLANNED |
| 6.3.3 | Exits with no position/holding | 404 with the specific message | PLANNED |
| 6.3.4 | Square-off LONG | correct P&L sign and funds release | PLANNED |
| 6.3.5 | Square-off SHORT | correct P&L sign and funds release | PLANNED |
| 6.3.6 | Double square-off | one succeeds; the other 409 | PLANNED |
| 6.3.7 | Square-off non-MIS | 400 | PLANNED |
| 6.3.8 | Square-off with no `ltp` | 400 | PLANNED |
| 6.3.9 | Square-off cancels exits | open exits become `CANCELLED` | PLANNED |
| 6.3.10 | Square-off records a closing order | `EXECUTED` MARKET order present | PLANNED |

### 6.4 Funds

| # | Test | Expected | Status |
|---|---|---|---|
| 6.4.1 | Deposit | 201, balance increases, transaction positive | PLANNED |
| 6.4.2 | Withdraw within balance | 201, balance decreases, transaction negative | PLANNED |
| 6.4.3 | Withdraw beyond balance | 400, balance unchanged | PLANNED |
| 6.4.4 | Parallel withdrawals | total never exceeds the starting balance | PLANNED |
| 6.4.5 | Derived margin | `usedMargin = blockedInOrders + misMargin` matches Express | PLANNED |
| 6.4.6 | Realised P&L | equals the sum of SETTLEMENT amounts | PLANNED |
| 6.4.7 | Unknown method label | falls back to the default label | PLANNED |
| 6.4.8 | Zero/negative/NaN amount | 400 `"Invalid transaction"` | PLANNED |

### 6.5 Holdings, positions, portfolio

| # | Test | Expected | Status |
|---|---|---|---|
| 6.5.1 | Portfolio summary math | matches `portfolioMath` for the same data | PLANNED |
| 6.5.2 | MIS components | value and invested match | PLANNED |
| 6.5.3 | History with no snapshots | returns today's live point only | PLANNED |
| 6.5.4 | History with legacy rows | `invested: null` and no zero drop | PLANNED |
| 6.5.5 | History range fallbacks | unknown range behaves as 30 days | PLANNED |
| 6.5.6 | Duplicate today point | overwritten, not duplicated | PLANNED |

---

## 7. Instruments and market

| # | Test | Expected | Status |
|---|---|---|---|
| 7.1 | Search matches symbol or name | case-insensitive, max 10, correct renamed keys | PLANNED |
| 7.2 | Search with regex characters | treated literally | PLANNED |
| 7.3 | Search with empty `q` | `[]` | PLANNED |
| 7.4 | Lookup valid | mapped fields, uppercase symbol | PLANNED |
| 7.5 | Lookup invalid | 404 `"Instrument not found"` | PLANNED |
| 7.6 | Detail fields | same keys and mapping as Express | PLANNED |
| 7.7 | Candles, all ranges | key set and IST shift identical | PLANNED |
| 7.8 | Candles provider failure | 404 `"Could not fetch candle data"` | PLANNED |
| 7.9 | Overview with cold cache | `asOf: null`, empty arrays | PLANNED |
| 7.10 | Overview index ordering | order from `data/nifty50.js` | PLANNED |
| 7.11 | Overview cache integrity | `stocks` contains only `kind: "stock"` | PLANNED |

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
