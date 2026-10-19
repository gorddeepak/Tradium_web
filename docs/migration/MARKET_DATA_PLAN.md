# Market Data Plan

**Status:** Phase 2a (historical candles) is implemented and measured — see §3.1. Phase 2b evaluated
streaming and decided **not** to adopt it — see §3.2. Everything about the quote phase, the cache jobs
and the provider adapter (§3.3 – §3.5) is still a plan: nothing there should be described as working
until it has been tested and the result recorded.

---

## 1. What consumes market data today

| Consumer | Endpoint / job | Provider call | Required fields |
|---|---|---|---|
| Instrument search | `GET /api/instruments/search` | none (Mongo cache only) | cached `ltp`, `dayChangePct` |
| Instrument lookup | `GET /api/instruments/lookup/:symbol` | `quote()` | `regularMarketPrice`, `regularMarketChange`, `regularMarketChangePercent`, names |
| Instrument detail | `GET /api/instruments/:symbol` | `quote()` | above + open, high, low, prevClose, volume, 52-week high/low |
| Candles | `GET /api/instruments/:symbol/candles` | `chart()` | OHLC per bar, with empty bars filtered |
| Markets page | `GET /api/market/overview` | none (cache only) | full `MarketQuote` docs, max `updatedAt` |
| Market cache refresh | `jobs/marketSync.js` | batch `quote(53 tickers)` | ltp, dayChange, dayChangePct, prevClose, volume, marketCap, sector |
| Price sync | `jobs/priceSync.js` | `quote()` per symbol | `regularMarketPrice`, `regularMarketChangePercent` |
| Sector backfill | both jobs | `quoteSummary()` `assetProfile` | `sector` |
| MARKET order fill | `POST /api/orders` → `fetchQuote` | `quote()` | `regularMarketPrice` |
| Square-off | `POST /api/positions/:id/square-off` | `quote()` | `regularMarketPrice` (optional; falls back to stored `ltp`) |

Observed behaviour of the current integration:

