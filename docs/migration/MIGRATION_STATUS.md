# Migration Status

**Last updated:** 2026-10-18 (Phase 0)
**Current phase:** **Phase 0 — repository isolation and planning**
**Application code modified:** **No.** The FastAPI implementation has not been started.
**Phase 0 docs commit:** `629af4d Phase 0: migration docs and repository guidance`
(`migration/fastapi-backend`, local only — not pushed; see §6.1)

---

## 1. Current state at a glance

| Item | Value |
|---|---|
| Phase | 0 — isolation and planning |
| FastAPI application | **not started** |
| Express backend | unchanged, retained in-tree as reference |
| Frontend | unchanged |
| MongoDB | unchanged; not contacted |
| New repository path | `D:\deepak\coding\Full Stack Dev\Tradium-FastAPI` |
| Intended GitHub repository | `tradium-fastapi` (private) |
| GitHub push | **BLOCKED** — no `gh` CLI and no authenticated remote |
| Branch for migration work | `migration/fastapi-backend` |
| Source snapshot | `23099b7 single service deployment - Express serves the built frontend` |
| Original repository | `D:\deepak\coding\Full Stack Dev\Zerodha` — untouched |
| Production (Render) | untouched; no service, branch, or env changes |
| Tests executed | **none in this repository** (nothing has been run; see §5) |

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
| Application tests | **not run — none exist** |
| Lint / build in the new repo | **not run** (no dependencies installed) |

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

1. Exact MongoDB collection names (must be confirmed against an isolated database).
2. Whether PydanticAI's `VercelAIAdapter` matches `@ai-sdk/react` 4.0.61.
3. Whether Yahoo streaming delivers messages for exact `.NS` symbols.
4. Which candle intervals/ranges `yfinance` returns identically.
5. Whether Yahoo data is permitted for the intended display and deployment.
6. The approved fallback if streaming fails.
7. Current Render build/start configuration (not in the repository).
8. Whether the FastAPI service replaces the existing Render service or is added alongside it.

---

## 8. Explicitly not approved / not done

- No FastAPI application, routes, models, or dependency installation.
- No change to `server/`, `src/`, or any other application file.
- No database migration, schema change, or data access.
- No Render service created, modified, or deployed.
- No change to the original repository's history, branch, remotes, or working tree.
- No merge of `migration/fastapi-backend` into `main`.
- No secret rotation, and no attempt to remove anything from the original Git history.

---

## 9. Immediate next step

**Awaiting review of Phase 0.** After approval:

1. Resolve the GitHub blocker and push both branches (§6.1).
2. Begin Phase 1 by creating the FastAPI skeleton, settings, Mongo access, and a single read route
   (`GET /api/holdings`) with a parity test against the Express reference on an isolated database.
