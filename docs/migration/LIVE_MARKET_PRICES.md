# Live market prices (Yahoo stream → browser)

An optional upstream WebSocket feed for intraday prices. It does **not** replace
the scheduled REST sync, the persisted quote cache, or order matching. The
default is off: with `LIVE_QUOTES_ENABLED` unset the app behaves exactly as it
did before this feature.

## What moves and what does not

```
Yahoo streamer ──► one FastAPI connection ──► in-memory cache
                                                  │
                              immediate ──────────┼──► /api/quotes/stream
                                                  │
              every LIVE_QUOTES_FLUSH_SECONDS ───┴──► latest_quotes (PostgreSQL)
                                                          │
                                        existing REST reads and watchlist stream
```

- `latest_quotes` is still the persisted latest quote. The live feed updates
  rows; there is no tick history table and no Redis.
- Browser delivery happens **before** the database write, deliberately: the
  cache exists so a tick does not wait for the coalesced flush. A restored row
  is labelled `live: false` and never claims to be a fresh tick.
- Order placement, matching, portfolio math and trading semantics are
  unchanged. `price_sync` still runs on its one-minute schedule and is the
  only thing that fills crossed orders.

## Configuration

Add to `api/.env`:

```env
# Optional, defaults to OFF. Opens one upstream Yahoo stream per API process.
LIVE_QUOTES_ENABLED=true

# Optional, default 5 seconds, minimum 0.5. How often pending ticks are
# written to latest_quotes. Browser delivery is not delayed by this.
# LIVE_QUOTES_FLUSH_SECONDS=5

# Optional, default 60 seconds, minimum 5. A quote older than this is marked
# stale in the frame, and a tick older than this is not accepted at all.
# LIVE_QUOTES_STALE_SECONDS=60
```

`api/config.py` reads these at call time, so tests patch the environment
without restarting anything.

## Provider caveat (read before enabling)

The endpoint is `wss://streamer.finance.yahoo.com/?version=2`. Yahoo does not
publish it as a supported market-data API and its terms do not grant
redistribution rights. This repository therefore:

- ships the feed **off** by default;
- subscribes only to the same 53-symbol universe the REST cache already uses;
- opens **one** connection per process, never one per browser;
- does not label the source as authorised for redistribution.

Whether this use is acceptable is a decision for the operator of a deployment,
not something this code can assert. If it is not, leave the flag off; the REST
sync remains a complete fallback.

## Symbol coverage

The upstream subscription is built from `INDICES` + `NIFTY50` in
`api/data/nifty50.py` and mapped with `ticker_for`, so it matches
`market_sync`. Book-only instruments (`in_market_universe = false`, added by
`price_sync` for a held or ordered symbol outside that list) are **not**
streamed. They keep updating through the existing REST sync. Their rows are
still returned in snapshots when the cache has a restored value, but no live
frame arrives for them.

Two symbols are normalised on the way in: `INFY.NS` → `INFY`, and `^NSEI`
stays as it is.

## Browser contract

`/api/quotes/stream?symbols=INFY,TCS,^NSEI` authenticates with the same `token`
cookie as the REST routes.

- A missing or invalid token is accepted and closed with `1008`, the same
  pattern as `/api/watchlist/stream`. The client stops retrying on `1008`.
- On connect the server sends one `status` frame, then a `quotes` snapshot when
  the cache has any of the requested symbols:

```json
{"type": "status", "enabled": true, "state": "live", "streaming": true,
 "staleAfterSeconds": 60, "flushSeconds": 5,
 "connectedAt": "...", "lastTickAt": "..."}

{"type": "quotes", "quotes": [
  {"symbol": "INFY", "ltp": 1512.5, "dayChange": 12.5, "dayChangePct": 0.83,
   "updatedAt": "...", "sourceTime": "...", "receivedAt": "...",
   "live": true, "restored": false, "stale": false}
]}
```

- `subscribe` / `unsubscribe` messages with a `symbols` list extend or shrink
  the set without reconnecting. A `subscribe` is answered with a snapshot.
- `sourceTime` is the provider's market time. `receivedAt` is when this process
  received the tick and is `null` for a value restored from PostgreSQL.
  `updatedAt` is the persistence time (or the receipt time for a tick still
  waiting to be flushed).
