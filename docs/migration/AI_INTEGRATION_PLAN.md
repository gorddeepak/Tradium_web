# AI Integration Plan (Nova)

**Status:** documentation only. Nova is **not** migrated in Phase 0 or Phase 1. Migrate in Phase 3.

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

These three defects are **documented, not fixed** (AD-9). Reproduce current behaviour in the port, then
fix deliberately with approval — or fix them as a separate, tested change. Either way, record which
choice was made in `MIGRATION_STATUS.md`.

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
