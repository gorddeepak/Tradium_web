# API Contracts (as of the source snapshot)

Source of truth: read-only inspection of **this** repository at snapshot `23099b7`.
Notation:

- **Auth** = requires the `token` cookie (the `protect` middleware). Unauthenticated calls get
  `401 { message }`.
- "doc" = a full serialised Mongoose document, including `_id`, `__v`, `createdAt`, `updatedAt`.
- Every JSON response uses `Content-Type: application/json` unless it is a stream.
- **UNVERIFIED** marks behaviour reasoned from library semantics but not exercised against a running
  server in Phase 0.

---

## 0. Cross-cutting contract rules

These apply everywhere and must survive the migration unchanged unless a change is approved.

### 0.1 Error envelope

| Case | Body |
|---|---|
| Any route error handler | `{ "message": "<text>" }` |
| Unhandled 500 from the central handler | `{ "message": "Something went wrong" }` |
| `ValidationError` from Mongoose | 400 `{ "message": "<mongoose message>" }` |
| Auth controller 500s | `{ "message": "Server error", "error": "<raw message>" }` |
| Assistant 400 / 500 | `{ "error": "<text>" }` — note the key is `error`, not `message` |
| Rate limited | 429 `{ "message": "Too many attempts. Try again in a few minutes." }` |

The frontend reads `body.message` when throwing from `src/services/api.js`. **The assistant endpoints
are the exception**: their non-2xx bodies use `error`, so the generic helper would surface
`"Request failed: 500"` instead. Preserve this exactly, or fix it deliberately in both places.

### 0.2 Authentication

- Cookie: `token`, httpOnly, `SameSite=Strict`, `Secure` when `NODE_ENV=production`, `Max-Age` 7 days.
- JWT: HS256, payload `{ "id": "<user _id hex>" }`, `exp` 7 days.
- The token is never present in a response body.
- No `Authorization: Bearer` support. Cookie only.
- `POST /api/auth/logout` is **not** protected and always succeeds.
- Missing cookie → 401 `{ "message": "Not authenticated" }`.
- Bad/expired token → 401 `{ "message": "Invalid or expired token" }`.

### 0.3 Serialization rules

| Value | Wire form |
|---|---|
| ObjectId | 24-char hex string |
| Date | ISO-8601 UTC string (`"2026-01-31T12:00:00.000Z"`) |
| Numbers | JSON numbers (Mongoose may use `Decimal128`; these models declare plain numbers) |
| `undefined` fields | omitted by `JSON.stringify` |
| `null` | preserved (e.g. `invested: null` in portfolio history) |

`_id` keeps its underscore. Any Python layer must not expose `id` instead, must not drop `__v`, and
must not rename `createdAt`/`updatedAt` — the React code reads these names directly.

### 0.4 Ordering and pagination

- `GET /api/orders` and `GET /api/funds/transactions` sort by `createdAt: -1`.
- `GET /api/portfolio/history` sorts by `date: 1`.
- Everything else returns MongoDB natural order.
- **No endpoint paginates.** Lists are complete.

### 0.5 Date and timezone handling

- Timestamps are stored in UTC and serialised as UTC.
- Business-day logic (market hours, snapshot date) uses **IST** (`Asia/Kolkata`, UTC+05:30).
- Snapshot dates are the IST calendar day, stored as `Date` at UTC midnight of that day.
- Candle times are unix seconds **shifted by +19800 s** (IST offset) so the chart renders local time.
  See `GET /api/instruments/:symbol/candles`.

### 0.6 Concurrency contracts

Several endpoints are written as atomic compare-and-set. The equivalent FastAPI implementation must
preserve the **atomicity**, not just the response:

| Operation | Guard |
|---|---|
| Funds debit (order placement) | `{ user, available: { $gte: cost } }` then `$inc` |
| Funds debit (withdrawal) | `{ user, available: { $gte: amount } }` then `$inc` |
| Order fill claim | `{ _id, status: "OPEN" }` → `EXECUTED` |
| Position square-off claim | `deleteOne({ _id })`, require `deletedCount == 1` |
| CNC sell quantity | `{ user, symbol, exchange, qty: { $gte: qty } }` |
| MIS position averaging | update pipeline (`$add`/`$divide`) |

