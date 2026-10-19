# Migration Plan: Express → FastAPI

**Target:** replace the Express backend with FastAPI while keeping the React frontend and MongoDB
unchanged. The Express implementation stays in the repository as reference until the replacement is
validated.

Every phase has a **gate**. A phase is complete only when its acceptance criteria have actually been
executed and recorded in [MIGRATION_STATUS.md](./MIGRATION_STATUS.md). A phase is **not** complete
because files exist, the app starts, or endpoints return 200 once.

---

## Phase overview

| Phase | Goal | Explicitly out of scope |
|---|---|---|
| 0 | Isolated repo + planning docs | Any application code |
| 1 | Core API: auth, data access, ordinary routes | Market data, Nova, deployment |
| 2 | Market data: historical, quotes, jobs | Nova, deployment |
| 3a | CORS and frontend cutover | Nova, production deployment |
| 3 | Nova AI | Deployment |
| 4 | Integration, regression, deployment | Relational DB |
| 5 | Optional relational DB | — |

Each phase requires **explicit user approval** before it begins. Approval for one phase does not carry
into the next.

---

## Phase 0 — Repository isolation and planning

### Prerequisites

- Original repository clean, HEAD recorded, remote recorded.
- No uncommitted work that could be lost.

### Deliverables

- A new sibling repository with a fresh history (`main` = original snapshot).
- Branch `migration/fastapi-backend`.
- Documents: `CLAUDE.md`, `MIGRATION_PLAN.md`, `CURRENT_ARCHITECTURE.md`, `API_CONTRACTS.md`,
  `ARCHITECTURE_DECISIONS.md`, `TEST_PLAN.md`, `AI_INTEGRATION_PLAN.md`, `MARKET_DATA_PLAN.md`,
  `MIGRATION_STATUS.md`.
- Secret scan of the snapshot.
- Private GitHub repository `tradium-fastapi`, if credentials allow.

### Acceptance criteria

1. The original repository is byte-for-byte untouched (same HEAD, same branch, same clean status).
2. The new repository has no commit or remote from the original history, and no remote pointing at
   the original.
3. No real `.env`, API key, JWT secret, or database URL is present in the new repository.
4. Every migrated document exists and contains verified specifics, not placeholders.
5. The new repository exists on GitHub as **private** (or the blocker is documented with exact manual
   steps).

### Rollback

Delete the new directory and the new GitHub repository. The original is unaffected by design.

---

## Phase 1 — Core Express → FastAPI

### Goal

A FastAPI application that serves every endpoint that does **not** require live external market data
or AI, with byte-level response parity on those endpoints.

### Prerequisites

- Phase 0 approved.
- Python version recorded and pinned.
- An isolated MongoDB: a local instance or a copy of the schema with demo data. **Never the production
  database.**

### In scope

| Area | Work |
|---|---|
| Config | Settings object for `MONGO_URL`, `PORT`, `JWT_SECRET`, `GOOGLE_GENERATIVE_AI_API_KEY`, `NODE_ENV` equivalents. Names unchanged. |
| Mongo access | PyMongo/Motor client + collection handles matching Mongoose collection names. |
| Serialization | ObjectId → hex string, datetimes → ISO-8601 UTC, preserve `_id`, `__v`, `createdAt`, `updatedAt`. |
| Auth | Signup, login, logout, `/me`; bcrypt verification of existing hashes; JWT cookie identical to current. |
| Security | Same cookie flags; rate limit on signup/login (20/15 min/IP); CORS equivalent. |
| Validation | Pydantic models that reproduce the **current** validation order and messages. |
| Error handling | `{ message }` envelope, 400/401/404/409/503 mapping, `ValidationError` → 400. |
| Read routes | holdings, positions, orders, watchlist, funds, transactions, portfolio history, market overview, instrument search. |
| Safe CRUD | watchlist add/delete, deposit/withdrawal, order **creation without MARKET**, order cancel, exits, square-off — only once their quote dependency is handled. |
| Static serving | Production mode serves `dist/` with SPA fallback. |

