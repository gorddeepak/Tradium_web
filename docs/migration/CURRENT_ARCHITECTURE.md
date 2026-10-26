# Current Architecture (as of the source snapshot)

> **Status:** Phase 0 audit of the copied source tree.
> **Snapshot commit in the original repository:** `23099b7 single service deployment - Express serves the built frontend`
> **Method:** read-only inspection of the copied repository. Nothing in this document was inferred from memory of a
> different project; where a behaviour could not be confirmed from source, it is marked **UNRESOLVED** or
> **ASSUMPTION**.
>
> **Current state (2026-10-26, Phase 3C1).** This document describes the Express reference in
> `server/` (the source snapshot) and remains accurate for it. The active FastAPI service in `api/` now
> splits the data layer: PostgreSQL owns `users` (authentication, snapshot user list), `instruments`,
> `latest_quotes` (market cache), `watchlists` (API, `price_sync` symbol source and Nova's
> `getWatchlist`) and `portfolio_snapshots` (daily job and historical history points, plus the snapshot
> archive for `/api/portfolio/history`); MongoDB still owns `holdings`, `positions`, `orders`, `funds`,
> `transactions`, the old `portfoliosnapshots` documents (retired archive) and Nova's other tools. There
> is no automatic MongoDB → PostgreSQL loader for users, watchlists or snapshots. See
> `MIGRATION_STATUS.md` §4.

This document describes the application **as it exists today**. The target design is in
[ARCHITECTURE_DECISIONS.md](./ARCHITECTURE_DECISIONS.md) and [MIGRATION_PLAN.md](./MIGRATION_PLAN.md).

---

## 1. System shape

Two npm projects in one repository:

| Project | Directory | Runtime | Dev port | Production role |
|---|---|---|---|---|
| Frontend | repository root | React 19 + Vite 8 | 5173 | built to `dist/`, served by Express |
| Backend | `server/` | Node.js + Express 5 | 3002 | API + static file host |

In production there is **one process**: Express serves the Vite build from `../dist` and the API under `/api`.
There is no separate static host and no reverse proxy in the repository. Deployment is a single Render web
service (recorded in the project memory; no Render manifest exists in the repo — see §11).

```
Browser
  │  React SPA (Vite build)
  ├── axios/fetch ──► Express :3002 /api/*        (JWT httpOnly cookie)
  └── useChat / useCompletion streams ◄── SSE / plain-text
                          │
                          ├── MongoDB (Mongoose)
                          ├── Yahoo Finance (yahoo-finance2)
                          └── Google Gemini (via Vercel AI SDK)
```

---

## 2. Frontend

### 2.1 Entry and shell

| File | Responsibility |
|---|---|
| `index.html` | Vite document root |
| `src/main.jsx` | React root, router, providers |
| `src/App.jsx` | Route table, dashboard layout |
| `src/pages/routes/routes.js` | Route path constants |
| `src/components/ProtectedRoute.jsx` | Redirects to `/login` when unauthenticated |

### 2.2 Feature layout

The frontend is organised **by feature**, not by file type:

- `src/features/assistant/` — Nova chat panel, page insight cards, `AssistantContext.jsx`
  - `components/AssistantPanel.jsx` — chat UI (rendered inside a shadcn `Sheet` side panel)
  - `components/PageInsight.jsx` — per-page AI insight card + "Ask about this"
  - `ai-elements/` — vendored Vercel AI Elements primitives (conversation, message, prompt-input,
    suggestion, tool)
- `src/features/auth/` — `AuthContext.jsx`, login and signup pages
- `src/features/dashboard/` — dashboard shell, pages (Holdings, Positions, Orders, WatchList,
  Instrument), tables, hooks
- `src/features/marketing/` — landing page sections
- `src/components/ui/` — shadcn/Radix primitives (Button, Input, Spinner, Sheet, …)
- `src/services/api.js` — every REST call and the exported `BASE_URL`
- `src/utils/tradiumUtils.jsx` — formatters, small display components, portfolio math
- `src/styles/index.css` — Tailwind v4 setup and theme tokens
- `src/styles/dashboard.css` — dashboard styles, including `animate-entry`