---

## 1. Health

### `GET /api/health`

- **Auth:** no.
- **Response 200:** `{ "ok": true }`
- **Mongo:** touches nothing; the server only starts listening after a successful `mongoose.connect`.

---

## 2. Auth — `/api/auth`

Rate limiting applies to `signup` and `login` only: 20 requests / 15 min / IP. Responses use
`RateLimit-*` headers (`standardHeaders: "draft-7"`), with no legacy `X-RateLimit-*` headers.

### 2.1 `POST /api/auth/signup`

- **Auth:** no. **Rate limited:** yes.
- **Body:**

  ```json
  { "username": "string", "email": "string", "password": "string" }
  ```

- **Validation, in order:**
  1. Any of the three missing → 400 `"Username, email and password are required"`.
  2. `password` not a string or shorter than 8 → 400 `"Password must be at least 8 characters"`.
  3. Email already present → 400 `"User already exists"`.
  4. Username already present → 400 `"User already exists"`.
- **Success 201:**

  ```json
  {
    "message": "Signup successful",
    "user": { "id": "<hex>", "username": "...", "email": "..." }
  }
  ```

  plus `Set-Cookie: token=...`.
- **500:** `{ "message": "Server error", "error": "<raw>" }`.
- **DB ops:** `User.findOne` twice (by email, then username), `User.create` (password hashed in a
  `pre("save")` hook, bcrypt cost 10).
- **Note:** there is no email format validation and no uniqueness pre-check race guard beyond the
  unique indexes. A duplicate-key error from a concurrent signup hits the 500 path.

### 2.2 `POST /api/auth/login`

- **Auth:** no. **Rate limited:** yes.
- **Body:** `{ "email": "string", "password": "string" }`
- **Errors:**
  - missing either → 400 `"Email and password are required"`
  - no user, or wrong password → 401 `"Invalid credentials"` (identical for both, deliberately)
  - unexpected → 500 `{ message, error }`
- **Success 200:** `{ "message": "Login successful", "user": { "id", "username", "email" } }` +
  `Set-Cookie`.
- **DB ops:** `User.findOne({ email })`, then `bcrypt.compare` against the stored hash.

### 2.3 `POST /api/auth/logout`

- **Auth:** no.
- **Body:** none, ignored.
- **Response 200:** `{ "message": "Logged out" }` + `Set-Cookie: token=; Max-Age=0` with the same
  attributes as the set cookie.
- **DB ops:** none.

### 2.4 `GET /api/auth/me`

- **Auth:** yes.
- **Response 200:** `{ "user": { ...full user doc, password excluded... } }`

  The user object therefore includes `_id`, `username`, `email`, `createdAt`, `updatedAt`, `__v` —
  **not** the compact `{ id, username, email }` shape used by login/signup.
- **Errors:** 404 `"User not found"` (valid token for a deleted user); 500 `{ message, error }`.
- **DB ops:** `User.findById(req.userId).select("-password")`.

---

## 3. Holdings — `/api/holdings`

### `GET /api/holdings`

- **Auth:** yes.
- **Response 200:** array of holding docs:

  ```json
  [{
    "_id": "...", "user": "...", "symbol": "TCS", "name": "Tata Consultancy Services",
    "exchange": "NSE", "qty": 10, "avgPrice": 3450.5, "ltp": 3500.0,
    "dayChangePct": 1.2, "sector": "IT", "createdAt": "...", "updatedAt": "...", "__v": 0
  }]
  ```

- **Errors:** only 401 from `protect`.
- **DB ops:** `HoldingsModel.find({ user })`.
- **Consumers:** Holdings page, dashboard cards, Nova `getHoldings`.

---

## 4. Positions — `/api/positions`

