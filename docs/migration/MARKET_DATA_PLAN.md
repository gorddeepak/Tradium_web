# Market Data Plan

**Status:** Phases 2a–2d are implemented and measured: historical candles (§3.1), streaming evaluated
and **not** adopted (§3.2), REST quotes and the provider adapter (§3.3), and the scheduled jobs
(§3.4). The cache those jobs fill was moved from MongoDB's `marketquotes` collection to PostgreSQL in
Phase 3B2 — see §3.6. No WebSocket, push channel or streaming ingestion exists in the application.

---

## 1. What consumes market data today

| Consumer | Endpoint / job | Provider call | Required fields |
|---|---|---|---|
| Instrument search | `GET /api/instruments/search` | none (PostgreSQL cache only) | cached `ltp`, `dayChangePct` |
| Instrument lookup | `GET /api/instruments/lookup/:symbol` | `quote()` | `regularMarketPrice`, `regularMarketChange`, `regularMarketChangePercent`, names |
| Instrument detail | `GET /api/instruments/:symbol` | `quote()` | above + open, high, low, prevClose, volume, 52-week high/low |
| Candles | `GET /api/instruments/:symbol/candles` | `chart()` | OHLC per bar, with empty bars filtered |
| Markets page | `GET /api/market/overview` | none (PostgreSQL cache only) | `instruments` ⋈ `latest_quotes`, max `updated_at` |
| Market cache refresh | `jobs/market_sync.py` | batch `quote(53 tickers)` | ltp, dayChange, dayChangePct, prevClose, volume, marketCap, sector → `instruments`/`latest_quotes` |
| Price sync | `jobs/price_sync.py` | batch `quote()` for held/ordered/watchlisted symbols | `regularMarketPrice`, `regularMarketChangePercent`; mirrors Mongo `ltp` and upserts the PostgreSQL quote (§3.6) |
| Sector backfill | both jobs | `quoteSummary()` `assetProfile` | `sector` on `instruments` |
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

**Implemented for REST quotes in Phase 2c.** The shape that shipped:

```
api/market_data.py
  ├─ fetch_quote_row(symbol)  -> raw Yahoo quote row | None   # detail routes; raises on provider failure
  ├─ fetch_quote(symbol)      -> {"ltp", "dayChangePct"} | None # orders/square-off; swallows failures
  ├─ fetch_quotes(tickers)    -> {ticker: raw row}             # cache sync batch
  ├─ fetch_sector(symbol)     -> str ("" when absent)          # cache backfill
  └─ fetch_candles(...)       -> bars                          # Phase 2a, unchanged
```

Requirements:

- Routes, order execution and jobs depend on these functions, never on `yfinance` directly.
- The adapter owns symbol normalisation (`ticker_for`) and field mapping, so swapping providers does
  not touch business logic.
