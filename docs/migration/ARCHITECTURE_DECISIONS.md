# Architecture Decisions

Format: each decision records the **approved direction**, the **reason**, and a **validation flag**
showing what is still unproven. A decision marked `APPROVED — NOT VALIDATED` is directionally settled
but must pass an explicit test before any work builds on it.

**Status legend**

| Flag | Meaning |
|---|---|
| `APPROVED` | Direction settled; no further validation needed to proceed |
| `APPROVED — NOT VALIDATED` | Direction settled; a specific test must pass before dependent work |
| `OPEN` | Not decided; must be resolved before the dependent phase |

---

## AD-1 — Replace Express with FastAPI incrementally

**Decision:** Port the backend from Express to FastAPI. Do **not** try to run Express and FastAPI in
parallel against production traffic during the migration. Keep the Express implementation in this
repository as a read-only reference and temporary rollback target until the FastAPI implementation is
validated.

**Why:** The purpose is to demonstrate Python/FastAPI ability on a real codebase, and FastAPI gives
typed request/response models (Pydantic v2) plus generated OpenAPI docs. A parallel run would require
duplicating scheduled jobs and money-moving writes, which risks double fills and double debits.

**Scope boundary:** The frontend is preserved unchanged. Its API calls, field names and stream
protocols are the contract (see [API_CONTRACTS.md](./API_CONTRACTS.md)).

**Status:** `APPROVED`

**Consequences:**

- `server/` (Express) stays in the tree after the FastAPI app exists. It is reference material, not a
  runtime.
- Only one process may own the cron jobs. During Phase 2 there must never be an Express process and a
  FastAPI process both running price sync against the same database.

---

## AD-2 — Preserve MongoDB; do not change the database in the initial migration

**Decision:** Use MongoDB with PyMongo (or Motor if async is chosen) for the FastAPI implementation.
Keep collection names, field names and document shapes identical.

**Why:** The frontend, the existing data, and the trading invariants are all tied to these documents.
Changing the database and the web framework at once makes regressions impossible to attribute.

**Status:** `APPROVED`

**Consequences:**

- Collection names are fixed by Mongoose: `holdings`, `positions`, `orders`, `funds`, `watchlists`,
  `transactions`, `marketquotes`, `portfoliosnapshots`, `users`. Note `watchlists` is **not**
  `watchlist`. Confirm the actual names against the live database before relying on them — Mongoose
  pluralises model names, and this is inferred, not observed.
- ObjectId handling must stay in the same JSON form (`_id` as a 24-char hex string).
- `__v` and the timestamps must still be emitted. If they are not written by Python, existing
  documents and new documents will differ; the React code tolerates missing fields but the parity
  tests should not.

**Validation flag:** `APPROVED — NOT VALIDATED` for collection-name confirmation against a live
database. Never inspect the production database to confirm this in Phase 0; do it against an isolated
copy during Phase 1.

---

## AD-3 — AI: PydanticAI + Google Gemini Python SDK for Nova

**Decision:** Replace the Vercel AI SDK server-side integration with PydanticAI using the Google
Gemini Python SDK. Evaluate PydanticAI's `VercelAIAdapter` against the **exact** React AI SDK version
installed in this repository (`@ai-sdk/react ^4.0.61`), because the adapter's job is to speak the
frontend's UI Message Stream protocol.

**Preserve exactly:**

- The system prompt text and behaviour (`You are Nova…` in `assistantController.js`).
- All six tools and their semantics: `getPortfolioSummary`, `getHoldings`, `getPositions`,
  `getWatchlist`, `getFunds`, `getOrders`.
- Per-user scoping — every tool reads the authenticated user's id from the request, never from a
  client-supplied argument.
- The five-step agent/tool limit (`stopWhen: stepCountIs(5)`), or a documented, verified equivalent.
  If PydanticAI expresses this as a max-step/iteration setting, record the exact setting and test that
  the observable limit matches.
- The chat endpoint path `/api/assistant/chat`, cookie auth, and the streaming content type.

**Do not migrate Nova in Phase 0.** The plan is written, not implemented.

**Status:** `APPROVED — NOT VALIDATED`

**Validation required before Phase 3 begins:**

1. Confirm `VercelAIAdapter` exists in the installed PydanticAI version and read its protocol
   documentation.
2. Produce a minimal spike that streams one message to the **installed** `useChat` client and renders
   text plus one tool call correctly.
3. Confirm multi-step tool calling can be capped at five.
4. Confirm the model identifier used by the Python SDK resolves to the same Gemini model.

**Provider/model note:** the current model ID is `gemini-3.5-flash-lite`, declared only in
`server/config/ai.js`. Keep that identifier until its availability through the Python SDK is verified.
Do not substitute a different model name and present it as equivalent.

---

## AD-4 — Page insights and dashboard briefing stay protocol-compatible

**Decision:** `/api/assistant/insight` and `/api/assistant/briefing` must continue to serve a plain
text stream consumable by `useCompletion({ streamProtocol: "text" })`.

**Why:** These are separate from chat and use a different client hook. Upgrading them to the UI
Message Stream protocol would require frontend changes, which are out of scope.

**Status:** `APPROVED`

**Validation flag:** `APPROVED — NOT VALIDATED` until a Python streaming response is consumed
correctly by the existing `PageInsight.jsx` without modification.

---

## AD-5 — Market data: `yfinance` for historical data, WebSocket tested separately