### 4.1 `GET /api/positions`

- **Auth:** yes.
- **Response 200:** array of position docs:
  `{ _id, user, symbol, name, exchange, side: "LONG"|"SHORT", product: "CNC"|"MIS", qty, entry, ltp,
  createdAt, updatedAt, __v }`.
  Positions here are MIS intraday only in practice; the model allows `CNC`.
- **DB ops:** `PositionsModel.find({ user })`.

### 4.2 `POST /api/positions/:id/square-off`

- **Auth:** yes.
- **Body:** none.
- **Preconditions, in order:**
  1. position exists for this user → else 404 `"Position not found"`
  2. `product === "MIS"` → else 400 `"Only MIS positions can be squared off here"`
  3. `ltp` is truthy → else 400 `"No live price for this position yet — try again shortly"`
- **Price:** live Yahoo `quote()` if it returns a price; on failure falls back to the stored `ltp`.
- **Success 200:**

  ```json
  { "message": "Squared off TCS", "pnl": 495.0 }
  ```

  `message` is `` `Squared off ${symbol}` ``. `pnl = (exit - entry) * qty * dir`, `dir = +1` LONG,
  `-1` SHORT.
- **409:** `"Position was already squared off"` — the `deleteOne` claim found nothing
  (concurrent request won).
- **Side effects, in order:**
  1. `FundsModel` `$inc available` by `entry * qty + pnl` (upsert).
  2. Insert `Transaction` `{ kind: "SETTLEMENT", method: "<SYMBOL> MIS square-off", amount: pnl,
     symbol, status: "COMPLETED" }`.
  3. Insert a closing `Order` `{ side: SELL for LONG / BUY for SHORT, type: "MARKET", product: "MIS",
     qty, filled: qty, price: exitPrice, status: "EXECUTED" }`.
  4. Cancel all open exit orders for that symbol/exchange/product.
- **UNVERIFIED:** a malformed `:id` causes a Mongoose CastError, which Express 5 forwards to the
  central handler as 500 `"Something went wrong"` rather than 404.
- **External dependency:** Yahoo quote. The route still works if Yahoo is down (falls back to `ltp`).

---

## 5. Orders — `/api/orders`

### 5.1 `GET /api/orders`

- **Auth:** yes.
- **Response 200:** array of order docs, newest first:

  ```json
  [{
    "_id": "...", "user": "...", "symbol": "INFY", "name": "Infosys", "exchange": "NSE",
    "side": "BUY", "type": "LIMIT", "product": "CNC",
    "qty": 5, "filled": 0, "price": 1500.0,
    "triggerPrice": 0, "slTrigger": 0, "tpPrice": 0,
    "groupId": "...", "isExit": false, "status": "OPEN",
    "createdAt": "...", "updatedAt": "...", "__v": 0
  }]
  ```

  Clients render the last 8 hex chars of `_id` as the order label.
- **Enums:** `side` BUY|SELL; `type` LIMIT|MARKET|SL|SL-M; `product` CNC|MIS;
  `status` OPEN|EXECUTED|CANCELLED|REJECTED.

### 5.2 `POST /api/orders`

- **Auth:** yes.
- **Body:**

  ```json
  {
    "symbol": "INFY", "name": "Infosys", "exchange": "NSE",
    "side": "BUY", "type": "LIMIT", "product": "CNC",
    "qty": 5, "price": 1500,
    "triggerPrice": 0, "slTrigger": 0, "tpPrice": 0
  }
  ```

  `qty`, `price`, `triggerPrice`, `slTrigger`, `tpPrice` are passed through `Number()`, so
  `"5"` is accepted. `exchange` defaults to `NSE` by the schema.
