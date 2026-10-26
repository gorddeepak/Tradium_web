# PostgreSQL Schema Design: Tradium Phase 2

> **Status:** Phase 2 design proposal for review. This document does **not** create
> tables, write SQLAlchemy models, add Alembic migrations, change application code, add
> dependencies, or modify tests/configuration.
>
> **Implemented in Phase 3B1/3B2:** the schema is now in `api/postgres/models.py` and
> `api/migrations/versions/0001_initial_schema.py`; authentication and the market cache use
> it. See `MIGRATION_STATUS.md` §3P and §3Q. The design rationale below is unchanged.
>
> **Scope:** the active FastAPI backend in `api/`, using the legacy Express/Mongoose code
> in `server/` as schema evidence. The external HTTP contract is held constant except
> where a change is explicitly labelled **Intentional change** below.
>
> **Evidence boundary:** source inspection of the current working tree plus a read-only
> profile of the two local MongoDB databases (`tradium_fastapi_dev` and the legacy
> `zerodha` database). No production data, production credentials, or live production
> indexes were inspected. Production-dependent statements are marked **PROFILE REQUIRED**.
>
> **Companion documents:** `docs/migration/POSTGRES_AUDIT.md` (Phase 1 findings),
> `docs/migration/API_CONTRACTS.md` (wire shapes/error envelopes), and
> `docs/migration/ARCHITECTURE_DECISIONS.md`.
>
> **Legend**
>
> - **[Verified]** observed in source or the local read-only profile.
> - **[Recommendation]** the design chosen by this document.
> - **[Assumption]** plausible but not proven; must be confirmed before cutover.
> - **[Intentional change]** the new system will behave differently from the current app.
>   These require explicit review and tests.
> - **[Deferred]** explicitly out of Phase 2.

## Contents