### 2.3 Data access

`src/services/api.js` is the **only** place the API origin is written:

```js
const BASE_URL = import.meta.env.VITE_API_URL
  || (import.meta.env.DEV ? "http://localhost:3002/api" : "/api");
```

All calls go through a small `request()` helper that:

- sends `credentials: "include"` (the JWT lives in an httpOnly cookie),
- sets `Content-Type: application/json`,
- treats HTTP 204 as `null`,
- throws `Error(body.message || "Request failed: <status>")` on non-2xx.

### 2.4 AI client integration

- `src/features/assistant/AssistantContext.jsx` — `useChat` from `@ai-sdk/react` with
  `DefaultChatTransport({ api: ${BASE_URL}/assistant/chat, credentials: "include" })`.
- `src/features/assistant/components/PageInsight.jsx` — `useCompletion` with
  `streamProtocol: "text"`, pointed at `/api/assistant/briefing` (dashboard) or
  `/api/assistant/insight` (other pages). It fires once per page visit / data change, guarded by an
  effect over `[page, JSON.stringify(data)]`.

### 2.5 Installed versions (from `package.json`)

Runtime dependencies of note: `react ^19.2.7`, `react-dom`, `react-router-dom ^7.18.1`,
`@ai-sdk/react ^4.0.61`, `ai ^7.0.58`, `axios ^1.18.1`, `recharts ^3.8.0`,
`lightweight-charts ^5.2.1`, `streamdown ^2.5.0`, `openalgo-heatmap ^0.2.0`, Tailwind v4 tooling,
Radix/shadcn primitives. Dev: `vite ^8.1.1`, `eslint ^10.6.0`, `puppeteer-core ^25.8.0`
(used only by the `screens` script).

Scripts: `dev` (Vite), `build` (`vite build`), `lint` (`eslint .`), `preview`, `screens`.

---

## 3. Backend

### 3.1 Entry point — `server/index.js`

Order of setup:

1. `dotenv.config()` — requires `server/.env`.
2. `app.use(cors({ origin: ["http://localhost:5173" … "http://localhost:5177"], credentials: true }))`.
3. `express.json()`, `express.urlencoded({ extended: true })`, `cookieParser()`.
4. Route mounts:

   | Mount | Router |
   |---|---|
   | `/api/auth` | `routes/authRoutes.js` |
   | `/api/holdings` | `routes/holdingsRoutes.js` |
   | `/api/positions` | `routes/positionsRoutes.js` |
   | `/api/orders` | `routes/ordersRoutes.js` |
   | `/api/watchlist` | `routes/watchlistRoutes.js` |
   | `/api/funds` | `routes/fundsRoutes.js` |
   | `/api/portfolio` | `routes/portfolioRoutes.js` |
   | `/api/instruments` | `routes/instrumentRoutes.js` |
   | `/api/market` | `routes/marketRoutes.js` |
   | `/api/assistant` | `routes/assistantRoutes.js` |

5. `GET /api/health` → `{ ok: true }`, unauthenticated.
6. If `NODE_ENV === "production"`: serve `../dist` statically; any non-`/api` path falls back to
   `dist/index.html` (SPA routing).
7. 404 handler → `{ message: "Route not found" }`.
8. Central error handler:
   - `err.name === "ValidationError"` → 400 `{ message: err.message }`
   - otherwise `err.status || 500`; when 500 the message is replaced with `"Something went wrong"`.
9. `mongoose.connect(process.env.MONGO_URL)`; on success register cron jobs and `app.listen(PORT)`;
   on failure log and `process.exit(1)`.

**Express 5 note:** async route handlers reject into the central error handler automatically. Only
routes that need a specific status wrap themselves in `try/catch`.

### 3.2 Middleware — `server/middlewares/auth.js`

`protect`:

1. Reads `req.cookies.token`.
2. Missing → 401 `{ message: "Not authenticated" }`.
3. `jwt.verify(token, process.env.JWT_SECRET)`; payload is `{ id }` (the user `_id`).
4. Sets `req.userId = decoded.id` and continues.
5. Any verification failure → 401 `{ message: "Invalid or expired token" }`.

