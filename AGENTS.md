# Tradium (Zerodha-clone) Project Context

A mock stock-trading dashboard: React frontend + FastAPI/PostgreSQL backend, with
a Gemini-powered assistant ("Nova") and per-page AI insight cards.

## Commands
- `npm install` then `npm run dev` — frontend dev server on **port 5173** (Vite default)
- `npm run build` — production build
- `npm run lint` — ESLint
- `.venv/Scripts/python.exe -m uvicorn api.main:app --reload --port 8000` — FastAPI on **port 8000**
- `alembic upgrade head` — apply PostgreSQL migrations

The frontend is a Node project; the backend is a Python project (`api/`) using
the repository-root virtualenv. Install `api/requirements.txt` and the npm
packages separately.

## Architecture
Frontend is organised **by feature**, not by file type.

- `src/features/assistant/` — Nova chat panel, insight cards, `AssistantContext.jsx`
  - `components/` — `AssistantPanel.jsx`, `PageInsight.jsx`
  - `ai-elements/` — vendored Vercel AI Elements UI primitives (third-party)
- `src/features/auth/` — `AuthContext.jsx`, login/signup pages
- `src/features/dashboard/` — dashboard shell, pages (Holdings, Positions, Orders, WatchList, Instrument), tables, hooks
- `src/features/marketing/` — landing page sections
- `src/components/ui/` — shadcn primitives (Button, Input, Spinner, …)
- `src/components/ProtectedRoute.jsx` — redirects to `/login` when unauthenticated
- `src/pages/routes/routes.js` — route path constants
- `src/services/api.js` — all API calls + the exported `BASE_URL`
- `src/utils/tradiumUtils.jsx` — formatters, small display components, portfolio math
- `src/styles/` — `index.css` (Tailwind v4 setup + theme tokens), `dashboard.css`

Backend:
- `api/main.py` — app setup, router mounts, scheduler startup, static mount, error handlers
- `api/routes/` — one FastAPI router per resource (`auth`, `holdings`, `orders`, …)
- `api/trading_book.py` — the trading core (orders, positions, funds, transactions) in PostgreSQL
- `api/postgres/models.py` — SQLAlchemy models for the schema
- `api/migrations/` — Alembic history; never rewrite an applied migration
- `api/auth.py` — JWT and bcrypt helpers; `api/rate_limit.py` — auth limiter
- `api/assistant.py` — Nova's agent, tools and Gemini model
- `api/jobs/` — `market_sync`, `price_sync` (every minute), `portfolio_snapshot` (daily 6pm IST)
- `api/market_data.py`, `market_store.py`, `market_hours.py` — Yahoo quotes/candles and the PostgreSQL cache
- `api/serialization.py`, `js_compat.py`, `portfolio_math.py` — response shapes and shared money helpers

## Key Files
- `src/features/assistant/components/AssistantPanel.jsx` — chat UI
- `src/features/assistant/components/PageInsight.jsx` — insight card + "Ask about this"
- `src/features/assistant/AssistantContext.jsx` — chat state and seed context
- `src/features/auth/AuthContext.jsx` — auth state
- `api/assistant.py` — AI tool definitions (getHoldings, etc.)
- `src/services/api.js` — `BASE_URL` and the watchlist WebSocket URL

## Code Style
- Beginner-simple: plain JSX, minimal helper functions, inline Tailwind classes
- Avoid over-abstraction; prefer verbose and obvious over clever and short
- Use `animate-entry` (from `dashboard.css`) for entrance animations
- Use `Spinner` from `@/components/ui/spinner` for loading states
- `@` is aliased to `./src`

## Gotchas
- **Chat is a `Sheet` side panel, not a floating bubble.** Don't change this without discussing.
- **AI rate limits are real**: `gemini-3.5-flash-lite` allows ~500 requests/day, 15/min.
  Never fire AI calls on every render or inside a polling loop. `PageInsight` fires
  once per page visit, which is intentional and already at the limit of acceptable.