- Provider errors map to the current status codes: instrument routes return 404; MARKET order
  placement returns 503. That distinction is deliberate and lives in two places on purpose —
  `fetch_quote` swallows errors (Express's `fetchQuote` catches its own), while `fetch_quote_row`
  raises so the routes can apply Express's bare `catch { 404 }`.

#### The quote endpoint needs credentials the chart endpoint does not

Measured in Phase 2c. A bare `GET /v7/finance/quote` answers `401` with
`{"code":"Unauthorized","description":"Invalid Crumb"}`. The working handshake:

| Step | Request | Result |
|---|---|---|
| 1 | `GET https://fc.yahoo.com` | `404` by design; sets the `A3` cookie |
| 2 | `GET https://query1.finance.yahoo.com/v1/test/getcrumb` | plain-text crumb |
| 3 | `GET https://query2.finance.yahoo.com/v7/finance/quote?symbols=…&crumb=…` | `200` |

`yahoo-finance2` bootstraps from `https://finance.yahoo.com/quote/AAPL` instead. **That does not work
from `requests`**: the request returns a 301 with no `Set-Cookie`, so step 2 fails. Use
`fc.yahoo.com`. The session and crumb are cached process-wide; a `401` triggers one forced
cookie+crumb refresh (a new crumb alone still answers 401).

`quoteSummary` for the sector uses the same crumb against
`https://query2.finance.yahoo.com/v10/finance/quoteSummary/{ticker}?formatted=false&modules=assetProfile`.

#### Known gaps in the adapter

- **No staleness cutoff.** Express has none, and measurements show why a naive one is unsafe: at
  15:31 IST (one minute after the close) `regularMarketTime` ages were `^NSEI` 1 s, `RELIANCE` 106 s,
  `^BSESN` **903 s**. A 5-minute threshold would have rejected a legitimately current quote and turned
  valid MARKET fills into 503s. Missing, non-numeric, zero and negative prices *are* rejected. Adding
  an age check is an open decision, not an oversight.
- **No holiday calendar** — inherited from Express (§3.4).
- **Indices carry no `marketCap`.** Yahoo omits the key, so `?? 0` writes `0`, and the `marketCap > 0`
  heatmap filter excludes them. That is the existing behaviour, reproduced.
- **`^NSEI` has no `quoteSummary` profile** (404), so its sector stays `""` — which is correct, since
  the backfill only asks for `kind: "stock"`.

### 3.4 Jobs

- Keep price sync, market sync and the daily snapshot as scheduled jobs. The provider choice does not
  remove the need for the snapshot or for reconciliation.
- **One process owns the schedules.** No overlap with the Express deployment. Enforced in code, not
  just documented: `MARKET_SYNC_ENABLED` gates the tick and **defaults to off**; `create_app(database=…)`
  (tests) never starts it. The in-process `threading.Lock` stops overlapping ticks within one process;
  it is **not** a cross-process lease, so the flag must be set on exactly one worker.
- Preserve the market-hours gate (Mon–Fri 09:15–15:30 IST) and note that there is **no holiday
  calendar** today. Decide explicitly whether to add one; do not add it silently. *(Port:
  `api/market_hours.py`; whole-minute comparison, inclusive at both ends, IST as a fixed +05:30 offset
  since India has no DST and `tzdata` is not installed.)*
- Preserve single-flight behaviour (the `isSyncing` flag) or replace it with an equivalent lock.
  *(Port: non-blocking `threading.Lock`. A tick arriving mid-run returns immediately.)*
- The cache sync keeps the last good rows on a provider failure — stale prices beat an empty Markets
  page — and still runs the sector backfill when the quote refresh is skipped.

### 3.5 Backend → frontend delivery

Currently the UI polls REST endpoints on navigation/interval; there is no push channel.

If live prices are adopted, the provider → backend ingestion and backend → frontend delivery are
**separate decisions**. Options for delivery include keeping REST polling of fresh values, SSE, or a
WebSocket to the browser. Choose one deliberately and document it. Do not introduce a push channel
that the React app does not already consume.

### 3.6 Cache persistence — moved to PostgreSQL in Phase 3B2

The cache is no longer MongoDB's `marketquotes` collection. It lives in two PostgreSQL tables created
by `api/migrations/versions/0001_initial_schema.py`:

| Table | Holds |
|---|---|
| `instruments` | one row per symbol: `symbol` (unique), `name`, `kind` (`stock`/`index`), `sector`, `in_market_universe` |
| `latest_quotes` | one row per instrument (`instrument_id` primary key, `ON DELETE CASCADE`): `ltp`, `day_change`, `day_change_pct`, `prev_close`, `volume`, `market_cap`, `updated_at`, `source_time` |

Ownership:

- `api/jobs/market_sync.py` owns the **53-symbol universe** (3 indices + 50 stocks). It upserts every
  universe symbol even when the provider omits a row, so `instruments` can hold all 53 while
  `latest_quotes` holds only the symbols that returned a usable price. A seeded symbol with no quote
  stays invisible to both read routes, which is what the Mongo cache did implicitly.
- `api/jobs/price_sync.py` adds **book-only** instruments (`in_market_universe = false`) for symbols
  that are held, watchlisted or in an OPEN order but outside the universe. It writes only `ltp`,
  `day_change_pct`, `updated_at` and `source_time`, so the richer market-sync columns and the
  instrument's identity survive a one-minute tick.
- Sector backfill belongs to `instruments`. Either job may call it, capped at 10 unresolved symbols per
  run. The quote upsert never writes `sector`, so a price cycle cannot blank it; the backfill never
  touches `latest_quotes.updated_at`. While holdings remain Mongo-backed, `price_sync` also mirrors a
  sector it just resolved onto a holding whose `sector` is still empty, as a temporary read projection.

Two timestamps, deliberately separate:

- `updated_at` — when this service persisted the quote. It is the `updatedAt` the API has always
  exposed and the value `asOf` reports on `/api/market/overview`.
- `source_time` — the provider's `regularMarketTime`, or `NULL`. A missing provider time is **never**
  replaced by the write time.

Stale-quote rule (`api/market_store.py`):

- An incoming row whose `source_time` is **older** than the stored one is dropped, so a late provider
  response cannot overwrite a newer price.
- A row with **no** `source_time` is applied and clears the stored `source_time`: the price is the
  newest poll result but cannot be tied to a provider timestamp.
- A missing, zero, negative or non-numeric price never creates or overwrites a quote. A provider
  failure leaves the last good cache in place, so stale prices survive instead of blanking the Markets
  page.

Reads:

- `GET /api/market/overview` and `GET /api/instruments/search` join `instruments` to `latest_quotes`
  and filter `in_market_universe = true`.
- The wire shape is unchanged: `_id`, `symbol`, `name`, `kind`, `sector`, `ltp`, `dayChange`,
  `dayChangePct`, `prevClose`, `volume`, `marketCap`, `createdAt`, `updatedAt`, `__v`.
- `search` keeps the approved relevance order — exact symbol, symbol prefix, name prefix, substring —
  escapes `%` and `_` so the term is literal, and caps the result at 10 rows.
- Order is explicit, because PostgreSQL has none: overview returns indices `^NSEI`, `^NSEBANK`,
  `^BSESN` (unknown indices first) and stocks by `symbol ASC`. Express returned MongoDB natural order,
  which happened to follow the seed list; the change is approved in `POSTGRES_SCHEMA_DESIGN.md` §2.10.
- Both routes keep `Decimal` columns rendering as JSON numbers: integral values as integers, the rest
  as the shortest float (`api/serialization.py`).

Still Mongo: holdings, positions, orders, funds, transactions, watchlists and portfolio snapshots,
including everything Nova's tools read. Authentication (`users`) and the market cache are the only
PostgreSQL-backed surfaces so far.

The market-hours gate, the single-flight locks and the opt-in scheduler switches are unchanged
(§3.4); `MARKET_SYNC_ENABLED` and `TRADING_JOBS_ENABLED` still default to off.

---

## 4. Fallbacks and alternatives

| Option | Requirement | Status |
|---|---|---|
| Poll Yahoo's chart endpoint directly | an HTTP client only | **in use for candles (Phase 2a)** |
| Poll Yahoo's quote endpoint directly (cookie + crumb) | an HTTP client only | **in use for live quotes and the cache (Phase 2c)**, see §3.3 |
| Poll Yahoo through `yfinance` | pandas + numpy | **rejected for candles** — a different series for 5 of the 8 ranges, see §3.1 |
| Keep REST polling for quotes | an HTTP client only | **adopted (Phase 2c)** — `marketCap`/`sector` need the batch anyway, see §3.2 |
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
| g | How old may a quote be before it must not become a fill price? | **Open, narrower.** Phase 3B2 added a provider-time guard to the canonical cache (an older `source_time` cannot overwrite a newer quote — see §3.6), but there is still no age cutoff, and MARKET fills and square-offs use live `fetch_quote`, not the cache. A cutoff needs a decision, not a silent change — see §3.3 |

---

## 6. Parity tests for Phase 2

| Test | Expected |
|---|---|
| Candles for each of the eight ranges | Same key set; sane bar counts; timestamps carry the IST shift — **closed in Phase 2a**, see §3.1 |
| Empty-bar filtering | Bars without open are absent — **closed in Phase 2a**, see §3.1 |
| Streamed quote for an `.NS` symbol | Real frames, sane price, decodable timestamp — **verified in Phase 2b**, see §3.2 |
| Stream vs REST agreement | Prices within a tick — **verified in Phase 2b**, see §3.2 |
| Instrument detail | Same field names; missing values omitted rather than nulled — **closed in Phase 2c**, see §3.3 and `MIGRATION_STATUS.md` §3I |
| Lookup for an unknown symbol | 404 `{ message: "Instrument not found" }` — **closed in Phase 2c** (also for a zero price and a provider failure, as Express does) |
| Batch quote for the whole universe | 53/53 tickers in one request; field-for-field identical to `yahoo-finance2` — **closed in Phase 2c** |
| Market cap and sector survive a price cycle | `sector` written only by the backfill; `marketCap` never blanked — **closed in Phase 2c** |
| Cache persistence after the move to PostgreSQL | 53 instruments seeded, quotes upserted, repeated syncs neither duplicate nor blank metadata — **closed in Phase 3B2**, see §3.6 |
| Stale provider response | An older `source_time` does not overwrite a newer stored quote; a missing one is applied and clears it — **closed in Phase 3B2** |
| Price sync dual-write | Mongo `ltp` updates and the PostgreSQL quote upsert from one provider batch; a PostgreSQL failure does not block fills — **closed in Phase 3B2** |
| MARKET order with a live quote | Fills at the quote; holdings/positions/funds updated — unit-tested with a stubbed quote; Express HTTP parity still PENDING |
| MARKET order while provider is down | 503 with the documented message — covered by `fetch_quote` returning `None` |
| Square-off while provider is down | Falls back to stored `ltp`, still succeeds — covered |
| Quote staleness | **Partly decided (Phase 3B2):** the canonical cache rejects a row whose provider `source_time` is older than the stored one. **No age cutoff on a fresh row** — §3.3 explains why a naive threshold is unsafe |
| Price sync outside market hours | No provider calls |
| Price sync with one symbol failing | Other symbols still update; failure is logged |
| LIMIT order crossing | Fills once, at the limit price |
| SL/SL-M trigger crossing | Fires once; sibling exit cancelled |
| MIS exit | Position deleted; P&L settled; funds released |
| Snapshot job re-run | No duplicate row for the same user/day |
| Concurrent matching cycles | No double fill (atomic claim holds) |

Record actual results in [MIGRATION_STATUS.md](./MIGRATION_STATUS.md). Do not mark a test passed
because the endpoint returned 200.