**Decision:**

1. Use the Python `yfinance` package for historical candles first, subject to compatibility tests
   against the current `yahoo-finance2` output (intervals, ranges, missing bars, timestamps).
2. Test `yfinance.AsyncWebSocket` **separately** for Indian symbols. Historical working does not
   imply streaming works.
3. Keep the provider behind an adapter interface so it can be replaced without touching routes,
   trading logic, or jobs.
4. Evaluate Upstox only after documenting access requirements, limitations, and approvals. Do not
   assume an account exists or that access is free.
5. Keep scheduled jobs for the daily snapshot and for reconciliation.
6. Treat live price updates as **two separate concerns**: (a) provider → backend ingestion,
   (b) backend → frontend delivery. They may be solved independently.

**Status:** `APPROVED — NOT VALIDATED`

**Hard rule:** Do not state that Yahoo live streaming works for Indian symbols until it has been
tested and the results recorded in [MARKET_DATA_PLAN.md](./MARKET_DATA_PLAN.md) and
[MIGRATION_STATUS.md](./MIGRATION_STATUS.md).

---

## AD-6 — Relational database is a later, separate decision

**Decision:** No MongoDB → SQLite/PostgreSQL migration during the initial FastAPI port. Evaluate a
relational model only after the FastAPI backend is stable and equivalent.

**When it is evaluated:**

- **PostgreSQL** is the candidate for a durable deployed application (constraints, transactions,
  concurrent balance updates).
- **SQLite** is a candidate for a separate local learning exercise, not the deployed application.

**Why:** Swapping the database and the framework simultaneously doubles the failure surface. The
funds/orders invariants are exactly where a botched schema change does lasting damage.

**Status:** `APPROVED` (as a deferral)

---

## AD-7 — Authentication stays cookie-based JWT

**Decision:** Preserve the `token` httpOnly cookie, same attributes, HS256, `{ id }` payload, 7-day
expiry. Do not introduce bearer tokens, sessions in Redis, or an external identity provider during the
migration.

**Why:** `AuthContext`, `ProtectedRoute`, and every `fetch`/`axios` call already rely on
`credentials: "include"`. Cookies are also the safer choice against token exfiltration via XSS.

**Status:** `APPROVED`

**Notes for the implementer:**

- Python equivalents: `python-jose` or `PyJWT` for signing, `bcrypt` (or `passlib[bcrypt]`) for
  hashing. The stored hashes are bcrypt cost 10 and must remain verifiable — do not rehash on read.
- Cookie `secure` must key off the deployment environment, not a hardcoded `True`, or local HTTP
  development breaks.
- `SameSite=Strict` works because the frontend and API share an origin in production.

---

## AD-8 — Preserve the money semantics exactly

**Decision:** `Funds.available` means **free cash**, not equity. Cash is blocked at order placement
and released on cancel, rejection, or settlement. `usedMargin` stays derived, never stored.

**Why:** Every screen and the Nova tools read these numbers. A subtly different definition silently
changes every displayed balance.

**Status:** `APPROVED`

**Validation requirement:** the concurrency tests in [TEST_PLAN.md](./TEST_PLAN.md) must pass; the
guarded updates must be ported as atomic operations (`find_one_and_update` with the guard in the
filter), not as read-then-write Python.

---

## AD-9 — Preserve the odd behaviours unless separately approved

**Decision:** Latent bugs and inconsistencies listed in
[CURRENT_ARCHITECTURE.md](./CURRENT_ARCHITECTURE.md) §9 are **documented, not fixed** in the initial
port. Each fix is a separate, explicitly approved change.

**Why:** A migration that also changes behaviour cannot be verified against the original. Bugs are
cheap to fix once parity is proven.

**Status:** `APPROVED`

**Exception:** a bug that causes data corruption or a security hole may be fixed during the port, but
it must be listed in [MIGRATION_STATUS.md](./MIGRATION_STATUS.md) with a rationale and approved before
being merged.

---

## AD-10 — Documentation lives with the code and is updated as work proceeds

**Decision:** The migration documents are the handoff mechanism. Every session updates
`MIGRATION_STATUS.md` (phase, what changed, what was run) and `ARCHITECTURE_DECISIONS.md` (new
decisions or invalidated assumptions) before it ends.

**Why:** Multiple fresh Claude Code sessions will work on this repository with no conversation
history. The docs are the only memory.

**Status:** `APPROVED`

---

## Unresolved questions

| # | Question | Blocks |
|---|---|---|
| 1 | Exact collection names as they exist in MongoDB | Phase 1 data layer |
| 2 | Does PydanticAI's `VercelAIAdapter` exist in the target version and match `@ai-sdk/react` 4.0.61? | Phase 3 |
| 3 | Does Yahoo's WebSocket feed deliver messages for `.NS` symbols, and at what rate/stability? | Phase 2 live prices |
| 4 | Which candle intervals and ranges does `yfinance` return identically to `yahoo-finance2`? | Phase 2 candles |
| 5 | Are Yahoo's terms acceptable for this display/deployment? | Phase 2 / deployment |
| 6 | If streaming fails, which fallback is approved and what account requirements does it have? | Phase 2 |
| 7 | How are Render build/start commands currently configured? | Deployment parity |
| 8 | Should the FastAPI service be a second Render service, or a replacement on the existing one? | Phase 4 (must not be done in Phase 0) |