There is no role system, no scope checks, and no admin path. Every protected query filters by
`user: req.userId` (or `user: userId` inside helpers).

### 3.3 Controllers

| File | Responsibility |
|---|---|
| `controllers/authController.js` | signup, login, logout, getMe; JWT issue, cookie set/clear |
| `controllers/assistantController.js` | Nova chat: message conversion, tool definitions, streamed response |
| `controllers/insightController.js` | page insight and dashboard briefing prompts; plain-text streaming |

### 3.4 Utilities

| File | Responsibility |
|---|---|
| `utils/executeOrder.js` | applying a fill to holdings/positions, bracket exit creation, MIS settlement, OCO cancellation |
| `utils/portfolioMath.js` | `calculatePortfolioSummary`, `misComponents`, `dayChangeRupees` |
| `utils/marketHours.js` | `isMarketOpen()` — Mon–Fri 09:15–15:30 IST, **no holiday calendar** |
| `utils/symbol.js` | `tickerFor(symbol)` — passthrough if it starts with `^`, else `${symbol}.NS` |

### 3.5 Jobs

| Job | Schedule (timezone `Asia/Kolkata`) | File |
|---|---|---|
| Price sync | `* * * * *` — every minute | `jobs/priceSync.js` |
| Market sync | `*/5 * * * *` — every 5 minutes | `jobs/marketSync.js` |
| Portfolio snapshot | `0 18 * * *` — daily 18:00 | `jobs/portfolioSnapshot.js` |

Each is also invoked once immediately at startup (price sync and market sync).

**Discrepancy with project documentation:** `CLAUDE.md` states price sync runs every 5 minutes. The
registered schedule is every minute (`* * * * *`). The 5-minute figure matches `marketSync`, not
`priceSync`. The source is authoritative. Also, `server/package.json` defines `start` as
`node index.js` (not nodemon); nodemon is only the `dev` script.

### 3.6 Configuration

- `server/config/ai.js` — the only place the model ID appears:
  `const MODEL_ID = "gemini-3.5-flash-lite"`.
- `server/modelSeed.js`, `server/backfill.js` — one-off seed/backfill scripts (npm `seed`, `backfill`).
- `server/data/nifty50.js` — 50 NIFTY constituents plus three indices, used by `marketSync` and by
  the index ordering in `marketRoutes.js`.

---

## 4. Data layer (MongoDB / Mongoose 9)

Connection string comes from `MONGO_URL`. Each model file owns exactly one schema and model.

### 4.1 Models and indexes

| Model (file) | Collection | Fields | Indexes |
|---|---|---|---|
| `User` (`models/User.js`) | `users` | `username`, `email`, `password` (bcrypt hash) | `username` unique, `email` unique |
| `HoldingsModel` (`model("holding")`) | `holdings` | `user`, `symbol`, `name`, `exchange` (`NSE`\|`BSE`), `qty`, `avgPrice`, `ltp`, `dayChangePct`, `sector` | unique `{user, symbol, exchange}` |
| `PositionsModel` (`model("position")`) | `positions` | `user`, `symbol`, `name`, `exchange`, `side` (`LONG`\|`SHORT`), `product` (`CNC`\|`MIS`), `qty`, `entry`, `ltp` | unique `{user, symbol, exchange, side, product}` |
| `OrdersModel` (`model("order")`) | `orders` | `user`, `symbol`, `name`, `exchange`, `side`, `type`, `product`, `qty`, `filled`, `price`, `triggerPrice`, `slTrigger`, `tpPrice`, `groupId`, `isExit`, `status` | **none declared** |
| `FundsModel` (`model("funds")`) | `funds` | `user`, `available` | `user` unique |
| `WatchlistModel` (`model("watchlist")`) | `watchlists` | `user`, `symbol`, `name`, `exchange`, `ltp`, `dayChangePct` | unique `{user, symbol, exchange}` |
| `TransactionModel` (`model("transaction")`) | `transactions` | `user`, `kind` (`DEPOSIT`\|`WITHDRAWAL`\|`SETTLEMENT`\|`FEE`), `method`, `amount`, `symbol`, `status` (`COMPLETED`\|`PROCESSING`) | none declared |
| `MarketQuoteModel` (`model("MarketQuote")`) | `marketquotes` | `symbol`, `name`, `kind` (`stock`\|`index`), `ltp`, `dayChange`, `dayChangePct`, `prevClose`, `volume`, `marketCap`, `sector` | `symbol` unique |
| `PortfolioSnapshotModel` (`model("PortfolioSnapshot")`) | `portfoliosnapshots` | `user`, `date`, `value`, `invested`, `misInvested`, `misValue` | unique `{user, date}` |