- **Validation order and exact errors:**

  | Check | Status | Message |
  |---|---|---|
  | missing `symbol`/`side`/`type`/`name` | 400 | `symbol, name, side and type are required` |
  | bad `side` | 400 | `side must be BUY or SELL` |
  | bad `type` | 400 | `type must be LIMIT, MARKET, SL or SL-M` |
  | bad `product` | 400 | `product must be CNC or MIS` |
  | `qty <= 0` or NaN | 400 | `Quantity must be greater than zero` |
  | non-integer `qty` | 400 | `Quantity must be a whole number` |
  | `price <= 0` and type ≠ MARKET | 400 | `Price must be greater than zero` |
  | MARKET quote unavailable | 503 | `No live price available for <SYMBOL>, try again in a moment` |
  | SL/SL-M with `triggerPrice <= 0` | 400 | `SL and SL-M orders need a trigger price` |
  | bracket SL/TP on wrong side of each other | 400 | `Stop-loss trigger must be below the target price for a buy` / `...above the target price for a sell` |
  | insufficient cash | 400 | `Insufficient funds: order needs ₹1,23,456 but only ₹1,00,000 is available` |
  | CNC sell larger than holdings | 400 | `Insufficient holdings: you hold 5 INFY but tried to sell 10` |

  Money in messages uses `toLocaleString("en-IN")` — Indian grouping, comma separators, no decimals
  forced.

- **Execution price:**
  - `MARKET` → live Yahoo `ltp` at placement time (this is also the 503 case).
  - `LIMIT` / `SL` / `SL-M` → the submitted `price`.
- **Cash block:** if `side === "BUY"` **or** `product === "MIS"`, atomically debit
  `qty * execPrice`. This happens **before** the CNC holdings check.
- **Success 201:** the full order doc.
  - `MARKET`: created with `status: "EXECUTED"`, `filled: qty`, then `applyFill` runs
    synchronously, so holdings/positions/funds are already updated when the response returns.
  - Others: `status: "OPEN"`, `filled: 0`.
  - If `slTrigger > 0` **or** `tpPrice > 0`, the order is saved again with
    `groupId = String(order._id)`.
- **DB ops:** `FundsModel.findOneAndUpdate` (guarded `$inc`), `HoldingsModel.findOne`,
  `OrdersModel.create`, optional `order.save()`, and on MARKET `applyFill` → holdings/positions/
  funds/transactions writes plus bracket exit creation.
- **External dependency:** Yahoo quote for MARKET orders. **Not gated on market hours.**
- **Known inconsistency:** a CNC sell that fails the holdings check returns 400 *after* the debit,
  with no refund. Documented in CURRENT_ARCHITECTURE §9; not changed here.

### 5.3 `POST /api/orders/exits`

Sets or replaces SL/target exits on an existing holding or open MIS position.

- **Auth:** yes.
- **Body:** `{ "symbol", "exchange", "product", "slTrigger", "tpPrice" }` — numeric fields run
  through `Number() || 0`.
- **Errors:**

  | Check | Status | Message |
  |---|---|---|
  | missing `symbol` or `product` | 400 | `symbol and product are required` |
  | both triggers ≤ 0 | 400 | `Set at least a stop-loss trigger or a target price` |
  | CNC, no holding | 404 | `No holding found for <SYMBOL>` |
  | CNC, SL ≥ TP when both set | 400 | `Stop-loss trigger must be below the target price` |
  | MIS, no open position | 404 | `No open MIS position found for <SYMBOL>` |
  | MIS, SL/TP on the wrong side | 400 | `...below the target price for a long` / `...above the target price for a short` |
  | product not CNC/MIS | 400 | `product must be CNC or MIS` |

- **Derived values:** `qty` from the holding/position; `side` is `SELL` for a CNC holding, and the
  opposite of the position side for MIS (`LONG` → `SELL`, `SHORT` → `BUY`).
- **Side effects:**
  1. Cancel existing `OPEN` exit orders for the same symbol/exchange/product; refund
     `qty * price` only when the old exit was `BUY` + `CNC` (upsert into funds).
  2. Generate a new `groupId` with `randomUUID()`.
  3. `createExitPair` → up to two orders: `SL-M` at `slTrigger`, `LIMIT` at `tpPrice`, both
     `isExit: true`.
