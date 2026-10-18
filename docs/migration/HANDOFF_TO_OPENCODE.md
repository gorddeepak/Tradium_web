# Handoff to OpenCode — Tradium FastAPI migration

**Written:** 2026-10-18, by the Claude Code session that performed Phase 0 and Phase 1a.
**Purpose:** continue the migration from this exact point on a different agent platform.

---

## 1. Where this work lives

| Item | Value |
|---|---|
| Working directory | `D:\deepak\coding\Full Stack Dev\Tradium-FastAPI` |
| Repository root | `D:/deepak/coding/Full Stack Dev/Tradium-FastAPI` |
| Branch | `migration/fastapi-backend` |
| HEAD | `82b5c8f150ef62b364b57d1fe8e551bcfb3fe55b` (`82b5c8f`) |
| Remotes | **none** — this repository has no connection to the original |
| Working tree | clean |
| Python | 3.13.7, repository-local `.venv` (gitignored) |
| Original repository | `D:\deepak\coding\Full Stack Dev\Zerodha` — branch `main`, HEAD `23099b7`, untouched |

The original repository and its Render deployment are **reference only**. Do not modify them, do
not push to them, and do not run their server: `server/index.js` schedules and fires price/market
sync jobs on database connect.

---

## 2. Task history in this chat

### Completed: migration impact analysis (read-only)
Produced the analysis that the Phase 0 documents later formalise.

### Completed: Phase 0 — repository isolation and planning
- Exported the original repo at `23099b7` with `git archive` (177 files, `.git` and `server/.env`
  excluded by construction).
- `git init -b main`, baseline commit `1979884`, then branch `migration/fastapi-backend`.
- No remote added. No secret found in the tracked files.
- Wrote nine migration documents (see §5).
- Commit `629af4d`, later `8a7cc6d` for status bookkeeping.
- GitHub publication remains **BLOCKED**: `gh` is not installed and no authenticated remote exists.

### Completed: Phase 1a — FastAPI foundation + `GET /api/holdings` (this session)
Commit `82b5c8f`, 23 files changed, 824 insertions, 18 deletions.

Scope boundary the user set explicitly: **stop after this endpoint; do not add another route without
approval.**

---

## 3. What Phase 1a actually implements

| File | Behaviour |
|---|---|
| `api/main.py` | `create_app(database=None)` factory; lifespan injects or connects; Express-shaped error envelope; mounts health + holdings. Module-level `app = create_app()`. |
| `api/config.py` | Frozen `Settings` from env: `MONGO_URL`, `JWT_SECRET`, `HOST` (default `0.0.0.0`), `PORT` (default `8000`). `.env` loaded via `python-dotenv`. |
| `api/db.py` | One module-level `MongoClient` (`serverSelectionTimeoutMS=5000`), `get_default_database()`. `connect()` raises `RuntimeError("MONGO_URL is not set")`. Tests never touch it. |
| `api/auth.py` | `require_user` dependency: missing `token` cookie → 401 `"Not authenticated"`; `jwt.decode(..., algorithms=["HS256"])` failure or missing `id` → 401 `"Invalid or expired token"`; returns the claim as a string. |
| `api/serialization.py` | `to_json_value`: ObjectId → 24-char hex; datetime → `%Y-%m-%dT%H:%M:%S.` + 3-digit ms + `Z`, naive treated as UTC, aware converted to UTC; recurses dict/list. |
| `api/routes/health.py` | `GET /api/health` → `{"ok": True}`, no auth, no DB. |
| `api/routes/holdings.py` | `GET /api/holdings`: `db["holdings"].find({"user": ObjectId(user_id)})`, natural order, no sort, each document passed through `to_json_value`. |

Error envelope in `api/main.py`:

- `StarletteHTTPException` → `{"message": exc.detail}`, except the framework's own 404, which becomes
  `{"message": "Route not found"}`.
- `RequestValidationError` → 400 `{"message": "Invalid request"}` (placeholder; no bodies in 1a).
- `Exception` → logged, then 500 `{"message": "Something went wrong"}`.