All models use `{ timestamps: true }`, so every document carries `createdAt` and `updatedAt`.
`User` hashes the password in a `pre("save")` hook at bcrypt cost 10.

### 4.2 Serialization behaviour that the frontend depends on

- Every response is the raw Mongoose document, so **all** fields are present, including `_id`,
  `__v`, `createdAt` and `updatedAt`.
- `user` is stored as an `ObjectId` and serialised as a hex string.
- The frontend uses the last 8 characters of `_id` for display labels (e.g. order IDs).
- Dates serialise through `JSON.stringify` as ISO-8601 UTC strings.
- `PortfolioSnapshot.date` is stored as a `Date` at UTC midnight of the IST calendar day (see §6.3).

### 4.3 Query patterns

- Almost every read is `find({ user: req.userId })`.
- Writes that must not race use atomic find-and-modify with a guard in the filter
  (e.g. `{ user, available: { $gte: amount } }` for debits, `{ _id, status: "OPEN" }` when claiming
  an order).
- Position averaging uses an **update pipeline** (`$set` with `$add`/`$divide` over existing fields)
  with `{ updatePipeline: true }` in Mongoose, so the weighted average is computed atomically
  server-side.
- Holdings writes use read-modify-write with a compare-and-swap guard for the CNC sell path.

---

## 5. Trading logic

### 5.1 Funds model

There is a single stored number: `Funds.available`. Everything else is derived in
`fundsRoutes.js#derivedFunds`:

- `blockedInOrders` — sum over `OPEN` orders where the order is **not** an exit and either
  `side === "BUY"` or `product === "MIS"`, of `(qty - filled) * price`.
- `misMargin` — sum over `MIS` positions of `entry * qty`.
- `usedMargin` = `blockedInOrders + misMargin`.
- `realizedPnl` — sum of all `SETTLEMENT` transaction `amount`s.

Cash is debited **up front** when an order is placed, and refunded on cancellation, rejection, or
completion of the opposite leg. As a result, `available` is "free cash", not "account balance".

### 5.2 Order placement — `POST /api/orders`

1. Coerce `qty`, `price`, `triggerPrice`, `slTrigger`, `tpPrice` with `Number()`.
2. Validate required fields and enums; validate `qty` is a positive whole number; validate `price > 0`
   unless the type is `MARKET`; require a trigger for `SL`/`SL-M`.
3. If a bracket is supplied (`slTrigger > 0 && tpPrice > 0`), require SL below TP for a BUY and above
   TP for a SELL.
4. Resolve the execution price: `MARKET` calls `fetchQuote(symbol)` and uses the live `ltp`;
   `LIMIT`/`SL`/`SL-M` keep the submitted `price`.
5. Debit funds atomically if `side === "BUY" || product === "MIS"`. A `MIS` SELL (short) also
   blocks cash equal to `qty * execPrice`.
6. For `CNC` SELL (anything not `MIS`), confirm the user holds at least `qty`.
7. Create the order. `MARKET` orders are created as `EXECUTED` with `filled = qty`; everything else
   is `OPEN`.
8. If a bracket was requested, set `groupId = String(order._id)` and save.
9. If the order is already executed, run `applyFill(order)`.

Note the ordering consequence: the funds debit happens **before** the holdings check, so a rejected
CNC sell still passes through a debit that is not compensated (see §9, known issues).

