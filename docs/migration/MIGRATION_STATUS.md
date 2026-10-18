# Migration Status

**Last updated:** 2026-10-18 (Phase 1c)
**Current phase:** **Phase 1c — local development database + `GET /api/positions` and `GET /api/funds`**
**Application code modified:** **Yes.** New files under `api/` only; the snapshot, `server/`, `src/`,
and the original repository are untouched.
**Phase 0 docs commit:** `629af4d Phase 0: migration docs and repository guidance`
(`migration/fastapi-backend`, local only — not pushed; see §6.1)

---

## 1. Current state at a glance

| Item | Value |
|---|---|
| Phase | 1c — local dev database and the positions/funds reads |
| FastAPI application | **started** — health, holdings, orders, watchlist, positions, funds |
| Express backend | unchanged, retained in-tree as reference |
| Frontend | unchanged |
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
| Tests executed | **35 passed, 3 skipped** (default); **38 passed** with `TEST_MONGO_URL` — see §5 |

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

Not ported: `GET /api/funds/transactions` (the other funds read), all write routes, jobs, market
data, and Nova.

---

## 4. Known issues recorded (not fixed)

These were found during the audit and are documented in `CURRENT_ARCHITECTURE.md` §9. None has been
changed.

1. Nova `getOrders` returns `quantity` where the schema field is `qty`.
2. Nova `getOrders` filters lowercase statuses while stored values are uppercase.
3. Nova `getFunds` reads a non-existent `used` field.
4. `POST /api/orders` debits funds before the CNC holdings check and does not refund on rejection.
5. Price sync runs every minute; project documentation says every 5 minutes.
6. `npm start` uses `node`, not nodemon, contrary to project documentation.
7. `DELETE /api/watchlist/:id` returns 204 even when nothing matched.
8. Market-hours logic has no exchange holiday calendar.

Decision: reproduce current behaviour during the port; fix separately with approval (AD-9).

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
| Application tests | **run:** 35 passed, 3 skipped; 38 passed with `TEST_MONGO_URL` |
| Local `mongod` reachability | **verified** — admin `ping` ok on `127.0.0.1:27017` |
| Effective dev database name | **verified** — `tradium_fastapi_dev`, from a normal `create_app()` startup |
| `zerodha` database | untouched — same 9 collections, no writes |
| Lint / build in the new repo | **not applicable** — no frontend dependencies installed |
| Repository root / branch / remotes before writing | verified: `Tradium-FastAPI`, `migration/fastapi-backend`, **no remote** |
| Scratch database after the integration run | absent from `list_database_names()`; `zerodha` untouched |
| Express reference harness | **not run** — `server/index.js` starts cron jobs on connect |

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
3. Whether Yahoo streaming delivers messages for exact `.NS` symbols.
4. Which candle intervals/ranges `yfinance` returns identically.
5. Whether Yahoo data is permitted for the intended display and deployment.
6. The approved fallback if streaming fails.
7. Current Render build/start configuration (not in the repository).
8. Whether the FastAPI service replaces the existing Render service or is added alongside it.

---

## 8. Explicitly not approved / not done

- No route beyond the six read endpoints: `GET /api/health`, `GET /api/holdings`, `GET /api/orders`,
  `GET /api/watchlist`, `GET /api/positions`, `GET /api/funds`.
- No write or execution route (no POST/DELETE orders or watchlist, no `POST /api/funds/transactions`),
  no `GET /api/funds/transactions`, history, instruments, or market-data route.
- No write to the `zerodha` database and no production data copied into `tradium_fastapi_dev`.
- No scheduled or background job of any kind; no Yahoo Finance call.
- No Nova / Gemini / PydanticAI work.
- No frontend change and no frontend-to-FastAPI connection.
- No change to `server/`, `src/`, or any other original application file.
- No database migration, schema change, or write to the application database.
- No Render service created, modified, or deployed.
- No change to the original repository's history, branch, remotes, or working tree.
- No merge of `migration/fastapi-backend` into `main`.
- No secret rotation, and no attempt to remove anything from the original Git history.

---

## 9. Immediate next step

**Phase 1c complete (local dev DB, positions + funds reads). Awaiting review.** Nothing further will
be implemented without approval.

Open items:

1. All six read routes are tested in isolation; a live Express-vs-FastAPI comparison is still
   **PENDING** (no safe reference harness exists).
2. Recommended next: port `GET /api/funds/transactions` (read-only, newest-first), then the remaining
   read routes (`GET /api/portfolio/history`, instruments, market). Write and execution routes stay
   out until separately approved.