### Out of scope until Phase 2

- `GET /api/instruments/lookup/:symbol`, `GET /api/instruments/:symbol`, candles.
- `MARKET` order placement (needs a quote).
- Square-off's live-quote enhancement (the stored-`ltp` fallback can be implemented, but the live path
  waits).
- Price sync, market sync.
- Nova.

If a route is mounted but its dependency is pending, it must return a deliberate, documented error —
not a fake success and not a silent empty list.

### Recommended build order

1. App skeleton + settings + health + error handlers.
2. Mongo access + serialization + a single read route (`GET /api/holdings`) + parity test.
3. Auth (signup/login/logout/me) + cookie behaviour + rate limit.
4. Remaining read routes.
5. Funds transactions (the simplest money path) + concurrency test.
6. Watchlist CRUD.
7. Orders: creation validation, funds debit, cancel — with MARKET gated.
8. Exits and square-off.

### Acceptance criteria

1. For every in-scope endpoint, the OpenAPI schema and the observed response **field set** match the
   Express responses on the same seeded database. Compare keys and types, not just status codes.
2. `Set-Cookie` attributes match: name, `HttpOnly`, `SameSite`, `Path`, `Max-Age`, and `Secure` under
   the production setting.
3. The React app runs against FastAPI **without code changes**, for the pages that only use
   in-scope endpoints. Screens that need quotes may show their loading/error states.
4. Concurrency tests pass: parallel withdrawals cannot overdraw; parallel order placements cannot
   overdraw; parallel cancel/fill cannot double-refund.
5. Per-user isolation: user A cannot read, modify, cancel, or square off user B's documents.
6. Error bodies and status codes match the contract table for every documented failure.

### Rollback

Set the frontend back to the Express base URL (or run Express locally). No data changed by Phase 1 is
schema-incompatible, so Express continues to work against the same database.

---

## Phase 2 — Market data

### Goal

Restore every market-data-dependent behaviour using Python: quotes, candles, price sync, market
overview refresh, and order matching.

### Prerequisites

- Phase 1 accepted.
- The provider experiments in [MARKET_DATA_PLAN.md](./MARKET_DATA_PLAN.md) have been run and recorded.
- Only **one** process owns the schedules.

### In scope

- Provider adapter (interface + one implementation).
- Historical candles for all eight ranges and their intervals.
- Single-symbol quote for instrument detail, lookup, MARKET fills and square-off.
- Price sync job: symbol collection, sequential fetch, LTP writes, sector backfill, order matching,
  billing.
- Market sync job: 53-symbol batch refresh, bulk upsert, sector backfill, market-hours gate.
- Daily portfolio snapshot.
- Startup behaviour equivalent to today (immediate first run).

### Acceptance criteria

1. Every endpoint that consumed Yahoo now consumes the adapter and returns the same **shape**.
2. Candle timestamps carry the same IST shift and the same filtering of empty bars.
3. A MARKET order fills at a live quote; when the provider fails, it returns 503 with the same message
   shape.
4. Price sync matches bracket exits exactly: SL/SL-M trigger crossing, LIMIT crossing, one leg fires
   and the sibling is cancelled, MIS exits settle, CNC fills hit holdings.
5. An `SL-M` order does not double-fill when two matching cycles overlap (claim test).
6. The jobs do not run when the market is closed, and the market overview cache is not overwritten
   outside hours.
7. The snapshot job writes one row per user per IST day and is idempotent when re-run.
8. Provider outage behaviour is defined and recorded: what the UI shows, what the logs say, and
   whether the job retries.

### Rollback

Stop the FastAPI scheduler; the Express implementation (if still deployed) resumes ownership. Do not
run both schedulers at once, even briefly.

---

## Phase 3a — CORS and frontend cutover (interim)

### Goal

Point this repository's React app at FastAPI while keeping the original MERN repository untouched.

### In scope