Dependencies (`api/requirements.txt`): fastapi 0.144.0, uvicorn[standard] 0.54.0, pymongo 4.19.0,
PyJWT 2.15.1, python-dotenv 1.2.4. Dev (`api/requirements-dev.txt`): pytest 9.1.1, httpx 0.28.1,
mongomock 4.3.0.

---

## 4. Test status — observed, not assumed

| Command | Result |
|---|---|
| `.venv/Scripts/python.exe -m pytest -q` | **23 passed, 1 skipped** |
| `TEST_MONGO_URL=mongodb://127.0.0.1:27017/tradium_fastapi_phase1_test .venv/Scripts/python.exe -m pytest -q` | **24 passed** |

Covered: startup with injected DB, health, unknown-route 404, six auth-rejection cases, valid empty
read, two-user isolation, caller-supplied `user`/`userId` ignored, exact 13-key response set including
`__v`, ObjectId hex, 3-decimal UTC timestamps (naive, aware, IST input), malformed-claim 500,
database-failure 500 with no leak, and one real-MongoDB read.

The integration test refuses any database name not ending in `_test` and drops the database
afterwards. `zerodha` was never written to. Verified afterwards that
`tradium_fastapi_phase1_test` was absent from `list_database_names()`.

**Not verified — do not claim it:**
- No live side-by-side comparison against a running Express server. `server/index.js` starts cron
  jobs, which the user forbade. Parity rests on the documented contract, the Mongoose model, and a
  hand-built fixture. Recorded as `PENDING` in `TEST_PLAN.md` §1A.
- No login/cookie-setting parity (login is not in Phase 1a).
- Nothing deployed; no Render change.

---

## 5. Documents in the repository

`docs/migration/`: `MIGRATION_PLAN.md`, `CURRENT_ARCHITECTURE.md`, `API_CONTRACTS.md`,
`ARCHITECTURE_DECISIONS.md`, `TEST_PLAN.md`, `AI_INTEGRATION_PLAN.md`, `MARKET_DATA_PLAN.md`,
`MIGRATION_STATUS.md`. Read `MIGRATION_STATUS.md` first; it is current as of Phase 1a.

---

## 6. Constraints that must continue to hold

1. Never modify or push to `D:\deepak\coding\Full Stack Dev\Zerodha`, and never run its server.
2. Never contact the production database. Tests use mongomock or a `*_test` scratch database.
3. Do not enable scheduled market-data jobs, Yahoo Finance calls, or any background job.
4. Do not connect the React frontend to FastAPI yet.
5. Do not add routes beyond those approved phase by phase.
6. Do not claim behavioural parity that has not been observed.
7. No SQLAlchemy, SQLite, or a second database layer.
8. Keep the design beginner-simple: plain code, minimal abstraction.

---

## 7. Verify you are continuing from the exact same point

Run these from `D:\deepak\coding\Full Stack Dev\Tradium-FastAPI`:

```bash
git rev-parse --show-toplevel
git branch --show-current
git rev-parse --short HEAD
git status --short
git remote -v
```

Expect: the `Tradium-FastAPI` path, `migration/fastapi-backend`, `82b5c8f`, no output from
`git status --short`, and no remotes.

Then confirm the last change is present:

```bash
git show --stat --oneline HEAD | head -5
grep -n "Route not found" api/main.py
grep -n "def list_holdings" api/routes/holdings.py
```

Expect `23 files changed, 824 insertions(+), 18 deletions(-)`, the 404 mapping at `api/main.py`,
and the holdings view function.

Then confirm the suite:

```bash
.venv/Scripts/python.exe -m pytest -q
```

Expect `23 passed, 1 skipped`. If `.venv` is missing, recreate it:

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r api/requirements-dev.txt
```

---

## 8. Next proposed step — awaiting user approval

1. Build a safe Express reference harness that mounts `holdingsRoutes` **without** importing or
   starting `server/index.js`'s cron jobs; seed both implementations from equivalent documents on the
   scratch database and compare status, key set, value types, and timestamp text. This closes the one
   `PENDING` parity row.
2. Only then port the next read-only routes, one at a time, with tests and documented status:
   `GET /api/orders`, `GET /api/watchlist`.

Note: `core.autocrlf` is `true` on this machine, so Git may report LF→CRLF warnings on Windows. That
is expected and is not a content change.