- **Success 201:**

  ```json
  { "message": "Exit rules set for INFY", "orders": [ { ...order doc... }, { ... } ] }
  ```

  `orders` contains only the created exits, and may have one or two elements.
- **DB ops:** `HoldingsModel.findOne` / `PositionsModel.findOne`, `OrdersModel.find` + saves,
  `FundsModel.findOneAndUpdate` (conditional), `OrdersModel.create` × ≤2.

### 5.4 `DELETE /api/orders/:id`

Cancels an `OPEN` order and refunds its blocked cash.

- **Auth:** yes.
- **Claim:** `findOneAndUpdate({ _id, user, status: "OPEN" }, { status: "CANCELLED" })`.
- **Success 200:** the cancelled order doc.
- **Errors:**
  - no order for this user → 404 `"Order not found"`
  - exists but not OPEN → 400 `` `Order is already ${status.toLowerCase()}` `` (e.g.
    `"Order is already executed"`, `"Order is already cancelled"`)
- **Refund:** `unfilled = qty - filled`; if `unfilled > 0` and the order blocks cash
  (exit: only `BUY` + `CNC`; entry: `BUY` **or** `MIS`), credit `unfilled * price` (upsert).
- **UNVERIFIED:** malformed `:id` → CastError → 500, not 404.

---

## 6. Watchlist — `/api/watchlist`

### 6.1 `GET /api/watchlist`

- **Auth:** yes.
- **Response 200:** array of watchlist docs
  (`_id, user, symbol, name, exchange, ltp, dayChangePct, createdAt, updatedAt, __v`).

### 6.2 `POST /api/watchlist`

- **Auth:** yes.
- **Body:** `{ "symbol", "name", "exchange" }`
- **Validation:** symbol must match `^[\^A-Z0-9&-]{1,20}$` → else 400 `"Invalid symbol"`.
  A leading `^` is allowed for index tickers.
- **Duplicate check:** `findOne({ user, symbol })` (note: **not** scoped by exchange) → 409
  `"Already in watchlist"`.
- **Success 201:** the created doc.
- **Note:** `name` and `exchange` are not validated; `exchange` falls back to the schema default
  `NSE` when absent.

### 6.3 `DELETE /api/watchlist/:id`

- **Auth:** yes.
- **Response 204:** empty body, **always** — even when no document matched the user/id pair.
- **DB ops:** `deleteOne({ _id, user })`.
- **UNVERIFIED:** malformed `:id` → 500 via CastError.

---

## 7. Funds — `/api/funds`

### 7.1 `GET /api/funds`

- **Auth:** yes.
- **DB ops:** upsert a `Funds` row with `available: 0` if the user has none, then three reads
  (open orders, MIS positions, settlement transactions).
- **Response 200:**

  ```json
  {
    "_id": "...", "user": "...", "available": 50000,
    "createdAt": "...", "updatedAt": "...", "__v": 0,
    "usedMargin": 12000, "blockedInOrders": 2000, "misMargin": 10000, "realizedPnl": -350.5
  }
  ```

  - `blockedInOrders`: Σ `(qty − filled) × price` over `OPEN` orders that are **not** exits and are
    `BUY` or `MIS`.
  - `misMargin`: Σ `entry × qty` over `MIS` positions.
  - `usedMargin = blockedInOrders + misMargin`.
  - `realizedPnl`: Σ `amount` over `SETTLEMENT` transactions.
  - The `Funds` document's own fields are spread first, so the derived keys override any collision
    (there is none today).
- **Important:** `available` is **free cash**, not account equity. The UI derives equity itself.

### 7.2 `GET /api/funds/transactions`

- **Auth:** yes.
- **Response 200:** array of transaction docs, newest first:
  `{ _id, user, kind, method, amount, symbol?, status, createdAt, updatedAt, __v }`.
- `amount` is signed: deposits positive, withdrawals and losses negative.

### 7.3 `POST /api/funds/transactions`