### 5.3 `applyFill` — `utils/executeOrder.js`

- **MIS**: an upsert/atomic pipeline on `positions` keyed by
  `{user, symbol, exchange, side, product}`. A fill on the same side adds quantity and recomputes the
  weighted average entry; the stored `ltp` is updated. Opposite-side fills are not netted here.
- **CNC BUY**: `holdings` upsert with weighted-average `avgPrice`.
- **CNC SELL**: guarded decrement `{ qty: { $gte: order.qty } }`. If the guard fails, the order is
  marked `REJECTED`, sibling exits are cancelled, and the function returns. On success, holdings are
  reduced (or removed at zero) and proceeds are credited to `available`.
- After a CNC SELL, a `SETTLEMENT` transaction records the capital movement.
- When the filled order has a `groupId`, `spawnBracketExits` creates the opposite-side pair.

### 5.4 Bracket exits (OCO)

`createExitPair` creates up to two orders sharing a `groupId`:

- an `SL-M` order at `slTrigger` (if provided),
- a `LIMIT` order at `tpPrice` (if provided).

`cancelSiblingExits` cancels the other leg when one fires, and refunds blocked cash if the cancelled
exit was a `CNC` BUY (i.e. covering a short — note that a short is `MIS`, so in practice the refund
branch applies to exit BUY orders on CNC products).

`settleMisExit` closes an MIS leg: it guards on remaining quantity, computes realised P&L as
`(exit - entry) * qty * dir`, where `dir` is `+1` for `LONG` and `-1` for `SHORT`, releases
`entry * qty + pnl` back to `available`, writes a `SETTLEMENT` transaction, and deletes the position.

### 5.5 Order matching — `priceSync`

For each `OPEN` order on a user's held symbols:

- `SL` / `SL-M` fire when the live price crosses the trigger in the losing direction.
- `LIMIT` fires when the live price crosses the limit.
- `SL-M` fills at the live `ltp`.
- The fill uses an atomic claim: `findOneAndUpdate({ _id, status: "OPEN" }, { status: "EXECUTED",
  filled: qty, price: fillPrice })`, so a concurrent job or request cannot double-fill.
- MIS exits go through `settleMisExit`; everything else goes through `applyFill`, then
  `cancelSiblingExits`.

### 5.6 Square-off — `POST /api/positions/:id/square-off`

Only `MIS` positions. Uses the live Yahoo quote when available, falling back to the stored `ltp`.
The position is claimed with `deleteOne` before any cash is released, so only one square-off pays.
It then credits the release amount, writes a `SETTLEMENT` transaction, records a closing `MARKET`
order, and cancels any open exit pair for that symbol.

### 5.7 Portfolio history — `GET /api/portfolio/history`

Reads `PortfolioSnapshot` rows since `now - days`, sorted ascending, and maps each to
`{ label, value, invested }`:

- `label` is a `YYYY-MM-DD` local date string (`toLocaleDateString("en-CA")`).
- `value` = `value + misValue`.
- `invested` = `invested + misInvested`, or `null` for legacy snapshots without `invested` (the chart
  renders a gap).

Then today's live value is appended or overwrites the last point, so the chart always ends at "now".

---

## 6. External integrations

### 6.1 Yahoo Finance (`yahoo-finance2 ^4.0.1`)

Call sites:

| Call site | Method | Purpose |
|---|---|---|
| `jobs/priceSync.js#fetchQuote` | `quote()` | LTP + day change for held/watchlist symbols; also exported and reused by `ordersRoutes` for `MARKET` fills |
| `jobs/priceSync.js#fetchSector` | `quoteSummary()` `assetProfile` | Backfill `sector` on holdings |
| `jobs/marketSync.js` | `quote(tickers, {}, { validateResult: false })` | Batch refresh of the NIFTY-50 + 3 index cache |
| `routes/instrumentRoutes.js` | `quote()`, `chart()` | Instrument detail, lookup, candles |
| `routes/positionsRoutes.js` | `quote()` | Live price for square-off |

Symbol normalisation lives in `utils/symbol.js`. Index symbols (`^NSEI`, `^NSEBANK`, `^BSESN`)
pass through unchanged; everything else gets `.NS`.