- `restored` is `true` only for a value seeded from `latest_quotes` at startup.
  The frontend treats it as first paint, not a price update, so it cannot
  freeze a row that the REST poll is still refreshing. A polling frame has
  `live: false, restored: false` because it is a newly committed row.
- The `status` frame is also re-sent on the flush interval, so a dropped or
  recovered upstream connection reaches the browser without a reconnect.

`/api/watchlist/stream` keeps its existing frame shape and polling publisher.
It is unchanged for older clients.

## Freshness and ordering rules

Server (`api/quote_cache.py`, `api/quote_service.py`):

- a price must be a finite number greater than zero;
- a tick needs a provider `sourceTime`;
- a tick older than `LIVE_QUOTES_STALE_SECONDS`, or more than 120 seconds in
  the future, is dropped;
- a tick whose `sourceTime` is not strictly newer than the cached one is
  dropped, which also absorbs duplicate frames after a reconnect;
- a value restored from `latest_quotes` never replaces a live cached tick.

Persistence:

- `flush()` keeps only the newest pending tick per symbol and writes them with
  the existing `persist_price_quotes`;
- a failed write leaves the pending entries queued for the next attempt, and a
  newer tick that arrived meanwhile wins;
- after a successful write the watchlist channel is notified;
- `stop()` flushes whatever is still pending.

Fallback and the polling conflict:

- `price_sync` and `market_sync` only publish generic polling frames while the
  upstream feed is **not** streaming. Watchlist polling frames stay
  unconditional for backward compatibility.
- The frontend compares `sourceTime` only. An update without a provider time
  cannot replace a live row that has one, so a REST poll cannot move a
  streamed price backwards. A restored snapshot (`live: false`) is only a
  seed and never blocks the REST row, so polling keeps moving prices while the
  upstream feed is down.
- If the socket is unavailable the pages keep their REST behaviour; the badge
  reports `Offline`, `Polling` or `Reconnecting` rather than pretending to be
  live.

## Frontend

- `src/features/dashboard/quotes/QuoteContext.jsx` — one socket per dashboard,
  ref-counted subscriptions, backoff reconnect, `1008` stop.
- `src/features/dashboard/quotes/quoteMerge.js` — pure merge/freshness rules.
- `src/features/dashboard/quotes/LivePriceBadge.jsx` — the header state badge.
- `QuoteProvider` wraps the dashboard shell in
  `src/features/dashboard/pages/Dashboard.jsx`.
- `useMarketOverview`, `useHoldings`, `usePositions`, `useInstrument` and
  `useWatchlist` overlay the shared store on their REST rows. Rows are only
  updated in place: a streamed symbol never adds or reorders a table line.
- The watchlist keeps its 30-second REST poll and its flash animation; the
  poll result is re-overlaid with the newest streamed quotes.
- `useWatchlistStream.jsx` and `/api/watchlist/stream` are untouched.

## Tests

Backend (no network, no real Yahoo calls):

```
pytest api/tests/test_yahoo_stream.py api/tests/test_quote_cache.py \
       api/tests/test_quote_feed.py api/tests/test_quote_service.py \
       api/tests/test_quotes_stream.py -q
```

They cover decoder fixtures, invalid/stale/out-of-order ticks, restore-vs-live
precedence, coalesced writes, failed-write retry, shutdown flush, feed
disabled/reconnect/stop, WebSocket auth (`1008`), snapshots, subscribe and
subscriber isolation.

Frontend merge rules:

```
npm run test:quotes
```

## Limitations

- One upstream connection per FastAPI process. Two processes with
  `LIVE_QUOTES_ENABLED=true` open two connections and both flush the same rows;
  run it in exactly one process, like the scheduler switches.
- Browser delivery is real-time, but PostgreSQL lags by up to
  `LIVE_QUOTES_FLUSH_SECONDS`. A REST read in that window can return the
  previous price; the frontend keeps the newer streamed value.
- Order matching is still schedule-driven. A live tick does not fill a crossed
  order; the next `price_sync` tick does. Expect up to one minute of matching
  latency, unchanged from before this feature.
- Only the 53-symbol universe is streamed; book-only symbols stay REST-only.
- The streamer sends nothing outside market hours. The UI reports the feed
  state, not a promise of continuous ticks.
- No history, backfill or replay: a browser that misses a tick gets the next
  one or the REST poll.