- Credentialed CORS for the Vite origins (5173-5177) plus a `CORS_ORIGINS` override.
- Development `BASE_URL` on FastAPI's port; `VITE_API_URL` and same-origin production behaviour kept.
- The signup caller fixed to send one object with `username`, `email`, `password`.

### Acceptance criteria

1. A credentialed preflight from `http://localhost:5173` succeeds.
2. Signup, login, session restoration and logout work through the UI against FastAPI.
3. The dashboard pages load without CORS errors; deferred Nova cards degrade visibly, not fatally.

Result: **all three met**; see [MIGRATION_STATUS.md](./MIGRATION_STATUS.md) §3L. Production static
serving remains in Phase 4, or the frontend can be deployed separately with its origin in
`CORS_ORIGINS`.

---

## Phase 3 — Nova AI

### Goal

Server-side AI parity: chat with six tools and a five-step limit, page insight, dashboard briefing.

### Prerequisites

- Phase 2 accepted.
- The PydanticAI spike from AD-3 has passed: `VercelAIAdapter` streams to the installed
  `@ai-sdk/react` version.
- Model identifier availability through the Python Gemini SDK confirmed.

### In scope

- PydanticAI agent with the existing system prompt and six tools, all user-scoped from the request.
- `POST /api/assistant/chat` returning a Vercel UI Message Stream.
- `POST /api/assistant/insight` and `/briefing` returning plain-text streams.
- Rate-limit/quota behaviour documented (what happens at 429 from the provider; whether retries exist).

### Acceptance criteria

1. The unmodified chat panel renders text and tool cards for a real multi-tool question.
2. Tool calls are bounded at five steps, demonstrated in a test with a prompt that would otherwise
   loop.
3. A user cannot see another user's data through any tool.
4. Insight and briefing stream into the existing `PageInsight` untouched.
5. Provider errors surface as a documented client-visible state, not a hung stream.

### Rollback

Point the assistant routes back at the Express implementation, or keep Express deployed for AI only
during verification.

---

## Phase 4 — Integration, regression, deployment

### Goal

Prove the whole system, then deploy on a **separate** service.

**Progress (Phase 4a):** the frontend build and production static serving are done and verified locally,
and [DEPLOYMENT.md](./DEPLOYMENT.md) records the required environment, scheduler ownership and rollback
plan. The deployment itself (a new service, HTTPS, scheduler switchover) is **not** done and still needs
explicit approval.

### Prerequisites

- Phases 1–3 accepted.
- A rollback target exists and is known to work.
- Explicit approval to touch deployment.

### In scope

- Full regression pass per [TEST_PLAN.md](./TEST_PLAN.md).
- Frontend build and production static serving.
- Environment variable parity.
- A new Render service (only when approved separately).
- Runbook: start command, health check, scheduler ownership, log locations.

### Acceptance criteria

1. Every workflow in the test plan has an executed result.
2. Production build serves the SPA and the API from one origin, as today.
3. The old deployment remains available for rollback until the new one is verified.
4. No production MongoDB data was mutated during testing.
5. `MIGRATION_STATUS.md` records what was actually run.

**Do not delete or repoint the existing Render service in this phase without a separate, explicit
instruction.**

---

## Phase 5 — Optional relational database

**Not part of this migration.** Evaluate only after Phase 4 is stable. PostgreSQL for a durable
deployment; SQLite for a separate local learning exercise. A relational schema must preserve the
funds/orders invariants and the atomic operations they rely on.

---

## Cross-phase rules

1. **One owner of scheduled jobs.** Never run Express and FastAPI schedulers simultaneously against
   the same database.
2. **No production data in tests.** Use an isolated database.
3. **No parity claim without a comparison.** "It returns 200" is not parity.
4. **The frontend is frozen.** Any frontend change needed to make Python work is a red flag; document
   it and get approval.
5. **Record reality.** Every phase ends by updating `MIGRATION_STATUS.md` with commands actually run
   and results actually observed.