There is **no** WebSocket/streaming integration today. All data is polled.

### 6.2 Google Gemini (Vercel AI SDK)

- `ai ^7.0.58`, `@ai-sdk/google ^4.0.39`.
- Model resolved in `server/config/ai.js` only.
- Chat: `streamText` with six tools and `stopWhen: stepCountIs(5)`, piped as a Vercel UI Message
  Stream (SSE).
- Insight/briefing: `streamText` piped as plain text.
- API key: `GOOGLE_GENERATIVE_AI_API_KEY`.

Details are in [AI_INTEGRATION_PLAN.md](./AI_INTEGRATION_PLAN.md).

---

## 7. Background jobs

### 7.1 `jobs/priceSync.js`

- `syncPrices()` gates on `isMarketOpen()` (09:15–15:30 IST, Mon–Fri; no holidays) and on an
  in-process `isSyncing` flag.
- `runSync()` collects distinct symbols from holdings, positions, watchlist and `OPEN` orders, then
  fetches quotes **sequentially** (deliberate: Yahoo rate limits).
- Updates stored `ltp` (and `dayChangePct` where the field exists), backfills missing `sector` values,
  and runs the order-matching logic described in §5.5.
- Exports `fetchQuote`, which `ordersRoutes` reuses for `MARKET` fills.

**Operational note:** with the job gated on market hours only, a `MARKET` order placed while the
market is closed can still call Yahoo directly through the route — the gate is in the job, not in the
route.

### 7.2 `jobs/marketSync.js`

- 53 tickers (50 NIFTY constituents + `^NSEI`, `^NSEBANK`, `^BSESN`) from `data/nifty50.js`.
- One batched `quote()` call, then `bulkWrite` upserts into `marketquotes`.
- Backfills up to 10 missing `sector` values per run.
- Refreshes quotes only when the market is open or the cache is empty; otherwise it still runs but
  does not overwrite cached prices.

### 7.3 `jobs/portfolioSnapshot.js`

- Runs daily at 18:00 IST.
- For every user, computes holdings value/invested plus combined MIS value/invested
  (`misComponents`) and upserts `PortfolioSnapshot` keyed by `{user, date}` with `date` set to the
  IST calendar day at UTC midnight.

---

## 8. Authentication and authorisation

- **Transport:** JWT in an httpOnly cookie named `token`. Not returned in the response body.
- **Algorithm:** HS256, secret `JWT_SECRET`, payload `{ id }`, lifetime 7 days.
- **Cookie flags:** `httpOnly: true`, `secure` only when `NODE_ENV === "production"`,
  `sameSite: "strict"`, `maxAge` 7 days.
- **Rate limiting:** `express-rate-limit` on `/api/auth/signup` and `/api/auth/login` only —
  20 requests / 15 minutes / IP, `standardHeaders: "draft-7"`, custom body
  `{ message: "Too many attempts. Try again in a few minutes." }`.
- **Authorisation:** per-document ownership only. There are no roles or scopes.
- **CORS:** explicit localhost origins 5173–5177 with `credentials: true`. In production the
  frontend is same-origin, so CORS is not exercised.

---

## 9. Known issues and inconsistencies found in the audit

These are observations, **not** approved changes. Fixing them must be its own decision.

1. **Nova `getOrders` tool** maps `quantity: o.quantity`, but the schema field is `qty`, so the tool
   returns `undefined` for quantity.
2. **Nova `getOrders` tool** filters with lowercase statuses (`pending`, `executed`, `cancelled`)
   while stored statuses are uppercase, so a status filter can silently match nothing.
3. **Nova `getFunds` tool** reads `funds.used`, which is not a field on `FundsModel`; `usedMargin` is
   derived in `fundsRoutes.js` and is not available to the controller.
4. **CNC sell funds ordering** — the debit in `POST /api/orders` happens before the holdings check,
   so a rejected sell leaves cash blocked. Whether this is a real leak depends on whether an order
   document is created afterwards; the code returns 400 *after* the debit and never refunds it.