1. [Executive recommendation](#1-executive-recommendation)
2. [Resolved Phase 1 audit decisions](#2-resolved-phase-1-audit-decisions)
3. [Relational model](#3-relational-model)
4. [Table definitions, constraints, and indexes](#4-table-definitions-constraints-and-indexes)
5. [Financial precision and rounding](#5-financial-precision-and-rounding)
6. [Transaction and concurrency design](#6-transaction-and-concurrency-design)
7. [Quote and instrument storage](#7-quote-and-instrument-storage)
8. [Data profiling and migration prerequisites](#8-data-profiling-and-migration-prerequisites)
9. [Migration mapping and cutover](#9-migration-mapping-and-cutover)
10. [Risks, trade-offs, and test acceptance criteria](#10-risks-trade-offs-and-test-acceptance-criteria)

---

## 1. Executive recommendation

**Adopt a relational PostgreSQL schema that preserves the existing 24-character ObjectId
hex identifiers, stores all money and prices as `NUMERIC` with Python `Decimal`
end-to-end, makes every money/order/position flow one database transaction, and separates
slow-changing instrument metadata from volatile quotes.**

The design is intentionally conservative about identity and API shape, and intentionally
strict about financial correctness:

- Existing `_id` and `user` values remain 24-character lowercase hex strings, so JWTs,
  URLs, `groupId` matching, and the frontend's order labels keep working. New IDs are
  12 random bytes rendered as 24 lowercase hex characters.
- The schema uses `NUMERIC` and `Decimal`, not `DOUBLE PRECISION` and not a mixture. This
  is the only way to make cash, weighted averages, P&L, and refunds exact. It requires a
  deliberate serialization policy so JSON still emits numbers, not strings.
- Order placement, fills, cancels, refunds, exits/OCO, square-off, deposits, withdrawals,
  and snapshot upserts become atomic. This fixes several current partial-write paths
  rather than reproducing them.
- `marketquotes` becomes `instruments` (identity, name, kind, sector, market-universe
  membership) plus `latest_quotes` (volatile prices). Holdings, positions, and watchlists
  stop storing their own `ltp`/`dayChangePct` copies and read the canonical quote.
- The known defects are fixed explicitly: Nova reads `watchlists`, not the phantom
  `watchlist`; a partial MIS exit keeps the remainder; an oversized exit is rejected
  instead of silently capped; order placement rolls back its debit if any later step fails;
  OCO settlement and sibling cancellation share one transaction.
- Phase 2 supports **NSE equity listings only**. The instrument identity stays
  symbol-only, and the provider ticker is derived by `ticker_for()`; non-NSE writes are
  rejected, not coerced. The `^BSESN` quote is a BSE **index**, not a BSE equity listing.
- Quote receipt time and provider market time are separate. `latest_quotes.updated_at`
  remains the persisted timestamp used by the API; an optional `source_time` records the
  provider's market time and drives the stale/future-quote guard before a fill.
- Every list response gets deterministic `ORDER BY` rules, because PostgreSQL has no
  natural insertion order.
- The cutover is offline and one-way: MongoDB remains authoritative until a write freeze,
  PostgreSQL becomes the sole writer, and MongoDB is retained read-only for audit and
  rollback. No dual writes.

### 1.1 Decision summary

| Area | Decision | Consequence |
|---|---|---|
| Identifiers | `varchar(24)` + `CHECK (id ~ '^[0-9a-f]{24}$')`; preserve all existing IDs | Existing cookies, URLs, and order labels survive; no mapping table |
| New IDs | `secrets.token_hex(12)` (24 lowercase hex) | Same external shape as ObjectId; no timestamp semantics |
| Money/prices | Cash/ledger `NUMERIC(20,2)`; prices/quotes `NUMERIC(20,4)`; Python `Decimal` | Paise-accurate cash, 4-dp market prices; Decimal-aware JSON required |
| Average cost/entry | `NUMERIC(20,6)` | Weighted averages lose less precision |
| Percentages | `NUMERIC(12,6)` | Provider percentages fit comfortably |
| Quantities | `integer` (`qty`, `filled`) | No fractional shares; migration blocks fractional values |
| Volume | `bigint` | Whole-share/index volume; max local value 33,521,732 |
| Market cap | `NUMERIC(24,2)` | Provider values are floats even when integral; avoids silent loss |
| Timestamps | `timestamptz(3)` | Millisecond precision, matching BSON Date |
| Snapshot day | `date`, interpreted as an IST calendar day | Cleaner history; deliberate range-semantics change |
| Quotes | `instruments` + `latest_quotes`; no cached `ltp` in book tables | One quote source; extra joins; reconciliation required |
| Exchange scope | NSE equity listings only; symbol-only instrument identity; `ticker_for()` derives the provider ticker | Non-NSE writes rejected; BSE index quotes are indices, not listings; future BSE needs `(symbol, exchange)` |
| Quote time | `updated_at` = received/persisted; optional `source_time` = provider market time | API `updatedAt`/`asOf` unchanged; stale/future quotes cannot fill orders |
| Rejected orders | Lock and validate before the final transition; rejection preserves `filled`/`price` | A rejected order can never persist as fully filled |
| Transactions | One transaction per financial flow + per-user advisory lock | No lost cash, orphan position, or duplicate refund |
| OCO | Per-user lock + order/position row locks + final conditional transition + sibling cancel in one transaction | Exactly one leg can settle |
| Partial MIS exit | Keep the remaining position; reject an oversized exit | Fixes the current unconditional delete |
| Nova watchlist | Read `watchlists`; regression test | Tool stops returning an empty list |
| Ordering | Explicit, stable `ORDER BY` on every list | PostgreSQL output becomes deterministic |
| Indexes | Alembic owns every index/constraint | Fresh databases cannot duplicate business keys |
| Migration | Offline, one-way, no dual writes | Simple source of truth; rollback after writes is a restore |

### 1.2 What stays the same

- The HTTP routes, request bodies, response field names, status codes, and error envelopes
  in `docs/migration/API_CONTRACTS.md`, except for the intentional changes enumerated in
  §2.16 and labelled **[Intentional change]** inline.
- The `_id`, `user`, `createdAt`, `updatedAt`, and `__v` fields in API responses.
- The business meaning of `OPEN`, `EXECUTED`, `CANCELLED`, and `REJECTED`.
- `funds.available` as free cash; `usedMargin`, `blockedInOrders`, `misMargin`, and
  `realizedPnl` remain derived, not stored.
- The assistant's read-only tool boundary (the user comes from the JWT, never from a tool
  argument).
- The scheduler ownership model: one process owns the jobs.

### 1.3 What changes intentionally

The changes are enumerated with IDs in §2.16 and labelled inline where they are not
F-numbered. The highest-impact ones are:

1. Financial writes become atomic, so a failure no longer leaves a debit without an order
   or a position without proceeds, and a rejected order never keeps a fully filled
   `filled` value.
2. A partial MIS exit keeps the remaining position instead of deleting it.
3. OCO sibling cancellation is in the same transaction as the fill.
4. Nova's watchlist tool reads the real collection.
5. List responses have deterministic ordering.
6. `portfolio_snapshots.snapshot_date` becomes a `date`, and history ranges use IST
   calendar days.
7. Decimal arithmetic and half-up quantization replace binary-float arithmetic; cash is
   stored at 2 dp while prices stay at 4 dp.
8. Holdings/positions/watchlists read the canonical quote rather than their own cached
   copy; quote migration chooses the freshest trustworthy timestamp, not the marketquote
   automatically.
9. Malformed IDs and unique-constraint races return explicit 4xx responses instead of a
   generic 500.
10. Non-NSE exchange writes are rejected at the route and database boundary; legacy
    non-NSE rows are quarantined rather than silently relabelled.
11. A quote whose provider market time is missing, stale, or future-dated cannot fill an
    order; the order stays OPEN and the tick is logged.

### 1.4 What this document does not do

It does not write SQLAlchemy models, Alembic revisions, repository code, route rewrites,
migration scripts, or tests. It does not change `api/`, `server/`, `src/`, dependencies, or
configuration. It stops here for review.

---

## 2. Resolved Phase 1 audit decisions

The Phase 1 audit left eight questions in §8.1 and twenty ranked risks in §8. All are
answered below. The table is the decision record; the subsections give the reasoning and
the implementation constraints.

### 2.1 Decision record

| # | Phase 1 question / risk | Decision | Change class |
|---|---|---|---|
| D1 | Preserve 24-hex IDs or switch to UUID? | Preserve. `varchar(24)` primary/foreign keys; new IDs are 12 random bytes as 24 lowercase hex. | No API change |
| D2 | `double precision` parity or `numeric` correctness? | `NUMERIC` + Python `Decimal` end-to-end (audit Strategy B). | Intentional change |
| D3 | Which flows become atomic? | All money/order/position flows, plus snapshot upsert and market bulk upsert. | Intentional change |
| D4 | Nulls, duplicates, enums, negatives, non-finite numbers? | Safe constraints now; production profile gates the rest. Quarantine, never auto-repair silently. | Gate |
| D5 | Who creates indexes? | Alembic owns all tables, constraints, and indexes. The app never calls `create_all`. | No API change |
| D6 | Can both OCO legs fill? | No. Per-user advisory lock, row locks on the exit and backing position, validation/settlement, then a final conditional `OPEN -> EXECUTED` transition and sibling cancel in one transaction. | Intentional fix |
| D7 | Delete the position after a partial MIS exit? | No. Decrement; keep until zero. Reject an exit larger than the position. | Intentional fix |
| D8 | Phantom `watchlist` read? | Read `watchlists`; add a regression test. | Intentional fix |
| D9 | What replaces natural order? | Explicit `ORDER BY` per endpoint, with `id` tie-breakers. | Intentional change |
| D10 | Snapshot date type? | `date` representing the IST calendar day; convert legacy timestamps to IST date. | Intentional change |
| D11 | Enforce `exchange = 'NSE'` and other enums? | Enforce side/type/product/status/kind/transaction status **and** `exchange = 'NSE'`. Legacy non-NSE rows are quarantined, never relabelled. | Intentional change |
| D12 | Order price history? | Preserve current `price` overwrite semantics. `requested_price`/`filled_price` are future work. | Deferred |
| D13 | Error mapping for malformed IDs/unique races? | Validate IDs at the boundary; 404/204 as appropriate; map unique violations to documented 4xx. | Intentional change |
| D14 | Scheduler ownership? | One owner. Transaction-scoped advisory locks protect a batch transaction, not a job-wide run. Row locks and conditional order transitions plus idempotent upserts are the actual double-execution guards. | Hardening |
| D15 | Non-finite numbers? | Reject at the boundary; quarantine during migration; never store `NaN`/`Infinity`. | Gate |
| D16 | `citext` and cascade? | Keep case-sensitive text unique indexes; FKs use `ON DELETE RESTRICT`. | No API change |
| D17 | Derived values with Decimal? | Keep them derived; update portfolio math, assistant rounding, and serializers. | Intentional change |
| D18 | `__v` semantics? | Preserve as `version integer NOT NULL DEFAULT 0`, serialized as `__v`; no optimistic locking. | No API change |
| D19 | Transaction-to-order link? | No `order_id` in Phase 2; document the reporting gap. | Deferred |
| D20 | Seed/backfill scripts? | Retire Mongo seed/backfill for production; port only what is needed for local/test fixtures. | Deferred |
| D21 | NSE and BSE listings? | Phase 2 is NSE-only for equity listings; instrument identity remains symbol-only. `^BSESN` is a BSE **index** quote, not a BSE equity listing. Reject non-NSE exchange writes; quarantine legacy non-NSE rows. | Intentional change |
| D22 | Watchlist uniqueness? | Enforce `(user_id, symbol)` in PostgreSQL, matching the route's existing duplicate check; `exchange` is stored but not part of the key. | No API change |
| D23 | Scheduler advisory locks? | Keep one scheduler owner. Transaction-scoped advisory locks protect only their transaction; they are not a job-wide lease. Row locks, conditional order transitions, and idempotent upserts are the double-execution guards. | Hardening |
| D24 | Cash precision? | Cash and ledger amounts are `NUMERIC(20,2)` (paise). Prices/quotes are `NUMERIC(20,4)`; averages are `NUMERIC(20,6)`. | Intentional change |
| D25 | Quote timestamps? | `updated_at` is when this service persisted the quote; optional `source_time` is the provider's market time. API `updatedAt`/`asOf` keep using `updated_at`. | No API change |
| D26 | Rejected order state? | Lock the order, validate the fill, then make the final conditional transition. Rejection preserves the stored `filled` (normally 0) and `price`; only success sets `EXECUTED`, `filled=qty`, and the fill price. | Intentional fix |
| D27 | Where do quarantined rows go? | A separate `migration.quarantine` table, keyed by source collection + source id. Rows with an `OPEN` or `EXCLUDED` rule are not loaded into application tables; every unresolved row blocks cutover. | Gate |

### 2.2 Identifiers (D1)

**Decision:** every existing document `_id` and user reference becomes `varchar(24)` holding
the lowercase ObjectId hex. Every table's primary key is that value. Foreign keys use the
same type and a `CHECK` regex. New rows use `secrets.token_hex(12)`.

**Why:**

- JWTs contain the same 24-hex `id` claim (`api/auth.py:31-43`). Preserving it means
  existing cookies keep working without a token refresh.
- URLs such as `/api/positions/:id/square-off`, `/api/orders/:id`, and
  `/api/watchlist/:id` keep their shape.
- The frontend displays the last eight characters of an order `_id`
  (`src/features/dashboard/pages/Orders.jsx:154`).
- Bracket `groupId` values that are ObjectId hex continue to match order IDs; UUID4
  groups remain text.

**Rules:**

- `id`, `user_id`, and `instrument_id` are `varchar(24)`.
- `CHECK (id ~ '^[0-9a-f]{24}$')` on every ID column, not just the primary key.
- The migration rejects uppercase or otherwise malformed IDs rather than normalizing
  them silently. A production-only normalization would change an externally visible
  identifier, which requires its own decision.
- No UUID column, no `bytea`, no separate mapping table. The storage cost of `varchar(24)`
  versus `bytea` is irrelevant at this application's scale.
- `varchar(24)` is preferred over PostgreSQL `char(24)`: `char(n)` blank-pads and compares
  with space-insensitive semantics, while the explicit length plus regex check is
  unambiguous. A 24-character value occupies the same space in either type.

### 2.3 Numerics (D2)

**Decision:** `NUMERIC` columns and Python `Decimal` everywhere money, prices, averages,
percentages, or P&L are read, written, or calculated. No `double precision` money columns.
No mixed mode where a `NUMERIC` column is read into a float and written back.

**Why:** the current system uses JavaScript numbers. `0.1 + 0.2`, weighted averages, and
repeated P&L additions can drift; a brokerage ledger should not. `NUMERIC` is exact and
PostgreSQL's `sum`/`avg` preserve exactness. The cost is a deliberate change in arithmetic
and serialization, covered in §5.

**Rejected:** audit Strategy A (`double precision` for parity). It is easier for a
mechanical cutover, but it preserves a class of financial rounding defects and makes the
schema's intent ambiguous. The team should pay the Decimal cost once, before cutover, not
after.

### 2.4 Transactions (D3)

**Decision:** each flow in §6.2 is one transaction. The current multi-document sequences
are not preserved. A failure rolls the whole flow back; no compensation/saga layer is
introduced.

**Why:** the current code has no compensation logic. Preserving partial writes would
preserve lost cash, orphan positions, and orders marked `EXECUTED` without their fill.
Making the flow atomic is the simplest correct behaviour at this scale.

### 2.5 Constraints and data quality (D4, D11, D15, D16)

**Decision:** enforce what the local profile and source semantics prove; defer what only
production can prove. The safe set is in §8.12. The deferred set is:

- `funds.available >= 0`, because `inc_funds` (`api/documents.py:30-47`) and some SL-M
  adjustment paths can write a negative value. Add it after every caller is guarded.
- `groupId` format, because the local profile has no non-empty groups and the format is
  mixed 24-hex/UUID4. Keep `varchar(36)` with no format check.
- `watchlists.name <> ''`, because the route can write `null`; the migration/route will
  fall back to `symbol` first, then the check can be added.
- Transaction amount sign, because `SETTLEMENT` can be positive or negative.
- Any `price > 0` rule; use `>= 0` in the database and `> 0` in the placement validator.

**Exchange is not deferred.** `exchange = 'NSE'` is a Phase A check on `holdings`,
`positions`, `orders`, and `watchlists`. Phase 2 supports NSE equity listings only:
`ticker_for()` in `api/market_data.py:93-95` appends `.NS` to every non-index symbol, and
the instrument routes ignore the request's `exchange` and return `"NSE"`
(`api/routes/instruments.py`). The order and watchlist routes currently accept arbitrary
strings (`api/routes/orders.py:167`, `api/routes/watchlist.py:60`); Phase 2 adds a
route-level rejection for anything other than exactly `"NSE"`. The migration quarantines
legacy non-NSE rows rather than relabelling them. `^BSESN` is a BSE **index** quote and
remains a `kind='index'` instrument; it is not a BSE equity listing. Supporting BSE
equities later requires an `(symbol, exchange)` identity, a `.BO` provider mapping, and a
separate migration — not a flag flip.

**Case sensitivity:** ordinary `text` unique indexes. MongoDB unique indexes are
case-sensitive; `citext` would change login and duplicate semantics. The local `zerodha`
database has one case-insensitive username collision, which is direct evidence that
`citext` would fail migration.

**Cascades:** `ON DELETE RESTRICT` for every user-scoped FK. There is no user-delete route,
and cascading financial history would be dangerous. `latest_quotes` uses
`ON DELETE CASCADE` from `instruments` because a quote cannot exist without its
instrument; that is cache data, not financial history.

### 2.6 Index ownership (D5)

**Decision:** Alembic migrations create every table, unique constraint, check, and index.
The application never creates schema objects at startup.

**Evidence:** the FastAPI-created local database `tradium_fastapi_dev` has only `_id_`
indexes; the legacy `zerodha` database has the Mongoose indexes. The FastAPI code has no
`create_index` call. A fresh PostgreSQL database must not rely on legacy Mongo indexes.

### 2.7 OCO coordination (D6)

**Decision:** a bracket/exit group is coordinated by:

1. a transaction-scoped per-user advisory lock;
2. a `SELECT ... FOR UPDATE` on the exit order, then on the backing position (or holding);
3. validation and settlement while both rows are locked;
4. a final conditional `UPDATE orders ... WHERE id = ? AND status = 'OPEN' RETURNING *`,
   setting `filled=qty` and the fill price only on success;
5. sibling cancellation in the same transaction.

**Why:** the current code claims an exit by writing `EXECUTED`/`filled=qty`, then settles
it, and only then cancels siblings (`api/jobs/price_sync.py:209-243`,
`api/order_engine.py:281-299`). A later rejection can leave a rejected order that still
looks fully filled. Two workers or two ticks can also both act before either cancels. A
per-user lock, a row lock, and a final status guard make the OCO rule true by construction.

**Scope:** the group lookup uses the partial index on `(group_id) WHERE is_exit AND
status = 'OPEN'`. A group has zero, one, or two open exits (a bracket may set only a stop,
only a target, or both); no unique constraint on `group_id`.

### 2.8 Partial MIS exit (D7)

**Decision:** `settle_mis_exit` must:

- reject an exit whose `qty` exceeds the position's `qty` (status `REJECTED`, no cash
  movement, `filled`/`price` unchanged, siblings cancelled);
- decrement by the exit quantity when it is less than or equal to the position;
- keep the position when the remainder is greater than zero;
- delete the position only when the remainder is zero;
- credit `entry * qty + pnl` and insert the settlement transaction in the same
  transaction.

**Why:** the current code computes `qty = min(order.qty, position.qty)`, decrements, and
then deletes unconditionally (`api/order_engine.py:245-278`). A 40-share exit against a
100-share position silently loses 60 shares. The current test documents the behaviour
(`api/tests/test_price_sync.py:557-572`); it must be replaced with the corrected
expectation.

**Accounting:** the settlement amount is the realized P&L for the filled quantity, not the
whole position. The remaining position keeps its original `entry` and reduced `qty`.
After a partial exit, the sibling is cancelled; the remainder is unprotected until the
user sets new exits. That is safer than leaving an exit sized for the old quantity.

### 2.9 Nova watchlist (D8)

**Decision:** change `api/assistant.py:227` from `db["watchlist"]` to
`db["watchlists"]`, join the canonical quote, order by `created_at ASC, id ASC`, and add a
regression test that seeds a watchlist row and asserts `watchlist_snapshot` returns it.

**Why:** there is no writer for the singular collection; Nova's tool always returns an
empty list. A direct table-per-collection migration would create a phantom table. The test
must fail on the old code and pass on the new code.

### 2.10 Deterministic ordering (D9)

**Decision:** every list endpoint uses an explicit order. The full rules are in §4.13.
Summary:

- holdings, positions, watchlists: `created_at ASC, id ASC`;
- orders, transactions: `created_at DESC, id DESC`;
- portfolio history: `snapshot_date ASC`;
- market indices: unknown first, then `^NSEI`, `^NSEBANK`, `^BSESN`;
- market stocks: `symbol ASC`;
- search: exact symbol, then symbol prefix, then name prefix, then substring, then
  `symbol ASC`, limit 10;
- assistant tools: same as their corresponding pages.

**Why:** MongoDB `find({})` has no guaranteed order. PostgreSQL has no natural order.
The current visible order is accidental; the new order is a documented API decision.

### 2.11 Snapshot date (D10)

**Decision:** `portfolio_snapshots.snapshot_date` is a PostgreSQL `date` representing the
IST calendar day. The migration converts a BSON Date with
`(ts AT TIME ZONE 'Asia/Kolkata')::date`. The history route uses IST calendar-day ranges.

**Why:** the current job stores the IST day at UTC midnight
(`api/jobs/portfolio_snapshot.py:26-30`), but the local data contains two conventions:
740 rows at `18:30Z` (legacy IST local midnight) and 16 at `00:00Z`. A `date` removes the
ambiguity and makes the unique key truthful. The range boundary changes from a rolling
`now - days` timestamp window to a calendar-day window: today plus the previous `N` IST
days, where `N` is the existing `RANGE_DAYS` lookback (so `1D` still returns yesterday and
today). This is an intentional boundary change; it preserves the number of lookback days
rather than dropping one.

### 2.12 Error mapping (D13)

**Decision:** validate 24-hex IDs at the route boundary. Malformed IDs produce:

- `GET`/mutation of a missing order/position: 404 with the existing message;
- `GET /api/auth/me` with a malformed id: 404 `"User not found"`;
- watchlist delete: 204 (current behaviour is "always 204" for a missing row);
- no route returns a generic 500 merely because an ID is not hexadecimal.

Unique-constraint races map to the route's existing duplicate status: signup 400 with
`"User already exists"`, watchlist add 409 with `"Already in watchlist"`, funds first-read
`ON CONFLICT DO NOTHING`.

**Why:** the current `ObjectId(...)` cast raises `InvalidId`, which the generic handler
turns into 500 (`api/main.py:155-159`). Text IDs naturally match no rows. Returning
404/204 is clearer and consistent with "not found". This is an intentional change.

### 2.13 Scheduler ownership (D14)

**Decision:** exactly one scheduler owner. The deployment enables `MARKET_SYNC_ENABLED` on
one instance and `TRADING_JOBS_ENABLED` on one instance (`api/scheduler.py:47-58`). This is
the primary guard.

Transaction-scoped PostgreSQL advisory locks are **not** a job-wide lease. A
`pg_advisory_xact_lock` is released at the end of the transaction that acquired it, so a
second process can start the same job immediately after that transaction commits. It can
serialize one batch or one order fill; it cannot make the whole job run exclusive.

**Actual double-execution safeguards:**

- **Price-sync fills:** each order is locked with `SELECT ... FOR UPDATE`, validated, and
  transitioned with a conditional `WHERE status = 'OPEN'` update in one transaction. A
  second worker waits, then sees a non-`OPEN` order and skips it. The financial effect is
  tied to the order transition, not to "the job ran".
- **Quote/market sync:** upserts are keyed by unique `instruments.symbol` and
  `latest_quotes.instrument_id`. A duplicate job writes the same values; it cannot create a
  second quote or double a financial value.
- **Sector backfill:** `FOR UPDATE SKIP LOCKED` splits rows between workers instead of
  duplicating work.
- **Snapshot:** `UNIQUE (user_id, snapshot_date)` plus `ON CONFLICT DO UPDATE` makes a
  repeated run idempotent for that day.
- **Funds/order side effects:** never performed by a bare job insert; they occur only
  inside a conditional order/position transition (§6.4, §6.7, §6.9).

**Why:** the current single-flight guards are process-local `threading.Lock`s
(`api/jobs/price_sync.py:38-40`, `api/jobs/market_sync.py:44-47`). Two processes can both
run a tick; the database transitions, not the lock, must make that safe. A true job-wide
lease (`job_locks` table or session-level lock on a dedicated connection) is deferred
until a real requirement exists — for example, avoiding duplicate provider calls. Do not
describe the transaction-scoped lock as providing that guarantee.

### 2.14 Derived values and `__v` (D17, D18)

**Decision:** keep `usedMargin`, `blockedInOrders`, `misMargin`, `realizedPnl`, portfolio
summary, and all P&L derived. Do not add stored columns. Keep `version` as the wire `__v`
and do not auto-increment it or use it for optimistic locking in Phase 2.

**Why:** the audit's invariants depend on these being computed from one source of truth.
Changing `__v` semantics would be a new feature and a new API behaviour.

### 2.15 Deferred items (D12, D19, D20)

The following are explicitly out of Phase 2:

- `order_fills` / partial-fill history;
- `order_groups` normalization;
- `requested_price` / `filled_price` audit columns;
- `transactions.order_id` / `position_id`;
- `quote_history` / time-series quotes;
- double-entry cash ledger;
- session storage (auth is stateless JWT);
- a `watchlist` singular table;
- Redis or another quote cache;
- porting the legacy seed/backfill scripts to production.

These are future projects, not migration details.

### 2.16 Intentional correctness fixes

| ID | Fix | Current behaviour | New behaviour | Test |
|---|---|---|---|---|
| F1 | Atomic order placement | The debit is a separate write that commits before the order insert and MARKET fill; a later failure leaves cash debited with no order or no fill (`api/routes/orders.py:127-184`). The debit predicate (`side == 'BUY' or product == 'MIS'`) and the CNC-holdings predicate (`side == 'SELL' and product != 'MIS'`) are **mutually exclusive**, so a CNC sell never debits cash. | Debit, order insert, validation, and MARKET fill share one transaction; any failure rolls the debit back entirely | A fault injected after the debit asserts funds unchanged; the insufficient-holdings test alone does not exercise the debit |
| F2 | Atomic OCO | Fill and sibling cancel are separate writes; both legs can settle | One transaction; exactly one leg fills | Two-connection OCO race test |
| F3 | Partial MIS exit | Position deleted even after a partial fill (`api/order_engine.py:245-278`) | Remainder kept; oversized exit rejected | 40-of-100 exit and 120-of-100 exit |
| F4 | Nova watchlist | Reads phantom `db["watchlist"]` (`api/assistant.py:227`) | Reads `watchlists` | Tool returns seeded row |
| F5 | Deterministic list order | Natural MongoDB order | Explicit `ORDER BY` | Fixtures with tied timestamps |
| F6 | Malformed IDs | 500 from `ObjectId` cast | 404/204 as documented | Invalid 24-hex/malformed ID contract tests |
| F7 | `updated_at` on every mutation | Some merge paths leave it stale | Every write sets it | Timestamp-change assertions |
| F8 | Snapshot date semantics | Rolling timestamp window over two stored conventions | IST `date` + calendar-day window | 18:30Z and 00:00Z fixtures map to the same IST day |
| F9 | Quote single source | Book tables cache `ltp`; market cache is separate | Canonical `latest_quotes` join | Cross-table quote consistency tests |
| F10 | Watchlist name | Route can store `null` | Fallback to `symbol`; `NOT NULL` | Missing-name add test |
| F11 | Decimal rounding | Binary float arithmetic | Exact Decimal + half-up at defined points | Numeric parity and exact-sum tests |
| F12 | Error envelope for unique races | Generic 500 | Route-specific 4xx | Duplicate signup/watchlist race tests |
| F13 | Exchange validation | Routes accept an arbitrary `exchange` string; the database would store it | Only `"NSE"` is accepted; non-NSE rows are quarantined during migration | Non-NSE order/watchlist request returns 400; DB check rejects a direct insert |

---

## 3. Relational model

### 3.1 Design principles

1. **One row per entity.** The current documents are flat scalars; no arrays or embedded
   documents need JSONB. Each collection maps to a table, except `marketquotes`, which
   splits into identity and quote halves.
2. **Preserve external identity.** IDs are the existing ObjectId hex, not new UUIDs.
3. **Use real foreign keys only where the reference is guaranteed.** Every user-scoped
   table has `user_id -> users.id`. Symbol references are soft because a holding, order,
   or watchlist row can exist without a quote, and a quote can exist without a user.
4. **Do not store derived values.** `usedMargin`, `blockedInOrders`, `misMargin`,
   `realizedPnl`, portfolio summaries, and P&L are computed at read time.
5. **Make money writes atomic.** The schema is only half the design; §6 defines the
   transaction boundaries.
6. **Profile before tightening.** Constraints that depend on production data are
   introduced in a documented rollout, not guessed from local fixtures.

### 3.2 Relationship diagram

```mermaid
erDiagram
    users ||--o| funds : "has one optional cash row"
    users ||--o{ holdings : "owns"
    users ||--o{ positions : "owns"
    users ||--o{ orders : "places"
    users ||--o{ transactions : "ledger"
    users ||--o{ watchlists : "tracks"
    users ||--o{ portfolio_snapshots : "daily history"

    instruments ||--o| latest_quotes : "has zero or one quote"
    instruments ||..o{ holdings : "symbol (soft)"
    instruments ||..o{ positions : "symbol (soft)"
    instruments ||..o{ watchlists : "symbol (soft)"
    instruments ||..o{ orders : "symbol (soft)"

    orders ||..o{ orders : "group_id (soft, OCO)"
    orders ||..o{ transactions : "symbol (soft, no link)"
```

Text view:

```text
users 1 ─── 0..1 funds
users 1 ─── N    holdings
users 1 ─── N    positions
users 1 ─── N    orders
users 1 ─── N    transactions
users 1 ─── N    watchlists
users 1 ─── N    portfolio_snapshots

instruments 1 ─── 0..1 latest_quotes
instruments 1 ──soft── N holdings / positions / watchlists / orders   (by symbol)
orders      N ──soft── N orders                                       (by group_id)
transactions N ──soft── N orders                                      (by symbol only)
```

### 3.3 Relationship rules

| Relationship | Cardinality | Enforcement | Why |
|---|---|---|---|
| `users -> funds` | 1:0..1 | `funds.user_id UNIQUE`, FK `RESTRICT` | Funds row is created lazily on first read; 3 of 6 local legacy users have none. |
| `users -> holdings` | 1:N | FK `RESTRICT` | One row per `(user, symbol, exchange)`. |
| `users -> positions` | 1:N | FK `RESTRICT` | One row per `(user, symbol, exchange, side, product)`. |
| `users -> orders` | 1:N | FK `RESTRICT` | Order history must survive user edits. |
| `users -> transactions` | 1:N | FK `RESTRICT` | Ledger history must survive. |
| `users -> watchlists` | 1:N | FK `RESTRICT` | One row per `(user, symbol)`; `exchange` is stored but not part of the key. |
| `users -> portfolio_snapshots` | 1:N | FK `RESTRICT` | One row per `(user, IST day)`. |
| `instruments -> latest_quotes` | 1:0..1 | PK/FK `CASCADE` | A quote cannot exist without its instrument; an instrument may temporarily have no quote (missing cache row), so reads use a left join. |
| `instruments -> book tables` | 1:N soft | No FK; `symbol` join | A book symbol can lack a quote, and a quote can lack a user. |
| `orders -> orders` via `group_id` | 0..2 open exits per group | No FK; partial index | `group_id` is mixed 24-hex/UUID4 and is not an entity in Phase 2. |
| `transactions -> orders` | soft only | None | The current ledger has no order/position link; backfilling is unreliable. |

### 3.4 Table inventory

| Table | Source collection | Purpose | Write owner |
|---|---|---|---|
| `users` | `users` | Identity and bcrypt credentials | Auth routes |
| `funds` | `funds` | One free-cash balance per user | Funds/orders/fills/exits/square-off |
| `holdings` | `holdings` | Delivery (CNC) current state | Fills (CNC buy/sell) |
| `positions` | `positions` | Intraday (MIS) current state | Fills, square-off |
| `orders` | `orders` | Order lifecycle, exits, brackets | Orders, price sync, square-off |
| `transactions` | `transactions` | Cash/ledger history | Funds, fills, exits, square-off |
| `watchlists` | `watchlists` | Tracked symbols | Watchlist route, assistant (read) |
| `instruments` | `marketquotes` identity fields | Symbol, name, kind, sector, market-universe flag | Market sync, price sync |
| `latest_quotes` | `marketquotes` price fields | One current quote per instrument | Market sync, price sync |
| `portfolio_snapshots` | `portfoliosnapshots` | Daily portfolio history | Snapshot job |

### 3.5 Why these tables are not proposed

- **`order_fills`:** the current order model has `filled` but no fill rows. Adding fill
  history is a product feature, not a migration.
- **`order_groups`:** `group_id` is a string shared by at most two exits and sometimes an
  entry. A separate group table would need a mixed-format key and a backfill rule; the
  partial index is enough for Phase 2.
- **`quote_history`:** the current cache stores only the latest quote. Historical quotes
  are a market-data feature.
- **`cash_ledger` / double-entry:** `transactions` is a ledger but not double-entry and
  has no order link. Replacing it is a separate accounting project.
- **`watchlist` (singular):** a bug, not an entity. See F4.
- **`sessions`:** auth is stateless JWT.
- **`migration_*` tables in the app schema:** the migration report belongs in a separate
  schema or a CSV, not in the application's public schema.

---

## 4. Table definitions, constraints, and indexes

### 4.1 Conventions

**Common identity/timestamp columns.** Every table except `latest_quotes` has:

| Column | Type | Null | Default | Constraint |
|---|---|---|---|---|
| `id` | `varchar(24)` | NOT NULL | — | PK; `CHECK (id ~ '^[0-9a-f]{24}$')` |
| `created_at` | `timestamptz(3)` | NOT NULL | — | Application supplies; truncate to milliseconds |
| `updated_at` | `timestamptz(3)` | NOT NULL | — | Application sets on every mutation |
| `version` | `integer` | NOT NULL | `0` | Serialized as `__v`; no auto-increment |

`latest_quotes` is the exception: its primary key is `instrument_id`, it has
`updated_at` but no `created_at`/`version`; the instrument owns those API fields.

**Identifier type.** IDs use `varchar(24)`, not `char(24)`. PostgreSQL `char(n)` blank-pads
values and ignores trailing spaces in comparisons, which is the wrong semantics for an
external identifier. The regex check enforces the exact 24-lowercase-hex shape; `varchar`
stores the same 24 characters without padding.

**Naming.** Tables and columns are snake_case. API serializers map to camelCase and to the
legacy `_id`/`user`/`__v` names. Constraint names use `pk_`, `fk_`, `uq_`, `ck_`, and
`ix_` prefixes so Alembic can manage them predictably.

**Foreign keys.** `user_id varchar(24) NOT NULL REFERENCES users(id) ON DELETE RESTRICT`.
`latest_quotes.instrument_id varchar(24) PRIMARY KEY REFERENCES instruments(id) ON DELETE
CASCADE`. Every `id`, `user_id`, and `instrument_id` column also carries
`CHECK (col ~ '^[0-9a-f]{24}$')`; the per-table rows below do not repeat that check.

**Defaults.** Simple constants have database defaults (`0`, `''`, `false`, `'OPEN'`,
`'PROCESSING'`). Timestamps and IDs are application-supplied so the write path is explicit
and testable.

**Truncation.** The application truncates datetimes to milliseconds before writing. A
`timestamptz(3)` column also rounds to milliseconds, so a mistake cannot produce
microsecond-only API output.

### 4.2 `users`

**Purpose:** identity and credentials. **Source:** `users`. **Write owner:** auth routes.

| Column | Type | Null | Default | Constraints / evidence |
|---|---|---|---|---|
| `username` | `text` | NOT NULL | — | `UNIQUE`; `CHECK (username <> '')`; case-sensitive. Mongoose required/unique (`server/models/User.js`). |
| `email` | `text` | NOT NULL | — | `UNIQUE`; `CHECK (email <> '')`; case-sensitive. Login is exact match (`api/routes/auth.py:105`). |
| `password_hash` | `text` | NOT NULL | — | Bcrypt hash from `users.password`; never serialized. Local hashes all start `$2b$`. |

**Keys/indexes:**

- PK `(id)`.
- `uq_users_username (username)`.
- `uq_users_email (email)`.

**Query patterns:**

- Signup duplicate checks by `email`, then `username`; the unique indexes close the race.
- Login by exact `email`.
- `GET /me` by `id`; select `id, username, email, created_at, updated_at, version`.
- Snapshot job enumerates `id` only.

**Notes:** no email-format check (the current app has none; adding one would reject
legacy data). No role/profile columns are evidenced. `created_at`/`updated_at`/`version`
are part of the API response.

### 4.3 `funds`

**Purpose:** one free-cash row per user. **Source:** `funds`. **Write owner:** funds
routes, order placement, fills, exits, square-off.

| Column | Type | Null | Default | Constraints / evidence |
|---|---|---|---|---|
| `user_id` | `varchar(24)` | NOT NULL | — | `UNIQUE`; FK `users(id) ON DELETE RESTRICT`. One row per user (`server/models/FundsModel.js:4`). |
| `available` | `numeric(20,2)` | NOT NULL | `0` | Cash at paise precision; no non-negative check yet; see §2.5. Local sample values 0..2,476,200. |

**Keys/indexes:**

- PK `(id)`.
- `uq_funds_user (user_id)`.

**Query patterns:**

- `GET /api/funds`: `INSERT ... ON CONFLICT (user_id) DO NOTHING`, then select; this
  replaces the current read-then-insert race.
- Deposit: `UPDATE ... SET available = available + $1` or `INSERT ... ON CONFLICT`.
- Withdrawal/order debit: conditional `UPDATE ... WHERE available >= $1 RETURNING`.
- Refund: `UPDATE ... SET available = available + $1`.
- Assistant: select `available`.

**Notes:** the API exposes `_id` and `user`; map `id`/`user_id` back. A missing funds row is
valid until first read. Legacy `collateral`/`usedMargin` fields are ignored and reported
by the migration. Cash is stored at 2 dp (`numeric(20,2)`), not at price precision. Every
debit, refund, fill adjustment, and settlement is quantized to 2 dp **after** multiplying
quantity by the 4-dp price; a `numeric(20,2)` value never carries a sub-paise remainder.

### 4.4 `holdings`

**Purpose:** delivery (CNC) current state. **Source:** `holdings`. **Write owner:** fills
and CNC sell; reads by holdings route, snapshot job, assistant.

| Column | Type | Null | Default | Constraints / evidence |
|---|---|---|---|---|
| `user_id` | `varchar(24)` | NOT NULL | — | FK `users(id) ON DELETE RESTRICT`. |
| `symbol` | `text` | NOT NULL | — | `CHECK (symbol <> '')`; local symbols match `^[\^A-Z0-9&-]{1,20}$`. |
| `name` | `text` | NOT NULL | — | Mongoose required; local all present. Empty-name tightening is deferred. |
| `exchange` | `text` | NOT NULL | `'NSE'` | `CHECK (exchange = 'NSE')`; Phase 2 is NSE-only (§2.5). |
| `qty` | `integer` | NOT NULL | — | `CHECK (qty > 0)`; local qty 20..150, all integral. Zero rows are deleted. |
| `avg_price` | `numeric(20,6)` | NOT NULL | — | `CHECK (avg_price >= 0)`; weighted average, 6 dp. |

No `ltp`, `day_change_pct`, or `sector` columns. Those are read from `latest_quotes` and
`instruments` (§7).

**Keys/indexes:**

- PK `(id)`.
- `uq_holdings_user_symbol_exchange (user_id, symbol, exchange)`.
- `ix_holdings_user_created (user_id, created_at, id)` for deterministic list order.

**Query patterns:**

- List: `WHERE user_id = $1 ORDER BY created_at ASC, id ASC`, left-join instrument/quote.
- Merge on buy: `INSERT ... ON CONFLICT (user_id, symbol, exchange) DO UPDATE` with the
  weighted-average formula in §5.6.
- Sell: `UPDATE ... SET qty = qty - $1 WHERE user_id = $2 AND symbol = $3 AND exchange =
  $4 AND qty >= $1 RETURNING *`; delete when zero.
- CNC sell precondition: select by `(user_id, symbol, exchange)` with `FOR UPDATE`.
- Snapshot valuation: join quote, `sum(qty * ltp)`.
- Assistant: list for user.

**Notes:** the unique key is the merge key and the race guard. The list order is a
deliberate change from natural order. A missing quote serializes as `ltp: 0`,
`dayChangePct: 0`, `sector: ""` to preserve the shape.

### 4.5 `positions`

**Purpose:** intraday (MIS) current state. **Source:** `positions`. **Write owner:**
fills, MIS exit settlement, square-off.

| Column | Type | Null | Default | Constraints / evidence |
|---|---|---|---|---|
| `user_id` | `varchar(24)` | NOT NULL | — | FK `users(id) ON DELETE RESTRICT`. |
| `symbol` | `text` | NOT NULL | — | `CHECK (symbol <> '')`. |
| `name` | `text` | NOT NULL | — | Current model required; local all present. |
| `exchange` | `text` | NOT NULL | `'NSE'` | `CHECK (exchange = 'NSE')`; Phase 2 is NSE-only. |
| `side` | `text` | NOT NULL | — | `CHECK (side IN ('LONG','SHORT'))`; local both values present. |
| `product` | `text` | NOT NULL | — | `CHECK (product IN ('CNC','MIS'))`; current writes create MIS only. |
| `qty` | `integer` | NOT NULL | — | `CHECK (qty > 0)`; local 20..300. |
| `entry` | `numeric(20,6)` | NOT NULL | — | `CHECK (entry >= 0)`; weighted average entry. |

No `ltp` column; the position read joins `latest_quotes`.

**Keys/indexes:**

- PK `(id)`.
- `uq_positions_user_symbol_exchange_side_product (user_id, symbol, exchange, side, product)`.
- `ix_positions_user_product (user_id, product)` for MIS reads/snapshot.
- `ix_positions_user_created (user_id, created_at, id)` for list order.

**Query patterns:**

- List: `WHERE user_id = $1 ORDER BY created_at ASC, id ASC`, join quote.
- MIS fill merge: `ON CONFLICT` on the five-column key, weighted entry formula.
- Exit lookup: `WHERE user_id/symbol/exchange/product='MIS'/side=... FOR UPDATE`.
- Square-off: select by `id` + user, then delete-returning.
- Snapshot: `WHERE user_id = $1 AND product = 'MIS'`, join quote.

**Notes:** long and short rows coexist. A zero quantity is deleted, never stored. The
current model allows CNC positions but current fill code creates MIS only; the check keeps
the model's enum rather than narrowing to MIS.

### 4.6 `orders`

**Purpose:** order lifecycle, exits, and bracket legs. **Source:** `orders`.
**Write owner:** order routes, price sync, square-off; sibling cancellation by the order
engine.

| Column | Type | Null | Default | Constraints / evidence |
|---|---|---|---|---|
| `user_id` | `varchar(24)` | NOT NULL | — | FK `users(id) ON DELETE RESTRICT`. |
| `symbol` | `text` | NOT NULL | — | `CHECK (symbol <> '')`. |
| `name` | `text` | NOT NULL | — | Required by the current model; local all present. |
| `exchange` | `text` | NOT NULL | `'NSE'` | `CHECK (exchange = 'NSE')`; route rejects other values (F13). |
| `side` | `text` | NOT NULL | — | `CHECK (side IN ('BUY','SELL'))`. |
| `type` | `text` | NOT NULL | — | `CHECK (type IN ('MARKET','LIMIT','SL','SL-M'))`. |
| `product` | `text` | NOT NULL | — | `CHECK (product IN ('CNC','MIS'))`. |
| `qty` | `integer` | NOT NULL | — | `CHECK (qty > 0)`; local 10..300. |
| `filled` | `integer` | NOT NULL | `0` | `CHECK (filled >= 0 AND filled <= qty)`. Local has two `OPEN` orders with `filled=120, qty=300`; do not require `OPEN => filled=0`. |
| `price` | `numeric(20,4)` | NOT NULL | — | `CHECK (price >= 0)`; app requires `> 0` for non-MARKET. MARKET stores the execution price; SL-M overwrites it at fill. |
| `trigger_price` | `numeric(20,4)` | NOT NULL | `0` | `CHECK (trigger_price >= 0)`. |
| `sl_trigger` | `numeric(20,4)` | NOT NULL | `0` | `CHECK (sl_trigger >= 0)`. |
| `tp_price` | `numeric(20,4)` | NOT NULL | `0` | `CHECK (tp_price >= 0)`. |
| `group_id` | `varchar(36)` | NOT NULL | `''` | No FK, no format check in Phase 2. Holds 24-hex or UUID4. |
| `is_exit` | `boolean` | NOT NULL | `false` | Current model default. |
| `status` | `text` | NOT NULL | `'OPEN'` | `CHECK (status IN ('OPEN','EXECUTED','CANCELLED','REJECTED'))`. |

**Keys/indexes:**

- PK `(id)`.
- `ix_orders_user_created (user_id, created_at DESC, id DESC)` for the orders page and
  assistant.
- `ix_orders_user_status (user_id, status)` for blocked cash and assistant filters.
- `ix_orders_open (symbol, exchange) WHERE status = 'OPEN'` for the price-sync scan.
- `ix_orders_group_open (group_id) WHERE is_exit AND status = 'OPEN'` for OCO.
- `ix_orders_exit_lookup (user_id, symbol, exchange, product, is_exit, status)` for
  set-exits and square-off cancellation.

No unique constraint on `group_id`: a group has up to two exits, plus historical cancelled
rows.

**Query patterns:**

- List by user, newest first.
- Blocked cash: `WHERE user_id = $1 AND status = 'OPEN'`, then filter non-exit
  BUY/MIS in the query or application.
- Price sync: lock by `id`; the final transition uses `id` + `status = 'OPEN'`.
- OCO: `WHERE group_id = $1 AND is_exit AND status = 'OPEN'`.
- Set exits: old open exits by `(user_id, symbol, exchange, product, is_exit)`.
- Square-off: cancel open MIS exits by `(user_id, symbol, exchange, product)`.
- Assistant: optional status, newest first, limit 10.

**Notes:** `price` is not a complete audit trail; it is overwritten on MARKET/SL-M fills.
Preserve that shape for Phase 2. The index on `group_id` is partial and small.

**Partial `filled` gate.** The local data contains two `OPEN` orders with `filled=120`,
`qty=300`. Phase 2 has no fill history, so it cannot prove whether the filled portion was
settled. The runtime remains all-or-nothing (`filled = qty` only on a successful
`EXECUTED`; `filled` is used only for the cancel/rejection refund and blocked-cash display).
Before
cutover, every `OPEN` order with `0 < filled < qty` must be reviewed and either confirmed
as a display-only legacy value or quarantined. Do not silently settle the full quantity or
refund the full unfilled amount until that review is complete. A `REJECTED` or `CANCELLED`
order with `filled=qty` is quarantined; the new runtime never produces it.

### 4.7 `transactions`

**Purpose:** cash/ledger history. **Source:** `transactions`. **Write owner:** deposit/
withdrawal, CNC sell fill, MIS exit, square-off.

| Column | Type | Null | Default | Constraints / evidence |
|---|---|---|---|---|
| `user_id` | `varchar(24)` | NOT NULL | — | FK `users(id) ON DELETE RESTRICT`. |
| `kind` | `text` | NOT NULL | — | `CHECK (kind IN ('DEPOSIT','WITHDRAWAL','SETTLEMENT','FEE'))`; `FEE` exists in seed data (`server/scripts/seedDemo.js:78-84`). |
| `method` | `text` | NOT NULL | `'Bank transfer'` | Human-readable; no enum. |
| `amount` | `numeric(20,2)` | NOT NULL | — | Signed cash/P&L amount at paise precision; no sign check. Local sample -25,000..2,500,000. |
| `symbol` | `text` | NOT NULL | `''` | Not a FK; settlement rows usually carry it. |
| `status` | `text` | NOT NULL | `'PROCESSING'` | `CHECK (status IN ('COMPLETED','PROCESSING'))`; both occur locally. |

**Keys/indexes:**

- PK `(id)`.
- `ix_transactions_user_created (user_id, created_at DESC, id DESC)`.
- `ix_transactions_user_kind (user_id, kind)` for realized P&L and assistant settlement
  sums.

**Query patterns:**

- List by user, newest first.
- `SUM(amount) WHERE user_id = $1 AND kind = 'SETTLEMENT'` for realized P&L.
- Insert settlement inside the fill/square-off transaction.

**Notes:** no `order_id`/`position_id` in Phase 2. A transaction can be a `FEE` with no
symbol. The `method` label is not a reliable type discriminator. `amount` is a cash/ledger
value and is always 2 dp, including a derived P&L or fee; a price or average used to
compute it stays 4 dp/6 dp until the final cash quantization.

### 4.8 `watchlists`

**Purpose:** tracked symbols. **Source:** `watchlists`. **Write owner:** watchlist route;
assistant reads.

| Column | Type | Null | Default | Constraints / evidence |
|---|---|---|---|---|
| `user_id` | `varchar(24)` | NOT NULL | — | FK `users(id) ON DELETE RESTRICT`. |
| `symbol` | `text` | NOT NULL | — | `CHECK (symbol <> '')`; route validates `[\^A-Z0-9&-]{1,20}`. |
| `name` | `text` | NOT NULL | — | Mongoose required; route currently can write `null`. Migration and route fall back to `symbol` (F10). |
| `exchange` | `text` | NOT NULL | `'NSE'` | `CHECK (exchange = 'NSE')`; Phase 2 is NSE-only. |

No `ltp`/`day_change_pct`; the read joins `latest_quotes`.

**Keys/indexes:**

- PK `(id)`.
- `uq_watchlists_user_symbol (user_id, symbol)`.
- `ix_watchlists_user_created (user_id, created_at, id)`.

**Query patterns:**

- List by user, `ORDER BY created_at ASC, id ASC`, join quote.
- Add: duplicate pre-check remains `(user_id, symbol)` to preserve the current 409
  semantics; the unique key is the race guard.
- Delete: `WHERE id = $1 AND user_id = $2`; always 204.
- Assistant: `watchlists` by user, same order, join quote.

**Notes:** the route's duplicate check and the database key are both `(user_id, symbol)`
(`api/routes/watchlist.py:52-54`). `exchange` is stored but deliberately excluded from the
key: a second row for the same symbol on a different exchange must not exist. That also
means the migration must first check for duplicate `(user, symbol)` pairs across exchanges
and quarantine the later rows; a production dataset that only ever wrote `NSE` passes
without change. The concurrent-add test in §6.12 covers the same-symbol/different-exchange
case.

### 4.9 `instruments`

**Purpose:** slow-changing identity and metadata for a tradable symbol. **Source:**
identity fields of `marketquotes` plus synthetic rows for book-only symbols. **Write
owner:** market sync, price sync, sector backfill.

| Column | Type | Null | Default | Constraints / evidence |
|---|---|---|---|---|
| `symbol` | `text` | NOT NULL | — | `UNIQUE`; `CHECK (symbol <> '')`; local max length 10, all match the symbol pattern. |
| `name` | `text` | NOT NULL | — | Market quote name, or holding/order name for synthetic rows. |
| `kind` | `text` | NOT NULL | `'stock'` | `CHECK (kind IN ('stock','index'))`; local 3 indices, 50 stocks. |
| `sector` | `text` | NOT NULL | `''` | Empty means pending backfill; local all present. |
| `in_market_universe` | `boolean` | NOT NULL | `false` | True only for the 53 symbols the market cache displays. Book-only instruments are false. |

**Keys/indexes:**

- PK `(id)`.
- `uq_instruments_symbol (symbol)`.
- `ix_instruments_sector_pending (kind) WHERE sector = ''` for the backfill scan.

**Query patterns:**

- Market overview/search: filter `in_market_universe = true`.
- Quote join: `instruments.symbol = holdings.symbol` etc.
- Upsert by `symbol` from market sync.
- Sector backfill: `WHERE kind = 'stock' AND sector = '' LIMIT 10 FOR UPDATE SKIP LOCKED`.

**Notes:** the `in_market_universe` flag is new. Without it, creating an instrument for a
non-Nifty holding would make that stock appear on the Markets page and in search, changing
current behaviour. The flag preserves the existing 53-symbol universe.

**Identity scope (D21).** There is intentionally no `exchange` column in Phase 2. An
instrument is identified by `symbol` alone, and the provider ticker is derived by
`ticker_for()` (`api/market_data.py:93-95`): symbols beginning with `^` pass through as
indices, every other symbol gets the `.NS` suffix. The instrument routes ignore the
client's `exchange` and return `"NSE"`. `^BSESN` is a BSE **index** and is stored with
`kind='index'`; it is not evidence of BSE equity support. There is no stored
`provider_ticker` column because the mapping is total for the supported universe; a future
BSE equity would need both an `(symbol, exchange)` identity and an explicit `.BO` mapping.
The `.NS` rule is syntactically total but not semantically validated: a symbol the provider
returns no row for is not treated as a listing. Quarantine it or report it as unquotable;
never invent a ticker or silently relabel its exchange.

### 4.10 `latest_quotes`

**Purpose:** one current quote per instrument. **Source:** price fields of `marketquotes`.
**Write owner:** market sync, price sync.

| Column | Type | Null | Default | Constraints / evidence |
|---|---|---|---|---|
| `instrument_id` | `varchar(24)` | NOT NULL | — | PK; FK `instruments(id) ON DELETE CASCADE`; `CHECK` ID regex. |
| `ltp` | `numeric(20,4)` | NOT NULL | `0` | `CHECK (ltp >= 0)`; local 167.31..74,916.31. |
| `day_change` | `numeric(20,4)` | NOT NULL | `0` | Signed; combined local -876.375..134.60156. |
| `day_change_pct` | `numeric(12,6)` | NOT NULL | `0` | Signed; combined local -4.1860466..2.624672. |
| `prev_close` | `numeric(20,4)` | NOT NULL | `0` | `CHECK (prev_close >= 0)`; local 166.3..74,764.2. |
| `volume` | `bigint` | NOT NULL | `0` | `CHECK (volume >= 0)`; local max 33,521,732; integral. |
| `market_cap` | `numeric(24,2)` | NOT NULL | `0` | `CHECK (market_cap >= 0)`; local max 17,091,513,024,512. |
| `updated_at` | `timestamptz(3)` | NOT NULL | — | Received/persisted time; API `updatedAt` and `asOf`. |
| `source_time` | `timestamptz(3)` | NULL | — | Provider market time (`regularMarketTime`); internal freshness/guard only; `NULL` for migrated legacy rows. |

**Keys/indexes:**

- PK `(instrument_id)`.
- No extra index needed at 53 rows. If the universe grows, add `(updated_at)` or a partial
  index for `asOf`.

**Query patterns:**

- Market overview: join instruments; order indices/stocks as in §4.13.
- Book reads: left join on `instrument_id`.
- Market sync: upsert by instrument.
- Price sync: update `ltp`, `day_change_pct`, `source_time`, `updated_at`.

**Notes:** `createdAt` and `__v` for the API come from `instruments`; `updatedAt` comes
from `latest_quotes.updated_at`. That keeps quote receipt freshness separate from metadata
edits. Sector backfill must not bump `latest_quotes.updated_at` (see §7.7).

**Two timestamps, two meanings.** `updated_at` is when this service persisted the row; it
is what the API has always exposed as `updatedAt`, and what `asOf` uses. `source_time` is
the provider's market timestamp for the quote, converted from epoch seconds to
`timestamptz(3)`; it can be older than `updated_at` by the network/provider delay. The API
does not expose `source_time` in Phase 2. A migrated row has `source_time = NULL` because
the legacy code discarded `regularMarketTime`; do not infer it from `updated_at`. The
execution freshness guard (§6.4) uses `source_time` when present, never the receipt time.

### 4.11 `portfolio_snapshots`

**Purpose:** one daily portfolio point per user. **Source:** `portfoliosnapshots`.
**Write owner:** daily snapshot job.

| Column | Type | Null | Default | Constraints / evidence |
|---|---|---|---|---|
| `user_id` | `varchar(24)` | NOT NULL | — | FK `users(id) ON DELETE RESTRICT`. |
| `snapshot_date` | `date` | NOT NULL | — | IST calendar day; unique with user. |
| `value` | `numeric(20,4)` | NOT NULL | — | Holdings value + open MIS value; no non-negative check (short MIS can be negative). Local 0..851,316.66. |
| `invested` | `numeric(20,4)` | NOT NULL | `0` | Cost basis; older rows may omit it. Local 0..817,379.35. |
| `mis_invested` | `numeric(20,4)` | NOT NULL | `0` | Local max 422,923.89999999997 (float artifact). |
| `mis_value` | `numeric(20,4)` | NOT NULL | `0` | Local max 430,990.4. |

**Keys/indexes:**

- PK `(id)`.
- `uq_portfolio_snapshots_user_date (user_id, snapshot_date)`.

**Query patterns:**

- History: `WHERE user_id = $1 AND snapshot_date >= $2 ORDER BY snapshot_date ASC`.
- Daily upsert: `INSERT ... ON CONFLICT (user_id, snapshot_date) DO UPDATE`.
- Snapshot job reads users, then holdings/positions for each.

**Notes:** the unique key is per user per IST day. The local data has 756 rows, 372
distinct IST days, and zero duplicate `(user, IST day)` pairs. The two timestamp
conventions both convert correctly with the IST date rule.

**History response.** The route maps `invested = 0` (and a missing value) to `null`,
matching the current `if s.invested` check; positive `invested` adds `mis_invested`.
`mis_invested` and `mis_value` missing are `0`. The range is
`snapshot_date >= today - RANGE_DAYS[range]` in IST, so `1D` includes yesterday and today;
this preserves the lookback-day count while removing the rolling timestamp boundary.

### 4.12 Index summary

| Table | Index | Kind | Purpose |
|---|---|---|---|
| `users` | `(username)` | unique | Signup duplicate check |
| `users` | `(email)` | unique | Login/signup |
| `funds` | `(user_id)` | unique | One row per user; funds read |
| `holdings` | `(user_id, symbol, exchange)` | unique | Merge key and list filter |
| `holdings` | `(user_id, created_at, id)` | btree | Deterministic list |
| `positions` | `(user_id, symbol, exchange, side, product)` | unique | Merge key |
| `positions` | `(user_id, product)` | btree | MIS reads/snapshot |
| `positions` | `(user_id, created_at, id)` | btree | Deterministic list |
| `orders` | `(user_id, created_at DESC, id DESC)` | btree | Orders page/assistant |
| `orders` | `(user_id, status)` | btree | Blocked cash/filters |
| `orders` | `(symbol, exchange) WHERE status='OPEN'` | partial | Price-sync scan |
| `orders` | `(group_id) WHERE is_exit AND status='OPEN'` | partial | OCO lookup |
| `orders` | `(user_id, symbol, exchange, product, is_exit, status)` | btree | Exits/square-off |
| `transactions` | `(user_id, created_at DESC, id DESC)` | btree | Ledger page |
| `transactions` | `(user_id, kind)` | btree | Realized P&L/assistant |
| `watchlists` | `(user_id, symbol)` | unique | Add/race guard; exchange is not in the key |
| `watchlists` | `(user_id, created_at, id)` | btree | Deterministic list |
| `instruments` | `(symbol)` | unique | Quote upsert/join/search |
| `instruments` | `(kind) WHERE sector=''` | partial | Sector backfill |
| `latest_quotes` | `(instrument_id)` | PK | Quote lookup |
| `portfolio_snapshots` | `(user_id, snapshot_date)` | unique | History/upsert |

At the observed scale (53 quotes, 10 orders, 756 snapshots) these indexes are not
performance-critical; they are correctness and determinism guards. The orders page index
is the one that matters first if data grows.

### 4.13 Deterministic ordering rules

| Endpoint / tool | `ORDER BY` | Notes |
|---|---|---|
| `GET /api/holdings` | `created_at ASC, id ASC` | Closest to insertion order; stable ties. |
| `GET /api/positions` | `created_at ASC, id ASC` | Same. |
| `GET /api/watchlist` | `created_at ASC, id ASC` | Same. |
| `GET /api/orders` | `created_at DESC, id DESC` | Newest first; id breaks same-ms ties. |
| `GET /api/funds/transactions` | `created_at DESC, id DESC` | Newest first. |
| `GET /api/portfolio/history` | `snapshot_date ASC` | Unique per user/day; today's live point appended. |
| `GET /api/market/overview` indices | `CASE` rank, then `symbol ASC` | Unknown indices first, then `^NSEI`, `^NSEBANK`, `^BSESN`. |
| `GET /api/market/overview` stocks | `symbol ASC` | Replaces natural order. |
| `GET /api/instruments/search` | relevance, then `symbol ASC`, limit 10 | Exact symbol, symbol prefix, name prefix, substring. |
| Assistant `getHoldings` / `getPositions` / `getWatchlist` | Same as the page | Consistency. |
| Assistant `getOrders` | `created_at DESC, id DESC`, limit 10 | Status filter preserved. |

**Search relevance expression:**

```sql
SELECT i.symbol, i.name, i.kind,
       q.ltp AS price, q.day_change_pct AS "changePct"
FROM instruments i
JOIN latest_quotes q ON q.instrument_id = i.id
WHERE i.in_market_universe = true
  AND (i.symbol ILIKE :q_contains OR i.name ILIKE :q_contains)
ORDER BY
  CASE
    WHEN lower(i.symbol) = lower(:q) THEN 0
    WHEN i.symbol ILIKE :q_prefix THEN 1
    WHEN i.name ILIKE :q_prefix THEN 2
    ELSE 3
  END,
  i.symbol ASC
LIMIT 10;
```

`q_contains` is `%escaped_query%` and `q_prefix` is `escaped_query%`; escape `%`, `_`, and
`\` in the user input. The `WHERE` clause is what makes a no-match query return `[]`; the
`CASE` only ranks the matching rows. The current regex search escapes all metacharacters
(`api/routes/instruments.py:42`); preserve that intent.

---

## 5. Financial precision and rounding

### 5.1 `NUMERIC` versus `DOUBLE PRECISION`

| Criterion | `NUMERIC` + `Decimal` | `DOUBLE PRECISION` + `float` |
|---|---|---|
| Exactness | Exact decimal arithmetic; `0.1 + 0.2 = 0.3` | Binary approximation; drift under repeated additions |
| Range | Effectively bounded by declared precision/scale | ~15-17 significant digits |
| Storage | Variable-length, typically 9-13 bytes for these precisions | 8 bytes |
| Arithmetic speed | Slower per operation | Faster |
| Indexes | B-tree indexes work; exact comparisons | B-tree indexes work; approximate comparisons |
| PostgreSQL aggregates | `sum`/`avg` return exact numeric | `sum`/`avg` return approximate double |
| Python driver | psycopg/asyncpg return `Decimal` | Returns `float` |
| JSON | Needs an explicit Decimal encoder | Native JSON float |
| JS parity | Changes arithmetic and formatting | Preserves current JS number behaviour |
| Financial suitability | **Recommended** | Not acceptable for cash/ledger |

**Recommendation:** `NUMERIC` and `Decimal` for every monetary, price, average, percentage,
and P&L value. The current app's JavaScript-number behaviour is a compatibility property,
not a correctness property. The migration should pay the one-time serialization cost.

**Do not mix.** A `NUMERIC` column read into a Python float and written back defeats the
purpose and creates nondeterministic rounding. If a value is `NUMERIC` in PostgreSQL, it is
`Decimal` in the repository, service, math, and serializer layers.

### 5.2 Candidate precision and scale

| Table.column | Type | Rationale |
|---|---|---|
| `funds.available` | `numeric(20,2)` | Free cash at paise precision; every debit/refund is quantized to 2 dp after the quantity × price multiplication. |
| `holdings.qty` | `integer` | Whole shares; local max 150. |
| `holdings.avg_price` | `numeric(20,6)` | Weighted average; 6 dp limits drift across merges. |
| `positions.qty` | `integer` | Whole shares; local max 300. |
| `positions.entry` | `numeric(20,6)` | Weighted entry. |
| `orders.qty` | `integer` | Whole shares; local max 300. |
| `orders.filled` | `integer` | Whole shares; local max 120, never > qty. |
| `orders.price` | `numeric(20,4)` | Limit/execution price; 4 dp covers provider prices. |
| `orders.trigger_price` | `numeric(20,4)` | Stop trigger. |
| `orders.sl_trigger` | `numeric(20,4)` | Bracket stop. |
| `orders.tp_price` | `numeric(20,4)` | Bracket target. |
| `transactions.amount` | `numeric(20,2)` | Signed cash/P&L amount at paise precision. |
| `latest_quotes.ltp` | `numeric(20,4)` | Last traded price. |
| `latest_quotes.day_change` | `numeric(20,4)` | Absolute change; signed. |
| `latest_quotes.day_change_pct` | `numeric(12,6)` | Percentage; signed; 6 dp. |
| `latest_quotes.prev_close` | `numeric(20,4)` | Previous close. |
| `latest_quotes.volume` | `bigint` | Whole-share/index volume; local max 33,521,732. |
| `latest_quotes.market_cap` | `numeric(24,2)` | Provider values are floats even when integral; 2 dp avoids silent loss. |
| `portfolio_snapshots.value` | `numeric(20,4)` | Derived daily valuation, not cash; keeps price-derived precision and is displayed at 2 dp. |
| `portfolio_snapshots.invested` | `numeric(20,4)` | Derived cost basis; not cash. |
| `portfolio_snapshots.mis_invested` | `numeric(20,4)` | Derived MIS cost basis; not cash. |
| `portfolio_snapshots.mis_value` | `numeric(20,4)` | Derived MIS current value; not cash. |
| Derived P&L / totals | Python `Decimal`, no column | Quantize to cash 2 dp only when the value is a cash/ledger amount; portfolio valuations stay at 4 dp. |
| Derived percentages | Python `Decimal`, no column | Quantize to 6 dp for responses. |

**Cash versus price.** The distinction is intentional:

- **Cash/ledger** columns (`funds.available`, `transactions.amount`) are `numeric(20,2)`.
  A cash value cannot carry a sub-paise fraction after a debit, refund, proceeds credit, or
  settlement.
- **Prices/quotes** are `numeric(20,4)`. A provider LTP or limit price is kept at 4 dp;
  rounding it to 2 dp before multiplying by quantity would lose trade value.
- **Averages** are `numeric(20,6)`. The average is a cost basis per share, not a cash
  amount; extra scale reduces repeated-merge drift.
- **Derived valuations** (`portfolio_snapshots.*`) are `numeric(20,4)` because they are
  `quantity × price` sums, not ledger cash. They are serialized at the API's normal
  currency formatting; storing them at 4 dp keeps the arithmetic traceable.

`numeric(20,2)` allows 18 integer digits and 2 decimals, far above the local cash maximum
of ₹2,476,200. `numeric(20,4)` allows 16 integer digits and 4 decimals. `numeric(24,2)`
allows 22 integer digits and 2 decimals, far above the local maximum market cap of
17,091,513,024,512. If a future instrument exceeds these bounds, the insert/update must
fail loudly, not truncate.

### 5.3 Quantity policy

- `qty` and `filled` are integers. The order route already rejects fractional quantities
  (`api/routes/orders.py:88-91`).
- `volume` is a `bigint` count. Provider volume may arrive as a float; convert with
  `Decimal(str(value)).to_integral_value(ROUND_HALF_UP)` only if it is finite and
  non-negative. A fractional volume is not expected; log and quarantine during migration.
- If the business later supports fractional shares, change the quantity columns to
  `numeric(20,6)` in a separate migration. Do not round fractional quantities to integers
  during this migration.

### 5.4 Rounding rules

Use one Decimal context for financial calculations:

```python
from decimal import Decimal, ROUND_HALF_UP, getcontext

getcontext().prec = 28
CASH = Decimal("0.01")          # funds, transactions
PRICE = Decimal("0.0001")       # orders, quotes
AVERAGE = Decimal("0.000001")   # holdings/positions cost basis
PERCENT = Decimal("0.000001")
VALUATION = Decimal("0.0001")   # derived portfolio values, not cash
MARKET_CAP = Decimal("0.01")

def quantize(value, unit=CASH):
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(unit, rounding=ROUND_HALF_UP)
```

Never call `Decimal(float)`; `Decimal(str(value))` preserves the provider's decimal text and
avoids capturing binary noise.

- **Cash:** 2 dp, `ROUND_HALF_UP` (ties away from zero). This is the storage and API
  boundary for `funds.available` and `transactions.amount`.
- **Prices/quotes:** 4 dp, `ROUND_HALF_UP`. A price is stored before it is multiplied by a
  quantity; do not pre-round it to cash precision.
- **Averages:** 6 dp, `ROUND_HALF_UP`, after each weighted-average merge.
- **Derived valuations:** 4 dp, `ROUND_HALF_UP`; they are not ledger cash.
- **Percentages:** 6 dp, `ROUND_HALF_UP`.
- **Market cap:** 2 dp; volume: 0 dp.
- **No intermediate rounding:** compute `(exit - entry) * qty * direction` in full
  precision, then quantize the final cash/P&L value. Do not round per share first.
- **No cumulative rounding:** sum exact Decimal products, then quantize once for the
  response/snapshot.
- **Negative zero:** normalize `Decimal("-0.0000")` to `0` before JSON; a financial value
  should never render as `-0`.
- **NaN/Infinity:** validate with `is_finite()`; reject at request/provider boundaries.

**Repeated weighted-average rounding.** The merge is recursive: the next merge uses the
previously stored 6-dp average, not an unbounded exact cost basis. After each merge the
exact numerator is divided and quantized to 6 dp, so the stored average can differ from the
infinite-precision average by at most `0.0000005` per share. With integer quantities the
total cost error per merge is at most `0.0000005 × new_qty`; it does not compound
multiplicatively, but it can accumulate additively over many merges. This is a deliberate
fixed-precision state, not a bug:

- The API exposes an average, not a cost-basis ledger; 6 dp is already far finer than the
  2-dp price display.
- Quantizing only the average (never each share's contribution) keeps the formula
  deterministic and matches PostgreSQL's `round(numeric, 6)`.
- A test performs at least three merges with repeating-decimal prices and asserts the
  exact 6-dp result against a Decimal reference implementation.

If exact cost-basis accounting is required later, add a `cost_basis numeric(20,2)` column
and derive the average from it; do not silently change the Phase 2 semantics.

**Intentional change:** the current code uses Python floats and `js_number`, and
`format_inr` uses Python's `round` (banker's rounding) for display
(`api/js_compat.py:72-91`). The new system uses half-up quantization for storage and
response values, with cash at 2 dp and prices at 4 dp. A cash value that currently carries
sub-paise float noise will be rounded to the nearest paisa; a price keeps 4 dp. Tests must
pin the new behaviour; the assistant's display formatting remains 2 dp / Indian grouping.

### 5.5 Where rounding happens

| Point | Value | Rule |
|---|---|---|
| Provider quote ingestion | `ltp`, `day_change`, `prev_close` | `Decimal(str(raw))` or raw Decimal, quantize 4 dp; reject non-finite; `ltp` must be > 0 for a usable quote |
| Provider percentage | `day_change_pct` | Quantize 6 dp; invalid → `0` |
| Provider market time | `source_time` | Epoch seconds → UTC `timestamptz(3)`; absent/invalid → `NULL`; never substitute receipt time |
| Request price/trigger | order fields | `Decimal(str(raw))`, validate > 0 where required, quantize 4 dp |
| Order blocked cash | `qty * price` | Quantize to 2 dp cash once, after the multiplication |
| Fill adjustment (SL-M) | blocked − actual | Quantize each total to 2 dp, then subtract; do not quantize the per-share difference first |
| Fill proceeds/P&L | `price * qty`; `(price - avg) * qty` | Quantize each cash value to 2 dp at the settlement boundary |
| Weighted average | holdings/positions merge | Quantize 6 dp after the division |
| Funds balance | `available` | Every increment/decrement quantized 2 dp |
| Snapshot | `value`, `invested`, `mis_*` | Quantize 4 dp (derived valuation) before upsert |
| Portfolio summary | `invested`, `value`, `pnl`, `dayPnl` | Quantize 4 dp for response; format to 2 dp for display |
| Portfolio percentages | `pnlPct`, `dayPnlPct` | Quantize 6 dp for response |
| Assistant formatting | display only | 2 dp percentages; whole-rupee currency per prompt |

### 5.6 Formulas

**Order cost / blocked cash:**

```text
amount = quantize(Decimal(qty) * price, CASH)
```

**SL-M blocked-cash adjustment:**

```text
blocked = quantize(Decimal(qty) * old_price, CASH)
actual = quantize(Decimal(qty) * fill_price, CASH)
adjustment = blocked - actual
```

Quantize the two totals separately. `quantize((old_price - fill_price) * qty, CASH)` can
differ by one paisa from the difference of the cash totals.

**Cancel / partial refund:** use the stored blocked total, not a fresh per-share
multiplication:

```text
blocked = quantize(Decimal(qty) * price, CASH)
filled_cash = quantize(Decimal(filled) * price, CASH)
refund = blocked - filled_cash
```

`quantize((qty - filled) * price, CASH)` can differ by one paisa from `blocked -
filled_cash`. The ledger must return exactly the amount that was blocked and not consumed.

**Weighted average (holdings or positions):**

```text
new_qty = old_qty + fill_qty
new_avg = quantize(
    (Decimal(old_qty) * old_avg + Decimal(fill_qty) * fill_price) / Decimal(new_qty),
    AVERAGE,
)
```

**CNC sell settlement:**

```text
proceeds = quantize(Decimal(qty) * fill_price, CASH)
pnl = quantize((fill_price - avg_price) * Decimal(qty), CASH)
```

The current code credits `qty * price` to funds and records P&L as a separate transaction
(`api/order_engine.py:145-158`). Preserve that split: cash proceeds and realized P&L are
different values, each quantized to 2 dp. Do not derive one from the other after rounding.

**MIS exit:**

```text
direction = 1 if position.side == "LONG" else -1
pnl = quantize((exit_price - entry) * Decimal(qty) * direction, CASH)
release = quantize(Decimal(entry) * Decimal(qty), CASH) + pnl
```

**Square-off:** same formula; the closing order uses the exit price and the full position
quantity.

**Portfolio summary:**

```text
invested = quantize(sum(qty * avg_price), VALUATION)
value = quantize(sum(qty * ltp), VALUATION)
pnl = value - invested
pnl_pct = quantize(pnl / invested * 100, PERCENT) if invested else 0
```

`pnl` is a derived valuation at 4 dp, not a cash ledger amount; format it to 2 dp at the
display boundary.

**Day P&L:** `qty * ltp * pct / (100 + pct)`; compute exact, quantize 4 dp at the end.
The denominator guard for `-100%` remains (`api/portfolio_math.py:9-19`).

### 5.7 Provider prices into Decimal

Provider adapters (`api/market_data.py`) currently return Python floats because `requests`
decodes the JSON with the standard library. The new boundary should parse provider JSON
with `json.loads(..., parse_float=Decimal)` so the provider's decimal text is preserved.
If a value has already become a `float` (for example, a cached response or a third-party
client), convert it with `Decimal(str(value))`; this recovers the shortest round-trip
decimal representation, not the binary expansion. Never use `Decimal(float)` directly.

```python
def provider_decimal(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, Decimal):
        number = value
    else:
        try:
            number = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
    if not number.is_finite():
        return None
    return number
```

- `fetch_quote` returns `{"ltp": Decimal, "dayChangePct": Decimal, "sourceTime": datetime | None}`
  or `None`. `regularMarketTime` is epoch seconds in UTC; convert it with
  `datetime.fromtimestamp(value, tz=timezone.utc)`. A missing/invalid time becomes `None`.
- `fetch_quotes` returns raw rows; the sync job converts each field with
  `provider_decimal` before quantization and captures `source_time` from
  `regularMarketTime`.
- `_quote_value` becomes `0` when `provider_decimal(value)` returns `None`, otherwise
  `quantize(decimal, ...)`; do not call `quantize(None)`.
- A missing, zero, negative, `NaN`, or infinite `ltp` means "no usable quote"; preserve
  the current skip/keep-stored-price behaviour (`api/jobs/price_sync.py:43-63, 110-120`).
- A float artifact such as `422923.89999999997` is a stored-source value, not a provider
  decimal. Quantize it to the target scale (4 dp for a valuation) and report the source
  text in the migration report; do not treat the trailing binary noise as meaningful
  precision.
- The migration has no legacy `source_time`: the current jobs discard
  `regularMarketTime` (`api/jobs/market_sync.py:62-92`, `api/jobs/price_sync.py:43-63`).
  Migrated rows therefore get `source_time = NULL`, not a fabricated value.

### 5.8 Decimal to numeric JSON

FastAPI's default `JSONResponse` uses `json.dumps`, which cannot encode `Decimal`.
Pydantic's default JSON mode often renders `Decimal` as a string. Both are wrong for this
API: the frontend expects JSON numbers.

**Recommendation:** a custom response class using `simplejson` with `use_decimal=True`,
plus a `to_json_value` branch for `Decimal`:

```python
from decimal import Decimal
import simplejson

def json_number(value: Decimal):
    if value == value.to_integral_value():
        return int(value)
    # Fixed-point, no exponent, no trailing zeros.
    text = format(value, "f").rstrip("0").rstrip(".")
    return Decimal(text)
```

- Integral Decimals become Python `int`, so `500.0000` renders as `500`, matching
  JavaScript's `JSON.stringify(500.0) === "500"`.
- Non-integral Decimals keep their exact decimal digits; `simplejson` emits a JSON number,
  not a string.
- Percentages render as `1.23`, not `1.230000`.
- The response class must preserve the existing ISO timestamp format
  (`api/serialization.py:19-25`) and the existing error envelopes.

**Fallback if `simplejson` is not accepted:** convert `Decimal` to `int` when integral,
otherwise `float`. This is simpler but reintroduces binary representation at the JSON
boundary. If chosen, document it and test that values up to the maximum precision still
render as the expected decimal text. The recommended path is exact Decimal JSON.

**Do not** serialize money as strings; the frontend does arithmetic and formatting on
numbers.

### 5.9 Request coercion

- Replace money/qty parsing with a `js_decimal` helper that mirrors the current
  `js_number` coercion (`None -> 0`, bool -> 1/0, numeric strings, trim) but returns
  `Decimal`.
- `is_falsy_number` and `is_whole_number` become Decimal-aware.
- Reject `NaN`/`Infinity` before validation branches.
- `format_inr` accepts `Decimal`; use `quantize`/string formatting, not float `round`.
- Assistant `_js_round` becomes a Decimal `floor(value + 0.5)` equivalent; `_json_text`
  uses the Decimal-aware encoder.
- Keep `js_number` only for non-financial values if needed; do not use it for money.

### 5.10 Numeric tests

- Exact sums: deposit 0.1 + 0.2, assert `available == Decimal("0.3")`.
- Cash boundary: `3 × 10.005` stores `30.02`, while the 4-dp price remains `10.0050`.
- Weighted average: two buys at repeating-decimal prices; assert 6-dp result and no drift
  after a third merge; compare against a Decimal reference.
- SL-M adjustment: blocked and actual totals are each quantized to 2 dp; the adjustment is
  their difference, including a one-paisa case that a per-share difference would miss.
- P&L: long and short, positive and negative, half-up ties.
- JSON: `json.loads(body, parse_float=Decimal)` round-trips the stored Decimal exactly;
  integral values are JSON integers; percentages strip trailing zeros.
- Provider: `NaN`, `Infinity`, `None`, bool, numeric string, zero, negative; raw JSON parsed
  with `parse_float=Decimal`; a float input converted with `Decimal(str(value))`.
- Quote time: valid epoch seconds → UTC `source_time`; missing/invalid → `None`; receipt
  time is never substituted.
- Migration: no `NaN`/`Infinity`; fractional qty quarantined; exact source/target sums.
- Assistant: `_js_round` returns the same integer as `Math.round` for positive/negative
  halves (or a documented Decimal equivalent).

---

## 6. Transaction and concurrency design

### 6.1 Primitives

| Primitive | Use |
|---|---|
| `READ COMMITTED` | Default isolation. Row locks and conditional updates provide the guarantees. |
| `pg_advisory_xact_lock(hashtextextended(user_id, 0))` | Serialize all financial writes for one user; released at commit/rollback. |
| `SELECT ... FOR UPDATE` | Lock the specific order/position/holding row after the user lock; validate while it is locked. |
| `UPDATE ... WHERE status = 'OPEN' RETURNING *` | Final conditional transition/cancel; the affected row is the idempotency token. |
| `INSERT ... ON CONFLICT` | Funds first-read, weighted-average merge, snapshot upsert, quote upsert. |
| `pg_advisory_xact_lock(hashtextextended(job_name, 0))` | Serialize a **single batch transaction** within a job. It is released at commit and is **not** a job-wide lease. |
| `statement_timeout` / `lock_timeout` | Bound waits; map timeouts to a retryable 503 or a generic 500, never a partial write. |
| Retry on `40001`/`40P01` | Jobs retry a bounded number of times; API requests do not retry automatically. |

**Why a per-user advisory lock:** it is a simple, deadlock-resistant mutex that works even
when the funds row does not exist yet. It serializes order placement, fills, cancels,
deposits, withdrawals, exits, and square-offs for the same user. Cross-user operations
touch different rows and proceed concurrently. At this application's scale, the throughput
cost is negligible; correctness is worth more.

**Lock order:** the per-user advisory lock is acquired before any row lock and is the
serialization point, so the exact row order within one user's transaction is not a deadlock
source. Keep each flow's order stable for readability (placement locks the holding or funds
row before inserting/updating the order; a fill locks the order row before the backing
position/holding). Never acquire a second user's lock inside a transaction. Jobs that process
many users acquire and release one user lock at a time.

**PgBouncer/Neon:** use transaction-scoped advisory locks, not session-scoped
`pg_advisory_lock`. Transaction pooling may move a session between transactions.

**Job locks are not leases.** A transaction-scoped job lock serializes the transaction that
takes it, then disappears. Another process can take the same lock immediately afterward.
The job-wide single-flight guarantee comes from the deployment's single owner plus the
per-order/per-row conditional transitions (D14, §6.10). Do not build a correctness
argument on "the scheduler holds the lock for the whole run."

### 6.2 Transaction boundaries by flow

| Flow | Transaction contents | Commit point | Failure behaviour |
|---|---|---|---|
| Signup | Insert user | After insert | Unique violation → 400 `"User already exists"`; no user row |
| Login / `/me` | Read only | — | No writes |
| First `GET /funds` | `INSERT ... ON CONFLICT DO NOTHING`; select | After insert/select | Concurrent first reads create one row |
| Deposit | Upsert/credit funds; insert transaction | After both | Rollback both; no credit without ledger |
| Withdrawal | Conditional debit; insert transaction | After both | Rollback both; 400 if insufficient |
| Order placement | Advisory lock; pre-validate CNC holdings; debit (BUY/MIS); insert order as OPEN; MARKET fill; finalize status | After final transition | Rollback debit/order/fill; no lost cash; a rejected MARKET order keeps `filled=0` |
| Limit/stop fill | Advisory lock; lock order; validate quote/backing position; adjust SL-M cash; apply fill/settle; final EXECUTED; cancel siblings | After siblings | Business rejection sets REJECTED with `filled`/`price` unchanged; a technical failure rolls back and leaves the order OPEN |
| Cancel | Advisory lock; conditional `OPEN -> CANCELLED`; refund | After refund | Rollback; order stays OPEN |
| Set exits | Advisory lock; lock holding/position; cancel old/refund; create new/debit | After new legs | Rollback; old exits remain |
| Square-off | Advisory lock; lock/delete position; credit; settlement; closing order; cancel exits | After all | Rollback; position remains |
| Snapshot (per user) | Upsert one `(user, date)` row | After upsert | Previous users stay committed; current user unchanged |
| Market sync | Upsert instruments + quotes in one transaction | After batch | Previous cache remains |
| Price refresh | Update quotes in one transaction | After batch | Stored prices remain |
| Watchlist add | Insert; unique constraint | After insert | 409 on duplicate |
| Watchlist delete | Delete by id+user | After delete | Always 204 |

### 6.3 Order placement

**Current problem:** the debit (`api/routes/orders.py:127-143`) and the order insert
(`api/routes/orders.py:161-184`) are separate Mongo writes. The CNC holdings check
(`api/routes/orders.py:145-159`) is **not** the cause of a lost debit: its predicate
(`side == 'SELL' and product != 'MIS'`) is mutually exclusive with the debit predicate
(`side == 'BUY' or product == 'MIS'`), so a CNC sell never debits cash. The real defect is
that any later failure — order insert, `apply_fill`, or a process crash — leaves the debit
committed with no order or no fill. A MARKET order is also inserted as
`status='EXECUTED'`, `filled=qty` before `apply_fill`
(`api/routes/orders.py:162-180`), so a fill-time rejection can persist a rejected order
that still looks fully filled (`api/order_engine.py:133-141`).

**New sequence:**

1. Validate the body, `exchange == 'NSE'`, and coerce quantities/prices (outside the
   transaction).
2. For MARKET, fetch the provider quote (outside the transaction). Require a usable
   `ltp` and a trustworthy `source_time` (§6.4); otherwise 503.
3. `BEGIN`; acquire the per-user advisory lock.
4. Validate the cash/holdings precondition:
   - `side == 'SELL' and product != 'MIS'`: `SELECT ... FROM holdings WHERE user_id = $user
     AND symbol = $symbol AND exchange = 'NSE' FOR UPDATE`; require `qty >= order.qty`.
     **No cash is debited for this branch.**
   - `side == 'BUY' or product == 'MIS'`: guarded debit
     `UPDATE funds SET available = available - $amount WHERE user_id = $user AND available
     >= $amount RETURNING *`, with `amount` quantized to 2 dp. No row → 400 insufficient
     funds; rollback.
   - The two predicates cannot both be true; do not run both in one placement.
5. Insert the order with `status='OPEN'`, `filled=0`, and `price=exec_price` (the observed
   MARKET price or the requested limit/trigger price). For a bracket entry, set
   `group_id = id`.
6. If MARKET:
   - Run every business validation **before** any fill mutation (backing position/holding,
     quantity, bracket-exit preconditions, any other rule). A validation failure is the
     only path that commits `REJECTED`, and it does so before `apply_fill` has touched
     anything.
   - Call `apply_fill` inside the same transaction.
   - On success, set `status='EXECUTED'`, `filled=qty`, `price=$fill_price` with a
     conditional `WHERE id = $id AND status = 'OPEN'` update.
   - On a validation rejection, set `status='REJECTED'` only. Leave `filled` at its inserted
     value (normally `0`) and leave `price` unchanged. Reverse the debit in the same
     transaction if the order blocks cash; cancel siblings. Commit and return 201 with the
     `REJECTED` order, matching the current response shape.
   - If `apply_fill` raises after any mutation, roll back the whole transaction. Do not
     commit a `REJECTED` order with a partially applied fill, spawned exits, or a
     settlement.
7. If not MARKET, leave the order `OPEN` with `filled=0`; the fill job owns the later
   transition.
8. `COMMIT`; return the order.

**Rejection rule (D26):** `filled=qty` is written **only** by a successful `EXECUTED`
transition. A rejected order never receives a fill price, a settlement, or a cash credit.
If it blocked cash, rejection refunds the blocked amount in the same transaction. The same
rule applies to a limit/stop fill-time rejection in §6.4.

**Cash-block predicate:** the predicate differs for exit legs. Use one helper everywhere:

```text
blocks_cash(order):
    if order.is_exit:
        return order.side == "BUY" and order.product == "CNC"
    return order.side == "BUY" or order.product == "MIS"
```

This matches the current cancel/refund logic (`api/routes/orders.py:312-319`) and prevents
an exit leg from receiving a refund it never paid.

### 6.4 Limit/stop fills and claims

For each crossed OPEN order:

1. `BEGIN`; acquire the per-user advisory lock.
2. Lock the order:
   ```sql
   SELECT * FROM orders WHERE id = $id FOR UPDATE;
   ```
   If the row is missing or `status <> 'OPEN'`, rollback/skip. This row lock is the claim:
   a concurrent cancel or fill waits here, then sees the terminal status after the winner
   commits. **Do not change `status`, `filled`, or `price` yet.**
3. Validate the fill while the row is locked. Compute `fill_price` from the locked order and
   the quote once, before any mutation:
   - `SL-M` -> the provider LTP; `LIMIT`/`SL` -> the order's stored `price`;
   - the quote has a trustworthy `source_time` and passes the freshness guard below;
   - the backing holding/position exists and has enough quantity;
   - the order is not an oversized MIS exit;
   - any other business precondition.
4. If validation fails for a business reason:
   - `UPDATE orders SET status = 'REJECTED', updated_at = $now WHERE id = $id AND status =
     'OPEN' RETURNING *;`
   - leave `filled` and `price` exactly as stored (a legacy partial `filled` remains
     partial; a normal order stays `0`);
   - refund the unfilled blocked cash in the same transaction when
     `blocks_cash(order)` is true, using the same `blocked - filled_cash` rule as cancel
     (§5.6);
   - cancel open siblings;
   - `COMMIT`.
5. If validation passes:
   - For SL-M, adjust cash by `blocked − actual` (each total quantized to 2 dp).
   - Apply the fill/settlement (`apply_fill` or the corrected MIS-exit path) with the
     computed `fill_price`; do not let an SL-M fill settle at the stale stored `price`.
   - Make the final conditional transition:
     ```sql
     UPDATE orders
     SET status = 'EXECUTED', filled = qty, price = $fill_price, updated_at = $now
     WHERE id = $id AND status = 'OPEN'
     RETURNING *;
     ```
     No row here is an invariant violation; raise and roll back the whole transaction so
     the fill and the status cannot diverge.
   - Cancel open siblings and refund their blocked cash.
   - `COMMIT`.
6. On a technical exception, roll back the order's transaction. The order stays `OPEN`; log
   and continue with the next order. Do not mark it `REJECTED` for a database/provider
   failure.

The row lock plus the final conditional update is the idempotency guard. A cancel or
another fill that already moved the order out of `OPEN` is observed after the lock is
acquired, so it cannot also settle. The `UPDATE` is a defensive assertion, not a
pre-validation claim.

**Quote freshness guard.** A fill needs a provider market time, not just a recent receipt
time:

- `source_time` must be non-`NULL`. Migrated legacy quotes have `NULL` and cannot fill
  until a fresh provider sync writes a value.
- `source_time` must not be more than 2 minutes in the future relative to the transaction
  clock (clock skew guard).
- `source_time` must be within 10 minutes of the transaction clock. These constants are
  named (`MAX_QUOTE_AGE`, `MAX_FUTURE_SKEW`) and tested at the boundary.
- `updated_at` is **not** used for this guard; it remains the API's receipt timestamp.
- A stale, future-dated, or missing `source_time` means "skip this order this tick". Keep
  the order `OPEN`, log the symbol/reason, and do not mark it `REJECTED`. MARKET
  placement uses the same helper and returns 503 instead of placing the order.

**Legacy partial `filled`.** The success transition sets `filled = qty`, preserving the
current all-or-nothing fill. If an `OPEN` order has `0 < filled < qty`, the migration gate
in §4.6 must resolve it before the order can be filled in production. A rejection preserves
the stored partial value; it does not rewrite it to `0` or `qty`.

### 6.5 Cancellation versus fill

| Interleaving | Result |
|---|---|
| Cancel commits first | Fill locks the order, sees `CANCELLED`, and skips; refund happened once |
| Fill commits first | Cancel update matches 0 rows; route reads `EXECUTED` and returns 400 `"Order is already executed"`; no refund |
| Both attempt the conditional update concurrently | The row lock and per-user advisory lock serialize them; exactly one `RETURNING` row |
| Two cancels | One refunds; the second sees non-OPEN and returns 400 |
| Fill rejects for a business reason | `OPEN -> REJECTED`, `filled`/`price` unchanged, blocked cash refunded once; a concurrent cancel sees `REJECTED` |
| Cancel of an exit leg | Only that leg is cancelled; the sibling remains open (current behaviour) |

### 6.6 OCO coordination

A group consists of an optional entry plus up to two exits (`SL-M`, `LIMIT`) sharing
`group_id`. The invariant is: **at most one exit in a group may reach `EXECUTED`.**

**Fill sequence:**

1. `BEGIN`; acquire the per-user advisory lock.
2. Lock the exit order (`SELECT ... FOR UPDATE`) and verify `status='OPEN'`. Do not change
   `status`, `filled`, or `price` yet. Then lock the backing position/holding row. If it is
   gone:
   - MIS exit → mark the exit `CANCELLED` (current behaviour), leave `filled`/`price`
     unchanged, and cancel siblings;
   - non-MIS exit → mark it `REJECTED`, leave `filled`/`price` unchanged, refund its unfilled
     blocked cash if `blocks_cash(order)`, and cancel siblings.
3. Validate and settle the fill using the §6.4 `fill_price`; insert the settlement
   transaction.
4. Make the final conditional transition to `EXECUTED`, setting `filled=qty` and
   `price=$fill_price` only now.
5. Cancel siblings:
   ```sql
   UPDATE orders
   SET status = 'CANCELLED', updated_at = $now
   WHERE group_id = $group AND is_exit AND status = 'OPEN' AND id <> $current
   RETURNING *;
   ```
6. Refund each returned CNC BUY sibling's blocked cash in the same transaction.
7. `COMMIT`.

**Concurrent two-leg fill:** the advisory lock serializes the two workers. The first
finalizes and cancels the second; the second sees a non-`OPEN` order and does nothing. Even
without the advisory lock, the row lock plus the conditional final update would allow only
one `EXECUTED`; the lock also prevents interleaved position updates and duplicate sibling
refunds.

**Status transitions:**

| From | To | Trigger | Guard |
|---|---|---|---|
| `OPEN` | `EXECUTED` | Successful fill, after validation and settlement | `status = 'OPEN'` |
| `OPEN` | `CANCELLED` | Manual cancel, sibling cancel, set-exits replacement, square-off | `status = 'OPEN'` |
| `OPEN` | `REJECTED` | Fill cannot apply (no holding/position, oversized exit, stale/future quote is *not* a rejection) | `status = 'OPEN'`; `filled`/`price` unchanged |
| `EXECUTED` | — | Terminal | No transition |
| `CANCELLED` | — | Terminal | No transition |
| `REJECTED` | — | Terminal | No transition |

The database enforces the value set, not the transition graph. Transitions are
application-enforced and tested; a trigger is deferred because it would hide business
logic.

### 6.7 Partial MIS exit accounting

**Decision:** reject `order.qty > position.qty`; otherwise decrement and keep the
remainder.

```text
if order.qty > position.qty:
    UPDATE orders SET status = 'REJECTED', updated_at = now
        WHERE id = order.id AND status = 'OPEN'
        RETURNING *       # filled and price are not touched
    cancel_siblings()
    commit
    return  # no funds, no settlement, position unchanged

qty = order.qty
fill_price = provider_ltp if order.type == "SL-M" else order.price
pnl = quantize((fill_price - position.entry) * qty * direction, CASH)
release = quantize(position.entry * qty, CASH) + pnl
updated = UPDATE positions SET qty = qty - order.qty, updated_at = now
    WHERE id = position.id AND qty >= order.qty
    RETURNING qty
if no row returned:                    # concurrent exit/square-off won
    UPDATE orders SET status = 'REJECTED', updated_at = now
        WHERE id = order.id AND status = 'OPEN'
        RETURNING *       # filled and price are not touched
    cancel_siblings()
    commit
    return  # no funds, no settlement
remaining = updated.qty
if remaining == 0: DELETE position
credit funds release
insert SETTLEMENT amount=pnl
UPDATE orders SET status = 'EXECUTED', filled = qty, price = fill_price
    WHERE id = order.id AND status = 'OPEN'
cancel_siblings()
commit
```

The `EXECUTED` transition is last. If it returns no row, roll back the whole transaction
so the position decrement, credit, and order status cannot diverge. Rejection leaves the
order's stored `filled` (normally 0) and `price` intact; it never sets `filled=qty` for an
order that did not settle. An MIS exit does not block cash (`blocks_cash` is false for
`is_exit` + `product='MIS'`), so its rejection needs no refund.

**Example:** position 100 @ ₹100, exit 40 @ ₹110, LONG. Remainder 60 @ ₹100. P&L ₹400.
Funds credited ₹4,400 (entry ₹4,000 + P&L ₹400). Position row remains with `qty=60`.

**Oversized example:** position 100, exit 120. No decrement, no credit, order `REJECTED`,
siblings cancelled. This is safer than the current `min()` cap, which would silently fill
100 and delete the position.

**After a partial exit:** the sibling is cancelled (OCO), so the remaining 60 shares have
no exit. The user can set a new exit pair. This is explicit in the API docs/tests; do not
leave a stale exit sized for 100.

### 6.8 Square-off race

1. Fetch the live quote (or the canonical `latest_quotes.ltp` fallback) before `BEGIN`; if
   neither is usable, return 400 `"No live price..."`.
2. `BEGIN`; advisory lock; `SELECT ... FROM positions WHERE id = $id AND user_id = $user
   FOR UPDATE`.
3. Validate `product='MIS'` and `ltp > 0`; if the row is gone, rollback and return 404.
4. Compute P&L/release.
5. `DELETE ... WHERE id = $id AND user_id = $user RETURNING *` as the claim.
6. Credit funds; insert settlement; insert closing MARKET order; cancel open MIS exits.
7. `COMMIT`.

A concurrent exit fill either commits first (position qty reduced or deleted; square-off
sees the new state) or waits for the square-off lock and then finds no position.
**[Intentional change]** The second square-off returns 404 after the lock, whereas the
current race-specific path can return 409 `"Position was already squared off"`; the normal
not-found path is already 404. Tests must pin the new status. **[Intentional change]** If
neither the provider nor the canonical quote has a usable price, square-off returns 400;
the old per-position `ltp` cache fallback does not exist after normalization.

### 6.9 Duplicate refunds

Every refund is tied to a conditional status transition that returns the affected row:

- cancel refunds only when `OPEN -> CANCELLED` returned the order;
- sibling refunds only for rows returned by the sibling-cancel `UPDATE`;
- SL-M adjustment only for the order being filled, after its row lock and validation;
- square-off credits only when `DELETE ... RETURNING` returned the position.

No status transition, no refund. This is the idempotency mechanism; there is no separate
refund ledger in Phase 2. A client retry of a deposit/withdrawal is still a new request
(there is no idempotency key); that is a pre-existing API limitation, noted as future work.

### 6.10 Job boundaries

- **Market sync:** provider call outside; one transaction for the instrument/quote batch;
  sector backfill in small per-instrument transactions with `FOR UPDATE SKIP LOCKED`.
- **Price sync:** provider call outside; one transaction for quote updates; then one
  transaction per crossed order. One bad order does not abort the others.
- **Snapshot:** one transaction per user; current abort-on-first-error behaviour is
  preserved (completed users stay committed).
- **Scheduler ownership:** one process sets `MARKET_SYNC_ENABLED` /
  `TRADING_JOBS_ENABLED` (`api/scheduler.py:47-58`). Transaction-scoped job advisory locks
  may serialize a batch, but they are not a lease and do not prevent a second process from
  starting the next tick. The real duplicate guards are the per-order row
  lock/conditional transition, unique quote/instrument keys, `ON CONFLICT` snapshot upsert,
  and `FOR UPDATE SKIP LOCKED` sector backfill (§2.13).
- **If a job-wide lease is later required:** add a `job_locks` table with `owner`,
  `acquired_at`, `expires_at`, and a heartbeat, or hold a session-level advisory lock on a
  dedicated connection. Do not stretch `pg_advisory_xact_lock` beyond its transaction.

### 6.11 SQL patterns

**Guarded debit:**

```sql
UPDATE funds
SET available = available - $1, updated_at = $2
WHERE user_id = $3 AND available >= $1
RETURNING id, available;
```

**Final conditional transition (after validation and settlement):**

```sql
UPDATE orders
SET status = 'EXECUTED', filled = qty, price = $1, updated_at = $2
WHERE id = $3 AND status = 'OPEN'
RETURNING *;
```

**Business rejection (preserve `filled` and `price`):**

```sql
UPDATE orders
SET status = 'REJECTED', updated_at = $1
WHERE id = $2 AND status = 'OPEN'
RETURNING *;
```

**Sibling cancel/refund:**

```sql
UPDATE orders
SET status = 'CANCELLED', updated_at = $1
WHERE group_id = $2 AND is_exit AND status = 'OPEN' AND id <> $3
RETURNING *;
```

**Weighted-average merge:**

```sql
INSERT INTO holdings (id, user_id, symbol, name, exchange, qty, avg_price,
                      created_at, updated_at, version)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $8, 0)
ON CONFLICT (user_id, symbol, exchange) DO UPDATE
SET qty = holdings.qty + EXCLUDED.qty,
    avg_price = round(
      (holdings.qty * holdings.avg_price + EXCLUDED.qty * EXCLUDED.avg_price)
      / (holdings.qty + EXCLUDED.qty), 6),
    updated_at = EXCLUDED.updated_at;
```

PostgreSQL `round(numeric, 6)` rounds half away from zero, matching `ROUND_HALF_UP` for
positive averages. If the expression can be negative, use an explicit SQL rounding helper
or compute in Python; weighted averages are non-negative.

**Snapshot upsert:**

```sql
INSERT INTO portfolio_snapshots
  (id, user_id, snapshot_date, value, invested, mis_invested, mis_value,
   created_at, updated_at, version)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $8, 0)
ON CONFLICT (user_id, snapshot_date) DO UPDATE
SET value = EXCLUDED.value, invested = EXCLUDED.invested,
    mis_invested = EXCLUDED.mis_invested, mis_value = EXCLUDED.mis_value,
    updated_at = EXCLUDED.updated_at;
```

### 6.12 Concurrency tests

Use two or more real PostgreSQL connections, not one test transaction:

- two debits against the same funds row;
- two cancels against the same order;
- cancel versus fill;
- two fills against the same order;
- two fills merging the same holding/position;
- two square-offs of the same position;
- two OCO legs filling concurrently;
- square-off versus exit fill;
- two signups with the same email/username;
- two watchlist adds with the same `(user, symbol)` but different `exchange` values;
- a fill that rejects while a cancel is waiting; assert `filled`/`price` unchanged and one
  refund at most;
- two price-sync workers against the same OPEN order; assert one fill;
- two snapshot runs for the same user/day;
- two market-sync workers.

Assert invariants, not just row counts: no negative cash through guarded paths, no double
credit, no orphan position, no duplicate business key, exactly one OCO fill, and no
`REJECTED`/`CANCELLED` order with `filled=qty` unless it was already legacy data accepted by
the migration gate.

---

## 7. Quote and instrument storage

### 7.1 What the current model does

`marketquotes` is a single global cache of 53 rows: 3 indices and the 50 Nifty stocks. It
holds identity (`symbol`, `name`, `kind`, `sector`) and volatile prices (`ltp`,
`dayChange`, `dayChangePct`, `prevClose`, `volume`, `marketCap`) in one document. It is
written by `market_sync` (`api/jobs/market_sync.py:56-116`) and read by the Markets page,
search, and the instrument detail routes (the latter two call the provider directly).

Separately, `holdings`, `positions`, and `watchlists` each store their own `ltp` (and the
first two also `dayChangePct`), refreshed by `price_sync`
(`api/jobs/price_sync.py:122-159`). Those caches can diverge from `marketquotes`: the
schedules differ, a book symbol may not be in the 53-symbol universe, and a provider
failure affects each path independently.

`holdings.sector` is a third copy of instrument metadata, backfilled once by `price_sync`
(`api/jobs/price_sync.py:161-182`), while `marketquotes.sector` is backfilled by
`market_sync` (`api/jobs/market_sync.py:127-158`). Two owners, two columns.

### 7.2 Options

**Option A — minimal change: one `market_quotes` table.**

- Keep the 53-row cache exactly as it is.
- Keep `ltp`/`dayChangePct` cached in holdings/positions/watchlists.
- Translate the current upserts and reads mechanically.

Pros: smallest diff; exact current API values; no reconciliation of book caches.
Cons: three quote copies; price-sync and market-sync can disagree; sector has two owners;
the schema encodes the cache duplication.

**Option B — normalized: `instruments` + `latest_quotes`, no book caches.**

- `instruments`: one row per symbol, owning name, kind, sector, and market-universe
  membership.
- `latest_quotes`: one row per instrument, owning current prices.
- Holdings/positions/watchlists join the quote; they no longer store `ltp` /
  `dayChangePct`; holdings no longer stores `sector`.
- A synthetic instrument/quote row is created for a book symbol outside the 53-symbol
  universe.

Pros: one quote source; one sector owner; no drift; natural place for future history;
cleaner write paths.
Cons: extra joins; migration must reconcile cached values; market overview/search must
filter the original universe; price-sync now writes the canonical quote, which can change
what the Markets page shows; more code churn.

**Option C — normalized plus history: `instruments` + `latest_quotes` + `quote_history`.**

Out of scope. There is no historical quote requirement today; adding a time-series table
is a market-data feature, not a migration.

### 7.3 Comparison

| Criterion | A: minimal | B: normalized | C: history |
|---|---|---|---|
| Schema complexity | Low | Medium | High |
| Read cost | One table/row | One join on a unique symbol | Join + time filter |
| Write paths | Three caches + market cache | Two tables (instrument + quote) | Two tables + append |
| Quote consistency | Can drift | Single source | Single source |
| Sector ownership | Two columns | One column | One column |
| Migration cost | Low | Medium: reconcile book caches, universe flag | High |
| API parity risk | Low | Medium: canonical LTP may differ | Medium |
| Future history/streaming | Awkward | Natural | Built-in |
| Recommendation | Fallback only | **Recommended** | Deferred |

### 7.4 Recommendation

**Option B.** Normalize to `instruments` + `latest_quotes`, remove the per-book quote
caches, and keep `in_market_universe` on `instruments` so the Markets page and search keep
their current 53-symbol scope. Keep the per-book `name` fields (they are part of the book
API and survive a missing instrument), but read `sector` from `instruments`.

This is a deliberate structural improvement, not a mandatory part of "move to Postgres".
If the team decides exact cutover parity is more important than consistency, Option A is a
valid fallback; it is not the recommendation.

### 7.5 Mapping and the universe flag

| Source field | Target | Rule |
|---|---|---|
| `marketquotes._id` | `instruments.id` | Preserve 24-hex ID. |
| `marketquotes.symbol` | `instruments.symbol` | Unique. |
| `marketquotes.name` | `instruments.name` | Preserve. |
| `marketquotes.kind` | `instruments.kind` | `stock`/`index`. |
| `marketquotes.sector` | `instruments.sector` | Preserve; `""` means pending. |
| (new) | `instruments.in_market_universe` | `true` for migrated marketquotes; `false` for book-only synthetic rows. |
| `marketquotes.createdAt` | `instruments.created_at` | Preserve. |
| `marketquotes.__v` | `instruments.version` | Preserve. |
| `marketquotes.ltp` | `latest_quotes.ltp` | Quantize 4 dp. |
| `marketquotes.dayChange` | `latest_quotes.day_change` | Quantize 4 dp. |
| `marketquotes.dayChangePct` | `latest_quotes.day_change_pct` | Quantize 6 dp. |
| `marketquotes.prevClose` | `latest_quotes.prev_close` | Quantize 4 dp. |
| `marketquotes.volume` | `latest_quotes.volume` | `bigint`; reject fractional. |
| `marketquotes.marketCap` | `latest_quotes.market_cap` | Quantize 2 dp. |
| `marketquotes.updatedAt` | `latest_quotes.updated_at` | Persisted/received time; API `updatedAt`/`asOf`. |
| (new) | `latest_quotes.source_time` | `NULL` for every migrated row; the legacy jobs discarded the provider time. |

The `marketquotes` identity fields map to `instruments`; there is no `exchange` column
because Phase 2 identity is symbol-only (D21). `marketquotes.kind='index'` includes
`^BSESN`; that is a BSE index, not a BSE equity listing.

**Book-only symbols:** for every symbol in holdings/positions/watchlists/orders that has
no `marketquotes` row, create an instrument with:

- `id` = new 12-byte hex (migration-generated; the source has no quote ID);
- `symbol` = the book symbol;
- `name` = the book row's `name` (or `symbol` if empty);
- `kind` = `stock`;
- `sector` = the holding's sector if present, else `""`;
- `in_market_universe` = `false`;
- `created_at` = the earliest book row's `created_at`;
- `version` = `0`.

Then create a `latest_quotes` row from the freshest **trustworthy** cached book values
(`ltp`, `dayChangePct`; `day_change`, `prev_close`, `volume`, `market_cap` default 0). This
preserves the book's displayed price at cutover even when the symbol is outside the
universe. The synthetic quote's `updated_at` is the winning book row's `updatedAt`;
`source_time` is `NULL` because the book cache never stored provider time. If no book row
has a trustworthy `updatedAt`, fall back to the instrument's `created_at` and report it; do
not stamp the quote with migration time, which would claim provider freshness for an old
cached price. Report every synthetic quote and its age.

**Conflicts and timestamp precedence.** The migration must not automatically prefer
`marketquotes`. It must compare the actual persisted timestamps:

1. Collect the `marketquotes` row (if any) and every book row that carries a **usable**
   cached LTP for the symbol. A usable LTP is finite and greater than zero. A row with a
   missing or zero `ltp` (for example, a newly added watchlist row) is not a price source,
   even when its `updatedAt` is newer; it is recorded for the report and fallback only.
2. A source timestamp is **trustworthy** when `updatedAt` is present, parses as a BSON
   date, is not more than 5 minutes in the future relative to the migration clock, and is
   not before 2000-01-01. Missing, malformed, or future timestamps are not trustworthy.
3. For `ltp` and `dayChangePct`, choose the usable row with the maximum trustworthy
   `updatedAt`. A newer book cache beats an older `marketquotes` row, but a newer row whose
   LTP is zero never wins. This is not hypothetical: across the two local databases, 36
   book rows were newer than their `marketquotes` row, 2 were older, and several
   watchlists carry `ltp = 0`.
4. If the winner is the `marketquotes` row, take all its quote fields. If the winner is a
   book row and a `marketquotes` row exists, take `ltp`/`dayChangePct` from the book row,
   take `day_change`, `prev_close`, `volume`, and `market_cap` from the marketquote, set
   `updated_at` to the winning book timestamp, and mark the quote `mixed_freshness` in the
   report. Do not use the older marketquote LTP.
5. If no usable row has a trustworthy timestamp, choose the value fallback: a
   `marketquotes` LTP greater than zero when present, else the freshest usable book LTP,
   else `0`. Use the marketquote's metadata fields when a marketquote exists. Set
   `updated_at` to the chosen source's timestamp, or the instrument `created_at` when it is
   missing, and report the symbol as `untrusted_timestamp`. A quote with no trustworthy
   timestamp never fills an order until a fresh provider sync writes `source_time`.
6. If the same symbol has different cached LTPs across book tables, step 3 resolves the
   winner; the report lists every loser and the difference. The migration report is the
   review artifact; do not silently pick one.

**Timestamp limitation.** The book collections do not store a quote-specific timestamp.
`holdings.updatedAt`, `positions.updatedAt`, and `watchlists.updatedAt` are document write
times: a fill, a quantity change, or a name edit can advance them without refreshing `ltp`.
The migration can therefore only treat them as **candidate** quote times, not proof that the
cached price is fresh. Step 1 excludes zero/missing LTP, and the report must list every
winning book row, its `updatedAt`, its LTP, and the marketquote's LTP/time so a reviewer can
see whether a document edit masqueraded as a quote refresh. If the team cannot accept that
ambiguity, prefer the marketquote for symbols that have one and use book rows only for
book-only symbols; that is the conservative fallback, not the default.

### 7.6 Read paths

**Holdings** (`GET /api/holdings`):

```sql
SELECT h.id, h.user_id AS "user", h.symbol, h.name, h.exchange, h.qty,
       h.avg_price AS "avgPrice",
       COALESCE(q.ltp, 0) AS ltp,
       COALESCE(q.day_change_pct, 0) AS "dayChangePct",
       COALESCE(i.sector, '') AS sector,
       h.created_at AS "createdAt", h.updated_at AS "updatedAt", h.version AS "__v"
FROM holdings h
LEFT JOIN instruments i ON i.symbol = h.symbol
LEFT JOIN latest_quotes q ON q.instrument_id = i.id
WHERE h.user_id = $1
ORDER BY h.created_at ASC, h.id ASC;
```

Positions and watchlists use the same pattern (positions omit `dayChangePct`; watchlists
omit `sector`). Orders do not join quotes; they return stored order fields.

**Market overview:**

```sql
SELECT i.id AS "_id", i.symbol, i.name, i.kind, i.sector,
       q.ltp, q.day_change AS "dayChange", q.day_change_pct AS "dayChangePct",
       q.prev_close AS "prevClose", q.volume, q.market_cap AS "marketCap",
       i.created_at AS "createdAt", q.updated_at AS "updatedAt", i.version AS "__v"
FROM instruments i
JOIN latest_quotes q ON q.instrument_id = i.id
WHERE i.in_market_universe = true;
```

Then split indices/stocks and apply §4.13 ordering. `asOf` is
`max(q.updated_at)` over the same filtered set. This preserves the 53-row Markets page and
makes `asOf` mean "freshest quote **receipt**", not "freshest metadata edit". It does not
mean "freshest provider trade": `source_time` is deliberately not exposed and may be older
than `updated_at`. Do not switch `asOf` to `source_time`; that would be an API change.

**Search:** filter `i.in_market_universe = true`, join `latest_quotes`, apply the
relevance order, limit 10. Return the same aliases as today (`price` = `ltp`,
`changePct` = `day_change_pct`).

**Assistant:** holdings/positions/watchlists tools use the same joined reads and ordering
as the pages. The watchlist tool reads `watchlists`, not `watchlist` (F4).

### 7.7 Write paths

**Market sync:**

1. Provider batch outside the transaction.
2. One transaction: for each ticker, upsert `instruments` by `symbol` with
   `in_market_universe = true`, updating `name`/`kind` but **not** `sector`; upsert
   `latest_quotes` with the price fields, `source_time` from `regularMarketTime` (or `NULL`
   when absent/invalid), and `updated_at = now()`. If the incoming `source_time` is present
   and older than the stored one, skip that row; a late/out-of-order provider response must
   not overwrite a newer quote. A missing `source_time` still refreshes the display fields
   but stores `NULL`, so the quote cannot fill an order until a timed quote arrives; log it
   as a warning, do not keep the previous `source_time` next to a newer price.
3. Sector backfill separately: `SELECT ... WHERE kind='stock' AND sector='' LIMIT 10 FOR
   UPDATE SKIP LOCKED`; update `instruments.sector`; do not touch
   `latest_quotes.updated_at`.

**Price sync:**

1. Gather symbols from holdings, positions, watchlists, and OPEN orders.
2. Provider batch outside the transaction.
3. For valid quotes, ensure an instrument exists:
   - if the symbol is in the universe, use it;
   - otherwise insert a book-only instrument (`in_market_universe=false`) with the book
     name.
4. Upsert `latest_quotes.ltp`, `day_change_pct`, `source_time`, `updated_at` for every valid
   quote. Preserve `day_change`, `prev_close`, `volume`, `market_cap` unless the provider
   row supplies them (market sync owns the full row). Apply the same
   out-of-order and missing-`source_time` rules as market sync.
5. Fill orders per §6.4, using `source_time` for the freshness guard. A quote written with
   `source_time = NULL` is displayed but cannot fill.

This means a price-sync tick can refresh the Markets page's quote for a symbol in both the
book and the universe. That is a behaviour change (fresher canonical quote), but it is the
point of normalization. If exact separation is required, Option A is the fallback.

**Sector backfill ownership:** one shared function, called by the scheduler, updates
`instruments` for both universe and book-only stocks. Do not keep a second
`holdings.sector` path.

### 7.8 Migration cost and API effects

- **Schema:** two tables instead of one; one new boolean; one new nullable `source_time`; one FK.
- **Reads:** three joins; a missing quote yields `0`/`""` to preserve shape.
- **Writes:** market sync and price sync both touch `latest_quotes`; sector has one owner.
- **Migration:** create instruments/quotes for book-only symbols; reconcile cached values
  by trustworthy timestamp; filter the universe.
- **API effects:**
  - A holding/position/watchlist may show a different LTP if its cached value was newer
    than `marketquotes`; the reconciliation report lists every difference and the winning
    source.
  - **[Intentional change]** Market overview `asOf` remains the freshest quote **receipt**
    (`latest_quotes.updated_at`) and no longer moves when a sector is backfilled.
  - `source_time` is internal; no response field is added.
  - Search ordering becomes deterministic.
  - A non-Nifty holding does not appear on the Markets page/search, matching today.
  - Non-NSE holdings/orders are not loaded; they are quarantined and block cutover until
    resolved.
- **Performance:** joins are on unique indexes at a 53-row local quote table; negligible. If the
  universe grows to thousands, add covering indexes or a materialized read model later.

### 7.9 If exact parity is mandatory

Choose Option A: keep a single `market_quotes` table and retain the book caches. It is a
mechanical migration with the least API risk, but it preserves three quote copies and the
sector duplication. The rest of this design (IDs, Decimal, transactions, OCO, ordering,
snapshot date) still applies. Do not partially normalize (e.g., create `instruments` but
keep book caches); that adds complexity without removing the drift.

---

## 8. Data profiling and migration prerequisites

### 8.1 Method and safety

The profile was read-only and local:

- MongoDB at `mongodb://127.0.0.1:27017` (no credentials);
- databases `tradium_fastapi_dev` (the FastAPI dev database) and `zerodha` (legacy seed
  data);
- aggregate queries only: counts, distinct values, min/max, null counts, duplicate
  groups, regex shape checks, orphan checks, and ID checks;
- no document contents, personal records, password hashes, or credentials are reproduced
  in this document;
- no writes, repairs, index creation, or migrations were performed.

This is sufficient to validate the design against a small real dataset. It is **not**
sufficient to finalize production `NOT NULL`, `CHECK`, or unique constraints.

### 8.2 Local dataset size

| Collection | `tradium_fastapi_dev` | `zerodha` |
|---|---:|---:|
| `users` | 1 | 6 |
| `funds` | 1 | 3 |
| `holdings` | 1 | 12 |
| `positions` | 0 | 10 |
| `orders` | 2 | 10 |
| `transactions` | 1 | 10 |
| `watchlists` | 2 | 13 |
| `marketquotes` | 53 | 53 |
| `portfoliosnapshots` | 0 | 756 |
| **Total** | **61** | **873** |

The `zerodha` database is legacy seed/demo data, not a production sample. The
`tradium_fastapi_dev` database was created by the FastAPI app and has only `_id_` indexes
on every collection; `zerodha` has the legacy Mongoose indexes. This is direct evidence
that FastAPI does not create business indexes.

### 8.3 Identity, orphans, and duplicates

| Check | Result |
|---|---|
| `_id` values that are not 24 lowercase hex | 0 in both databases |
| `user` references that are not 24 lowercase hex | 0 |
| User-scoped rows whose `user` has no `users` row | 0 |
| Duplicate `users.email` / `users.username` | 0 |
| Duplicate `funds.user` | 0 |
| Duplicate `holdings (user, symbol, exchange)` | 0 |
| Duplicate `positions (user, symbol, exchange, side, product)` | 0 |
| Duplicate `watchlists (user, symbol, exchange)` | 0 |
| Duplicate `watchlists (user, symbol)` | 0 locally (all rows are `NSE`); PROFILE REQUIRED for a mixed-exchange production dataset |
| Duplicate `marketquotes.symbol` | 0 |
| Duplicate `portfoliosnapshots (user, date)` | 0 |
| Case-insensitive `users.username` collisions | 1 in `zerodha` |
| Case-insensitive `users.email` collisions | 0 |

**Implication:** `citext` would fail the legacy dataset because of the username collision.
Preserve case-sensitive unique `text`. The duplicate checks are clean locally, but the
FastAPI-created database has no unique indexes, so production must be profiled before
relying on the same result.

### 8.4 Nulls, missing fields, and legacy shapes

| Finding | Evidence | Design impact |
|---|---|---|
| 3 of 6 `zerodha` users have no `funds` row | Lazy creation on first read | `funds` is optional 1:0..1; do not backfill a row just to satisfy a FK |
| One legacy `funds` row has `collateral` and `usedMargin` | Not in the current model | Ignore; report as unmapped legacy fields |
| All `holdings.name`, `positions.name`, `orders.name`, `watchlists.name`, `marketquotes.name` present locally | No null/empty/missing | `NOT NULL` is safe locally; production profile still required |
| `watchlists.name` can be written as `null` by the route | `api/routes/watchlist.py:56-64` | Migration/route fallback to `symbol`; then `NOT NULL` (F10) |
| All local password hashes start `$2b$` | Bcrypt cost 10 | Map `password` -> `password_hash`; never expose |
| 4 snapshots lack `misInvested`/`misValue` | Legacy/backfill gap | Default 0; current API already treats them as 0 |
| 0 snapshots lack `invested` locally | But Mongoose default allows omission | Default 0; current API renders 0 as `null` |
| No `NaN`/`Infinity` in local numeric fields | Aggregate scan | Reject at boundaries; migration gate |
| Timestamps have millisecond components; no future dates | Local sample | `timestamptz(3)`; application truncation |

### 8.5 Numeric profile

The table combines both local databases (`tradium_fastapi_dev` + `zerodha`) so the
design is tested against the dev write shapes as well as the legacy seed data. Counts
are from the profiling snapshot; the local databases are mutable and are not a
production sample.

| Field | n | Observed range | Fractional? | Notes |
|---|---:|---|---|---|
| `funds.available` | 4 | 0 .. 2,476,200 | 2 of 4 | Non-negative locally; do not add a check yet |
| `holdings.qty` | 13 | 20 .. 150 | No | Integer |
| `holdings.avgPrice` | 13 | 249.68 .. 1,880.53 | 12 of 13 | 2 dp in seed; use 6 dp storage |
| `holdings.ltp` | 13 | 259.85 .. 1,927 | 10 of 13 | 2 dp |
| `holdings.dayChangePct` | 13 | -1.3865504 .. 2.0827346 | 12 of 13 | Up to 7 dp; quantize 6 |
| `positions.qty` | 10 | 20 .. 300 | No | Integer |
| `positions.entry` | 10 | 315.67 .. 2,523.11 | 10 of 10 | 2 dp |
| `positions.ltp` | 10 | 333.4 .. 2,472.5 | 6 of 10 | 1-2 dp |
| `orders.qty` | 12 | 10 .. 300 | No | Integer; dev MARKET order qty 10 |
| `orders.filled` | 12 | 0 .. 120 | No | Integer; two OPEN orders have `filled=120` |
| `orders.price` | 12 | 263.59 .. 3,382.3 | 10 of 12 | 2 dp |
| `transactions.amount` | 11 | -25,000 .. 2,500,000 | 4 of 11 | Signed; dev deposit is 2,500,000 |
| `watchlists.ltp` | 15 | 0 .. 12,400 | 7 of 15 | Zero is a valid cached value |
| `watchlists.dayChangePct` | 15 | -2.0103698 .. 0.19127426 | 13 of 15 | Up to 8 dp; quantize 6 |
| `marketquotes.ltp` | 106 | 167.31 .. 74,916.31 | 66 of 106 | Both DBs carry the 53 symbols with different values |
| `marketquotes.dayChange` | 106 | -876.375 .. 134.60156 | 80 of 106 | Up to 5 dp |
| `marketquotes.dayChangePct` | 106 | -4.1860466 .. 2.624672 | 106 of 106 | Up to 7 dp; quantize 6 |
| `marketquotes.prevClose` | 106 | 166.3 .. 74,764.2 | 65 of 106 | 1-2 dp |
| `marketquotes.volume` | 106 | 0 .. 33,521,732 | No | 6 zeros (3 per DB); `bigint` |
| `marketquotes.marketCap` | 106 | 0 .. 17,091,513,024,512 | No | Integral but stored as float in 100 of 106; 6 zeros |
| `portfoliosnapshots.value` | 756 | 0 .. 851,316.66 | 734 of 756 | 2 dp |
| `portfoliosnapshots.invested` | 756 | 0 .. 817,379.35 | 740 of 756 | 2 dp |
| `portfoliosnapshots.misInvested` | 752 | 0 .. 422,923.89999999997 | 4 of 752 | Float artifact; quantize 4 |
| `portfoliosnapshots.misValue` | 752 | 0 .. 430,990.4 | 4 of 752 | 2 dp |

The chosen precisions are comfortably above these ranges. They are not chosen to fit the
seed data; they are chosen for exact financial arithmetic with headroom. The maximum
observed values (2.5M transaction, 33.5M volume, 17.1T market cap) confirm that the
candidate scales are not oversized for this application.

**Mapping the observed scales:**

- Cash (`funds.available`, `transactions.amount`) is stored at 2 dp. The local values are
  already at 1-2 dp; no observed value loses meaningful precision.
- Prices (`orders.price`, quotes) are stored at 4 dp. The observed 5-dp `dayChange`
  (`134.60156`) becomes `134.6016`; this is an intentional quantization, reported by the
  migration.
- Averages (`holdings.avgPrice`, `positions.entry`) are stored at 6 dp although the seed
  data is 2 dp; the extra scale is for repeated merges, not for the source values.
- Derived snapshot values stay at 4 dp; `misInvested`'s `422923.89999999997` float artifact
  becomes `422923.9000`, not a meaningful 14-dp value.
- Percentages are stored at 6 dp; the observed 7-8 dp values are quantized half-up.

### 8.6 Enums and order consistency

| Collection.field | Local distinct values |
|---|---|
| `holdings.exchange` | `NSE` |
| `positions.exchange` | `NSE` |
| `positions.side` | `LONG`, `SHORT` |
| `positions.product` | `MIS` |
| `orders.exchange` | `NSE` |
| `orders.side` | `BUY`, `SELL` |
| `orders.type` | `LIMIT`, `MARKET` |
| `orders.product` | `CNC`, `MIS` |
| `orders.status` | `CANCELLED`, `EXECUTED`, `OPEN`, `REJECTED` |
| `orders.isExit` | `false` only |
| `transactions.kind` | `DEPOSIT`, `FEE`, `SETTLEMENT`, `WITHDRAWAL` |
| `transactions.status` | `COMPLETED`, `PROCESSING` |
| `watchlists.exchange` | `NSE` |
| `marketquotes.kind` | `index`, `stock` |

**Exchange.** Every local `holdings`, `positions`, `orders`, and `watchlists` row is
`NSE`. `marketquotes` has no exchange field; its three indices include `^BSESN`, which is a
BSE **index** quote, not a BSE equity listing. A production dataset with any other exchange
value is quarantined by the migration and rejected by the new route/DB validation; it is
never coerced to `NSE`.

**Order findings:**

- 2 `OPEN` orders have `filled=120`, `qty=300`. `OPEN => filled=0` is false; the schema
  allows partial `filled`.
- `EXECUTED` orders with `filled != qty`: 0 locally.
- `filled > qty`: 0 locally.
- Non-empty `groupId`: 0 locally. No exits, no SL/SL-M orders, no brackets.
- Therefore the OCO/group formats are **not** represented locally, while partial `filled`
  on `OPEN` is (two rows). Tests must cover both with synthetic fixtures; production
  profiling must confirm their distribution.

**Partial-`filled` migration gate:** list every `OPEN` order with `0 < filled < qty` and
quarantine it by default. Preserve the stored values; do not infer additional fills or a
refund. Cutover requires an explicit accept/quarantine decision per row (R21), and the
runtime remains all-or-nothing until a partial-fill feature is designed.

### 8.7 Snapshot dates

| Check | Result |
|---|---|
| Total snapshots | 756 |
| Rows at `18:30Z` | 740 (legacy IST local midnight) |
| Rows at `00:00Z` | 16 (current job's UTC midnight) |
| Distinct IST days | 372 |
| Duplicate `(user, IST day)` | 0 |
| Missing `misInvested`/`misValue` | 4 |
| Missing `invested` | 0 |

Both conventions convert correctly with `(ts AT TIME ZONE 'Asia/Kolkata')::date`. This is
why the design uses a `date`, not a timestamp. Do not convert with a plain UTC `date()`:
`18:30Z` is the next IST day.

### 8.8 Quote cache

The table combines both local databases; both carry the same 53 symbols but different
quote values.

| Check | Result |
|---|---|
| `marketquotes` rows | 106 (53 per DB; 3 indices + 50 stocks each) |
| Max symbol length | 10 |
| Symbols not matching `^[\^A-Z0-9&-]{1,20}$` | 0 |
| Book symbols with no quote row | 0 holdings, 0 positions, 0 watchlists, 0 orders |
| Zero volume / market cap | 6 rows (3 per DB) |
| Max market cap | 17,091,513,024,512 (combined) |
| Max volume | 33,521,732 (combined) |
| Provider `regularMarketTime` persisted | No; both jobs discard it |
| Book rows newer than their `marketquotes` row | 36 (both DBs) |
| `marketquotes` rows newer than all book rows | 2 (watchlists, `zerodha`) |
| Non-NSE quote rows | 0; `^BSESN` is an index, not an equity listing |

The local cache is complete. Production may have gaps; the read path must handle a missing
quote with `0`/`""`, and the migration must create book-only instruments where needed.

**Timestamp evidence.** The 36-vs-2 result is why the migration cannot prefer
`marketquotes` automatically. The counts come from a read-only comparison of each book
row's `updatedAt` with the same symbol's `marketquotes.updatedAt`; both local databases
are mutable, so treat the counts as illustrative, not as production evidence. Because the
legacy jobs never stored `regularMarketTime`, every migrated quote gets `source_time =
NULL`; the first successful provider sync after cutover supplies it.

### 8.9 What the local profile cannot prove

Do not finalize these from the local sample:

- production row counts, document sizes, or index usage;
- malformed/uppercase IDs, orphan users, duplicate business keys;
- null/empty names, fractional quantities, negative balances, `NaN`/`Infinity`;
- enum drift in `exchange`, `status`, `kind`, transaction `kind/status`, especially any
  non-NSE exchange values;
- SL/SL-M orders, bracket exits, non-empty `groupId` formats;
- partial `filled` values on `OPEN` orders in production;
- duplicate watchlist `(user, symbol)` pairs that differ only by exchange;
- quote source timestamps, future-dated quote times, and mixed-freshness book/market rows;
- snapshot date conventions and duplicate `(user, IST day)` rows;
- the full market-cap/volume range;
- credentials, TLS, pooling, or Neon behaviour.

Each is **PROFILE REQUIRED** and a cutover gate.

### 8.10 Production profiling plan

Run against a read-only replica or a restored snapshot, never production primary:

1. **Counts and sizes:** documents per collection, total/average size.
2. **ID shape:** `_id` and `user` not matching `^[0-9a-f]{24}$`.
3. **Orphans:** user-scoped rows with no `users` row.
4. **Duplicates:** every intended unique key, including keys the FastAPI app did not
   index.
5. **Required fields:** users username/email/password; holdings/positions name/qty/
   avgPrice or entry; orders symbol/name/side/type/product/qty/price; watchlists name;
   marketquotes name; snapshots value/date.
6. **Enum drift:** every distinct `exchange`, `side`, `type`, `product`, `status`, `kind`,
   transaction `kind/status`. Any non-NSE equity value is a quarantine input, not a value
   to normalize.
7. **Numeric anomalies:** negative qty/price, `filled > qty`, fractional qty/filled,
   non-finite numbers, values outside the declared precision/scale.
8. **Date anomalies:** snapshot timestamps not at a known convention; future timestamps;
   missing timestamps; timezone offsets.
9. **Financial anomalies:** negative `funds.available`; settlement amounts that do not
   match their symbol; duplicate-looking retry transactions.
10. **Snapshot gaps:** users with no snapshots, multiple rows per user/day, missing
    `invested`/`mis*`.
11. **Cache gaps:** book/order symbols with no quote; instruments with no
    `latest_quotes` row; book-only instruments not referenced by any holding, position,
    watchlist, or order.
12. **Order consistency:** `EXECUTED` with `filled != qty`; `OPEN` with `filled > qty`;
    `REJECTED`/`CANCELLED` with `filled = qty`; exits with empty `groupId`; exit side/product
    mismatch.
13. **Quote timestamps:** `updatedAt` missing/future/older than the instrument; book vs
    `marketquotes` age differences; whether any legacy document has a provider time field
    that can populate `source_time`.
14. **Watchlist identity:** duplicate `(user, symbol)` pairs across exchange values.

Credentials come from the environment/secret manager. Logs contain counts and rule names,
not documents, emails, usernames, hashes, or connection strings.

### 8.11 Quarantine and repair policy

**Storage.** Quarantine lives outside the application schema, in a dedicated
`migration.quarantine` table. It is written by the one-shot loader, not by the app, and is
not exposed by any API.

```sql
CREATE SCHEMA IF NOT EXISTS migration;

CREATE TABLE migration.quarantine (
  id              bigserial PRIMARY KEY,
  source_collection text NOT NULL,
  source_id       text NOT NULL,          -- raw _id; malformed values are allowed here
  rule            text NOT NULL,
  severity        text NOT NULL CHECK (severity IN ('BLOCKER','REVIEW','WARNING')),
  detail          jsonb NOT NULL DEFAULT '{}'::jsonb,
  status          text NOT NULL DEFAULT 'OPEN'
                  CHECK (status IN ('OPEN','REPAIRED','ACCEPTED','EXCLUDED')),
  target_table    text,
  target_id       text,
  reviewer        text,
  reviewed_at     timestamptz(3),
  resolution_note text,
  created_at      timestamptz(3) NOT NULL DEFAULT now(),
  UNIQUE (source_collection, source_id, rule)
);

CREATE INDEX ix_quarantine_open
  ON migration.quarantine (severity, source_collection)
  WHERE status = 'OPEN';
```

`source_id` is `text`, not `varchar(24)`: the whole point is to record an ID that failed the
24-hex check without casting or losing it. A source row that violates several rules gets
one row per rule; the unique key makes a repeated loader run idempotent. `detail` holds
rule-specific metadata (field name, source value, target value). It must not contain names,
emails, password hashes, or other personal record contents; the read-only Mongo snapshot is
the place to inspect a row.

**Exclusion rule.** A source row with any `OPEN` or `EXCLUDED` rule is **never loaded** into
a `public` application table. A `REPAIRED`/`ACCEPTED` row may be loaded only through its
recorded resolution and `target_id`. If a parent row is quarantined (for example, a user),
every dependent row is also quarantined with `PARENT_QUARANTINED`, so FKs never dangle. The
loader commits the target row or the quarantine row for each source row; it does not leave a
half-loaded row.

**Resolution states:**

| Status | Loaded? | Meaning |
|---|---|---|
| `OPEN` | No | Unresolved; blocks cutover. |
| `REPAIRED` | Yes | Corrected under a documented rule; `target_id` recorded. |
| `ACCEPTED` | Yes | Loaded as-is with an explicit reviewer override; `target_id` and reconciliation note required. |
| `EXCLUDED` | No | Explicitly not loaded, with reviewer sign-off; source row remains in Mongo. |

The `Loaded?` column describes a row whose only quarantine rule is that one; the row-level
precedence for multiple rules is defined below. A loaded `REPAIRED`/`ACCEPTED` row is part of
the active target data; an `EXCLUDED` row is not. An `ACCEPTED` or `REPAIRED` row without
`target_id`, `reviewer`, or `reviewed_at` is invalid. A repeated loader run updates the
existing `(collection, id, rule)` record; it does not create a duplicate.

**Multiple rules per source row.** One source row can produce several quarantine records (one per
rule). The count identity is evaluated on **distinct source rows**, not on quarantine records:

- a row with any `OPEN` rule is open and is not loaded;
- otherwise, a row with any `EXCLUDED` rule is excluded and is not loaded;
- otherwise it is loaded, counted once as `clean_loaded` (no terminal record), `repaired`
  (at least one `REPAIRED` and no `ACCEPTED`), or `accepted` (at least one `ACCEPTED`).

`quarantine_total` is the only **record-level** count; report it separately from the
row-level identity so a row with several rules is not double-counted as a missing row.

**Accounting identity.** The migration report must state, per collection and per user:

```text
source_count      = active_count + open_quarantine_count + excluded_count
active_count      = clean_loaded + repaired + accepted
quarantine_total  = open_records + repaired_records + accepted_records + excluded_records
                    # rule records, not source rows
```

For every numeric field, after quantization:

```text
source_sum = active_sum + open_quarantine_sum + excluded_sum + repair_delta
```

`active_sum` is the **source-value** sum of loaded rows (not the target sum).
`repair_delta` is the signed difference between the loaded target value and the source value
for `REPAIRED`/`ACCEPTED` rows. Active counts and sums must exclude `OPEN` quarantine rows;
quarantined sums are reported separately, never folded into the active totals. This is the
check that prevents a quarantined row from silently disappearing from a financial total.

**Accepted rows require reconciliation.** An accepted row is not just "loaded anyway":

- It has a `target_id`, reviewer, and resolution note.
- Its contribution to funds, holdings, positions, orders, transactions, and any blocked
  cash/settlement is recomputed from the target row and compared with the source.
- An accepted partial-`filled` order must reconcile its blocked cash and any recorded
  settlement against the source; the reviewer signs off on the exact treatment.
- An accepted non-NSE row is **not** allowed in Phase 2: the DB check would reject it.
  Non-NSE values can only be repaired (if the source is provably a mislabelled NSE row) or
  excluded; they cannot be accepted as-is.

**Cutover gate:** `SELECT count(*) FROM migration.quarantine WHERE status = 'OPEN'` must be
zero. Every `WARNING` must be resolved (repaired/accepted/excluded); a warning is not a
license to leave an open row. The runbook does not switch the application until the gate
passes.

**Auto-fix only with a documented rule:** missing `__v` -> 0; missing
`misInvested`/`misValue` -> 0; missing `invested` -> 0; missing `sector` -> `""`; missing
`exchange` -> `NSE` only because it is the model default; watchlist `name` null -> `symbol`.
Every auto-fix still produces a `REPAIRED` record.

**Quarantine/report, never auto-fix:** missing name, fractional qty, negative balance,
duplicate business key, non-finite number, malformed ID, missing timestamp, unknown enum,
any non-NSE exchange value, oversized/partial order inconsistency, a `REJECTED` or
`CANCELLED` order with `filled = qty`, a duplicate watchlist `(user, symbol)` pair, an
unmappable provider ticker, and a quote timestamp that is missing, malformed, implausibly
old, or more than 5 minutes in the future (§7.5).

**Never silently drop a row** to make a constraint pass. An `EXCLUDED` row is a reviewed
decision with a recorded count and sum, not a deletion.

### 8.12 Constraint rollout

**Phase A — enable at schema creation (safe on local evidence):**

- ID format, FKs, unique business keys;
- `qty > 0`, `filled >= 0 AND filled <= qty`;
- `avg_price`, `entry`, `ltp`, `prev_close`, `volume`, `market_cap` non-negative;
- side/type/product/status/kind/transaction-kind/transaction-status enums;
- `exchange = 'NSE'` on all four book tables;
- `symbol <> ''`, non-null names.

**Phase B — after production profile/cleanup:**

- `funds.available >= 0`;
- `watchlists.name <> ''`;
- `groupId` format (24-hex or UUID4);
- any `name <> ''` tightening;
- transaction amount sign/kind consistency.

**Phase C — future projects:**

- `order_fills`, `order_groups`, `quote_history`, transaction-to-order link, double-entry
  ledger, idempotency keys.

Adding a `CHECK`/`NOT NULL` later should use a validation scan (and `NOT VALID` +
`VALIDATE CONSTRAINT` if the table is large). At the observed scale, a direct migration is
fine.

---

## 9. Migration mapping and cutover

### 9.1 Strategy

**Offline, one-way, single source of truth.**

1. Before cutover, MongoDB is authoritative; PostgreSQL is a copy.
2. The migration reads MongoDB read-only and writes PostgreSQL.
3. The application is stopped (or writes frozen) for the final export/load.
4. PostgreSQL becomes the sole writer at cutover.
5. MongoDB remains read-only for audit/rollback until acceptance and retention expiry.

**No dual writes.** Dual writes create two sources of truth, require conflict resolution,
and make rollback ambiguous. If near-zero downtime becomes a requirement, design CDC/outbox
separately; do not bolt it onto this cutover.

### 9.2 Sole-writer rules

| Phase | Mongo writes | Postgres writes | Scheduler |
|---|---|---|---|
| Before cutover | Authoritative | Migration only (read-only app) | Mongo jobs only |
| Cutover window | Frozen | Migration/validation | Stopped |
| After cutover | None (read-only) | Authoritative | Postgres jobs only, one owner |
| Rollback before PG writes | Resume | Stop | Mongo owner |
| Rollback after PG writes | Restore backup + accept loss | Stop | Mongo owner |

- Stop the legacy Express server and the FastAPI Mongo app; neither may write during the
  load.
- Stop `market_sync`, `price_sync`, and `portfolio_snapshot` so no background write races
  the export.
- Start exactly one FastAPI instance after the switch, run smoke tests, then enable
  exactly one scheduler owner.
- The parity harness may read both databases; production writes have one owner.

### 9.3 Load order

Foreign-key order:

1. `users`
2. `funds`
3. `holdings`
4. `positions`
5. `orders`
6. `transactions`
7. `watchlists`
8. `instruments`
9. `latest_quotes`
10. `portfolio_snapshots`

`instruments`/`latest_quotes` are independent of the user tables and can be loaded in
parallel, but `latest_quotes` must follow `instruments`. Holdings/positions/watchlists do
not FK to instruments, so their load order is flexible; the quote tables are needed before
API verification.

`migration.quarantine` is not an application table and is not part of the FK order. The
loader writes it as it encounters skipped rows; a quarantined parent causes dependent rows
to be quarantined before their load step. The loader never loads a quarantined row into a
`public` table.

### 9.4 Field mapping

| MongoDB | PostgreSQL | Rule |
|---|---|---|
| `_id` | `id` | Lowercase 24-hex; fail/quarantine otherwise |
| `user` | `user_id` | Same conversion; verify the user exists |
| `createdAt` | `created_at` | BSON Date -> `timestamptz(3)`; preserve ms |
| `updatedAt` | `updated_at` | Same; missing -> quarantine (do not substitute migration time), except a quote handled by the §7.5 `untrusted_timestamp` fallback, which is display-only and cannot fill |
| `__v` | `version` | Preserve; missing -> 0 with a report |
| camelCase fields | snake_case columns | Explicit mapping; API serializers stay camelCase |
| BSON int32/int64/double | chosen numeric type | Record source type; reject non-finite; cash → 2 dp, price → 4 dp, average → 6 dp, percentage → 6 dp |
| `date` (snapshots) | `snapshot_date date` | `(ts AT TIME ZONE 'Asia/Kolkata')::date` |
| (provider time) | `latest_quotes.source_time` | Always `NULL` for migrated rows; do not infer from `updatedAt` |
| missing field | NULL/default | Per-column rule; report; no blanket default |

**Per-collection mapping:**

| Source | Target | Special rules |
|---|---|---|
| `users` | `users` | `password` -> `password_hash`; unique email/username; no password export in reports |
| `funds` | `funds` | `available` -> numeric; ignore `collateral`/`usedMargin`; report |
| `holdings` | `holdings` | Drop `ltp`/`dayChangePct`/`sector`; map them to instruments/quotes when needed |
| `positions` | `positions` | Drop `ltp`; map to quote |
| `orders` | `orders` | Preserve `price`, `triggerPrice`, `slTrigger`, `tpPrice`, `groupId`, `isExit`, `status`; no requested-price backfill; a `REJECTED`/`CANCELLED` row with `filled=qty` is quarantined |
| `transactions` | `transactions` | Preserve signed amount at 2 dp; no order link |
| `watchlists` | `watchlists` | Drop `ltp`/`dayChangePct`; null name -> symbol; enforce `(user, symbol)` uniqueness |
| `marketquotes` | `instruments` + `latest_quotes` | Preserve `_id` on instrument; split identity/quote; `in_market_universe=true`; `source_time=NULL` |
| `portfoliosnapshots` | `portfolio_snapshots` | Date conversion; missing mis fields -> 0 |
| book-only symbols | synthetic instruments/quotes | New 24-hex ID; `in_market_universe=false`; freshest cached LTP |

### 9.5 Special cases

**Cached book prices.** Do not make `marketquotes` the automatic winner. Compare the
trustworthy `updatedAt` values of the marketquote and every book row with a usable LTP
(finite and greater than zero), as defined in §7.5. A newer row whose LTP is zero is not a
price source. Take `ltp`/`dayChangePct` from the freshest trustworthy source; if a newer
book row wins, mark the quote `mixed_freshness` and keep the marketquote's `day_change`,
`prev_close`, `volume`, and `market_cap`. Set `updated_at` to the winning timestamp and
`source_time` to `NULL`. Report every difference and the chosen source. For a symbol without
a marketquote,
create a synthetic instrument/quote from the freshest book row. This preserves a book-only
holding's displayed price without pretending an older marketquote is fresher.

**Non-NSE rows.** Quarantine every `holdings`, `positions`, `orders`, or `watchlists` row
whose `exchange` is not exactly `"NSE"`; do not load it and do not relabel it. A book row
that depends on a quarantined order/user is quarantined too. `marketquotes` has no exchange
field; `^BSESN` remains an index instrument. This is a cutover gate, not a warning.

**Watchlist duplicates.** The target key is `(user, symbol)`, not
`(user, symbol, exchange)`. Group source watchlists by `(user, symbol)`; if a group has more
than one row, keep the earliest by `created_at` (tie: lowest `id`) and quarantine the rest
for review. Do not silently delete the later rows; if the reviewer wants a different
winner, accept the decision explicitly. A production dataset with only NSE rows should have
no duplicates, but profile it.

**Rejected/cancelled orders with `filled=qty`.** Quarantine them. The runtime never writes
that state after the fix; a legacy row with it cannot be trusted to have settled. Preserve
the stored values, reconcile any blocked cash/settlement, and require an explicit
accept/exclude decision. Do not reset `filled` to 0 or `qty` without evidence.

**Sector.** `marketquotes.sector` wins for universe symbols. For book-only symbols, use the
holding's sector if non-empty; otherwise `""`. Report conflicts where two holdings for the
same symbol disagree.

**Snapshot date.** Convert every BSON Date to an IST date. Both `18:30Z` and `00:00Z`
fixtures map correctly. Do not use UTC `date()`.

**Watchlist name.** `null`/missing -> `symbol`, with a report row. The route is changed to
the same fallback, so the `NOT NULL` constraint is truthful.

**Orders with `0 < filled < qty` and `OPEN`.** These are a migration gate (R21). Preserve
the row; do not "repair" it to 0 or to `qty`, and do not infer additional fills, refunds,
or settlements. The schema allows partial `filled`, but the runtime is all-or-nothing.
List every such row in the migration report, reconcile its blocked cash and any recorded
settlement, and require an explicit accept/quarantine decision before cutover. An
`EXECUTED` order with `filled != qty` is quarantined and reviewed; do not silently set
`filled=qty`.

**Malformed IDs.** Quarantine; do not generate a replacement ID silently, because the ID is
externally visible (JWT/URL). A production normalization would need a separate mapping and
token migration.

**Legacy funds fields.** Ignore `collateral`/`usedMargin`; they are not in the current
model and no route reads them. Report the row.

**Group IDs.** Preserve exactly. No format check until production profiling confirms the
mixed formats. If a group ID is an ObjectId hex, it still matches the order ID.

### 9.6 Validation and reconciliation

**Data checks:**

- Source/target row counts per collection and per user.
- The accounting identity (row-level): `source_count = active_count +
  open_quarantine_count + excluded_count`; the rule-record total is
  `quarantine_total = open_records + repaired_records + accepted_records +
  excluded_records`.
- Exact `sum`/`min`/`max` for every numeric field after quantization; report
  `source_sum = active_sum + open_quarantine_sum + excluded_sum + repair_delta` for each.
- Distinct counts for every enum-like field; zero non-NSE values in loaded book tables.
- Null/missing counts per column.
- FK coverage: every `user_id` resolves; `latest_quotes.instrument_id` resolves.
- Unique-key duplicates: zero, including `(user, symbol)` watchlists.
- Per-user aggregates: holdings value, invested, funds available, open order count,
  transaction count, snapshot count.
- Checksums of stable ordered projections (`id` + key business fields) before/after.
- Quote reconciliation: every active book symbol has an instrument/quote; the winning
  timestamp/source is recorded; cached-vs-canonical differences and `mixed_freshness` rows
  are listed; migrated `source_time` is `NULL`.
- Quarantine gate: zero `OPEN` rows; every accepted/repaired row has `target_id`,
  reviewer, and a reconciliation note; every excluded row has a reviewer decision and a
  reported sum.

**API checks:**

- Start the Mongo-backed app and the Postgres-backed app against equivalent datasets.
- Compare status, content type, JSON body, and ordering for every endpoint in
  `docs/migration/API_CONTRACTS.md`.
- Include assistant read-only snapshots, not just CRUD.
- Compare 400/401/404/409/500 envelopes and malformed IDs.
- Compare serialization: 24-hex IDs, ISO dates with three decimals, `__v`, missing vs null,
  whole numbers, percentages, Decimal precision.

**Write-flow checks:** every trace in §6.2, including failure injection between writes.

**Concurrency checks:** §6.12, with two real connections.

**Performance checks:** `EXPLAIN (ANALYZE, BUFFERS)` for orders, transactions, holdings,
positions, watchlist, portfolio history, market overview, search. Confirm the orders index
and the OPEN partial index are used.

### 9.7 Rehearsal

- Restore a production-like Mongo dump into a scratch environment.
- Run `alembic upgrade head` on an empty PostgreSQL database.
- Run the loader, validation, and API parity.
- Record counts, sums, and checksums; compare with the previous run.
- Repeat the full reload (truncate target, reload) to prove repeatability. Do not rely on
  upserts that hide duplicate source rows.
- Test the rollback path before the maintenance window.

### 9.8 Cutover runbook

**Before the window:**

1. Freeze code and schema versions; record the application commit and Alembic revision.
2. Take a full MongoDB backup (`mongodump`) and verify a restore into a scratch database.
3. Take a PostgreSQL base backup/snapshot; enable WAL/PITR if available.
4. Run the final rehearsal and sign off the data-quality report, including the quarantine
   counts/sums and every accepted/excluded row.

**Window:**

1. Announce maintenance; stop application writes.
2. Stop/disable all schedulers (market, price, snapshot) and the legacy Express writer.
3. Take the final MongoDB backup.
4. Run the export/load; record counts/checksums and the quarantine report.
5. Run validation gates, including `migration.quarantine` with zero `OPEN` rows; do not
   switch on failure or on an unresolved quarantine.
6. Switch the application database configuration to PostgreSQL.
7. Start one application instance; run smoke tests.
8. Enable exactly one scheduler owner; verify no duplicate jobs.
9. Monitor errors, latency, locks, and invariant checks.

**After:**

- Keep MongoDB read-only for a defined retention period.
- Reconcile the first day's snapshots and order fills against expectations.
- Decommission Mongo only after acceptance and retention expiry.

### 9.9 Rollback

- **Before any PostgreSQL writes:** switch back to MongoDB. It is still authoritative.
- **After PostgreSQL writes begin:** a config switch is not enough; writes exist only in
  PostgreSQL. Choose and document one:
  - restore MongoDB from the pre-cutover backup and accept the loss of writes since the
    freeze;
  - build and test a reverse migration (not in Phase 2).
- Keep the maintenance window short enough that "restore + accept loss" is acceptable.
  The app is a mock trading dashboard; a minutes-long loss window is preferable to an
  untested reverse migration.

### 9.10 Environment and Neon

**Local conventions:**

- `api/.env` holds `DATABASE_URL` and `TEST_DATABASE_URL`; never commit it.
- `api/.env.example` has placeholders, not credentials.
- Use a dedicated local database (e.g. `tradium`) and a separate test database
  (e.g. `tradium_test`).
- Tests run `alembic upgrade head` against the test database; no `create_all`.
- The frontend needs no database env.

**Connection strings:**

```text
# Application (pooled)
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST/DB?sslmode=require

# Migrations and the one-shot loader (direct)
DIRECT_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST/DB?sslmode=require
```

Use placeholders in docs and secret managers in deployment. Never log the DSN or include
the password in an error message.

**Neon considerations:**

- Use the **pooled** connection (Neon `-pooler` host) for the FastAPI app; use the
  **direct** connection for Alembic, the migration loader, and backup/restore.
- PgBouncer transaction pooling supports transaction-scoped advisory locks but **not**
  session-scoped `pg_advisory_lock`. Use `pg_advisory_xact_lock`.
- Avoid session-level `SET` state in the pooled path; set timeouts per transaction/role.
- Disable server-side prepared statements if the pooler is in transaction mode and the
  driver's prepared statements are not supported; use the direct connection for
  migrations.
- Set a small pool (`pool_size` 5-10, `max_overflow` small) and `pool_pre_ping=True`;
  respect Neon's connection limits.
- Set `statement_timeout` (e.g. 10s), `lock_timeout` (e.g. 3s), and
  `idle_in_transaction_session_timeout` so a stuck transaction cannot hold a user lock.
- Neon scale-to-zero can add first-connection latency; keep the pool warm in production.
- TLS is required; keep `sslmode=require` (or stricter) in every environment.

### 9.11 Alembic and schema ownership

- Alembic owns tables, constraints, and indexes. No `Base.metadata.create_all` at app
  startup.
- Use naming conventions for constraints/indexes so revisions are stable.
- `alembic upgrade head` must work on an empty database and on the migrated dump.
- Test `downgrade`/reapply in staging; destructive revisions need explicit review.
- The loader is a separate one-shot tool, not an application route.
- Seed/backfill scripts are retired for production; port only fixture data for tests.

### 9.12 Security

- No credentials in source control, docs, logs, or error bodies.
- Redact `DATABASE_URL`, `MONGO_URL`, and provider keys in logs.
- The migration report contains counts and rule names, not personal record contents.
- The PostgreSQL role used by the app has only the privileges it needs; the migration role
  can create schema objects, the app role cannot.
- Backups are encrypted and access-controlled.
- Rotate credentials after the cutover if they were shared during rehearsal.

---

## 10. Risks, trade-offs, and test acceptance criteria

### 10.1 Risk register

| # | Risk | Impact | Likelihood | Mitigation / gate |
|---|---|---|---|---|
| R1 | Decimal arithmetic changes API numbers/rounding | Medium | High | Exact Decimal tests; documented half-up policy; parity fixtures; assistant formatting tests |
| R2 | Decimal JSON serialization fails or renders strings | High | Medium | Custom `simplejson` response; `parse_float=Decimal` round-trip tests; no Pydantic string default |
| R3 | Production data violates unique/check constraints | High | Medium | Production profile gates; quarantine; Phase A/B constraint rollout |
| R4 | Normalized quotes change a book's displayed LTP | Medium | Medium | Timestamp-based reconciliation; report the winning source; accept documented difference or choose Option A |
| R5 | OCO lock contention/deadlock | Medium | Low | One per-user advisory lock; consistent lock order; bounded retries; concurrency tests |
| R6 | Partial-exit fix changes expected settlement | Medium | Medium | F3 tests; sign-off; explicit remainder behavior |
| R7 | Snapshot `date` range semantics change | Medium | Medium | API tests for 1D/1W/1M/1Y/ALL; document calendar-day rule |
| R8 | Malformed-ID error mapping changes clients | Low | Medium | Contract tests; 404/204 documented; no 500 for bad IDs |
| R9 | Duplicate refund / double credit | High | Low | Conditional status transitions; one transaction; concurrency tests |
| R10 | Two schedulers fill twice | High | Medium | One owner; per-order row lock + conditional transition; idempotent quote/snapshot upserts. A transaction-scoped job lock is not a lease |
| R11 | Rollback after PG writes is a restore | High | Medium | Short window; Mongo backup; rollback drill; accept-loss policy |
| R12 | Neon pooler/session-lock incompatibility | Medium | Medium | Pooled app + direct migrations; transaction-scoped locks; no session state |
| R13 | Case-insensitive `citext` breaks login | High | Low | Keep case-sensitive text; local collision evidence |
| R14 | Fractional quantities in production | High | Low | Migration blocks/quarantines; no rounding |
| R15 | Unknown `groupId`/SL-M formats | Medium | Medium | Defer format check; synthetic tests; production profile |
| R16 | Missing order/fill history limits reporting | Medium | High | Deferred `order_fills`; document gap |
| R17 | `__v` is not optimistic locking | Low | High | Document; do not use it for concurrency |
| R18 | No user-delete route, but FKs use RESTRICT | Low | Low | Revisit only if account deletion is added |
| R19 | Extra joins slow book reads | Low | Low | Unique symbol indexes; 53-row local quote table; EXPLAIN checks |
| R20 | Credentials leak in logs/config | High | Low | Env/secret manager; redaction; no DSN in errors; role separation |
| R21 | Partial `OPEN` orders (`0 < filled < qty`) have no runtime path | Medium | Low | Migration gate; per-row review/quarantine; no inferred fills/refunds; synthetic concurrency tests |
| R22 | A stale or future-dated quote fills an order at a bad price | High | Medium | Fail closed: require `source_time`, bound age/skew, skip the fill; test missing/stale/future timestamps |
| R23 | A rejected order persists as `filled=qty` or with a fill price | High | Medium | Lock, validate, then final conditional transition; rejection never writes `filled`/`price`; fault-injection tests |
| R24 | Quarantined rows vanish from counts or financial totals | High | Medium | `migration.quarantine`; active/quarantine/excluded identity; zero-`OPEN` cutover gate; signed reconciliation |
| R25 | Narrowing watchlist uniqueness to `(user, symbol)` finds legacy duplicates | Medium | Low | Production profile; keep the earliest row, quarantine the rest; concurrent different-exchange test |
| R26 | Legacy non-NSE rows cannot satisfy the new check | Medium | Medium | Profile the distinct exchanges; quarantine, never relabel; resolve zero `OPEN` rows before cutover |

### 10.2 Accepted trade-offs

| Trade-off | Choice | Why |
|---|---|---|
| ID storage | `varchar(24)` over `char(24)`/`bytea`/`uuid` | No blank-padding semantics; compatibility with JWTs, URLs, labels; negligible storage at this scale |
| Money arithmetic | `NUMERIC` over `double` | Exactness; cash 2 dp, prices 4 dp; one-time Decimal/serialization cost |
| Concurrency | Per-user serialization over fine-grained locks | Simpler, deadlock-resistant; adequate throughput here |
| Quotes | Normalized over minimal | One source of truth; accepts extra joins/reconciliation |
| Quote time | Add `source_time` but keep `updated_at` as API `updatedAt`/`asOf` | Provider freshness for execution without changing the wire contract |
| Scheduler | One owner; no job-wide lease in Phase 2 | The transaction-scoped lock cannot provide it; per-row transitions already prevent double fills |
| Cutover | Offline over dual-write/CDC | One source of truth; simpler rollback story |
| Snapshot date | `date` over `timestamptz` | Removes two-convention ambiguity; accepts range-semantics change |
| Fill history | Deferred | No current fill rows; adding it is a feature |
| Order price audit | Preserve overwrite | Avoids a schema/feature change during migration |
| Error mapping | 4xx over generic 500 | Clearer contract; intentional change |
| `__v` | Preserve as-is | Avoids a new optimistic-locking feature |

### 10.3 Test layers

1. **Schema/constraint tests:** IDs, FKs, unique keys (including `(user, symbol)`), checks
   (including `exchange='NSE'`), defaults, timestamp precision, index existence, `NOT NULL`,
   `source_time` nullability.
2. **Repository tests:** every query returns the same rows/order/shape as the current
   PyMongo query, with Decimal values.
3. **Route contract tests:** status, body, content type, error envelope, user isolation,
   malformed IDs, ordering, non-NSE rejection.
4. **Write-flow tests:** every flow in §6.2, including failure injection between writes and
   after the debit; rejected fills assert `filled`/`price` unchanged.
5. **Concurrency tests:** two real connections, row locks, OCO, double cancel/fill/
   square-off, duplicate signup/watchlist (including different exchange), two schedulers.
6. **Migration tests:** fixture Mongo -> PostgreSQL -> counts/sums/checksums; quarantine
   accounting; accepted-row reconciliation; zero-`OPEN` cutover gate; repeatable reload.
7. **Job tests:** market-hours gate, single-flight, provider failure, missing/stale/future
   `source_time`, sector backfill, snapshot idempotency, scheduler ownership.
8. **Numeric/serialization tests:** Decimal exactness, cash 2 dp vs price 4 dp, repeated
   weighted averages, JSON numbers, whole values, percentages, `NaN`/`Infinity`, request
   coercion, provider float conversion.
9. **Performance tests:** EXPLAIN plans and latency for the main reads.
10. **Backup/restore tests:** Mongo dump restore, PostgreSQL backup restore, smoke tests.

### 10.4 Acceptance criteria

#### Schema and migration

- [ ] `alembic upgrade head` applies cleanly to an empty database.
- [ ] Every table, FK, unique key, check, and index in §4 exists.
- [ ] A fresh database rejects duplicate holdings `(user, symbol, exchange)` and watchlist
      `(user, symbol)`, duplicate `(user, IST day)`, invalid IDs, `qty <= 0`, `filled >
      qty`, invalid enums, and any `exchange <> 'NSE'`.
- [ ] The migration preserves every source `_id`/`user` and every row count.
- [ ] No user-scoped row is orphaned; no malformed ID is silently rewritten.
- [ ] Numeric source/target sums match after quantization; cash uses 2 dp, prices 4 dp,
      averages 6 dp; deltas are reported.
- [ ] Duplicate business keys are zero or quarantined with review.
- [ ] The migration report lists every quarantine, auto-fix, and legacy field.
- [ ] `migration.quarantine` exists in a separate schema and the app role cannot read or
      write it.
- [ ] Every source row is accounted for at row level: `source_count = active_count +
      open_quarantine_count + excluded_count`; the rule-record total is reported
      separately; every numeric field satisfies the signed reconciliation identity.
- [ ] No `OPEN` quarantine row remains; every accepted/repaired row has `target_id`,
      reviewer, and a reconciliation note; every excluded row has a reviewer decision.
- [ ] Loaded book tables contain only `exchange='NSE'`; non-NSE rows are quarantined, not
      relabelled.
- [ ] Migrated `latest_quotes.source_time` is `NULL`; no value was inferred from
      `updated_at`.
- [ ] `latest_quotes` uses the freshest trustworthy source timestamp; a newer book cache
      beats an older marketquote only when its LTP is usable (> 0), and mixed-freshness rows
      are reported.
- [ ] A duplicate `(user, symbol)` watchlist pair is resolved (earliest kept, rest
      quarantined), never silently deleted.

#### API and serialization

- [ ] All endpoints in `API_CONTRACTS.md` return the same status/body shape, except the
      documented intentional changes.
- [ ] `_id`, `user`, `createdAt`, `updatedAt`, `__v` keep their wire names/format.
- [ ] Money/percentages are JSON numbers, not strings; integral values have no `.0`.
- [ ] `json.loads(body, parse_float=Decimal)` round-trips stored values exactly.
- [ ] ISO timestamps have exactly three fractional digits.
- [ ] Holdings/positions/watchlists/orders/transactions have deterministic order.
- [ ] Market indices follow unknown-first/`^NSEI`/`^NSEBANK`/`^BSESN`; stocks are
      `symbol ASC`; search is relevance then symbol, limit 10.
- [ ] Search with no matches returns `[]`, not an error or unfiltered rows.
- [ ] Portfolio history serializes zero `invested` as `null`; `1D` includes today plus the
      previous IST day, preserving the configured lookback count.
- [ ] `GET /api/auth/me` with a malformed ID returns 404, not 500.
- [ ] Malformed IDs return the documented 404/204, not 500.
- [ ] Duplicate signup/watchlist races return the documented 4xx.
- [ ] A watchlist add with the same `(user, symbol)` but a different `exchange` returns
      409 and creates at most one row.
- [ ] An order/watchlist request with `exchange` other than exactly `NSE` returns 400; a
      direct SQL insert with another exchange fails the check.
- [ ] `source_time` is not exposed in any API response; `updatedAt`/`asOf` still use
      `latest_quotes.updated_at`.

#### Financial invariants

- [ ] A failure after the debit but before the order insert/MARKET fill rolls back the
      debit and leaves no order (F1). The test injects the failure; it is not satisfied by
      the insufficient-holdings test alone.
- [ ] A CNC SELL never debits cash; the debit predicate (`BUY` or `MIS`) and holdings
      predicate (`SELL` and not `MIS`) are mutually exclusive.
- [ ] A rejected order keeps its pre-fill `filled` (normally 0) and `price`; it has no fill
      price, settlement, or cash credit, and any blocked cash is refunded exactly once.
- [ ] A MARKET fill is atomic with its order insert, debit, and final `EXECUTED`
      transition; the order is inserted `OPEN`/`filled=0` and only becomes `EXECUTED` after
      the fill succeeds.
- [ ] A CNC sell credits proceeds only after the holding decrement succeeds.
- [ ] A cancel refunds only the unfilled blocked cash, exactly once.
- [ ] Cancel vs fill yields exactly one terminal state and at most one refund.
- [ ] Two OCO legs yield exactly one `EXECUTED` and one `CANCELLED`; one settlement.
- [ ] A 40-of-100 MIS exit leaves 60 shares and credits only 40 shares' P&L (F3).
- [ ] A 120-of-100 MIS exit is `REJECTED`; position unchanged; no credit; `filled`/`price`
      unchanged.
- [ ] A full MIS exit deletes the position and credits entry + P&L.
- [ ] Square-off pays exactly once; a second attempt cannot double-credit.
- [ ] Square-off with no live or canonical quote returns 400 without touching the
      position; a second square-off returns 404; a losing race moves no cash.
- [ ] A missing, stale, or future-dated `source_time` skips a limit/stop fill and leaves
      the order `OPEN`; it does not mark the order `REJECTED` or move cash.
- [ ] Cash values are stored at 2 dp and prices at 4 dp; a 4-dp price is not pre-rounded to
      cash before `qty × price`.
- [ ] Deposit/withdrawal and ledger insert roll back together on failure.
- [ ] Guarded paths never produce negative `available` in concurrency tests.
- [ ] Snapshot upsert is idempotent per `(user, IST day)`.

#### Jobs and assistant

- [ ] Price sync preserves stored quotes on provider failure and does not fill duplicates.
- [ ] A quote without a valid `source_time`, older than the age bound, or future-dated
      cannot fill an order; the order stays `OPEN` and the tick is logged.
- [ ] Market sync preserves `sector` on quote upsert and does not let sector backfill
      change `asOf`; `asOf` equals the freshest `latest_quotes.updated_at` in the
      universe, not the freshest `source_time`.
- [ ] One scheduler owner. A second price-sync process can run, but the row lock and
      conditional transition ensure each order fills at most once; a transaction-scoped
      job lock is not claimed to prevent a second process from starting.
- [ ] Two concurrent market-sync workers produce one instrument/quote row per symbol.
- [ ] Snapshot date conversion handles both `18:30Z` and `00:00Z`.
- [ ] Nova's watchlist tool returns a seeded row and an empty list correctly (F4).
- [ ] Assistant tools use the same ordering as their pages.

#### Operations and security

- [ ] A Mongo dump restores into a scratch database and passes checksums.
- [ ] A PostgreSQL backup restores and passes smoke tests.
- [ ] The cutover runbook is rehearsed end-to-end.
- [ ] Rollback before/after writes is documented and tested to the agreed point.
- [ ] No credentials/DSNs/personal records appear in source, logs, or the migration report.
- [ ] The app role cannot create schema objects; Alembic owns them.
- [ ] Neon pooled/direct connection strings are used for the correct purposes.

### 10.5 Definition of done for Phase 2

Phase 2 is done when:

1. This design is reviewed and the intentional changes (F1-F13) are accepted or amended.
2. The production data profile is complete and every constraint has a pass/quarantine
   decision; `migration.quarantine` has zero `OPEN` rows.
3. The schema, migrations, loader, and test plan are approved for Phase 3.
4. No application code or schema has been changed by the design phase itself.

**Stop point:** this document is the deliverable. Do not start SQLAlchemy models, Alembic
revisions, route rewrites, or the migration loader until the design is reviewed.

---

*End of Phase 2 schema design.*