- All access is **polling**. There is no WebSocket anywhere in the codebase. (Phase 2b evaluated
  Yahoo's stream and chose not to adopt it — see §3.2.)
- Symbol normalisation: `^`-prefixed index symbols pass through; everything else gets `.NS`.
- Price sync fetches sequentially on purpose (rate-limit caution).
- Market sync uses one batched call for 53 tickers with `validateResult: false`.
- Instrument routes and MARKET fills call the provider **without** a market-hours gate.
- Instrument detail and candles perform **no caching**; every request is a live call.

---

## 2. Distinguish five different problems

They have different failure modes and should not be solved by one mechanism.

| # | Problem | Current mechanism | Constraints |
|---|---|---|---|
| 1 | Historical candles | per-request `chart()` | eight range/interval pairs; latency-tolerant; cacheable |
| 2 | One-off quotes (detail, lookup, MARKET fill, square-off) | per-request `quote()` | must be fresh at fill time; small volume |
| 3 | Live prices for held symbols | 1-minute poll | ~tens of symbols; must keep `ltp` fresh for margin and matching |
| 4 | Market overview cache | 5-minute batch | 53 tickers; one batch call preferable to 53 |
| 5 | Daily snapshot / reconciliation | 18:00 IST job | correctness, not latency |

A live stream (if adopted) only addresses #3 (and possibly #4). It does not replace #1, #2 or #5.

---

## 3. Intended Python approach

### 3.1 Historical data — done in Phase 2a (direct Yahoo chart request, not `yfinance`)

**Decision: `api/market_data.py` calls Yahoo's chart endpoint directly with `requests`.** That is the
same endpoint `yahoo-finance2`'s `chart()` reads, so the bars, the timestamps and the empty-bar
filtering are the same by construction — and no pandas/numpy dependency is pulled in.

`yfinance` was evaluated first, as planned, and it works: all eight ranges returned data for both an
Indian equity (`RELIANCE.NS`) and an index (`^NSEI`). It was rejected because for five of the eight
ranges it serves a **different series** from the one the Express route returns:

| `range` | interval | divergence from `yahoo-finance2` |
|---|---|---|
| `1D` | `1m` | none — identical bar count, timestamps and values |
| `5D` | `5m` | none |
| `6M` | `60m` | none |
| `SPARK` | `1d` | `time` off by 33300 s: yfinance labels a daily bar at exchange midnight, Yahoo labels it at the session open |
| `1Y` | `1d` | same 33300 s shift |
| `1M` | `30m` | timestamps 900 s earlier *and* different OHLC — different bucketing, not a relabelling |
| `5Y` | `1wk` | one bar short: yfinance omits the in-progress final week |
| `ALL` | `1mo` | one bar short, same reason |

Measured 2026-10-18 (market closed) on both symbols; every divergence above appeared in both. The
daily shift alone would move the candle chart's x-axis onto the previous day, and `1M` prices would
simply be different — so using yfinance would mean post-processing its output to reverse-engineer
Yahoo's own bar boundaries. A direct request reproduces them exactly instead, which is why it was
chosen.

#### Request contract

The query parameters are the ones the library actually sends, which is not visible in the Express
route: it passes only `period1` and `interval`, so the library's own defaults decide the rest.

```
GET https://query2.finance.yahoo.com/v8/finance/chart/{ticker}
    ?useYfid=true&includePrePost=true&events=div%7Csplit%7Cearn&lang=en-US
    &interval={interval}&period1={start}&period2={now}
```

`includePrePost=true` is load-bearing. With `false`, the `^NSEI` series came back one bar *longer*
than the library's for every intraday range; switching to the library's own value made all
comparisons agree. A browser `User-Agent` is sent as well, and unlike Express the call carries a 20 s
timeout. Neither changes the bars.

#### Range table

Unchanged from the original plan; taken from `server/routes/instrumentRoutes.js`. An unrecognised
range falls back to `{ days: 30, interval: "1d" }`, exactly as Express does.

| `range` | days | interval |
|---|---|---|
| `1D` | 3 | `1m` |
| `5D` | 5 | `5m` |
| `SPARK` | 6 | `1d` |
| `1M` | 30 | `30m` |
| `6M` | 182 | `60m` |
| `1Y` | 365 | `1d` |
| `5Y` | 1825 | `1wk` |
| `ALL` | 7300 | `1mo` |

#### Mapping

Mirrors `instrumentRoutes.js` exactly:

- drop bars whose `open` is null — Yahoo pads intraday sessions with placeholder bars;
- emit `time` as the bar's unix seconds **+ 19800** (IST) — `meta.gmtoffset` is 19800 for these
  symbols, so this is the UTC epoch expressed as IST wall-clock;
- emit `open`/`high`/`low`/`close` only: no volume, no `adjclose`, and no adjustment for splits or
  dividends;
- a result with no bars is `[]` with a 200, not an error, because that is what `res.json([])` does;
- a provider error object, a missing result, a non-2xx response and a non-JSON body all raise
  `MarketDataError`, which the route turns into `404 {"message": "Could not fetch candle data"}` —
  the single message Express uses for *every* failure, an unknown symbol included.

#### Observed bar counts

From the 2026-10-18 run, via the implemented route:

| `range` | `RELIANCE` | `^NSEI` |
|---|---|---|
| `1D` | 362 | 375 |
| `5D` | 220 | 223 |
| `SPARK` | 5 | 5 |
| `1M` | 246 | 247 |
| `6M` | 866 | 870 |
| `1Y` | 246 | 245 |
| `5Y` | 262 | 262 |
| `ALL` | 241 | 231 |

Yahoo caps intraday history by its own retention rather than by the requested window: the `1D`
request asks for 3 days and comes back with one session, and `5D` asks for 5 days and comes back with
three. That is the provider's behaviour and Express inherits it unchanged, so it is reproduced rather
than corrected.

#### How this was verified

Rather than assume the two libraries agree, `yahoo-finance2` was installed in a scratch directory
outside the repo, its outgoing chart URL was captured by wrapping `fetch`, and its `chart()` result
was mapped with the exact code from `server/routes/instrumentRoutes.js`. That reference output was
then compared with `api.market_data.fetch_candles` — 16 comparisons (2 symbols × 8 ranges), all
identical on bar count, first/last `time`, and first/last OHLC. The scratch harness is not part of
the repo.

### 3.2 Live prices — done in Phase 2b (streaming evaluated, not adopted)

**Verdict: the stream works for Indian symbols, but it cannot replace the polling jobs, and adopting
it now would add a stateful always-on connection for no visible benefit. Recommendation: keep REST
polling.** Evidence below.

The plan treated this as a hypothesis. It was tested during a live session on Monday 2026-10-19,
13:57–14:11 IST (NSE open, 09:15–15:30), with `RELIANCE.NS`, `INFY.NS`, `TCS.NS`, `HDFCBANK.NS`,
`^NSEI` and `^NSEBANK`.

#### Verified

| Question | Result |
|---|---|
| Endpoint / auth | `wss://streamer.finance.yahoo.com/?version=2`; no auth, crumb or cookie needed. |
| Do `.NS` symbols stream? | Yes — all four equities delivered frames. |
| Do `^` indices stream? | Yes — `^NSEI` and `^NSEBANK`, at the highest rate of all. |
| Frame format | Text frames only: `{"type":"pricing","message":"<base64 protobuf>"}`. |
| Update rate | ~1 update/second/symbol. A 240 s run gave 190–242 frames per symbol; median gap 1.0 s, worst gap 6.0 s. |
| Field names | `id`, `price`, `time`, `exchange` (`NSI`), `quote_type`, `market_hours`, `change`, `change_percent`; stocks also `day_volume`, `last_size`, `price_hint`. |
| Timestamp | **zigzag `sint64` milliseconds** — not seconds, and not a plain varint (see the trap below). |
| Price agreement | Stream vs the Phase 2a REST path: `RELIANCE` Δ0.4, `INFY` Δ0.0, `^NSEI` Δ0.3. |
| Reconnect after an abrupt transport abort | Detected; handshake 1.77 s, first frame 2.40 s. |
| Unsubscribe | Frames stop after one in-flight message per symbol. |
| Concurrent connections | 3 from one host all streamed normally. |

The prices were genuinely live rather than stale: `^NSEI` streamed `price=22889.05, change=-257.10`,
and `price - change = 23146.15` — exactly the previous session's close.

#### The timestamp trap

`pricing.proto` declares `sint64 time = 3` and `sint64 day_volume = 9`, and protobuf encodes `sint64`
as a **zigzag** varint. Reading `time` as a plain varint yields a plausible-looking integer that is
off by a factor of two and decodes to a date in **2083**, with no error raised. `api/yahoo_stream.py`
decodes zigzag explicitly, and a test pins it against real captured frames.

#### What the stream does not provide

This is the decisive finding. `marketSync` writes nine fields; the stream covers five of them:

| Cache field | Stream | Notes |
|---|---|---|
| `ltp` | `price` | |
| `dayChange` | `change` | |
| `dayChangePct` | `change_percent` | |
| `prevClose` | — | derivable as `price - change`; not sent directly |
| `volume` | `day_volume` | stocks only; indices never send it |
| `name`, `kind` | — | come from the static `data/nifty50` seed anyway |
| `marketCap` | **absent** | drives the Markets table column and the heatmap sizing |
| `sector` | **absent** | comes from `quoteSummary(assetProfile)` |

`SectorHeatmap.jsx` filters `marketCap > 0`, so a streaming-only cache would blank the heatmap. The
5-minute REST batch would have to keep running for `marketCap` and `sector` regardless, which removes
most of the reason to add a second, stateful data path.

#### Operational hazards

- **Unsupported symbols fail silently.** Subscribing to `NOTAREALSYMBOL.NS` and `ZZZZ.NS` produced no
  frames, no error frame and no rejection. Absence is the only signal, so a symbol that never updates
  is indistinguishable from one whose market is closed. Any adoption must detect staleness per symbol
  rather than trust the subscription.
- **Silence is ambiguous.** No frames could mean a closed market, a delisted symbol, or a dead socket.
  Only a heartbeat or a timestamp check tells them apart.
- **A heartbeat is prudent.** 240 s with no re-subscribe was stable, but yfinance re-subscribes every
  15 s and that is cheap insurance.
- **No holiday calendar** exists in the app today, so "market open" means weekday plus 09:15–15:30.

#### yfinance's own client

`yfinance.live.AsyncWebSocket` does work against this stream (verified by running it, not just by
reading it), but two defects matter:

- It decodes with `MessageToDict`, which renders `int64`/`sint64` as **strings**, so `time` arrives as
  `"1792399388000"` and `day_volume` as a string. Any arithmetic needs a cast first.
- In `listen()`, the `except Exception` path sleeps 3 s and calls `_connect()`, but `_connect()`
  returns early while `self._ws is not None`. After a clean close the `while True` loop can therefore
  re-enter without establishing a fresh connection. **Read from source; not exercised.**

Both are why the proof of concept decodes with a small standard-library parser instead of adopting
the library.

#### Decision

**Do not adopt streaming in this phase. Keep REST polling as the cache's source of truth.**

Reasons, in order of weight:

1. `marketCap` and `sector` are only available over REST, so the batch job cannot be removed.
2. The instrument page polls every 30 s (`useInstrument.jsx` `POLL_MS = 30000`). A 1 s feed behind a
   30 s poll has no visible effect.
3. Express parity is REST polling. A stateful always-on connection is new operational surface —
   reconnect loops, per-symbol staleness detection, one socket per worker — for no user-visible gain.
4. It would make the backend the authority for a value the frontend reads every 30 s anyway.

**Smallest practical alternative if a genuine sub-minute requirement appears:** keep the REST batch
for `marketCap`/`sector`, and use this stream only to refresh `ltp`/`dayChangePct`/`volume` for
symbols currently on screen, with REST reconciliation. `api/yahoo_stream.py` (decoder only, standard
library, tested against real frames) is the starting point; nothing is wired into the application and
no socket is opened at runtime.

#### Not verified

- **A full trading session.** The soak was ~14 minutes, not 09:15–15:30. Long-run stability, behaviour
  at the close, and reconnects over hours are unknown.
- **Market open and close**, including whether frames stop cleanly at 15:30.
- **A holiday or a weekend.** Only one live weekday session was observed.
- **Network failures other than an abrupt local abort** — DNS loss, a proxy dropping long-lived
  connections, a suspended laptop.
- **Whether Yahoo's terms permit this use** — still open (§5e), and unchanged by these results.

### 3.3 Provider adapter

```
MarketDataProvider (interface)
  ├─ get_quote(symbol) -> dict           # maps to the current quote fields
  ├─ get_candles(symbol, range) -> list  # time/open/high/low/close
  ├─ get_quotes(symbols) -> dict         # batch
  └─ (optional) subscribe(symbols) -> stream
```

Requirements:

- Routes, order execution and jobs depend on the interface, never on `yfinance` directly.
- The adapter owns symbol normalisation (`tickerFor`) and field mapping, so swapping providers does
  not touch business logic.
- Provider errors map to the current status codes: instrument routes return 404; MARKET order
  placement returns 503.

### 3.4 Jobs

- Keep price sync, market sync and the daily snapshot as scheduled jobs. The provider choice does not
  remove the need for the snapshot or for reconciliation.
- **One process owns the schedules.** No overlap with the Express deployment.
- Preserve the market-hours gate (Mon–Fri 09:15–15:30 IST) and note that there is **no holiday
  calendar** today. Decide explicitly whether to add one; do not add it silently.
- Preserve single-flight behaviour (the `isSyncing` flag) or replace it with an equivalent lock.

### 3.5 Backend → frontend delivery

Currently the UI polls REST endpoints on navigation/interval; there is no push channel.

If live prices are adopted, the provider → backend ingestion and backend → frontend delivery are
**separate decisions**. Options for delivery include keeping REST polling of fresh values, SSE, or a
WebSocket to the browser. Choose one deliberately and document it. Do not introduce a push channel
that the React app does not already consume.

---

## 4. Fallbacks and alternatives

| Option | Requirement | Status |
|---|---|---|
| Poll Yahoo's chart endpoint directly | an HTTP client only | **in use for candles (Phase 2a)** |
| Poll Yahoo through `yfinance` | pandas + numpy | **rejected for candles** — a different series for 5 of the 8 ranges, see §3.1 |
| Keep REST polling for quotes | an HTTP client only | **recommended (Phase 2b)** — `marketCap`/`sector` need it anyway, see §3.2 |
| Yahoo streaming via `AsyncWebSocket` | must pass the feasibility test | **works, not adopted** — the stream is real but cannot replace the batch; see §3.2 |
| Upstox | account, API access, approval, terms | **evaluate only after documenting requirements**; do not assume access |
| Another broker/data API | account and terms | not evaluated |

Do not state that a provider is approved for this use until its terms have been reviewed.

---

## 5. Open questions — must be answered before Phase 2 is called complete

| # | Question | How to answer |
|---|---|---|
| a | Does Yahoo's stream return messages for the exact Indian symbols (`.NS`) used here? | **Answered (Phase 2b): yes** for `.NS` equities and `^` indices — see §3.2 |
| b | What is the update frequency and connection stability? | **Partly answered (Phase 2b):** ~1 update/s/symbol, worst gap 6 s over a 14-minute run, reconnect in ~2 s. A full session is still unmeasured — see §3.2 |
| c | Which candle intervals and historical ranges are retrievable? | **Answered (Phase 2a):** all eight ranges return data, through `yfinance` and through the chart endpoint alike; see §3.1 |
| d | How do timestamps, field names and symbol formats normalise? | **Answered (Phase 2a):** `time` = the bar's UTC epoch + 19800; fields are `time`/`open`/`high`/`low`/`close`; `^` symbols pass through and everything else gets `.NS`. Verified against `yahoo-finance2` itself; see §3.1 |
| e | Is provider data permitted for the intended display and deployment? | Read the provider terms; record the conclusion — **still open**; Phase 2b did not settle it |
| f | If streaming fails, which fallback is approved, and what account/infrastructure does it need? | **Answered (Phase 2b):** no new infrastructure. Keep REST polling; the stream stays an option, see §3.2 |

---

## 6. Parity tests for Phase 2

| Test | Expected |
|---|---|
| Candles for each of the eight ranges | Same key set; sane bar counts; timestamps carry the IST shift — **closed in Phase 2a**, see §3.1 |
| Empty-bar filtering | Bars without open are absent — **closed in Phase 2a**, see §3.1 |
| Streamed quote for an `.NS` symbol | Real frames, sane price, decodable timestamp — **verified in Phase 2b**, see §3.2 |
| Stream vs REST agreement | Prices within a tick — **verified in Phase 2b**, see §3.2 |
| Instrument detail | Same field names; missing values omitted rather than nulled |
| Lookup for an unknown symbol | 404 `{ message: "Instrument not found" }` |
| MARKET order with a live quote | Fills at the quote; holdings/positions/funds updated |
| MARKET order while provider is down | 503 with the documented message |
| Square-off while provider is down | Falls back to stored `ltp`, still succeeds |
| Price sync outside market hours | No provider calls |
| Price sync with one symbol failing | Other symbols still update; failure is logged |
| LIMIT order crossing | Fills once, at the limit price |
| SL/SL-M trigger crossing | Fires once; sibling exit cancelled |
| MIS exit | Position deleted; P&L settled; funds released |
| Snapshot job re-run | No duplicate row for the same user/day |
| Concurrent matching cycles | No double fill (atomic claim holds) |

Record actual results in [MIGRATION_STATUS.md](./MIGRATION_STATUS.md). Do not mark a test passed
because the endpoint returned 200.