5. **Price sync cadence** — every minute, not every 5 minutes as `CLAUDE.md` says.
6. **`start` script** — `node index.js`, not nodemon, contrary to `CLAUDE.md`.
7. **`DELETE /api/watchlist/:id`** always returns 204, even when nothing matched.
8. **Market-hours check** has no holiday calendar, so it treats exchange holidays as trading days.

---

## 10. Testing and verification today

- **No automated test suite exists.** No test runner is configured in either `package.json`, and no
  `*.test.*` / `*.spec.*` files exist.
- `npm run lint` (ESLint) and `npm run build` (Vite) are the only automated checks.
- All functional verification is manual through the UI.
- `npm run screens` drives `puppeteer-core` for screenshots; it is a developer convenience, not a
  test.

---

## 11. Build, run, and deployment

### Local

```bash
# root
npm install
npm run dev            # Vite on 5173

# server
cd server
npm install
cp .env.example .env   # then fill in
npm start              # node index.js on 3002
```

### Environment variables (names only)

| Variable | Used by | Notes |
|---|---|---|
| `MONGO_URL` | `server/index.js` | required; process exits if missing |
| `PORT` | `server/index.js` | defaults to 3002 |
| `JWT_SECRET` | auth controller, `protect` | required for auth |
| `GOOGLE_GENERATIVE_AI_API_KEY` | `@ai-sdk/google` | required for Nova and insight cards |
| `VITE_API_URL` | `src/services/api.js` | optional; only for pointing a build at another API origin |
| `NODE_ENV` | cookie `secure`, static hosting | `production` enables both |

### Deployment assumptions

- One Render web service builds the frontend and runs the Express server.
- Express serves `dist/` and falls back to `index.html` for non-`/api` paths.
- There is no `render.yaml`, `Procfile`, `Dockerfile`, or CI workflow in the repository. Build and
  start commands are configured in the Render dashboard, outside source control — **UNRESOLVED**
  from the repository alone.
- Cron jobs run **inside** each server process. If more than one instance is ever started, every
  instance runs the same schedules against the same database. There is no distributed lock.

---

## 12. Dependency map (what breaks what)

```
auth ──► every protected route
   └── userId ──► all user-scoped queries

funds ──► orders (debit/refund)
     └──► positions (MIS margin)
     └──► executeOrder (credit proceeds, release margin)

orders ──► executeOrder ──► holdings, positions, funds, transactions
       └──► priceSync (matching) ──► executeOrder
       └──► positions square-off (cancels exits)

priceSync ──► holdings.ltp, positions.ltp, watchlist.ltp (what the UI and portfolio math read)
          └──► marketquotes (only marketSync writes that collection)

portfolioMath ──► funds (usedMargin), portfolio history, Nova tools, dashboard cards
snapshot job ──► portfolioMath

Yahoo ──► priceSync, marketSync, instrument routes, square-off, MARKET orders
Gemini ──► assistant chat, insight cards, dashboard briefing
```

Practical consequence for the migration: **market data is not a leaf dependency**. Order execution,
position valuation, funds margin and portfolio history all read prices. The FastAPI port must have a
working quote source before those paths can be considered equivalent.

---

## 13. Evidence status

| Claim | Status |
|---|---|
| Route mounts, middleware, cron expressions, error handler | **Verified** — read in `server/index.js` |
| Model fields and indexes | **Verified** — each model file read in full |
| Auth cookie flags, JWT payload and lifetime | **Verified** — `authController.js`, `middlewares/auth.js` |
| Trade execution and bracket logic | **Verified** — `utils/executeOrder.js`, `ordersRoutes.js`, `priceSync.js` |
| AI integration details | **Verified** — controllers, `config/ai.js`, `AssistantContext.jsx`, `PageInsight.jsx` |
| Render build/start commands | **UNRESOLVED** — not in the repository |
| Production database contents or indexes created outside Mongoose | **UNRESOLVED** — never inspected |
| Installed transitive dependency versions | **UNRESOLVED** — only `package.json` ranges were read; no `node_modules` in the snapshot |
