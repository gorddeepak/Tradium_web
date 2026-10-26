# PostgreSQL Migration Audit: MongoDB Usage

> **Status:** Phase 1 read-only audit. This document does not change application code,
> schemas, dependencies, configuration, tests, or MongoDB access.
>
> **Scope:** the active FastAPI backend in `api/`, the legacy Express/Mongoose code in
> `server/` as schema evidence, the test suite, the Express-parity harnesses, and the
> seed/backfill scripts.
>
> **Evidence boundary:** all findings below come from source inspection of the current
> working tree. No production data, live MongoDB index metadata, or sample documents were
> inspected in this pass. Claims that depend on actual data are marked **PROFILE REQUIRED**
> and must be confirmed before constraints are finalized.
>
> **Companion documents:** `docs/migration/API_CONTRACTS.md` (wire shapes and concurrency
> expectations), `docs/migration/CURRENT_ARCHITECTURE.md` (prior architecture findings),
> `docs/migration/MIGRATION_PLAN.md` (phase gates), and `docs/migration/MIGRATION_STATUS.md`
> (known issues and prior verification).
>
> **Current state (2026-10-26, Phase 3B3.1).** This audit is the pre-migration baseline and is kept
> unchanged below. Since it was written, four surfaces have moved to PostgreSQL:
> `users` (Phase 3B1 — authentication and the daily snapshot user list), `instruments` and
> `latest_quotes` (Phase 3B2 — market cache) and `watchlists` (Phase 3B3 — `GET`/`POST`/`DELETE
> `/api/watchlist`; Phase 3B3.1 — `price_sync` symbol source and Nova's `getWatchlist`). Still
> MongoDB-backed: `holdings`, `positions`, `orders`, `funds`, `transactions`, the `portfoliosnapshots`
> documents, and Nova's other tools. No automatic MongoDB → PostgreSQL data load exists for users or
> watchlists. See `MIGRATION_STATUS.md` §3P–§3S and §4 for the current gaps.

## Contents

1. [Executive summary](#1-executive-summary)
2. [Collection inventory](#2-collection-inventory)
3. [Usage and code references](#3-usage-and-code-references)
4. [Relationships and invariants](#4-relationships-and-invariants)
5. [MongoDB-specific patterns and migration implications](#5-mongodb-specific-patterns-and-migration-implications)
6. [Proposed PostgreSQL tables](#6-proposed-postgresql-tables)
7. [Migration and cutover](#7-migration-and-cutover)
8. [Ranked open questions and risks](#8-ranked-open-questions-and-risks)
9. [Implementation phases and testing](#9-implementation-phases-and-testing)
10. [Appendix A: Evidence index](#appendix-a-evidence-index)

---

## 1. Executive summary

### 1.1 What the database actually is

The application uses **nine real MongoDB collections**:

`users`, `holdings`, `positions`, `orders`, `funds`, `transactions`, `watchlists`,
`marketquotes`, and `portfoliosnapshots`.

Every document is a flat, scalar document. There are **no embedded documents, no arrays,
and no polymorphic sub-documents** in any model or write path. The data model is therefore
a straightforward relational model with one global cache table (`marketquotes`) and eight
user-scoped or identity tables.

The active runtime is the FastAPI app. It uses **PyMongo directly** (`api/db.py:17-27`),
not Mongoose. The Express/Mongoose code remains useful as evidence of intended schema,
defaults, enums, and indexes, but it is not the current write path. This distinction matters
because PyMongo bypasses Mongoose validation: required fields, enums, defaults, and
`__v` behaviour are reproduced by hand, and not always completely.

### 1.2 Main conclusion

A PostgreSQL migration is feasible without changing the external API shape. The hard part
is not table design; it is preserving **identity, numeric semantics, missing-field
tolerance, ordering, and multi-document financial behaviour**.

The safest migration path is:

1. Preserve the existing 24-character ObjectId hex as the primary/foreign-key identifier.
2. Profile the real data before deciding nullability, uniqueness enforcement, and numeric
   precision.
3. Translate the small set of Mongo-specific atomic operations into explicit PostgreSQL
   conditional updates/upserts and transactions.
4. Treat known behavioural defects (the phantom `watchlist` read, the unconditional
   position delete after a partial MIS exit, and the OCO race) as decisions that must be
   made **before** schema design, not as incidental refactors.
5. Cut over offline with one source of truth, not with dual writes.

### 1.3 Highest-impact findings

| # | Finding | Evidence | Why it matters |
|---|---|---|---|
| 1 | API IDs are 24-character ObjectId hex strings, and JWT `id` claims contain the same value. | `api/auth.py:31-43`, `api/serialization.py:14-25`, `docs/migration/API_CONTRACTS.md:34-42` | A UUID-only schema would break existing cookies, `_id` values, and the frontend's order-ID display. |
| 2 | The FastAPI app does not create indexes or unique constraints. | No `create_index`/`ensure_index` call exists under `api/`; `api/db.py:17-27` only connects. Legacy indexes are in `server/models/*.js`. | A fresh database used by FastAPI can contain duplicate funds, holdings, positions, watchlists, snapshots, or quotes. |
| 3 | PyMongo writes bypass Mongoose required/enum/default validation. | `api/documents.py:19-27`, `api/routes/watchlist.py:56-64`, `api/routes/orders.py:163-184` | Real data can violate the intended schema; PostgreSQL `NOT NULL`/`CHECK` constraints may fail during migration. |
| 4 | Financial writes span multiple documents without a transaction. | Order placement `api/routes/orders.py:127-188`; square-off `api/routes/positions.py:69-121`; deposit `api/routes/funds.py:95-119`; exits `api/order_engine.py:174-197`. | A failure between writes can lose cash, leave an order EXECUTED without its fill, or delete a position without crediting proceeds. |
| 5 | The `watchlist` tool reads the wrong collection. | `api/assistant.py:227` reads `db["watchlist"]`; the real collection is `watchlists` (`api/routes/watchlist.py:8,53,64`). | Nova's watchlist tool returns an empty list, and a direct table-for-collection mapping would create a phantom table. |
| 6 | MIS exit settlement deletes the whole position even after a partial fill. | `api/order_engine.py:245-278`; test `api/tests/test_price_sync.py:557-572` | A partial exit can silently discard the remaining position. PostgreSQL should not encode this accidentally. |
| 7 | Several read routes rely on MongoDB natural order. | `api/routes/holdings.py:33-35`, `api/routes/positions.py:33`, `api/routes/watchlist.py:35`, `api/routes/market.py:31-40` | PostgreSQL has no natural order; API output can change unless explicit `ORDER BY` is defined. |
| 8 | Numeric fields are BSON int32/int64/double and are treated as JavaScript numbers. | `api/js_compat.py:1-9`, `api/serialization.py:27-33`, parity harness `tools/express-parity/harness_env.py:53-84` | Choosing `numeric` without an end-to-end Decimal policy will change arithmetic, JSON rendering, and assistant formatting. |

### 1.4 Recommendation

**Do not begin PostgreSQL schema design or Alembic work yet.** First resolve the decisions
in §8, especially identifier strategy, numeric strategy, transaction boundaries, and
whether known defects are preserved or fixed. Then create the schema and migrations against
a profiled, representative dataset.

No application, schema, dependency, test, or MongoDB code was changed by this audit.

---

## 2. Collection inventory

### 2.1 Inventory summary

| Collection | Legacy model | Purpose | Scope | Business key / unique index | Current FastAPI index creation |
|---|---|---|---|---|---|
| `users` | `User` (`server/models/User.js`) | Identity and credentials | Global | `username`, `email` unique | None |
| `funds` | `funds` (`server/models/FundsModel.js`) | One cash balance per user | User | `user` unique | None |
| `holdings` | `holding` (`server/models/HoldingsModel.js`) | Delivery (CNC) holdings | User | `(user, symbol, exchange)` unique | None |
| `positions` | `position` (`server/models/PositionsModel.js`) | Intraday (MIS) positions | User | `(user, symbol, exchange, side, product)` unique | None |
| `orders` | `order` (`server/models/OrdersModel.js`) | Order lifecycle, exits, brackets | User | None | None |
| `transactions` | `transaction` (`server/models/TransactionModel.js`) | Cash/ledger history | User | None | None |
| `watchlists` | `watchlist` (`server/models/WatchlistModel.js`) | Tracked symbols | User | `(user, symbol, exchange)` unique | None |
| `marketquotes` | `MarketQuote` (`server/models/MarketQuoteModel.js`) | Shared market-data cache | Global | `symbol` unique | None |
| `portfoliosnapshots` | `PortfolioSnapshot` (`server/models/PortfolioSnapshotModel.js`) | Daily portfolio history | User | `(user, date)` unique | None |
| `watchlist` (singular) | — | **Phantom read-only collection** | — | — | — |

The singular `watchlist` entry is not a real collection. It appears only in
`api/assistant.py:227`. The legacy Express controller uses `WatchlistModel`
(`server/controllers/assistantController.js:8,122`), which resolves to `watchlists`.
There is no writer for `db["watchlist"]`.

### 2.2 `users`

| Field | Current shape | Legacy schema | Notes |
|---|---|---|---|
| `_id` | ObjectId | Auto | Exposed as 24-char hex; JWT `id` uses the same hex. |
| `username` | string | required, unique | Case-sensitive in MongoDB by default. |
| `email` | string | required, unique | No email-format validation in FastAPI. Login is exact-match (`api/routes/auth.py:105`). |
| `password` | string | required | bcrypt hash, cost 10 (`api/auth.py:23-24`, `server/models/User.js:11-14`). |
| `createdAt`, `updatedAt` | Date | Mongoose timestamps | Millisecond precision on the wire. |
| `__v` | integer | Mongoose version key | Created by `new_document` as 0 (`api/documents.py:19-27`); not incremented by current FastAPI updates. |

### 2.3 `funds`

| Field | Current shape | Legacy schema | Notes |
|---|---|---|---|
| `_id` | ObjectId | Auto | |
| `user` | ObjectId | required, unique | One row per user. |
| `available` | number | default 0 | Free cash. `usedMargin` is derived at read time, not stored (`api/routes/funds.py:62-67`). |
| `createdAt`, `updatedAt` | Date | Mongoose timestamps | |
| `__v` | integer | Mongoose version key | |

### 2.4 `holdings`

| Field | Current shape | Legacy schema | Notes |
|---|---|---|---|
| `_id` | ObjectId | Auto | |
| `user` | ObjectId | required | |
| `symbol` | string | required | e.g. `RELIANCE`. |
| `name` | string | required | Display name. |
| `exchange` | string | enum `NSE`, default `NSE` | FastAPI accepts arbitrary values when creating orders/watchlist; holdings come from order data. |
| `qty` | number | required | Current order route validates whole quantities; holdings merge uses order `qty`. |
| `avgPrice` | number | required | Weighted average cost. |
| `ltp` | number | default 0 | Refreshed by `price_sync`. |
| `dayChangePct` | number | default 0 | Refreshed by `price_sync`. |
| `sector` | string | default `""` | Backfilled once by `price_sync`; empty means pending. |
| `createdAt`, `updatedAt` | Date | Mongoose timestamps | Some FastAPI merge paths do not refresh `updatedAt`; see §5. |
| `__v` | integer | Mongoose version key | |

Unique index: `(user, symbol, exchange)` (`server/models/HoldingsModel.js:15-16`).

### 2.5 `positions`

| Field | Current shape | Legacy schema | Notes |
|---|---|---|---|
| `_id` | ObjectId | Auto | |
| `user` | ObjectId | required | |
| `symbol` | string | required | |
| `name` | string | required | |
| `exchange` | string | enum `NSE`, default `NSE` | |
| `side` | string | enum `LONG`, `SHORT`, required | |
| `product` | string | enum `CNC`, `MIS`, required | Current fill code creates MIS only; square-off rejects non-MIS. |
| `qty` | number | required | |
| `entry` | number | required | Weighted average entry. |
| `ltp` | number | default 0 | Refreshed by `price_sync`. |
| `createdAt`, `updatedAt` | Date | Mongoose timestamps | |
| `__v` | integer | Mongoose version key | |

Unique index: `(user, symbol, exchange, side, product)`
(`server/models/PositionsModel.js:15-16`).

### 2.6 `orders`

| Field | Current shape | Legacy schema | Notes |
|---|---|---|---|
| `_id` | ObjectId | Auto | |
| `user` | ObjectId | required | |
| `symbol` | string | required | |
| `name` | string | required | |
| `exchange` | string | enum `NSE`, default `NSE` | |
| `side` | string | enum `BUY`, `SELL`, required | |
| `type` | string | enum `MARKET`, `LIMIT`, `SL`, `SL-M`, required | |
| `product` | string | enum `CNC`, `MIS`, required | |
| `qty` | number | required | Validated as a positive whole number on placement (`api/routes/orders.py:88-91`). |
| `filled` | number | default 0 | Current system has no partial fills: 0 or full `qty`. |
| `price` | number | required | For LIMIT/SL this is the client's limit price (`triggerPrice` holds the stop trigger); MARKET stores the live execution price at placement, and SL-M overwrites it at fill (`api/jobs/price_sync.py:206-217`). |
| `triggerPrice` | number | default 0 | Used by SL/SL-M. |
| `slTrigger` | number | default 0 | Bracket stop-loss trigger. |
| `tpPrice` | number | default 0 | Bracket target. |
| `groupId` | string | default `""` | Bracket entry: its own `_id` hex. Exit request: a UUID4 string (`api/routes/orders.py:284`). |
| `isExit` | boolean | default false | |
| `status` | string | enum `EXECUTED`, `OPEN`, `CANCELLED`, `REJECTED`, default `OPEN` | |
| `createdAt`, `updatedAt` | Date | Mongoose timestamps | |
| `__v` | integer | Mongoose version key | |

No unique index and no non-unique index is declared in the legacy model. Query-heavy
columns are `user`, `status`, `createdAt`, `groupId`, and the symbol/product/isExit set.

### 2.7 `transactions`

| Field | Current shape | Legacy schema | Notes |
|---|---|---|---|
| `_id` | ObjectId | Auto | |
| `user` | ObjectId | required | |
| `kind` | string | enum `DEPOSIT`, `WITHDRAWAL`, `SETTLEMENT`, `FEE`, required | The FastAPI routes create only DEPOSIT, WITHDRAWAL, and SETTLEMENT. Seed data includes FEE (`server/scripts/seedDemo.js:78-84`). |
| `method` | string | default `"Bank transfer"` | Human-readable label, not an enum. |
| `amount` | number | required | Signed: deposits positive, withdrawals negative; settlements carry realized P&L and can be either sign; seed fees are negative. |
| `symbol` | string | default `""` | Only settlement rows usually carry a symbol. |
| `status` | string | enum `COMPLETED`, `PROCESSING`, default `PROCESSING` | Current route writes COMPLETED; seed data includes PROCESSING. |
| `createdAt`, `updatedAt` | Date | Mongoose timestamps | |
| `__v` | integer | Mongoose version key | |

There is **no foreign key or stored link from a transaction to an order or position**.
The only association is the `symbol` string and the human-readable `method`.

### 2.8 `watchlists`

| Field | Current shape | Legacy schema | Notes |
|---|---|---|---|
| `_id` | ObjectId | Auto | |
| `user` | ObjectId | required | |
| `symbol` | string | required | Validated by `SYMBOL_PATTERN` (`api/routes/watchlist.py:24-25,48-49`). |
| `name` | string or null | required | **FastAPI writes `body.get("name")`, so it can store null** (`api/routes/watchlist.py:56-64`). Mongoose would reject that. |
| `exchange` | string | enum `NSE`, default `NSE` | FastAPI accepts any supplied value. |
| `ltp` | number | default 0 | Refreshed by `price_sync`. |
| `dayChangePct` | number | default 0 | Refreshed by `price_sync`. |
| `createdAt`, `updatedAt` | Date | Mongoose timestamps | |
| `__v` | integer | Mongoose version key | |

Unique index: `(user, symbol, exchange)` (`server/models/WatchlistModel.js:12-13`). The
route's duplicate pre-check is only `(user, symbol)`, deliberately matching Express
(`api/routes/watchlist.py:52-54`).

### 2.9 `marketquotes`

| Field | Current shape | Legacy schema | Notes |
|---|---|---|---|
| `_id` | ObjectId | Auto | |
| `symbol` | string | required, unique | e.g. `RELIANCE`, `^NSEI`. |
| `name` | string | required | |
| `kind` | string | enum `stock`, `index`, default `stock` | |
| `ltp` | number | default 0 | |
| `dayChange` | number | default 0 | |
| `dayChangePct` | number | default 0 | |
| `prevClose` | number | default 0 | |
| `volume` | number | default 0 | Whole share/index volume in practice; profile required. |
| `marketCap` | number | default 0 | Can exceed 32-bit range; the test fixture uses ~16 trillion (`api/tests/test_market_sync.py:205-206`). |
| `sector` | string | default `""` | Backfilled separately; not written by the quote cycle. |
| `createdAt`, `updatedAt` | Date | Mongoose timestamps | `updatedAt` is the cache age; there is no `asOf` field. |
| `__v` | integer | Mongoose version key | |

This is a **global cache**, not user-scoped. There is no FK to holdings/positions/watchlists;
a symbol can exist in a user's book without a cache row, and vice versa.

### 2.10 `portfoliosnapshots`

| Field | Current shape | Legacy schema | Notes |
|---|---|---|---|
| `_id` | ObjectId | Auto | |
| `user` | ObjectId | required | |
| `date` | Date | required | IST calendar day stored at UTC midnight (`api/jobs/portfolio_snapshot.py:26-30`). |
| `value` | number | required | Holdings value plus open MIS value. |
| `invested` | number | default 0 | Older snapshots may omit it; the API renders that as `null` (`api/routes/portfolio.py:56-59`). |
| `misInvested` | number | default 0 | MIS cost basis. |
| `misValue` | number | default 0 | MIS current value. |
| `createdAt`, `updatedAt` | Date | Mongoose timestamps | |
| `__v` | integer | Mongoose version key | |

Unique index: `(user, date)` (`server/models/PortfolioSnapshotModel.js:14-15`).

---

## 3. Usage and code references

### 3.1 Access style

All runtime database access is through PyMongo collection handles (`db["..."].find`,
`find_one`, `insert_one`, `update_one`, `find_one_and_update`, `delete_one`,
`update_many`, `bulk_write`). There is no repository layer, no ODM, and no shared query
module. This means the PostgreSQL migration must reproduce both the query semantics and
the write sequencing, not just the table shapes.

The database is selected from the connection string in `api/db.py:17-27`. Tests inject a
`mongomock` database (`api/tests/conftest.py:33-42`); the optional real-Mongo suite is
skipped unless `TEST_MONGO_URL` is set (`api/tests/test_mongo_integration.py:28-32`).

### 3.2 Collection usage matrix

| Collection | Operation | Code reference | Filter / effect |
|---|---|---|---|
| `users` | signup duplicate checks | `api/routes/auth.py:72-75` | `email`, then `username`. |
| `users` | signup insert | `api/routes/auth.py:77-78` | New Mongoose-style document. |
| `users` | login lookup | `api/routes/auth.py:105` | Exact `email`; password checked with bcrypt. |
| `users` | `GET /me` lookup | `api/routes/auth.py:138` | `_id`; returns 404 if missing. |
| `users` | snapshot enumeration | `api/jobs/portfolio_snapshot.py:43` | All users, projection `{_id: 1}`. |
| `holdings` | list | `api/routes/holdings.py:33-35` | All rows for JWT user, natural order. |
| `holdings` | assistant reads | `api/assistant.py:127,155` | All rows for user. |
| `holdings` | snapshot valuation | `api/jobs/portfolio_snapshot.py:46-48` | All rows for user; direct `qty`/`ltp`/`avgPrice`. |
| `holdings` | price refresh | `api/jobs/price_sync.py:87,122-135` | Read all, update `ltp`, `dayChangePct`, `updatedAt`. |
| `holdings` | CNC sell check | `api/routes/orders.py:146-159` | `user` + `symbol` (+ `exchange` if supplied). |
| `holdings` | exit quantity source | `api/routes/orders.py:214-226` | `user` + `symbol` (+ `exchange` if supplied). |
| `holdings` | CNC buy merge | `api/order_engine.py:76-120` | Read by `(user, symbol, exchange)`, update pipeline or insert. |
| `holdings` | CNC sell fill | `api/order_engine.py:121-158` | Guarded `$inc` by `(user, symbol, exchange, qty >= order.qty)`; delete if zero; credit funds; insert settlement. |
| `positions` | list | `api/routes/positions.py:26-34` | All rows for user, natural order. |
| `positions` | assistant reads | `api/assistant.py:190` | All rows for user. |
| `positions` | snapshot valuation | `api/jobs/portfolio_snapshot.py:51-52` | `user` + `product=MIS`. |
| `positions` | price refresh | `api/jobs/price_sync.py:88,137-144` | Read all, update `ltp`, `updatedAt`. |
| `positions` | MIS fill merge | `api/order_engine.py:24-73` | Read by `(user, symbol, exchange, product=MIS, side)`, update pipeline or insert. |
| `positions` | MIS exit settlement | `api/order_engine.py:218-278` | Read by user/symbol/exchange/product/side; guarded decrement; delete; credit funds; insert settlement. |
| `positions` | square-off | `api/routes/positions.py:44-121` | Read by `_id` + user; delete claim; credit funds; insert transaction/order; cancel exits. |
| `orders` | list | `api/routes/orders.py:43-52` | `user`, sorted `createdAt` descending. |
| `orders` | place order | `api/routes/orders.py:56-190` | Validates; debits funds for BUY/MIS; checks holdings for CNC SELL; inserts order; applies MARKET fill. |
| `orders` | set exits | `api/routes/orders.py:193-287` | Reads holding/position, cancels old exits, creates new pair. |
| `orders` | cancel | `api/routes/orders.py:290-321` | Conditional `OPEN -> CANCELLED`; refunds unfilled blocked cash. |
| `orders` | funds blocked-cash view | `api/routes/funds.py:49-54` | `user` + `status=OPEN`; sums non-exit BUY/MIS. |
| `orders` | assistant reads | `api/assistant.py:266-316` | `user`, optional status, sorted `createdAt` descending, limited. |
| `orders` | price-sync fills | `api/jobs/price_sync.py:91,185-243` | All `OPEN` orders; conditional claim `_id + status=OPEN`; fill or settle. |
| `orders` | sibling cancellation | `api/order_engine.py:281-299` | `groupId` + `isExit` + `status=OPEN`; excludes current order. |
| `orders` | square-off history/cancel | `api/routes/positions.py:89-121` | Inserts closing order; cancels open MIS exits by user/symbol/exchange/product. |
| `funds` | get / first-read create | `api/routes/funds.py:35-67` | `user`; inserts `available: 0` if missing. |
| `funds` | deposit / withdraw | `api/routes/funds.py:82-122` | Deposit upserts/increments; withdrawal guarded decrement; inserts transaction. |
| `funds` | shared increment helper | `api/documents.py:30-47` | Upsert `$inc`, `$setOnInsert` timestamps/version. |
| `funds` | order debit | `api/routes/orders.py:127-143` | Guarded decrement by `user + available >= amount`. |
| `funds` | order refund | `api/routes/orders.py:312-319` | Refund unfilled blocked cash on cancel. |
| `funds` | fill credits/refunds | `api/order_engine.py:145-146,176-177,265,298-299` | Sell proceeds, exit blocking, MIS release, sibling refunds. |
| `funds` | assistant read | `api/assistant.py:263` | `user`. |
| `transactions` | list | `api/routes/funds.py:70-79` | `user`, sorted `createdAt` descending. |
| `transactions` | deposit/withdraw insert | `api/routes/funds.py:111-119` | New document. |
| `transactions` | assistant settlements | `api/assistant.py:279` | `user` + `kind=SETTLEMENT`. |
| `transactions` | fill settlements | `api/order_engine.py:149-158,268-277` | New document on CNC sell / MIS exit. |
| `transactions` | square-off settlement | `api/routes/positions.py:77-86` | New document. |
| `watchlists` | list | `api/routes/watchlist.py:28-36` | All rows for user, natural order. |
| `watchlists` | add | `api/routes/watchlist.py:39-65` | Duplicate check `(user, symbol)`; insert. |
| `watchlists` | delete | `api/routes/watchlist.py:68-77` | `_id` + user; always 204. |
| `watchlists` | price refresh | `api/jobs/price_sync.py:89,146-159` | Read all, update `ltp`, `dayChangePct`, `updatedAt`. |
| `watchlist` | **phantom read** | `api/assistant.py:227` | Reads `db["watchlist"]`, which no writer creates. |
| `marketquotes` | overview | `api/routes/market.py:31-48` | All rows; indices ordered by fixed `INDEX_ORDER`, stocks in natural order. |
| `marketquotes` | search | `api/routes/instruments.py:42-45` | Case-insensitive regex on `symbol` or `name`, limit 10, natural order. |
| `marketquotes` | quote bulk upsert | `api/jobs/market_sync.py:56-98,113-116` | `UpdateOne` on `symbol`, `$set` quote fields, `$setOnInsert` `createdAt`/`sector`/`__v`. |
| `marketquotes` | sector backfill | `api/jobs/market_sync.py:127-158` | `kind=stock` + `sector=""`, limit 10; update by `_id`. |
| `marketquotes` | cache count | `api/jobs/market_sync.py:172` | `estimated_document_count()`. |
| `portfoliosnapshots` | history | `api/routes/portfolio.py:48-50` | `user` + `date >= since`, sorted `date` ascending. |
| `portfoliosnapshots` | daily upsert | `api/jobs/portfolio_snapshot.py:57-70` | `user + date`; `$set` values, `$setOnInsert` timestamps/version. |
| `portfoliosnapshots` | backfill MIS fields | `server/scripts/backfillSnapshots.js:63-87` | `_id`; `$set` `misValue`/`misInvested` only. |

### 3.3 Critical write-path traces

#### Signup

1. Validate non-empty username/email/password and password length
   (`api/routes/auth.py:63-70`).
2. Check email and username separately (`api/routes/auth.py:72-75`).
3. Insert a Mongoose-shaped user document (`api/routes/auth.py:77-78`).
4. Sign a JWT whose `id` is the ObjectId hex (`api/auth.py:31-43`).
5. Set the cookie and return `{message, user: {id, username, email}}`
   (`api/routes/auth.py:80-84`).

There is no transaction and no database-level duplicate check in the FastAPI code; the
Mongoose unique indexes are the only race guard, and they are not created by FastAPI.

#### Limit order placement (BUY or SELL)

1. Validate symbol/name/side/type/product, coerce qty/price/trigger
   (`api/routes/orders.py:56-98`).
2. If side is BUY or product is MIS, atomically debit `qty * exec_price` with a
   `available >= amount` guard (`api/routes/orders.py:127-143`).
3. For CNC SELL only, check holdings (`api/routes/orders.py:145-159`).
4. Insert an OPEN order (`api/routes/orders.py:163-184`).
5. A later `price_sync` tick claims it and fills it (`api/jobs/price_sync.py:185-243`).

#### MARKET BUY placement

1. Fetch a live quote; if unavailable, return 503 (`api/routes/orders.py:92-104`).
2. Debit funds as above.
3. Insert an EXECUTED order with `filled = qty` and `price = exec_price`
   (`api/routes/orders.py:162-184`).
4. Call `apply_fill` immediately (`api/routes/orders.py:186-188`).

`apply_fill` may spawn bracket exits, merge a position, or merge a holding
(`api/order_engine.py:15-120`). These are separate writes from the order insert and debit.

#### CNC SELL fill

1. `apply_fill` reads the holding and performs a guarded decrement
   (`api/order_engine.py:121-132`).
2. If no row matched, the order is marked REJECTED and sibling exits are cancelled
   (`api/order_engine.py:133-141`).
3. If the remaining qty is zero, the holding is deleted (`api/order_engine.py:142-143`).
4. Sale proceeds are credited (`api/order_engine.py:145-146`).
5. A SETTLEMENT transaction is inserted (`api/order_engine.py:149-158`).
6. If the order is an exit, siblings are cancelled (`api/jobs/price_sync.py:242-243`).

#### MIS exit fill

1. `price_sync` claims the exit order (`api/jobs/price_sync.py:210-223`).
2. `settle_mis_exit` finds the opposite position (`api/order_engine.py:227-235`).
3. It computes `qty = min(order.qty, position.qty)` and P&L
   (`api/order_engine.py:245-248`).
4. It performs a guarded decrement (`api/order_engine.py:250-261`).
5. It credits entry + P&L (`api/order_engine.py:265`).
6. It inserts a SETTLEMENT transaction (`api/order_engine.py:268-277`).
7. It **deletes the position unconditionally** (`api/order_engine.py:278`).

#### Square-off

1. Read position by `_id` + user; reject non-MIS and missing `ltp`
   (`api/routes/positions.py:44-55`).
2. Choose live quote or stored `ltp` (`api/routes/positions.py:57-61`).
3. Compute P&L and release (`api/routes/positions.py:63-67`).
4. Delete the position as the claim (`api/routes/positions.py:69-72`).
5. Credit funds (`api/routes/positions.py:74`).
6. Insert SETTLEMENT transaction and closing order (`api/routes/positions.py:76-108`).
7. Cancel open MIS exits (`api/routes/positions.py:110-121`).

#### Deposit / withdrawal

1. Validate kind and positive finite amount (`api/routes/funds.py:88-92`).
2. Deposit: `inc_funds` upsert-increment (`api/routes/funds.py:95-96`).
3. Withdrawal: guarded decrement (`api/routes/funds.py:97-105`).
4. Insert transaction (`api/routes/funds.py:107-119`).
5. Return raw funds plus transaction (`api/routes/funds.py:121-122`).

#### Price-sync tick

1. Market-hours gate (`api/jobs/price_sync.py:66-71`).
2. Process-local non-blocking lock (`api/jobs/price_sync.py:73-82`).
3. Read all holdings, positions, watchlists, and OPEN orders
   (`api/jobs/price_sync.py:85-91`).
4. Build one distinct symbol+exchange map and one batched provider call
   (`api/jobs/price_sync.py:93-108`).
5. Update only rows with a usable quote (`api/jobs/price_sync.py:110-159`).
6. Backfill missing sectors one holding at a time (`api/jobs/price_sync.py:161-182`).
7. Match and fill OPEN orders with a conditional claim (`api/jobs/price_sync.py:184-247`).

#### Daily snapshot

1. Compute IST calendar day at UTC midnight (`api/jobs/portfolio_snapshot.py:26-30`).
2. For each user, read holdings and MIS positions
   (`api/jobs/portfolio_snapshot.py:42-52`).
3. Upsert on `(user, date)` (`api/jobs/portfolio_snapshot.py:57-70`).
4. A failure aborts the remaining users but does not raise
   (`api/jobs/portfolio_snapshot.py:72-74`; test `api/tests/test_portfolio_snapshot.py:120-135`).

### 3.4 Legacy and tooling references

- The legacy Express models define the intended schema and unique indexes
  (`server/models/*.js`).
- The legacy seed script writes users, funds, holdings, positions, orders, watchlists,
  transactions, and portfolio snapshots (`server/scripts/seedDemo.js:248-377`).
- The legacy backfill script writes only `portfoliosnapshots.misValue` and
  `portfoliosnapshots.misInvested` (`server/scripts/backfillSnapshots.js:63-87`).
- The Express-parity harness compares Mongo-backed FastAPI responses with Express and
  normalizes BSON numeric types (`tools/express-parity/harness_env.py:53-84`). This is
  direct evidence that int32/double distinctions are observable in test output and must be
  handled deliberately.
- The optional real-Mongo integration test covers deposit, watchlist add/remove, two
  MARKET MIS fills, square-off, limit placement, and cancel
  (`api/tests/test_mongo_integration.py:277-315`). It is skipped without
  `TEST_MONGO_URL`.

---

## 4. Relationships and invariants

### 4.1 Relationship map

```text
users 1 ─── N holdings
users 1 ─── N positions
users 1 ─── N orders
users 1 ─── 1 funds
users 1 ─── N transactions
users 1 ─── N watchlists
users 1 ─── N portfolio_snapshots

marketquotes          (global; no user FK)
orders.groupId ──soft──> orders._id / UUID group
orders.symbol ──soft──> marketquotes.symbol / holdings.symbol / positions.symbol
transactions.symbol ──soft──> holdings/positions/orders symbol
```

There are no MongoDB foreign keys and no cascade rules. User-scoped collections are linked
only by the stored `user` ObjectId. `groupId` is a string, not an ObjectId column, because
exit requests use UUID4 while bracket entries use the entry order's ObjectId hex.

### 4.2 Unique and business keys

| Collection | Key | Enforcement today | Notes |
|---|---|---|---|
| `users` | `username` | Mongoose unique index | Case-sensitive. |
| `users` | `email` | Mongoose unique index | Case-sensitive; login is exact match. |
| `funds` | `user` | Mongoose unique index | One balance row per user. |
| `holdings` | `(user, symbol, exchange)` | Mongoose unique index | FastAPI relies on legacy-created index. |
| `positions` | `(user, symbol, exchange, side, product)` | Mongoose unique index | Long and short can coexist. |
| `watchlists` | `(user, symbol, exchange)` | Mongoose unique index | Route duplicate check is only `(user, symbol)`. |
| `marketquotes` | `symbol` | Mongoose unique index | Global cache. |
| `portfoliosnapshots` | `(user, date)` | Mongoose unique index | Date is UTC midnight of IST day. |
| `orders` | none | — | Multiple orders per symbol/day/group are expected. |
| `transactions` | none | — | Multiple ledger rows per user/day/kind are expected. |

### 4.3 Invariants the system relies on

These are real behaviours that the relational implementation must either preserve or
deliberately change:

1. **User isolation.** Every user-scoped route derives the user from the JWT and filters
   by it. No route accepts a user id from the body or query
   (`api/auth.py:64-82`; e.g. `api/routes/holdings.py:30-35`).
2. **One funds row per user.** `GET /api/funds` creates one if missing
   (`api/routes/funds.py:42-46`); `inc_funds` upserts one (`api/documents.py:30-47`).
3. **Cash cannot go below zero through the guarded paths.** Order debit and withdrawal use
   `available >= amount` (`api/routes/orders.py:127-143`, `api/routes/funds.py:97-105`).
   `inc_funds` itself is unguarded and can create a negative balance if called with a
   negative amount.
4. **Order claim.** A fill only happens if `status` is still `OPEN`
   (`api/jobs/price_sync.py:209-223`). A cancel only happens if `status` is still `OPEN`
   (`api/routes/orders.py:297-302`).
5. **Order status semantics.** `OPEN` means unfilled; `EXECUTED` means filled; `CANCELLED`
   and `REJECTED` are terminal. Current code has no partial fills.
6. **Fill accounting.** On execution, `filled` is set to `qty`; on placement, `filled` is
   `qty` for MARKET and 0 otherwise (`api/routes/orders.py:162-179`,
   `api/jobs/price_sync.py:213-218`).
7. **Bracket/OCO.** A bracket entry's `groupId` is its own `_id` hex; exits share it
   (`api/routes/orders.py:181-183`). Filling one exit cancels open siblings
   (`api/order_engine.py:281-299`).
8. **Holdings merge.** CNC BUY merges quantity and weighted average; CNC SELL decrements
   with a qty guard and deletes at zero (`api/order_engine.py:76-158`).
9. **Positions merge.** MIS fills merge quantity and weighted entry per side
   (`api/order_engine.py:24-73`).
10. **Snapshot uniqueness.** One row per user per IST day; a rerun updates the numbers
    (`api/jobs/portfolio_snapshot.py:57-70`).
11. **Market cache uniqueness.** One row per symbol; quote sync never writes `sector`
    (`api/jobs/market_sync.py:74-96`).
12. **Price preservation on provider failure.** A failed or empty batch must not overwrite
    stored prices (`api/jobs/price_sync.py:100-120`; tests
    `api/tests/test_price_sync.py:189-220`).

### 4.4 Invariants that are not enforced

These are schema-drift and migration hazards:

- No FK constraints in MongoDB. Orphan `user` references are possible if a user is removed
  by a script or manual operation.
- No `NOT NULL` enforcement in FastAPI writes. `watchlists.name` can be null
  (`api/routes/watchlist.py:59`); tests also insert partial holdings/orders/watchlists
  directly (`api/tests/test_mongo_integration.py:110-149`).
- No enum enforcement. FastAPI accepts arbitrary `exchange` values in orders and
  watchlists; only `side`, `type`, `product` are checked in the orders route.
- No check that `qty > 0` in holdings/positions/orders after raw writes; order placement
  validates positive whole qty, but fills and direct inserts do not re-check.
- No check that `filled <= qty` or `price > 0` in the database.
- No check that `funds.available >= 0`; `inc_funds` can create a negative balance.
- No check that a snapshot `date` is exactly UTC midnight; the job writes that shape, but
  legacy/direct rows may not.
- No check that `groupId` is non-empty for bracket exits or that an exit's side/product
  matches its entry.
- No check that a transaction's `amount` sign matches its `kind`.
- No check that an order's `price` is still the original limit price; it is overwritten on
  SL-M/MARKET fills.
- No check that `updatedAt` changes on every mutation. CNC buy/position merge paths update
  quantities but do not set `updatedAt` (`api/order_engine.py:37-58,86-106`).
- No check that `__v` increments. Current FastAPI writes create 0 and generally leave it
  alone.

### 4.5 Derived values that must stay derived

Do not turn these into stored columns without a deliberate denormalization decision:

- `funds.usedMargin`, `blockedInOrders`, `misMargin`, `realizedPnl`
  (`api/routes/funds.py:48-67`).
- Portfolio summary values and P&L (`api/portfolio_math.py:22-58`).
- Today's live portfolio point (`api/routes/portfolio.py:64-84`).
- Holdings/positions current value and P&L; the stored `ltp` is a cache, not the source of
  truth for a trade.
- Assistant summaries; they are computed from the tables at request time
  (`api/assistant.py:125-339`).

`holdings` and `positions` are **current-state tables**, not projections that can be
rebuilt from `orders` today: order history is incomplete for reconstructing average cost,
and `orders.price` is overwritten on fills. Keep them as stored state unless a separate
event-sourcing project is approved.

---

## 5. MongoDB-specific patterns and migration implications

### 5.1 Pattern catalogue

| # | Pattern | Where | PostgreSQL implication | Risk |
|---|---|---|---|---|
| 1 | ObjectId `_id` and `user` references | All collections | Preserve 24-char hex or add a mapping layer. | High |
| 2 | Mongoose `createdAt`/`updatedAt`/`__v` | `api/documents.py:19-27`, all writes | Add timestamp/version columns and app-managed values. | Medium |
| 3 | Mongoose validation bypass | PyMongo writes throughout `api/` | Constraints may reject existing data; profile first. | High |
| 4 | FastAPI does not create indexes | `api/db.py:17-27`; no `create_index` in `api/` | Migrations must create all unique/non-unique indexes. | High |
| 5 | Atomic `$inc` upsert | `api/documents.py:30-47` | `INSERT ... ON CONFLICT` with additive update. | Medium |
| 6 | Guarded `$gte` debit | `api/routes/orders.py:127-143`, `api/routes/funds.py:97-105` | Conditional `UPDATE ... WHERE available >= amount`. | High |
| 7 | Conditional order claim | `api/jobs/price_sync.py:209-223`, `api/routes/orders.py:297-302` | Conditional `UPDATE ... WHERE status='OPEN' RETURNING`. | High |
| 8 | Server-side weighted-average update pipeline | `api/order_engine.py:37-58,86-106` | `ON CONFLICT DO UPDATE` with arithmetic on old row values, or transaction + row lock. | High |
| 9 | `$setOnInsert` sector/timestamp preservation | `api/jobs/market_sync.py:74-96`, `api/jobs/portfolio_snapshot.py:57-70` | `ON CONFLICT DO UPDATE` that omits `sector`/`created_at`; insert defaults separately. | Medium |
| 10 | Ordered `bulk_write` quote upserts | `api/jobs/market_sync.py:56-98,113-116` | Multi-row upsert in one transaction; decide all-or-nothing vs per-row. | Medium |
| 11 | Regex search | `api/routes/instruments.py:42-45` | `ILIKE`/`position(lower(...))` with escaped wildcards, or `pg_trgm` if needed. | Low |
| 12 | Natural-order reads | holdings/positions/watchlist/market stocks/search | Add explicit `ORDER BY`; do not assume insertion order. | Medium |
| 13 | No multi-document transactions | Orders, funds, exits, square-off, settlements | Add transactions or preserve partial-write behaviour. | Critical |
| 14 | IST date stored at UTC midnight | `api/jobs/portfolio_snapshot.py:26-30` | `timestamptz(3)` for parity, or `date` with a deliberate range-semantics change. | Medium |
| 15 | JS number semantics | `api/js_compat.py`, `api/serialization.py`, assistant `_js_round` | Decide `double precision` vs `numeric`; Decimal changes arithmetic and JSON. | High |
| 16 | Missing vs null vs default | Tests insert partial docs; FastAPI writes nullable name | Profile and choose nullable/default/NOT NULL per column. | High |
| 17 | Phantom `watchlist` read | `api/assistant.py:227` | Do not create a table for it; fix the read or map it to `watchlists`. | High (functional) |
| 18 | OCO is not atomic with fill | `api/jobs/price_sync.py:238-243`, `api/order_engine.py:281-299` | Lock the group/position or cancel siblings in the same transaction. | High |
| 19 | Position deleted after partial exit | `api/order_engine.py:245-278` | Preserve only if intentional; otherwise decrement and delete at zero. | High |
| 20 | No FK/cascade | All collections | Choose `RESTRICT` vs `CASCADE`; current app has no user-delete route. | Medium |
| 21 | Process-local job locks | `api/jobs/price_sync.py:73-82`, `api/jobs/market_sync.py:168-181` | Keep scheduler ownership or add PostgreSQL advisory locks. | Medium |
| 22 | Unique violations become generic 500s | `api/main.py:155-159`; auth catches at `api/routes/auth.py:85-88` | Map `IntegrityError` per route; preserve or deliberately improve status. | Medium |
| 23 | Malformed ObjectId becomes 500 | `ObjectId(...)` casts, generic handler `api/main.py:155-159` | Text IDs may return empty/404 instead; decide whether to preserve 500. | Medium |
| 24 | `estimated_document_count()` | `api/jobs/market_sync.py:172` | Use `count(*)`; the table is tiny. | Low |

### 5.2 The transaction problem in detail

The current system is not transactionally consistent. The important sequences are:

- **Order placement:** debit funds, insert order, then `apply_fill` for MARKET
  (`api/routes/orders.py:127-188`).
- **Limit fill:** claim order, adjust SL-M cash, merge position/holding, credit funds,
  insert settlement, cancel siblings (`api/jobs/price_sync.py:209-243`;
  `api/order_engine.py`).
- **Square-off:** delete position, credit funds, insert transaction, insert order, cancel
  exits (`api/routes/positions.py:69-121`).
- **Deposit/withdrawal:** mutate funds, insert transaction (`api/routes/funds.py:95-119`).
- **Set exits:** cancel old exits/refunds, create new legs/debits
  (`api/routes/orders.py:193-287`, `api/order_engine.py:161-198`).

PostgreSQL transactions can make each sequence atomic. That is an improvement, but it is a
**behaviour change**: today a mid-sequence failure can leave a partial state, and the
application has no compensation logic. The migration must decide, per flow, whether to:

- preserve partial-write behaviour exactly (not recommended),
- make the whole flow atomic (recommended), or
- add an explicit saga/compensation model (probably overkill for this app).

The schema alone cannot answer this. The write-path design must.

### 5.3 The OCO race in detail

`price_sync` claims an exit order, then `settle_mis_exit`, then cancels siblings
(`api/jobs/price_sync.py:210-243`). Two exit legs can be claimed by two workers or two
ticks before either cancels the other. The position decrement guard prevents releasing more
cash than the position quantity, but the OCO rule ("only one leg may fill") is not atomic
with the claim.

In PostgreSQL, the safe pattern is to serialize on the position or group before settling,
for example by locking the position row (`SELECT ... FOR UPDATE`) and cancelling siblings
inside the same transaction. If the group has no position row, lock the group's order rows
or use a transaction-scoped advisory lock keyed by `groupId`. This is a design decision,
not a mechanical translation.

### 5.4 The partial-exit bug

`settle_mis_exit` computes `qty = min(order.qty, position.qty)` and decrements by that
amount, but then deletes the position unconditionally (`api/order_engine.py:245-278`).
The test explicitly documents this (`api/tests/test_price_sync.py:557-572`). If an exit
order is smaller than the position, the remainder is lost.

Do not encode this as a PostgreSQL trigger or a `DELETE ... CASCADE` side effect. Decide
whether to preserve Express parity or fix the behaviour. If fixed, update the tests and the
settlement transaction amount, and add a regression test for a partial exit.

### 5.5 Natural order

MongoDB `find({})` has no guaranteed order. The current API returns:

- holdings, positions, watchlists: natural order (`api/routes/holdings.py:33-35`,
  `api/routes/positions.py:33`, `api/routes/watchlist.py:35`);
- market stocks: natural order after filtering (`api/routes/market.py:31-40`);
- search results: natural order after regex match, limit 10
  (`api/routes/instruments.py:42-45`);
- assistant holdings/positions/watchlists: natural order
  (`api/assistant.py:127,155,190,227`).

Orders, transactions, and portfolio history already have explicit sort orders. PostgreSQL
requires explicit ordering for deterministic output. Recommended orderings:

- holdings/positions/watchlists: `created_at ASC, id ASC` (closest to insertion order).
- market stocks: a stable symbol or seed order; define it explicitly.
- search: relevance is currently undefined; use `symbol` exact/prefix first, then `name`,
  or preserve the current unspecified behaviour and document it.
- assistant tools: same ordering as their corresponding pages.

This may change visible row order. Treat it as a deliberate API decision, not a silent
side effect.

### 5.6 Numeric semantics

The code deliberately reproduces JavaScript number behaviour:

- `js_number` converts request values to floats and renders whole values as ints
  (`api/js_compat.py:1-91`).
- `to_json_value` passes numbers through unchanged (`api/serialization.py:27-33`).
- The parity harness normalizes BSON int32/double to compare outputs
  (`tools/express-parity/harness_env.py:53-84`).
- The numbers parity test seeds `0.1 + 0.2`, `1e21`, `-0.0`, and whole floats
  (`tools/express-parity/fastapi_numbers.py:41-47`,
  `tools/express-parity/express_numbers.cjs:38-50`).

PostgreSQL `numeric` returns `Decimal`, which is not handled by `to_json_value` and is not
accepted by assistant `_js_round` arithmetic without conversion. A naive `numeric` switch
would change arithmetic, JSON rendering, and assistant formatting. This is why numeric type
selection is a Phase 2 decision, not a table-design afterthought.

### 5.7 Date and timezone semantics

- BSON Date is stored in UTC with millisecond precision. `to_json_value` always emits
  three fractional digits (`api/serialization.py:19-25`).
- Portfolio snapshot `date` is the IST calendar day at UTC midnight
  (`api/jobs/portfolio_snapshot.py:26-30`). The history route filters with a rolling
  `now - days` window and labels points in IST (`api/routes/portfolio.py:44-62`).
- `timestamptz(3)` preserves current behaviour. A `date` column is semantically cleaner
  but changes the range boundary from a rolling 24-hour window to calendar days; that is a
  deliberate API change, not a drop-in migration.

### 5.8 Error mapping and malformed IDs

- The generic FastAPI handler returns `{message: "Something went wrong"}` for unhandled
  exceptions (`api/main.py:155-159`).
- Auth routes catch everything and return `{message: "Server error", error: "..."}`
  (`api/routes/auth.py:85-88`).
- An invalid ObjectId in a route such as holdings/orders/watchlist raises `InvalidId`,
  which becomes the generic 500. A `char(24)` PostgreSQL column would simply match no rows,
  producing an empty list/404/204 instead.
- A PostgreSQL unique violation raises `IntegrityError`. Without translation it becomes a
  generic 500, which may or may not match the current race behaviour.

These are small but real API-contract differences. Decide whether to preserve the current
status codes/bodies or deliberately improve them.

---

## 6. Proposed PostgreSQL tables

> This section is a logical design proposal, not SQLAlchemy models or Alembic migrations.
> It is deliberately conditional on the decisions in §8.

### 6.1 Cross-cutting conventions

| Concern | Recommendation | Reason |
|---|---|---|
| Primary keys | `char(24)` containing the existing lowercase ObjectId hex, with a `^[0-9a-f]{24}$` check | Preserves JWT `id`, API `_id`, frontend order labels, and all existing references without a mapping table. |
| Foreign keys | `user_id char(24) NOT NULL REFERENCES users(id) ON DELETE RESTRICT` | Current app has no user-delete route; `RESTRICT` avoids silent data loss. Revisit if account deletion is added. |
| New IDs | Application-generated 12 random bytes rendered as 24 lowercase hex chars | Same external shape as ObjectId; do not rely on ObjectId timestamp internals. |
| `groupId` | `text NOT NULL DEFAULT ''` (or `varchar(36)`) | Holds both 24-char ObjectId hex and 36-char UUID4. Not a FK. |
| API field names | Keep camelCase in serializers; use snake_case columns | Avoid leaking SQL naming into the API contract. |
| `created_at`, `updated_at` | `timestamptz(3) NOT NULL` | BSON Date is millisecond precision; `(3)` avoids extra digits. Truncate application timestamps to milliseconds before insert. |
| `__v` | `version integer NOT NULL DEFAULT 0`, serialized as `__v` | Preserves the wire shape. Do not auto-increment in Phase 1; current FastAPI does not. |
| Defaults | Database defaults for simple constants; application supplies timestamps/IDs | Keeps the write path explicit and testable. |
| Text | `text` for symbols, names, methods, exchange, status | No evidence-based length limit; avoid truncation. |
| Case sensitivity | Ordinary `text` unique indexes | MongoDB unique indexes are case-sensitive by default; `citext` would change behaviour. |
| Derived values | Do not store `usedMargin`, `blockedInOrders`, `misMargin`, `realizedPnl`, portfolio summary | Keep one source of truth; compute at read time. |
| Arrays/JSONB | None needed | No embedded documents or arrays exist. |

### 6.2 Numeric type recommendation

There are two viable strategies. They must not be mixed.

**Strategy A — behaviour-preserving cutover (recommended first step):**

- Use `double precision` for every current BSON number that is not a whole count.
- Use `integer` for `qty`/`filled` **if profiling confirms all values are whole**;
  otherwise use `numeric(20,4)` temporarily and flag the offending rows.
- Use `bigint` for `volume` and `market_cap` if profiling confirms whole values; otherwise
  `numeric(24,2)`.
- Keep Python floats and the existing `js_compat`/serialization path.
- This preserves `0.1 + 0.2`, `1e21`, `-0.0`, whole-float rendering, and assistant
  arithmetic exactly.

**Strategy B — financially correct target:**

- Use `numeric(20,4)` for money/price fields, `numeric(12,4)` for percentages, and
  `numeric(20,4)` for quantities (or `integer` after integrality cleanup).
- Use Python `Decimal` end-to-end.
- Add explicit rounding and JSON-serialization policy; update `to_json_value`, `js_compat`,
  `portfolio_math`, assistant `_js_round`, and API tests.
- This is the better long-term schema, but it is a larger behavioural change.

**Recommendation:** if the cutover must be low-risk and API-identical, start with Strategy A
and schedule Strategy B as a separate hardening phase. If the team is willing to do the
Decimal work before cutover, use Strategy B and test it against the existing numeric parity
fixtures. Do not use `numeric` columns while leaving Python code on floats.

### 6.3 Table specifications

Common columns for all tables unless noted:

- `id char(24) PRIMARY KEY`
- `created_at timestamptz(3) NOT NULL`
- `updated_at timestamptz(3) NOT NULL`
- `version integer NOT NULL DEFAULT 0`

#### `users`

| Column | Type | Null | Default | Constraints / notes |
|---|---|---|---|---|
| `username` | `text` | NOT NULL | — | `UNIQUE`; `CHECK (username <> '')`. |
| `email` | `text` | NOT NULL | — | `UNIQUE`; `CHECK (email <> '')`. Case-sensitive to match Mongo. |
| `password_hash` | `text` | NOT NULL | — | Store the bcrypt hash; `GET /me` omits it. Never expose the hash. |

No role/profile columns are evidenced.

#### `funds`

| Column | Type | Null | Default | Constraints / notes |
|---|---|---|---|---|
| `user_id` | `char(24)` | NOT NULL | — | `UNIQUE`; `REFERENCES users(id) ON DELETE RESTRICT`. |
| `available` | `double precision` (Strategy A) or `numeric(20,4)` (Strategy B) | NOT NULL | 0 | Do not add `CHECK (available >= 0)` until existing negatives are profiled and the unguarded `inc_funds` paths are reviewed. |

#### `holdings`

| Column | Type | Null | Default | Constraints / notes |
|---|---|---|---|---|
| `user_id` | `char(24)` | NOT NULL | — | FK to `users`. |
| `symbol` | `text` | NOT NULL | — | `CHECK (symbol <> '')`. |
| `name` | `text` | NOT NULL | — | Profile for missing names; do not invent silently. |
| `exchange` | `text` | NOT NULL | `'NSE'` | Defer `CHECK (exchange = 'NSE')` until profile confirms no other values. |
| `qty` | `integer` or `numeric(20,4)` | NOT NULL | — | `CHECK (qty > 0)` after cleanup. |
| `avg_price` | `double precision` / `numeric(20,4)` | NOT NULL | — | `CHECK (avg_price >= 0)`. |
| `ltp` | same | NOT NULL | 0 | `CHECK (ltp >= 0)`. |
| `day_change_pct` | percentage | NOT NULL | 0 | No lower bound; `-100` is meaningful. |
| `sector` | `text` | NOT NULL | `''` | Empty means pending backfill. |

Unique: `(user_id, symbol, exchange)`.

#### `positions`

| Column | Type | Null | Default | Constraints / notes |
|---|---|---|---|---|
| `user_id` | `char(24)` | NOT NULL | — | FK to `users`. |
| `symbol` | `text` | NOT NULL | — | `CHECK (symbol <> '')`. |
| `name` | `text` | NOT NULL | — | |
| `exchange` | `text` | NOT NULL | `'NSE'` | |
| `side` | `text` | NOT NULL | — | `CHECK (side IN ('LONG','SHORT'))`. |
| `product` | `text` | NOT NULL | — | `CHECK (product IN ('CNC','MIS'))`; current writes create MIS. |
| `qty` | `integer` or `numeric(20,4)` | NOT NULL | — | `CHECK (qty > 0)`. |
| `entry` | same as money | NOT NULL | — | `CHECK (entry >= 0)`. |
| `ltp` | same as money | NOT NULL | 0 | `CHECK (ltp >= 0)`. |

Unique: `(user_id, symbol, exchange, side, product)`.

#### `orders`

| Column | Type | Null | Default | Constraints / notes |
|---|---|---|---|---|
| `user_id` | `char(24)` | NOT NULL | — | FK to `users`. |
| `symbol` | `text` | NOT NULL | — | `CHECK (symbol <> '')`. |
| `name` | `text` | NOT NULL | — | |
| `exchange` | `text` | NOT NULL | `'NSE'` | Defer enum check until profile. |
| `side` | `text` | NOT NULL | — | `CHECK (side IN ('BUY','SELL'))`. |
| `type` | `text` | NOT NULL | — | `CHECK (type IN ('MARKET','LIMIT','SL','SL-M'))`. |
| `product` | `text` | NOT NULL | — | `CHECK (product IN ('CNC','MIS'))`. |
| `qty` | `integer` (or `numeric`) | NOT NULL | — | `CHECK (qty > 0)`. |
| `filled` | same as qty | NOT NULL | 0 | `CHECK (filled >= 0 AND filled <= qty)`. |
| `price` | money | NOT NULL | — | `CHECK (price >= 0)`. |
| `trigger_price` | money | NOT NULL | 0 | `CHECK (trigger_price >= 0)`. |
| `sl_trigger` | money | NOT NULL | 0 | `CHECK (sl_trigger >= 0)`. |
| `tp_price` | money | NOT NULL | 0 | `CHECK (tp_price >= 0)`. |
| `group_id` | `text` | NOT NULL | `''` | No FK; mixed ObjectId/UUID formats. |
| `is_exit` | `boolean` | NOT NULL | false | |
| `status` | `text` | NOT NULL | `'OPEN'` | `CHECK (status IN ('OPEN','EXECUTED','CANCELLED','REJECTED'))`. |

Indexes:

- `(user_id, created_at DESC)` for `GET /api/orders`.
- `(user_id, status)` for funds blocked-cash and assistant filters.
- `(status)` or partial `(status) WHERE status = 'OPEN'` for price-sync scans.
- `(group_id) WHERE is_exit AND status = 'OPEN'` for OCO sibling lookup.
- `(symbol, product, is_exit, status)` for symbol-scoped exit/cancel flows, if profiling
  shows it is needed.

Do not add a unique constraint on `groupId`: a group has two exit legs and may have
historical cancelled rows.

#### `transactions`

| Column | Type | Null | Default | Constraints / notes |
|---|---|---|---|---|
| `user_id` | `char(24)` | NOT NULL | — | FK to `users`. |
| `kind` | `text` | NOT NULL | — | `CHECK (kind IN ('DEPOSIT','WITHDRAWAL','SETTLEMENT','FEE'))` to cover seed data. |
| `method` | `text` | NOT NULL | `'Bank transfer'` | Human-readable; no enum. |
| `amount` | money | NOT NULL | — | Signed. Do not add a sign check until every kind's convention is documented. |
| `symbol` | `text` | NOT NULL | `''` | Not a FK. |
| `status` | `text` | NOT NULL | `'PROCESSING'` | `CHECK (status IN ('COMPLETED','PROCESSING'))`. |

Indexes: `(user_id, created_at DESC)`, `(user_id, kind)`.

No `order_id`/`position_id` in Phase 1: current data has no such link and backfilling it is
not reliable. Consider nullable columns later if reporting requires them.

#### `watchlists`

| Column | Type | Null | Default | Constraints / notes |
|---|---|---|---|---|
| `user_id` | `char(24)` | NOT NULL | — | FK to `users`. |
| `symbol` | `text` | NOT NULL | — | `CHECK (symbol <> '')`. |
| `name` | `text` | NOT NULL after cleanup | — | Current FastAPI can write null; backfill first, or keep nullable during the transition. |
| `exchange` | `text` | NOT NULL | `'NSE'` | |
| `ltp` | money | NOT NULL | 0 | `CHECK (ltp >= 0)`. |
| `day_change_pct` | percentage | NOT NULL | 0 | |

Unique: `(user_id, symbol, exchange)`.

#### `market_quotes`

| Column | Type | Null | Default | Constraints / notes |
|---|---|---|---|---|
| `symbol` | `text` | NOT NULL | — | `UNIQUE`; `CHECK (symbol <> '')`. |
| `name` | `text` | NOT NULL | — | |
| `kind` | `text` | NOT NULL | `'stock'` | `CHECK (kind IN ('stock','index'))`. |
| `ltp` | money | NOT NULL | 0 | `CHECK (ltp >= 0)`. |
| `day_change` | money | NOT NULL | 0 | Can be negative. |
| `day_change_pct` | percentage | NOT NULL | 0 | Can be negative. |
| `prev_close` | money | NOT NULL | 0 | `CHECK (prev_close >= 0)`. |
| `volume` | `bigint` or `numeric` | NOT NULL | 0 | `CHECK (volume >= 0)` if whole. |
| `market_cap` | `bigint` or `numeric(24,2)` | NOT NULL | 0 | `CHECK (market_cap >= 0)`. |
| `sector` | `text` | NOT NULL | `''` | Never overwritten by quote sync. |

Indexes: unique `(symbol)`; optional `(kind, sector)` or partial
`(kind) WHERE sector = ''` for backfill. At ~53 rows, these are not performance-critical.

#### `portfolio_snapshots`

| Column | Type | Null | Default | Constraints / notes |
|---|---|---|---|---|
| `user_id` | `char(24)` | NOT NULL | — | FK to `users`. |
| `snapshot_date` | `timestamptz(3)` (parity) or `date` (semantic target) | NOT NULL | — | See §5.7. |
| `value` | money | NOT NULL | — | No non-negative check; short MIS value can be negative. |
| `invested` | money | NOT NULL after backfill | 0 | Legacy rows may be missing; backfill first, or keep nullable during the transition. |
| `mis_invested` | money | NOT NULL | 0 | |
| `mis_value` | money | NOT NULL | 0 | |

Unique: `(user_id, snapshot_date)`.

If `date` is chosen, add a conversion rule from BSON Date to IST calendar date and change
the history query from a rolling timestamp window to a calendar-day window. That is a
behaviour decision, not a mechanical mapping.

### 6.4 Index summary

| Table | Index | Purpose |
|---|---|---|
| `users` | `(username)` unique | Signup username duplicate check. |
| `users` | `(email)` unique | Login/signup. |
| `funds` | `(user_id)` unique | One row per user; funds read. |
| `holdings` | `(user_id, symbol, exchange)` unique | Holdings list and merge key. |
| `positions` | `(user_id, symbol, exchange, side, product)` unique | Position merge key. |
| `positions` | `(user_id, product)` | Funds/MIS and snapshot queries. |
| `orders` | `(user_id, created_at DESC)` | Orders page and assistant. |
| `orders` | `(user_id, status)` | Blocked cash and assistant filters. |
| `orders` | `(status) WHERE status = 'OPEN'` | Price-sync scan. |
| `orders` | `(group_id) WHERE is_exit AND status = 'OPEN'` | OCO sibling lookup. |
| `transactions` | `(user_id, created_at DESC)` | Transactions page. |
| `transactions` | `(user_id, kind)` | Realized P&L and assistant. |
| `watchlists` | `(user_id, symbol, exchange)` unique | Watchlist list/add. |
| `market_quotes` | `(symbol)` unique | Quote upsert/search. |
| `market_quotes` | `(kind, sector)` optional | Sector backfill. |
| `portfolio_snapshots` | `(user_id, snapshot_date)` unique | History and daily upsert. |

### 6.5 Tables deliberately not proposed

- `order_fills`: current orders have no partial fills and no fill history. Adding it would
  be a new feature, not a migration.
- `order_groups`: `groupId` is small and mixed-format; normalizing it is optional and would
  require a data decision.
- `cash_ledger`/double-entry: `transactions` is a ledger, but it is not double-entry and
  has no order link. Replacing it is a separate accounting project.
- `sessions`: auth is stateless JWT.
- `watchlist` singular: this is a bug, not a table.
- `market_quotes` replacement cache such as Redis: out of scope and unnecessary for the
  current 53-symbol cache.

---

## 7. Migration and cutover

### 7.1 Strategy and source of truth

**Recommended:** an offline, one-way migration.

1. MongoDB remains the authoritative source before cutover.
2. The migration reads MongoDB and writes PostgreSQL without changing MongoDB.
3. The application is stopped (or writes are frozen) during the final export/load.
4. PostgreSQL becomes the sole writer at cutover.
5. MongoDB remains read-only for audit/rollback until acceptance and retention expiry.

Do **not** run dual writes for the first cutover. Dual writes create two sources of truth,
require conflict resolution, and make rollback ambiguous. If near-zero downtime becomes a
requirement later, design a CDC/outbox strategy separately.

### 7.2 Export order and mapping

Load in FK order:

1. `users`
2. `funds`
3. `holdings`
4. `positions`
5. `orders`
6. `transactions`
7. `watchlists`
8. `market_quotes` (independent; can be parallel)
9. `portfolio_snapshots`

Field mapping:

| MongoDB | PostgreSQL | Rule |
|---|---|---|
| `_id` | `id` | Lowercase 24-char hex; fail the row if not exactly 24 hex. |
| `user` | `user_id` | Same conversion; verify the referenced user exists. |
| `createdAt` | `created_at` | BSON Date -> `timestamptz(3)`; preserve milliseconds. |
| `updatedAt` | `updated_at` | Same. If missing, flag; do not substitute migration time silently. |
| `__v` | `version` | Preserve; default 0 only if absent and documented. |
| camelCase fields | snake_case columns | Explicit mapping; keep API serializers camelCase. |
| BSON int32/int64/double | chosen numeric type | Record the source BSON type; flag mixed types and non-finite values. |
| `date` | `snapshot_date` | Preserve UTC midnight for parity; or convert to IST date if that decision is made. |
| missing field | NULL or default | Per-column decision; never blanket-default without a report. |

Use batched inserts/upserts with a deterministic order and a per-batch transaction. For a
one-shot production load, a full reload into an empty schema is simpler than idempotent
upserts. For rehearsal, make the loader repeatable by truncating/reloading the target
schema, not by silently overwriting production.

### 7.3 Data-quality gates

Before constraints are finalized, run profiling queries against a copy of the real data:

1. **Counts and sizes:** documents per collection, total size, average document size.
2. **ID shape:** any `_id` or `user` that is not a 24-char hex string.
3. **Orphans:** user-scoped rows whose `user` has no `users` row.
4. **Duplicates:** every intended unique key, including duplicates that could exist because
   the FastAPI app did not create indexes.
5. **Missing required fields:** `users.username/email/password`, holdings/positions
   `name/qty/avgPrice` or `entry`, orders `symbol/name/side/type/product/qty/price`,
   watchlists `name`, marketquotes `name`, snapshots `value/date`.
6. **Enum drift:** `exchange`, `side`, `type`, `product`, `status`, `kind`, transaction
   `kind/status`; list every distinct value.
7. **Numeric anomalies:** negative qty/price, `filled > qty`, fractional qty/filled,
   non-finite doubles (`NaN`, `Infinity`), values outside safe JS integer range.
8. **Date anomalies:** snapshot dates not at UTC midnight; timestamps in the future;
   missing timestamps; timezone offsets.
9. **Financial anomalies:** negative `funds.available`; settlement amounts that do not
   match their symbol/kind; duplicate transactions that look like retries.
10. **Snapshot gaps:** users with no snapshots, multiple snapshots per day, `invested`
    missing on old rows.
11. **Cache gaps:** symbols in holdings/positions/watchlists/orders with no market quote;
    quotes with no users.
12. **Order consistency:** EXECUTED orders with `filled != qty`; OPEN orders with
    `filled != 0`; bracket exits with empty `groupId`; exits whose side/product do not
    match an entry.

Handling policy:

- **Auto-fix only with a documented rule** (e.g. missing `__v` -> 0, missing `exchange` ->
  `NSE` if the model default is the intended value, missing `sector` -> `''`).
- **Quarantine/report** anything ambiguous (missing `name`, fractional qty, negative
  balance, duplicate business key, non-finite number).
- **Never silently drop a row** to make a constraint pass.
- Keep a row-level migration report with source `_id`, rule applied, and reviewer.

### 7.4 Identifier preservation

Recommended: preserve the ObjectId hex as `char(24)` for `users.id` and every `user_id`,
and for all document `id` columns.

Why:

- Existing JWT cookies contain `{id: "<24-hex>"}`. They keep working without reissuing
  tokens.
- The frontend uses `_id` as an opaque key and displays the last 8 characters of order IDs
  (`src/features/dashboard/pages/Orders.jsx:154`).
- Existing URLs such as `/api/positions/:id/square-off`, `/api/orders/:id`, and
  `/api/watchlist/:id` keep the same shape.
- `groupId` values that are ObjectId hex continue to match order IDs; UUID4 groups remain
  text.

Tradeoff: `char(24)` uses more space than a 12-byte `bytea` or 16-byte `uuid`. At this
application's scale, simplicity and compatibility outweigh the storage difference. If a
future UUID migration is desired, add a separate mapping/dual-ID project; do not combine it
with the MongoDB cutover.

New IDs should be generated as 12 random bytes -> 24 lowercase hex characters. They do not
need to be BSON ObjectIds, but they must satisfy the same format check.

### 7.5 Verification

#### Data verification

- Row counts per collection and per user.
- Sum/min/max for every numeric field, compared with tolerance appropriate to the chosen
  numeric strategy.
- Distinct counts for every enum-like field.
- Null counts per column.
- Foreign-key coverage: every `user_id` resolves.
- Unique-key duplicate count: zero.
- Per-user aggregates: holdings value, invested, funds available, open order count,
  transaction count, snapshot count.
- Checksums of stable ordered projections (e.g. `_id` + key business fields) before/after.

#### API verification

Reuse the existing parity approach:

- Start both applications against equivalent datasets (Mongo for the current app,
  PostgreSQL for the new one).
- Compare status, content type, JSON body, and ordering for every endpoint in
  `docs/migration/API_CONTRACTS.md`.
- Include the assistant read-only snapshots, not just CRUD routes.
- Compare error envelopes for 400/401/404/409/500 and malformed IDs.
- Compare serialization edge cases: ObjectId hex, ISO dates with three decimals, `__v`,
  missing vs null, whole floats, `-0.0`, `1e21`.

#### Write-flow verification

Run each flow on a disposable copy and compare final table state:

1. Signup, duplicate signup, login, `/me`.
2. First `GET /api/funds` creates a row.
3. Deposit, withdrawal, insufficient withdrawal.
4. Limit BUY (CNC and MIS), cancel/refund, duplicate cancel.
5. MARKET BUY with a mocked quote, including bracket creation.
6. CNC SELL fill, insufficient holdings, rejected fill.
7. MIS LONG/SHORT fill, partial exit, full exit, square-off.
8. Bracket OCO: one leg fills, sibling cancels; concurrent double-fill attempt.
9. Watchlist add, duplicate, delete, missing name, bad symbol.
10. Market sync success/failure, sector backfill, quote preservation.
11. Price sync success/failure/missing quote, market-hours gate, single-flight lock.
12. Snapshot success, rerun/idempotency, missing-field failure.
13. Assistant tools, including the corrected watchlist collection.

#### Concurrency verification

Use two or more real PostgreSQL connections (not a single test transaction):

- Two debits against the same funds row.
- Two cancels against the same order.
- Two fills against the same order.
- Two fills merging the same holding/position.
- Two square-offs of the same position.
- Two exit legs filling concurrently (OCO).
- Two signups with the same email/username.
- Two watchlist adds with the same key.
- Two snapshot runs for the same user/day.
- Two market-sync workers/processes.

Assert invariants, not just row counts: no negative cash through guarded paths, no double
credit, no orphan position, no duplicate business key, exactly one OCO fill.

#### Performance verification

- `EXPLAIN (ANALYZE, BUFFERS)` for orders, transactions, holdings, positions, watchlist,
  portfolio history, and market overview.
- Confirm the orders page uses `(user_id, created_at DESC)`.
- Confirm price-sync OPEN scan uses a partial/status index if the table grows.
- Check connection pool sizing and statement timeouts; current PyMongo has one shared
  client and synchronous endpoints in worker threads.

### 7.6 Backup and rollback

Before the maintenance window:

- Take a full MongoDB backup (`mongodump`) and verify a restore into a scratch database.
- Take a PostgreSQL base backup or snapshot; enable WAL archiving/PITR if available.
- Record the exact schema migration version and application commit.
- Record row counts/checksums from both sides.

Cutover:

1. Announce maintenance; stop application writes.
2. Stop/disable all schedulers (market sync, price sync, snapshot) so no background write
   can race the export.
3. Take the final MongoDB backup.
4. Run the export/load; record counts/checksums.
5. Run verification gates; do not switch on failure.
6. Switch the application database configuration to PostgreSQL.
7. Start one application instance; run smoke tests.
8. Enable exactly one scheduler owner; verify no duplicate jobs.
9. Monitor errors, latency, locks, and invariant checks.

Rollback:

- **Before any PostgreSQL writes:** switch back to MongoDB; it is still authoritative.
- **After PostgreSQL writes begin:** a simple config switch is not enough; writes exist only
  in PostgreSQL. Either restore MongoDB from the pre-cutover backup and accept data loss,
  or implement a reverse migration. Document which is acceptable before cutover.
- Keep MongoDB read-only for a defined retention period, then decommission.

### 7.7 Single-source-of-truth rules

- Before cutover: MongoDB is the only writer; PostgreSQL is a copy.
- At cutover: PostgreSQL is the only writer; MongoDB is read-only.
- Never run the Mongo jobs and PostgreSQL jobs simultaneously.
- Never let Express and FastAPI both write during the transition.
- Use the existing scheduler ownership switches (`api/scheduler.py:3-21`) as the model for
  a single owner; add a database-backend switch only when implementing.
- The parity harness and tests may read both databases, but production writes must have one
  owner.

---

## 8. Ranked open questions and risks

Ranking is by impact on correctness/security first, then likelihood, then effort.

| Rank | Risk / open question | Evidence | Impact | Decision needed before schema |
|---|---|---|---|---|
| 1 | **Identifier strategy:** preserve 24-hex ObjectId or switch to UUID? | `api/auth.py:31-43`, `api/serialization.py:14-25`, `src/features/dashboard/pages/Orders.jsx:154` | Breaks cookies, `_id`, URLs, order labels, `groupId` matching. | Choose `char(24)` preservation (recommended) or a dual-ID migration. |
| 2 | **Numeric strategy:** `double precision` parity or `numeric` correctness? | `api/js_compat.py`, `api/serialization.py`, assistant `_js_round`, parity numeric fixtures | Changes arithmetic, JSON rendering, assistant formatting, and test expectations. | Choose Strategy A (cutover parity) or Strategy B (Decimal end-to-end). |
| 3 | **Transaction boundaries and known defects:** make flows atomic or preserve partial writes? | Order placement, square-off, deposit, exits, fills (§5.2) | Cash loss, duplicate credit, orphan positions, EXECUTED orders without fills. | Define per-flow atomicity and whether to fix/refund. |
| 4 | **Data quality and constraints:** what happens to nulls, duplicates, enums, negatives, non-finite numbers? | `watchlists.name` nullable, partial test docs, no FastAPI indexes | Migration may fail or require silent coercion; unique constraints may reject real data. | Run the profile in §7.3 and approve cleanup rules. |
| 5 | **Index ownership:** who creates unique/non-unique indexes? | No `create_index` in `api/`; legacy indexes in models | Fresh database can duplicate funds/holdings/positions/watchlists/snapshots/quotes and run slowly. | Alembic/schema migrations must own all indexes; verify on an empty DB. |
| 6 | **OCO race:** can both bracket legs fill? | `api/jobs/price_sync.py:238-243`, `api/order_engine.py:281-299` | Double settlement, wrong cash, inconsistent positions. | Choose position/group locking or serializable transaction; add concurrency tests. |
| 7 | **Partial MIS exit:** should the whole position still be deleted? | `api/order_engine.py:245-278`, test `:557-572` | Remaining position silently lost. | Preserve parity or fix to decrement/delete at zero; update tests. |
| 8 | **Phantom `watchlist` read:** fix now or during repository work? | `api/assistant.py:227` vs `watchlists` | Nova's watchlist tool is always empty; a naive table map creates a phantom table. | Fix to `watchlists` (recommended) and add an assistant test. |
| 9 | **Ordering:** what explicit `ORDER BY` replaces natural order? | holdings/positions/watchlists/market/search | Visible row order can change; tests may become flaky. | Define stable order per endpoint and document the change. |
| 10 | **Snapshot date type:** `timestamptz(3)` or `date`? | `api/jobs/portfolio_snapshot.py:26-30`, `api/routes/portfolio.py:44-62` | Changes rolling-window vs calendar-day semantics and label boundaries. | Choose parity (`timestamptz`) or deliberate calendar-day refactor. |
| 11 | **Schema drift:** enforce `exchange`, `name`, enums, `qty>0`, `filled<=qty`? | PyMongo bypasses Mongoose; watchlist name nullable | Constraints may reject existing data; permissive schema preserves bugs. | Profile and decide per constraint; avoid blanket `CHECK` without cleanup. |
| 12 | **Order price history:** `price` is overwritten on SL-M/MARKET fills. | `api/jobs/price_sync.py:206-217` | Cannot reconstruct original limit/trigger price after fill; reporting/audit gap. | Preserve current shape or add `requested_price`/`filled_price` fields (new feature). |
| 13 | **Error mapping:** preserve 500 for malformed IDs/unique races? | `api/main.py:155-159`, `api/routes/auth.py:85-88` | Text IDs and `IntegrityError` will produce different statuses/bodies. | Decide preserve vs improve; add contract tests. |
| 14 | **Scheduler ownership and locks:** process-local only. | `api/jobs/price_sync.py:73-82`, `api/jobs/market_sync.py:168-181` | Multiple processes can duplicate fills/snapshots/quotes. | Keep one-owner deployment or add PostgreSQL advisory locks. |
| 15 | **Non-finite numbers:** `NaN`/`Infinity` in BSON. | No explicit serializer handling; quote validation rejects them only on write | Invalid JSON/500s or data corruption. | Profile and reject/quarantine before load. |
| 16 | **Case sensitivity and deletion policy:** `citext`? cascade? | Mongo unique indexes case-sensitive; no user-delete route | Changing case rules breaks login/duplicates; cascade can delete financial history. | Preserve case-sensitive text and `RESTRICT` initially. |
| 17 | **Derived values with Decimal:** assistant/portfolio math assumes floats. | `api/portfolio_math.py`, `api/assistant.py` `_js_round` | TypeError or changed rounding under `numeric`. | Decide numeric strategy first; update math/serializers if Decimal. |
| 18 | **`__v` semantics:** preserve 0 or implement optimistic locking? | `api/documents.py:19-27`; no increments | API shape changes; optimistic locking is a new feature. | Preserve as a version column without auto-increment in Phase 1. |
| 19 | **Transaction/order linkage:** add `order_id`? | `server/models/TransactionModel.js` has only symbol/method | Cannot reliably reconcile ledger to orders; backfill is impossible for old rows. | Defer; add nullable columns only in a later reporting project. |
| 20 | **Seed/backfill scripts:** rewrite or retire? | `server/scripts/seedDemo.js`, `backfillSnapshots.js` | Scripts write Mongo directly and bypass the new app. | Decide whether to port, retire, or keep as one-time migration tools. |

### 8.1 Questions that must be answered before schema design

At minimum:

1. Do we preserve 24-hex IDs and existing JWT cookies? (Recommended: yes.)
2. Do we cut over on `double precision` for parity, or do Decimal/`numeric` now?
3. Which financial flows become atomic, and which known defects are fixed?
4. What does the real data profile say about nulls, duplicates, enums, negatives, and
   fractional quantities?
5. What explicit ordering replaces natural order?
6. Is `snapshot_date` a timestamp at UTC midnight or an IST `date`?
7. Do we fix the phantom `watchlist` read and partial-exit delete before or during the
   repository migration?
8. Do we enforce `exchange = 'NSE'` and other enums, or preserve FastAPI's permissiveness?

---

## 9. Implementation phases and testing

> These phases begin only after explicit approval. This audit does not start any of them.

### 9.1 Phase plan

| Phase | Scope | Exit criteria |
|---|---|---|
| **2. Decisions and data profile** | Answer §8.1; run §7.3 profiling on a real copy; produce a data-quality report and schema decision record. | Signed-off decisions on IDs, numerics, transactions, nullability, ordering, and bug fixes. No schema code yet. |
| **3. Schema and migrations** | SQLAlchemy models and Alembic migrations for the agreed tables, keys, checks, indexes; no route rewrites. | Migrations apply cleanly to an empty DB and to a profiled dump; `alembic downgrade`/reapply works in staging; schema review passes. |
| **4. Read repository and read routes** | Replace PyMongo reads for auth/me, holdings, positions, orders, funds, transactions, watchlist, portfolio history, market overview, search, assistant snapshots. | Read-only API parity for all endpoints, including ordering and serialization. No writes switched yet. |
| **5. Write paths and transactions** | Signup/login, order placement/cancel, fills, square-off, deposits/withdrawals, exits/brackets, watchlist writes. | Write-flow parity plus concurrency/invariant tests; no negative-cash/double-credit/orphan-position failures. |
| **6. Jobs and assistant** | Market sync, price sync, daily snapshot, sector backfill; fix the phantom watchlist read. | Idempotency, market-hours gate, single-flight, failure preservation, one-owner scheduler tests. |
| **7. Migration rehearsal and cutover** | Export/load tooling, checksums, backup/restore drill, maintenance-window runbook. | Dry runs pass; counts/checksums/API parity pass; rollback is documented and tested. |
| **8. Decommission MongoDB** | Remove PyMongo, Mongo models/scripts, and Mongo configuration after retention. | No production reads/writes to Mongo; backups retained; docs updated. |

### 9.2 Test strategy

**Use real PostgreSQL for database tests.** `mongomock` cannot prove unique-index
enforcement, transactions, row locking, or concurrency. The existing optional real-Mongo
suite is a good pattern; the PostgreSQL suite should be mandatory in CI or a dedicated
integration job.

Test layers:

1. **Schema/constraint tests:** unique keys, FKs, checks, defaults, timestamp precision,
   ID format.
2. **Repository tests:** each query returns the same rows/order/shape as the current
   PyMongo query.
3. **Route contract tests:** status, body, content type, error envelope, user isolation,
   malformed IDs.
4. **Write-flow tests:** every trace in §3.3, including failure injection between writes.
5. **Concurrency tests:** two connections, row locks, deadlocks/serialization failures,
   OCO, double cancel, double fill, double square-off, duplicate signup/watchlist.
6. **Data-migration tests:** fixture MongoDB -> PostgreSQL -> checksums; idempotent
   rehearsal; invalid-row quarantine.
7. **Job tests:** market-hours gate, single-flight, provider failure, missing quote,
   sector backfill, snapshot idempotency, scheduler ownership.
8. **Serialization/numeric tests:** ObjectId hex, ISO dates, `__v`, whole floats,
   `0.1+0.2`, `1e21`, `-0.0`, NaN/Infinity rejection, Decimal rendering (if Strategy B).
9. **Performance tests:** explain plans and latency for orders/transactions/holdings/
   positions/watchlist/portfolio/market.
10. **Backup/restore tests:** restore Mongo dump and PostgreSQL backup into scratch
    environments; verify checksums and smoke tests.

### 9.3 Existing coverage and gaps

Current state: the focused Phase 0 suites pass, and the full suite last reported
**278 passed, 8 skipped**. The skips are the optional real-Mongo tests because
`TEST_MONGO_URL` is unset. This is useful but not sufficient for PostgreSQL:

| Area | Existing coverage | Gap for PostgreSQL |
|---|---|---|
| Auth | Signup/login/me, duplicate prechecks, hashes, cookie claims | No unique-race test; no real unique constraint proof. |
| Holdings/positions | Reads, merges, square-off, response shape | No partial-exit regression; no row-lock/concurrency test. |
| Orders | Validation, cash block, cancel/refund, exits, bracket group | No concurrent claim/OCO test; no transaction failure injection. |
| Funds | Derived values, first-read creation, deposit/withdraw | No mid-write failure test; no negative-balance profile. |
| Watchlist | Add/delete/duplicate, response shape | No missing-name test; assistant watchlist bug untested. |
| Portfolio | History windows, null-invested gap, today overwrite | No date-type/range-boundary decision. |
| Market data | Batch quotes, bulk upsert ops, sector backfill | `mongomock` cannot run `bulk_write`; real test optional. |
| Jobs | Market-hours, single-flight, price preservation, snapshot failure | No multi-process lock test; no PostgreSQL advisory-lock test. |
| Assistant | Read-only snapshots, streaming adapter | No watchlist tool test; Decimal/float assumptions untested. |
| Migration | None | No export/load/checksum/rollback harness yet. |

### 9.4 Definition of done for the migration

- All endpoints in `API_CONTRACTS.md` pass against PostgreSQL with identical status,
  body shape, ordering, and serialization (or approved, documented differences).
- Every intended unique key is enforced by PostgreSQL and tested on an empty database.
- Every user-scoped row has a valid user FK; no orphans.
- Guarded cash paths never produce a negative balance in concurrency tests.
- OCO produces exactly one fill; partial exits either preserve the remainder or are
  explicitly documented as changed.
- Price sync preserves stored prices on provider failure and never fires duplicate fills
  across processes.
- Snapshot upserts are idempotent per user/day.
- Backup/restore and rollback are rehearsed.
- One scheduler owner is verified; Mongo and PostgreSQL jobs never run simultaneously.
- The migration report lists every quarantined/fixed row and has reviewer sign-off.

---

## Appendix A. Evidence index

| Topic | Primary evidence |
|---|---|
| Active DB connection | `api/db.py:17-27` |
| App lifecycle/scheduler switches | `api/main.py:83-118`, `api/scheduler.py:3-21` |
| Mongoose-style document creation | `api/documents.py:19-27` |
| Atomic funds increment | `api/documents.py:30-47` |
| Serialization rules | `api/serialization.py:14-33`, `docs/migration/API_CONTRACTS.md:44-55` |
| JWT/id contract | `api/auth.py:31-43,64-82`, `docs/migration/API_CONTRACTS.md:34-42` |
| Signup/login/me | `api/routes/auth.py:63-147` |
| Holdings read | `api/routes/holdings.py:25-35` |
| Positions read/square-off | `api/routes/positions.py:26-123` |
| Orders list/place/exits/cancel | `api/routes/orders.py:43-321` |
| Funds read/transactions | `api/routes/funds.py:35-122` |
| Watchlist read/add/delete | `api/routes/watchlist.py:28-77` |
| Portfolio history | `api/routes/portfolio.py:31-86` |
| Market overview | `api/routes/market.py:26-48` |
| Instrument search | `api/routes/instruments.py:31-57` |
| Assistant tools | `api/assistant.py:125-339` |
| Fill/merge/settle/OCO | `api/order_engine.py:15-299` |
| Price sync | `api/jobs/price_sync.py:66-251` |
| Market sync | `api/jobs/market_sync.py:56-181` |
| Daily snapshot | `api/jobs/portfolio_snapshot.py:26-74` |
| Portfolio math | `api/portfolio_math.py:9-58` |
| Mongoose models/indexes | `server/models/*.js` |
| Legacy seed/backfill | `server/scripts/seedDemo.js:248-377`, `server/scripts/backfillSnapshots.js:63-87` |
| Optional real-Mongo tests | `api/tests/test_mongo_integration.py:1-32,277-315` |
| `mongomock` fixture | `api/tests/conftest.py:33-42` |
| Numeric parity harness | `tools/express-parity/harness_env.py:53-84`, `tools/express-parity/fastapi_numbers.py:41-47` |
| Frontend ID usage | `src/features/dashboard/pages/Orders.jsx:154`, `src/services/api.js:24,30-31,35-36` |

---

*End of Phase 1 audit. Awaiting review before PostgreSQL schema design or Alembic work.*
