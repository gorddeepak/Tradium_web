# Tradium (Zerodha-clone) Project Context

A mock stock-trading dashboard: React frontend + Express/MongoDB backend, with a
Gemini-powered assistant ("Nova") and per-page AI insight cards.

## Commands
- `npm install` then `npm run dev` — frontend dev server on **port 5173** (Vite default)
- `npm run build` — production build
- `npm run lint` — ESLint
- `cd server && npm install && npm start` — backend on **port 3002** (runs nodemon)

The frontend and backend are two separate npm projects, each with its own
`package.json`. Install in both.

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
- `server/index.js` — app setup, route mounts, cron jobs, central error handler
- `server/routes/` — one Express router per resource
- `server/controllers/` — `authController.js`, `assistantController.js` (AI tool calls), `insightController.js`
- `server/models/` — Mongoose models; **each file holds its own schema and model**
- `server/middlewares/auth.js` — `protect`, the JWT guard used by every router
- `server/config/ai.js` — the shared Gemini model instance
- `server/utils/portfolioMath.js` — portfolio totals (used by the assistant)
- `server/jobs/` — `priceSync.js` (every 5 min), `portfolioSnapshot.js` (daily 6pm)

## Key Files
- `src/features/assistant/components/AssistantPanel.jsx` — chat UI
- `src/features/assistant/components/PageInsight.jsx` — insight card + "Ask about this"
- `src/features/assistant/AssistantContext.jsx` — chat state and seed context
- `src/features/auth/AuthContext.jsx` — auth state
- `server/controllers/assistantController.js` — AI tool definitions (getHoldings, etc.)

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
- The model ID lives **only** in `server/config/ai.js`. Don't hardcode it in controllers.
- The API origin lives **only** in `src/services/api.js` as `BASE_URL`. Import it;
  don't write `http://localhost:3002` anywhere else.
- **Express 5 forwards async errors automatically** to the error handler at the bottom
  of `server/index.js`, so route handlers don't need their own try/catch. Only add one
  when you want a specific status (see `instrumentRoutes.js` returning 404s).
- `portfolioSummary` in `src/utils/tradiumUtils.jsx` is a deliberate duplicate of
  `calculatePortfolioSummary` in `server/utils/portfolioMath.js`. Change both together.
- "Ask about this" sends the AI-generated insight **text**, not raw JSON, so chat
  bubbles stay readable.
- No fabricated marketing claims on the landing page (no fake testimonials, uptime
  figures, or compliance badges).
- **`var()` DOES work in SVG `fill`/`stroke` attributes.** Verified in Chrome:
  `fill="var(--chart-1)"` computes to `rgb(42, 120, 214)`. The comment in
  `heatmapScale.js` says otherwise — that comment is over-general. `openalgo-heatmap`
  needs a literal because it does colour *math* on the string, not because attributes
  reject `var()`. So `holdingColors()` returning `var(--chart-N)` is fine.
- **The candle chart now uses a visx-based implementation** (in `CandleChart.jsx`),
  which replaces the previous `lightweight-charts` dependency. This MIT-licensed
  approach avoids the TradingView attribution requirement while providing
  equivalent candlestick charting functionality.

## Environment
- Node.js >= 18
- Backend requires `server/.env` — copy `server/.env.example` and fill it in.
  `MONGO_URL` and `JWT_SECRET` are required; the server exits if `MONGO_URL` is missing.
  `GOOGLE_GENERATIVE_AI_API_KEY` is required for the assistant and insight cards.
- Frontend needs no env file for local dev. Set `VITE_API_URL` only when pointing a
  production build at a deployed backend.

## Testing
- Manual testing via the UI; no automated test suite yet
- `npm run lint` should pass; check the browser console for warnings

## Workflow
1. `npm install` in the root and in `server/`
2. Create `server/.env` from `server/.env.example`
3. `cd server && npm start` (port 3002)
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
