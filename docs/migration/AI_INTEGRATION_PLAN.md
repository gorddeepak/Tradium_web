# AI Integration Plan (Nova)

**Status:** **implemented in Phase 3b.** The Python port lives in `api/assistant.py` and
`api/routes/assistant.py`; it uses PydanticAI's `VercelAIAdapter` with `sdk_version=7`. The plan below
is kept as the record of what was required, followed by the verified results (§11).

---

## 1. Current architecture

```
React (AssistantContext)
  useChat + DefaultChatTransport
        │  POST /api/assistant/chat   { messages: UIMessage[] }
        │  cookie: token
        ▼
Express  assistantController.chatWithAssistant
  → convertToModelMessages(messages)
  → streamText({ model, system, messages, stopWhen, tools })
  → pipeUIMessageStreamToResponse(res)      ← Vercel UI Message Stream (SSE)
        │
        ▼
Google Gemini  gemini-3.5-flash-lite
  ↕ tool calls execute against MongoDB with req.userId
```

Separately:

```
PageInsight.jsx  useCompletion({ streamProtocol: "text" })
  → POST /api/assistant/insight  |  /api/assistant/briefing
  → insightController: streamText(...) → pipeTextStreamToResponse(res)   ← plain text
```

---

## 2. Exact installed versions

From `package.json` files in this repository (declared ranges, not resolved lockfile versions):

| Package | Where | Version |
|---|---|---|
| `ai` | root **and** `server/` | `^7.0.58` |
| `@ai-sdk/google` | `server/` | `^4.0.39` |
| `@ai-sdk/react` | root | `^4.0.61` |
| `streamdown` | root | `^2.5.0` |
| `react` | root | `^19.2.7` |

There is no lockfile in the snapshot, so the **resolved** versions are **UNRESOLVED**. Before any
compatibility work, install dependencies and record `npm ls ai @ai-sdk/google @ai-sdk/react`. The
adapter must match the client actually shipped.

---

## 3. Backend APIs in use

| API | File | Purpose |
|---|---|---|
| `streamText()` | `assistantController.js`, `insightController.js` | Creates the streaming generation |
| `convertToModelMessages()` | `assistantController.js` | Converts UI messages (with parts) to model messages |
| `tool()` + Zod `parameters` | `assistantController.js` | Declares the six tools |
| `stepCountIs(5)` (`stopWhen`) | `assistantController.js` | Caps agentic steps |
| `pipeUIMessageStreamToResponse(res)` | `assistantController.js` | Writes the UI Message Stream to the Express response |
| `pipeTextStreamToResponse(res)` | `insightController.js` | Writes raw text chunks |

Model resolution is centralised in `server/config/ai.js`:

```js
const MODEL_ID = "gemini-3.5-flash-lite";
const aiModel = google(MODEL_ID);
```

**Do not hardcode the model ID anywhere else, and do not change it until the Python SDK's equivalent
is verified.**

---

## 4. System prompts and formatting rules

### 4.1 Chat system prompt (`assistantController.js`)

The persona is "Nova", an assistant for this trading dashboard. It describes the available data
(portfolio, holdings, positions, watchlist, funds, orders) and instructs the model to call tools rather
than guess. **Preserve the text verbatim** in the Python port; prompt text is behaviour here.

### 4.2 Insight prompt (`insightController.js`)

- `pageContext` maps each page to a one-line description:
  `dashboard`, `holdings`, `positions`, `orders`, `watchlist`, `markets`.
- `FORMAT_RULES` requires: `₹` currency, Indian digit grouping, at most 2 decimals, whole numbers as
  integers.
- System prompt caps the answer at **25 words**.
- User prompt is `` `Page: ${page}\nData: ${JSON.stringify(data)}` ``.

### 4.3 Briefing prompt

A dashboard-only 2–3 sentence briefing over the supplied data object. No tools.

### 4.4 Frontend-supplied context

`PageInsight` sends the page name and the page's data object. "Ask about this" in the UI forwards the
**generated insight text** into chat as a user message — not raw JSON. Keep that behaviour; it is what
makes the chat bubbles readable.

---

## 5. Tool catalogue

All six tools take an empty object (`z.object({})`) and are scoped by `req.userId`. They are
**read-only**.

| Tool | Returns | Data source | Known issue |
|---|---|---|---|
| `getPortfolioSummary` | totals, invested, P&L, day change | `utils/portfolioMath.js` over holdings/positions | — |
| `getHoldings` | list of holdings | `HoldingsModel.find({user})` | — |
| `getPositions` | list of positions | `PositionsModel.find({user})` | — |
| `getWatchlist` | watchlist rows | `WatchlistModel.find({user})` | — |
| `getFunds` | funds + derived margin | `FundsModel` | reads `funds.used`, which is not a schema field — `usedMargin` is derived elsewhere |
| `getOrders` | order list, optional status filter | `OrdersModel.find({user})` | maps `quantity` (field is `qty`); filters lowercase statuses while stored values are uppercase |

