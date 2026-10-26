# Live watchlist quotes (Phase 3C2 parallel task)

A small push channel beside the existing watchlist REST API. It does not fetch
market data and does not replace the REST read: the page still paints from
`GET /api/watchlist`, then applies pushed price changes.

## Endpoint and authentication

`GET /api/watchlist/stream` upgrades to a WebSocket. The handshake reads the
same `token` cookie as every HTTP route, verified by `user_from_token` in
`api/auth.py`. A missing or invalid token is accepted and immediately closed
with code `1008`; a browser cannot read a close code from a rejected handshake,
and `1008` lets the client stop retrying instead of looping forever.

Each connection is registered against the JWT's user id. A frame is only sent
to sockets whose user has a matching `watchlists` row, so one user's symbols
never reach another user's socket.

## Where updates come from

`price_sync` already fetches quotes and persists them in one PostgreSQL
transaction. After that transaction commits it calls
`publish_persisted_quotes` (`api/watchlist_stream.py`), which:

1. returns immediately when no socket is connected;
2. reads `watchlists` joined to `instruments` and `latest_quotes` for the
   symbols in that tick, so membership is current and the price is the
   committed row rather than the provider payload;
3. schedules one `{"type": "quotes", "quotes": [...]}` frame per connection on
   the FastAPI event loop with `asyncio.run_coroutine_threadsafe`.

A failed read is logged and swallowed: live delivery is best-effort and must
not fail the job that also fills orders. When `price_sync` is not running, the
REST poll remains the only price source, exactly as before.

The hub is in-process, like the existing scheduler ownership and rate limiter.
That is sufficient for the current single-service deployment; running the API
and `price_sync` in different processes would need a shared bus, which is
deliberately out of scope here.

Frame quote fields: `_id` (watchlist row), `symbol`, `ltp`, `dayChangePct`,
`updatedAt`.

## Frontend

`src/features/dashboard/hooks/useWatchlistStream.jsx` opens the socket only
after the initial REST load finishes. `useWatchlist` merges frames by watchlist
row id and reuses the existing flash animation. A close retries with exponential
backoff (5 s to 30 s); `1008` is terminal. The hook closes the socket and clears
its retry timer on unmount. The existing 30-second REST poll is unchanged as a
fallback.

## Tests

`api/tests/test_watchlist_stream.py` covers:

- missing and invalid cookie rejection (`1008`);
- two users receiving only their own watchlist rows;
- a frame carrying the committed PostgreSQL values;
- a watchlist row with no quote being omitted;
- a failed quote read being swallowed while the socket survives;
- disconnect removing the hub subscription;
- `price_sync.run_sync` persisting then publishing end to end.

Run focused:

```
pytest api/tests/test_watchlist_stream.py api/tests/test_watchlist.py \
       api/tests/test_price_sync.py -q
```

PostgreSQL tests need `TEST_DATABASE_URL` pointing at a disposable `*_test`
database; they skip when it is unset.

## Coordination with `phase3c2b-postgres-readers`

This branch does not change that branch's portfolio, snapshot or Nova reader
files, nor `api/main.py`, `api/scheduler.py`, `api/tests/conftest.py`,
`AGENTS.md` or `MIGRATION_STATUS.md`. The shared touch points are:

- `api/jobs/price_sync.py` — one additive call after quote persistence;
- `api/routes/watchlist.py` — the WebSocket route;
- `api/auth.py` — `user_from_token` extracted from `require_user`;
- `src/features/dashboard/hooks/useWatchlist.jsx` and
  `src/services/api.js` — frontend wiring.

Phase 3C2-B does not edit those files, so the merge should be additive.