- **Auth:** yes.
- **Body:** `{ "kind": "DEPOSIT"|"WITHDRAWAL", "amount": number|string, "method": string }`.
- **Validation:** `kind` must be DEPOSIT/WITHDRAWAL, `amount` must be a finite number > 0 after
  `Number()` → else 400 `"Invalid transaction"`.
- **Deposit:** upsert with `$inc available by amount`.
- **Withdrawal:** guarded `$inc -amount`; failure → 400 `"Amount exceeds available balance"`.
- **`method`:** stored only if it is one of
  `["Paper cash", "UPI", "Net banking", "Bank transfer", "Bank withdrawal"]`; otherwise the default
  `"Bank transfer"` (deposit) or `"Bank withdrawal"` (withdrawal).
- **Success 201:** `{ "funds": { ...funds doc... }, "transaction": { ...txn doc... } }`

  `funds` here is the **raw** document (`_id, user, available, timestamps`) — it does **not** include
  the derived `usedMargin`/`realizedPnl` keys that `GET /api/funds` adds.
- **Transaction record:** `kind`, `method`, `amount` (signed), `status: "COMPLETED"`, no `symbol`.

---

## 8. Portfolio — `/api/portfolio`

### `GET /api/portfolio/history?range=1M`

- **Auth:** yes.
- **Query:** `range` ∈ `1D | 1W | 1M | 1Y | ALL`; anything else falls back to 30 days. `ALL` = 100000
  days. Default `1M`.
- **Window:** `date >= now − days` (a `Date`, UTC arithmetic on the server).
- **Response 200:** array, ascending by date:

  ```json
  [
    { "label": "2026-09-01", "value": 812000.5, "invested": 750000 },
    { "label": "2026-09-02", "value": 819000, "invested": null }
  ]
  ```

  - `label`: `YYYY-MM-DD`, computed with `toLocaleDateString("en-CA")` on the server.
  - `value`: snapshot `value + misValue`.
  - `invested`: `snapshot.invested + misInvested`, or **`null`** when the snapshot has no `invested`
    (legacy rows) so the chart draws a gap.
- **Live point:** today's point is always appended using live holdings + open MIS positions. If a
  snapshot for today already exists, the last element is overwritten instead of duplicated.
- **Monitoring:** reads `PortfolioSnapshot`, `Holdings`, `Positions`, and `misComponents`.

---

## 9. Instruments — `/api/instruments`

Route order matters: `/search` and `/lookup/:symbol` are declared **before** `/:symbol`.

### 9.1 `GET /api/instruments/search?q=`

- **Auth:** yes.
- **Query:** `q` trimmed; empty → `[]`.
- **DB ops:** regex search over the **local** `MarketQuote` cache (`symbol` or `name`, case-insensitive,
  user input regex-escaped), limit 10, `.lean()`.
- **Response 200:**

  ```json
  [{ "symbol": "INFY", "name": "Infosys", "kind": "stock", "price": 1500.2, "changePct": 0.8 }]
  ```

  Field names are **renamed** here: `price` ← `ltp`, `changePct` ← `dayChangePct`.
- **No Yahoo call**, so it works offline and is cheap.

### 9.2 `GET /api/instruments/lookup/:symbol`

- **Auth:** yes.
- **External:** Yahoo `quote(tickerFor(symbol))`.
- **Response 200:**

  ```json
  {
    "symbol": "INFY", "name": "Infosys Limited", "exchange": "NSE",
    "price": 1500.2, "change": 12.1, "changePct": 0.81
  }
  ```

  `symbol` is uppercased; `name` falls back `longName → shortName → symbol`; `exchange` is always
  `"NSE"`.
- **404:** `"Instrument not found"` when Yahoo throws or returns no `regularMarketPrice`.

### 9.3 `GET /api/instruments/:symbol`

Same as lookup plus the extended quote:

```json
{
  "symbol": "...", "name": "...", "exchange": "NSE",
  "price": 0, "change": 0, "changePct": 0,
  "open": 0, "high": 0, "low": 0, "prevClose": 0, "volume": 0,
  "week52High": 0, "week52Low": 0
}
```

Field mapping: `regularMarketOpen`, `regularMarketDayHigh`, `regularMarketDayLow`,
`regularMarketPreviousClose`, `regularMarketVolume`, `fiftyTwoWeekHigh`, `fiftyTwoWeekLow`.
Missing values serialise as `undefined` → omitted from JSON.

### 9.4 `GET /api/instruments/:symbol/candles?range=1M`

- **Auth:** yes.
- **Range table:**

  | `range` | Lookback days | Interval |
  |---|---|---|
  | `1D` | 3 | `1m` |
  | `5D` | 5 | `5m` |
  | `SPARK` | 6 | `1d` |
  | `1M` | 30 | `30m` |
  | `6M` | 182 | `60m` |
  | `1Y` | 365 | `1d` |
  | `5Y` | 1825 | `1wk` |
  | `ALL` | 7300 | `1mo` |
  | anything else | 30 | `1d` |

- **External:** Yahoo `chart(tickerFor(symbol), { period1, interval })`, which resolves to
  `GET https://query2.finance.yahoo.com/v8/finance/chart/{ticker}` with `useYfid=true`,
  `includePrePost=true`, `events=div|split|earn`, `lang=en-US`, `interval`, `period1` and `period2`.
  The library supplies those extra parameters as defaults — the route passes only `period1` and
  `interval` — so they are part of the observed contract and are reproduced. See
  [MARKET_DATA_PLAN.md](./MARKET_DATA_PLAN.md) §3.1.
- **Response 200:** array; quotes with `open == null` are dropped:

  ```json
  [{ "time": 1758000000, "open": 0, "high": 0, "low": 0, "close": 0 }]
  ```

  `time` = unix seconds **+ 19800** (IST offset). There is no `volume` key.
- **404:** `"Could not fetch candle data"` on any provider error (message logged server-side).
- **No caching.** Each request is a live Yahoo call.

---

## 10. Market — `/api/market`

### `GET /api/market/overview`

- **Auth:** yes.
- **DB ops:** `MarketQuote.find({}).lean()` — cache only, no Yahoo call.
- **Response 200:**

  ```json
  {
    "asOf": "2026-09-13T10:05:00.000Z",
    "indices": [ { "symbol": "^NSEI", "name": "NIFTY 50", "kind": "index", "ltp": 0, ... } ],
    "stocks":  [ { "symbol": "RELIANCE", "kind": "stock", "ltp": 0, "dayChangePct": 0, ... } ]
  }
  ```

  - `indices` filtered to `kind === "index"` and sorted by the order declared in
    `server/data/nifty50.js`; unknown symbols sort to the front (`indexOf` returns `-1`).
  - `stocks` filtered to `kind === "stock"`, natural order.
  - `asOf` is the **maximum `updatedAt`** across rows, or `null` on a cold cache.
  - Full quote docs are returned (ltp, dayChange, dayChangePct, prevClose, volume, marketCap, sector).

---

## 11. Assistant — `/api/assistant`

All three endpoints are protected. All three **stream**; none returns a JSON body on success.

### 11.1 `POST /api/assistant/chat`

- **Auth:** yes.
- **Body:**

  ```json
  { "messages": [ { "id": "...", "role": "user", "parts": [ { "type": "text", "text": "..." } ] } ] }
  ```

  This is the Vercel AI SDK `UIMessage` array as produced by `useChat`. Assistant messages may carry
  `tool-*` parts.
- **Validation:** `messages` must be an array → else 400 `{ "error": "Invalid messages payload" }`.
- **Flow:** `convertToModelMessages(messages)` → `streamText({ model, system, messages, stopWhen:
  stepCountIs(5), tools })` → `pipeUIMessageStreamToResponse(res)`.