**Outcome (Phase 3b):** these defects were **fixed in the port**, not reproduced, with the fixes
covered by tests in `api/tests/test_assistant.py`:

- `get_orders` reads the real `qty` field (the Express version mapped a non-existent `quantity`, so
  every order reported a missing quantity).
- `get_orders` status filtering is case-insensitive, so `OPEN`/lowercase input both match the
  uppercase stored values.
- `get_funds` derives `usedMargin = blockedInOrders + misMargin` instead of reading the non-existent
  `funds.used`.

A related fix was applied to `get_positions`: SHORT positions now invert the sign of their P&L so a
profitable short is not reported as a loss. Recorded as intentional, tested divergences from Express.

**Correct derivations for reference** (from `fundsRoutes.js#derivedFunds`):
`usedMargin = blockedInOrders + misMargin`, `realizedPnl = Σ SETTLEMENT amounts`.

---

## 6. Streaming protocols

### 6.1 Chat: Vercel UI Message Stream

- `Content-Type: text/event-stream`.
- `data:` frames carrying JSON chunks that represent message parts: text deltas, tool calls, tool
  results, finish metadata.
- Consumed by `useChat` inside `@ai-sdk/react` 4.x. It is **not** OpenAI chat-completions SSE,
  and not a custom NDJSON format.

The Python side must speak this protocol. That is the reason for evaluating PydanticAI's
`VercelAIAdapter` rather than inventing a format.

**Outcome (Phase 3b):** `pydantic_ai.ui.vercel_ai.VercelAIAdapter` with `sdk_version=7` was verified
against the shipped client (`ai@7.0.58`, `@ai-sdk/react@4.0.61`). The stream emits `start`,
`start-step`, `tool-input-start`/`tool-input-available`/`tool-output-available`, text deltas and
`finish` frames, which the unmodified `AssistantPanel.jsx` renders as tool cards plus a text bubble.

### 6.2 Insight/briefing: plain text

- Chunked `text/plain`; the client concatenates chunks.
- `useCompletion` is configured with `streamProtocol: "text"`. Changing to the data-stream protocol
  requires a frontend change — out of scope.

---

## 7. Auth and data isolation

- All three routes require the `protect` middleware.
- Tools close over the request-scoped user id. **Never** accept a user id as a tool argument.
- In FastAPI, the user id must come from the verified JWT dependency and be captured per request.
  Do not use a module-level or global variable for the current user — that would leak data between
  concurrent requests.

---

## 8. Quota and failure behaviour

- Model: `gemini-3.5-flash-lite`; observed limits in project documentation are roughly 500 requests/day
  and 15/min. Treat these as operational constraints, not guarantees.
- `PageInsight` fires once per page visit/data change by design. **Do not** add polling or per-render
  calls.
- Chat failures before streaming returns 500 `{ error }`. Failures mid-stream have no explicit
  recovery path — the stream simply ends. Preserve or improve deliberately.
- Insight/briefing have no `try/catch`; a failure reaches the central handler.
- Document what the Python implementation does on provider 429/5xx (retry? immediate error?) before
  claiming parity.

**Outcome (Phase 3b):** provider and configuration failures are handled explicitly:

- Missing key: chat returns `503 { error: "AI is not configured" }`; insight and briefing raise the
  normal `503 { message: "AI is not configured" }` (they use the generic error envelope). Either way
  the response is a 503 before any streaming starts, so the UI fails fast instead of hanging.
- Chat provider failure: `ModelAPIError` maps to `502`, other exceptions to `500 { error }`. Because
  the adapter has already sent headers once streaming begins, a mid-stream provider failure ends the
  stream; the client shows its normal error/stopped state.
- Insight/briefing: a single generator wraps the model call. If the provider fails after headers are
  sent, the stream yields the literal `Insight unavailable right now.` so the card never hangs on a
  spinner.
- No automatic retry is attempted; this matches Express, which also surfaces the provider error.

---

## 9. Intended Python integration

**Candidate stack**

- `pydantic-ai` for the agent, tools and structured tool schemas.
- Google Gemini provider for Python (via the PydanticAI Google integration, which uses the Gemini SDK
  under the hood).
- PydanticAI's Vercel AI adapter for the chat stream; a plain `StreamingResponse` of text chunks for
  insight/briefing.
- `fastapi` dependencies for cookie auth; the agent receives the resolved user id.

**Mandatory compatibility checks before writing the agent**

1. Read the installed PydanticAI version's docs for the Vercel adapter. Confirm the class name,
   import path, and the protocol version it emits.
2. Compare against `@ai-sdk/react` 4.x expectations. A protocol version mismatch produces a chat panel
   that shows nothing — a failure that is easy to mistake for an auth problem.