- The model ID lives **only** in `api/config.py` (`DEFAULT_GEMINI_MODEL`). Don't
  hardcode it in routes or controllers.
- The API origin lives **only** in `src/services/api.js` as `BASE_URL`. Import it;
  don't write `http://localhost:8000` anywhere else.
- **FastAPI does not turn a raised exception into a JSON error envelope by itself.**
  The handlers in `api/main.py` reproduce the Express shape; raise `HTTPException`
  with a `detail` when you need a specific status.
- `portfolioSummary` in `src/utils/tradiumUtils.jsx` is a deliberate duplicate of
  `calculate_portfolio_summary` in `api/portfolio_math.py`. Change both together.
- "Ask about this" sends the AI-generated insight **text**, not raw JSON, so chat
  bubbles stay readable.
- No fabricated marketing claims on the landing page (no fake testimonials, uptime
  figures, or compliance badges).
- **`var()` DOES work in SVG `fill`/`stroke` attributes.** Verified in Chrome:
  `fill="var(--chart-1)"` computes to `rgb(42, 120, 214)`. The comment in
  `heatmapScale.js` says otherwise — that comment is over-general. `openalgo-heatmap`
  needs a literal because it does colour *math* on the string, not because attributes
  reject `var()`. So `holdingColors()` returning `var(--chart-N)` is fine.
- **`CandleChart.jsx` uses `lightweight-charts`**; the visx packages power the
  pie charts in `src/components/charts/`. Don't swap one for the other without
  checking both call sites.

## Environment
- Node.js >= 18 and Python 3.12+
- Backend reads `api/.env` — copy `api/.env.example` and fill it in.
  `DATABASE_URL` and `JWT_SECRET` are required; run `alembic upgrade head` first.
  `GOOGLE_GENERATIVE_AI_API_KEY` is required for the assistant and insight cards.
  Set `MARKET_SYNC_ENABLED=true` locally so the 53-symbol market cache is seeded.
- Frontend needs no env file for local dev. Set `VITE_API_URL` only when pointing a
  production build at a deployed backend.

## Testing
- Backend: `python -m pytest -q` from the repo root.
  - Set `TEST_DATABASE_URL` first. It must name a disposable PostgreSQL database
    ending in `_test`; the suite runs `alembic upgrade head` against it. With it
    unset every PostgreSQL test skips instead of failing.
  - Never point the tests at `DATABASE_URL` or at a database with real data.
- Frontend: no automated suite; verify manually in the browser.
- `npm run lint` should pass; check the browser console for warnings.

### Batch implementation and testing by coherent functionality
- Split migration work into batches that each touch one coherent feature area —
  for example portfolio reads and the snapshot job first, then the assistant
  tools, then any remaining readers.
- Implement a batch, then immediately run the focused tests for that area and
  fix the failures before starting the next batch. Don't stack a second batch on
  a red suite.
- After the final batch run the **full** suite with `TEST_DATABASE_URL`, plus
  `python -m compileall -q api`.
- Batch gates are checkpoints, not a replacement for the full run. Record the
  focused and full totals in `docs/migration/MIGRATION_STATUS.md`.

## Workflow
1. `npm install` in the root; install `api/requirements.txt` in the virtualenv
2. Create `api/.env` from `api/.env.example`, then `alembic upgrade head`
3. Start FastAPI on port 8000 (see Commands)
4. `npm run dev` in the root (port 5173)
5. Sign up or log in, then open Holdings / Positions / Orders
6. Click an insight card's "Ask about this" to open Nova with that context

## Working Agreement
Behavioral guidelines to reduce common LLM coding mistakes. They apply on top of
the project-specific instructions above.

**Tradeoff:** these guidelines bias toward caution over speed. For trivial tasks,
use judgment.

### 1. Think Before Coding
**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First
**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes
**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it — don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution
**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work")
require constant clarification.

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer
rewrites due to overcomplication, and clarifying questions come before
implementation rather than after mistakes.
