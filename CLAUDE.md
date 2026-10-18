# Tradium — FastAPI Migration Workspace

This repository is a **separate copy** of the Tradium project, created for migrating its backend from
Express to FastAPI. It is not the original repository and is not connected to it.

## Repository isolation — read this first

- Work **only** inside this repository.
- Never read from, write to, commit in, push to, or run Git commands in the original project directory
  (`D:\deepak\coding\Full Stack Dev\Zerodha`). Treat it as read-only and out of reach.
- Never push to the original GitHub repository. This repository's remote, when configured, is an
  independent private repository (`tradium-fastapi`).
- Never touch the production Render service: do not change its branch, build/start command,
  environment variables, or trigger a deploy. Do not create a deployment unless a task explicitly
  asks for it and the user has approved it.
- Never access or modify the production MongoDB.

Before **any** Git operation that writes (commit, push, branch, merge, reset):

1. `pwd` / `git rev-parse --show-toplevel` — confirm the root is this repository.
2. `git branch --show-current` — confirm you are on the intended branch.
3. `git remote -v` — confirm no remote points at the original repository.
4. `git status --short` — know what you are about to commit.

If any check looks unexpected, stop and report instead of proceeding.

## Read the migration docs before changing a subsystem

| Before you touch… | Read |
|---|---|
| Anything | `docs/migration/MIGRATION_STATUS.md` |
| Plans, phases, approvals | `docs/migration/MIGRATION_PLAN.md` |
| Backend behaviour, data model, jobs | `docs/migration/CURRENT_ARCHITECTURE.md` |
| An endpoint, request/response shape | `docs/migration/API_CONTRACTS.md` |
| A design choice | `docs/migration/ARCHITECTURE_DECISIONS.md` |
| Market data, prices, candles | `docs/migration/MARKET_DATA_PLAN.md` |
| Nova, Gemini, streaming | `docs/migration/AI_INTEGRATION_PLAN.md` |
| Verification | `docs/migration/TEST_PLAN.md` |

## Ground rules for the migration

- **Preserve behaviour.** The React frontend and MongoDB stay unchanged during the initial migration.
  API paths, field names (`_id`, `qty`, `ltp`, `avgPrice`, …), status codes, error bodies, and stream
  protocols are the contract.
- **Implement incrementally.** One subsystem at a time, with a test that proves it before moving on.
- **Do not start a phase without explicit approval.** Approval for one phase does not carry into the
  next.
- **Never claim a test passed unless you ran it.** Record what you actually executed in
  `MIGRATION_STATUS.md`, including failures and blocked tests.
- **Never expose or commit secrets.** No `.env` with real values, no API keys, no connection strings
  in tracked files. If you find a secret, report its path and the type of risk — do not print the
  value, rotate it, or rewrite history without approval.
- **Update the docs as you go.** `MIGRATION_STATUS.md` for progress and results;
  `ARCHITECTURE_DECISIONS.md` for new or invalidated decisions.
- **Stop and explain blockers.** Do not widen the scope to work around a missing prerequisite.
- **Do not fix unrelated bugs during a port.** The known defects are listed in
  `CURRENT_ARCHITECTURE.md` §9. Fixing one is a separate, approved change.

## Current layout

```
.
├── src/                 React + Vite frontend (unchanged; the contract)
├── server/              Express backend (reference implementation; keep working)
├── docs/migration/      Phase 0 documents
├── package.json         frontend project
└── CLAUDE.md            this file (gitignored upstream — stage with `git add -f`)
```

The FastAPI application does **not** exist yet.

## Commands

Frontend (repository root):

```bash
npm install
npm run dev        # Vite, port 5173
npm run build      # production build to dist/
npm run lint       # ESLint
```

Express reference backend:

```bash
cd server
npm install
npm start          # node index.js, port 3002
```

`server/` needs its own `.env` (copy from `server/.env.example`). Required: `MONGO_URL`, `JWT_SECRET`,
`GOOGLE_GENERATIVE_AI_API_KEY`. Never commit it.

Once the FastAPI application exists, document its commands here **only after verifying them**.

## Things that will bite you

- **Scheduled jobs must have exactly one owner.** Never run the Express server and a FastAPI process
  with schedulers against the same database at the same time — duplicate price sync can double-fill
  orders.
- **Collection names are singular/plural in non-obvious ways** (`watchlists`, `marketquotes`,
  `portfoliosnapshots`). Verify them against a database before writing queries.
- **Funds semantics:** `available` is free cash, and `usedMargin` is derived. Do not "fix" this into a
  stored balance.
- **Money paths are atomic by design.** Guards live in the query filter (`$gte`, status claim,
  `deleteOne` count). Port them as atomic operations, never as read-then-write Python.
- **AI quotas are real.** Do not fire model calls on every render, in polling loops, or in tests that
  loop over pages.
- **The chat stream is a Vercel UI Message Stream**, not OpenAI SSE. Page insight and briefing are
  plain text. They are different protocols on purpose.
- **`CLAUDE.md` is matched by `.gitignore`;** stage it with `git add -f` when committing docs.

## Testing

There is no automated test suite in the copied source. Until one exists:

- `npm run lint` and `npm run build` must pass.
- API parity is checked by comparing Express and FastAPI responses for the same seeded data.
- Use an isolated database. Never test against production.
- Manual UI verification is part of every phase gate.