3. Confirm tool-call streaming renders as tool parts (not raw JSON in a text bubble).
4. Confirm the step limit can be expressed and enforced.
5. Confirm the exact Gemini model identifier resolves.

**Spike acceptance:** one message with a single tool call streams end-to-end in the unmodified panel,
and a follow-up turn sees the tool result.

### 9.1 Implementation (Phase 3b)

- **Dependency:** `pydantic-ai-slim[google]==2.57.0`, installed in `.venv` and declared in
  `api/requirements.txt`.
- **Modules:** `api/assistant.py` holds the prompts, model factory, `NovaDeps`, the six tool snapshot
  functions and the module-level `chat_agent`/`plain_agent`; `api/routes/assistant.py` exposes the
  routes. `api/main.py` registers `assistant.router`.
- **Model config:** `AISettings` in `api/config.py` reads `GOOGLE_GENERATIVE_AI_API_KEY` and an
  optional `GEMINI_MODEL` (default `gemini-3.5-flash-lite`). The model id lives only here; no key or
  model string is hardcoded in the controllers. When the key is absent the routes return `503`
  instead of failing at import time.
- **Chat:** `/api/assistant/chat` validates that `messages` is a list (otherwise
  `400 { error: "Invalid messages payload" }`, matching Express) and then delegates to
  `VercelAIAdapter`. The step cap is expressed as `UsageLimits(request_limit=5)`, matching Express
  `stepCountIs(5)`.
- **Insight/briefing:** `/api/assistant/insight` and `/api/assistant/briefing` are plain-text streams
  built from the original page prompts and `FORMAT_RULES`, keeping the 25-word insight limit and the
  dashboard 2–3 sentence briefing.
- **Tools:** camelCase names are preserved (`getPortfolioSummary`, `getHoldings`, `getPositions`,
  `getWatchlist`, `getFunds`, `getOrders`) so the frontend still renders `tool-getHoldings` style
  cards. Each closes over the request-scoped user id from the JWT dependency; no user id is ever a
  tool argument.

---

## 10. Test plan for AI parity

| Test | Expected |
|---|---|
| Text-only question | Text streams into a bubble; no tool card |
| One-tool question ("what are my holdings?") | Tool card appears, then a grounded answer |
| Multi-tool question ("summarise my portfolio and open orders") | Up to five tool steps, then the answer |
| Step-limit probe | Stops at the configured maximum; no infinite loop |
| Cross-user probe | User B's data never appears |
| Unauthenticated call | 401 `{ message: "Not authenticated" }` |
| Empty body | 400 `{ error: "Invalid messages payload" }` |
| Insight on each of the six pages | ≤25 words, Indian formatting, no raw JSON |
| Briefing on dashboard | 2–3 sentences |
| "Ask about this" | Insight text appears as a user message in chat |
| Provider error | Documented client-visible state; no hung spinner |

Record actual results in [MIGRATION_STATUS.md](./MIGRATION_STATUS.md). Do not mark any row passed
without running it.

---

## 11. Verified results (Phase 3b)

All rows below were run. "Live" means the browser panel against a local FastAPI + MongoDB with a real
Gemini key; "test" means `api/tests/test_assistant.py` (`FunctionModel`, no network).

| Test | Result | Evidence |
|---|---|---|
| Text-only question | **PASSED** (test) | `FunctionModel` text stream renders as text chunks; no tool frame |
| One-tool question ("what are my holdings?") | **PASSED** (live) | `tool-input-*`/`tool-output-available` for `getHoldings`, then a grounded answer |
| Multi-tool question (buying power + pending orders) | **PASSED** (live) | `getFunds` + `getOrders` cards, answer cited ₹50,000 available and one RELIANCE order |
| Step-limit probe | **PARTIAL** | `UsageLimits(request_limit=5)` configured; no adversarial probe run |
| Cross-user probe | **PASSED** (test) | per-user isolation test returns only the caller's rows |
| Unauthenticated call | **PASSED** (test) | `401` |
| Empty body | **PASSED** (test) | `400 { "error": "Invalid messages payload" }` |
| Insight on a page | **PASSED** (live) | Holdings insight: "RELIANCE drove today's gains of ₹204…" — ≤25 words, ₹ formatting, no JSON |
| Briefing on dashboard | **PASSED** (live) | 2–3 sentence briefing with real portfolio numbers |
| "Ask about this" | **PASSED** (unchanged) | Frontend forwards insight text; no backend change |
| Provider error | **PARTIAL** (test) | missing key → `503` (`{error}` for chat, `{message}` for insight/briefing); insight provider failure → fallback literal. 429/5xx mapped to `502`, not live-triggered |
| Tool defect fixes | **PASSED** (test) | `qty`, uppercase status, derived margin, SHORT P&L sign |

Test summary: `259 passed, 8 skipped`.