- **Success 200:** `Content-Type: text/event-stream`; **Vercel UI Message Stream** protocol
  (`data:` lines carrying JSON chunks, terminated appropriately). This is not OpenAI-style SSE and not
  newline-delimited JSON.
- **Errors before streaming:** 400 as above; 500 `{ "error": "<raw>" }`.
- **Tools:** `getPortfolioSummary`, `getHoldings`, `getPositions`, `getWatchlist`, `getFunds`,
  `getOrders` — all take `{}` and read `req.userId` from the request scope.
- **External:** Gemini. Rate limits apply (see AI_INTEGRATION_PLAN).
- **Consumers:** `src/features/assistant/AssistantContext.jsx` via `useChat`.

### 11.2 `POST /api/assistant/insight`

- **Auth:** yes.
- **Body:** `{ "page": "holdings", "data": { ...page-specific JSON... } }`
- **Flow:** builds a system prompt from `pageContext[page]` + format rules, then
  `streamText(...)` and `pipeTextStreamToResponse(res)`.
- **Success 200:** `Content-Type: text/plain` chunked body. **However**, the frontend's `useCompletion`
  is configured with `streamProtocol: "text"`, so this is consumed as a raw text stream.
- **Errors:** unhandled (no `try/catch`) → central handler → 500 `{ "message": "Something went wrong" }`
  if it fails before the pipe starts.
- **Prompt contract:** max 25 words; `pageContext` covers dashboard, holdings, positions, orders,
  watchlist, markets.

### 11.3 `POST /api/assistant/briefing`

- **Auth:** yes.
- **Body:** `{ "data": { ...portfolio summary... } }`
- **Flow:** a 2–3 sentence dashboard briefing, `streamText` → `pipeTextStreamToResponse`.
- **Success 200:** `text/plain` chunked.
- **Errors:** same as insight.

---

## 12. Frontend consumer map

| Endpoint | Consumer |
|---|---|
| `/api/auth/*` | `src/features/auth/AuthContext.jsx` |
| `/api/holdings` | Holdings page, dashboard cards, Nova |
| `/api/positions` (+ square-off) | Positions page, Nova |
| `/api/orders` (+ exits, cancel) | Orders page, order ticket, holdings "set exit" |
| `/api/watchlist` | WatchList page, instrument page |
| `/api/funds` (+ transactions) | Funds page, order ticket, Nova |
| `/api/portfolio/history` | Dashboard portfolio chart |
| `/api/instruments/search` | Symbol search in the order ticket / watchlist |
| `/api/instruments/lookup/:symbol` | Adding to watchlist |
| `/api/instruments/:symbol` | Instrument page header/stats |
| `/api/instruments/:symbol/candles` | Instrument chart (lightweight-charts) |
| `/api/market/overview` | Markets page |
| `/api/assistant/chat` | `AssistantContext` (`useChat`) |
| `/api/assistant/insight`, `/briefing` | `PageInsight` (`useCompletion`, text protocol) |

---

## 13. What a FastAPI implementation must reproduce

Non-negotiable for response parity:

1. Exact key names, including `_id`, `__v`, `qty` (not `quantity`), `ltp`, `avgPrice`, `dayChangePct`.
2. `user` serialised as a hex string.
3. ISO-8601 UTC timestamps.
4. Cookie-only auth, same cookie name and flags, 7-day JWT with `{ id }`.
5. The `{ message }` error envelope (and `{ error }` for the three assistant routes).
6. The exact status codes, including 503 for a missing MARKET price and 409 for the two conflict cases.
7. The `text/event-stream` UI Message Stream for chat and `text/plain` for insight/briefing.
8. The Indian number formatting inside error strings.
9. `null` vs omitted distinctions: `invested: null`, omitted `undefined` quote fields.
10. Atomicity of the guarded updates in §0.6.

Explicitly **not** guaranteed by this document:

- Byte-identical SSE chunking (the protocol must be equivalent, not identical).
- Yahoo field availability for any given symbol.
- Behaviour under concurrent load beyond what the guards imply.
