"""Market-data provider seam.

Everything here talks to Yahoo Finance, the same provider the Express app uses.
The operations are:

- ``fetch_candles`` — historical OHLC for the instrument chart (§3.1 of
  ``MARKET_DATA_PLAN.md``).
- ``fetch_quote`` — the reduced ``{"ltp", "dayChangePct"}`` shape used by
  MARKET order placement and square-off, matching ``fetchQuote`` in
  ``server/jobs/priceSync.js``.
- ``fetch_quote_row`` — the raw Yahoo quote row, used by the two instrument
  detail routes.
- ``fetch_quotes`` / ``fetch_sector`` — the batch and profile reads behind the
  market-data sync jobs.

The candle and quote endpoints are not the same, and neither is trivial to
reach: candles need no credentials, while the quote endpoints require a cookie
plus a matching "crumb" token. ``_yahoo_session`` reproduces that handshake,
which is what ``yahoo-finance2`` does internally. See ``MARKET_DATA_PLAN.md``
§3.3 for the measurements.

WebSocket streaming was evaluated separately and deliberately not adopted
(§3.2); nothing here opens a socket.
"""

import logging
import math
import threading
from datetime import datetime, timedelta

import requests

logger = logging.getLogger(__name__)

# Yahoo returns raw bar timestamps in UTC; the Express route adds IST's offset
# so the chart shows local time. `meta.gmtoffset` is 19800 for these symbols.
IST_OFFSET_SECONDS = 19800

# The query parameters yahoo-finance2 sends for chart(), in URL order.
CHART_URL = "https://query2.finance.yahoo.com/v8/finance/chart/{ticker}"
YAHOO_PARAMS = {
    "useYfid": "true",
    "includePrePost": "true",  # the library's default; the route never overrides it
    "events": "div|split|earn",
    "lang": "en-US",
}

# The quote endpoints require a crumb. A bare request answers 401 "User is
# unable to access this feature"; fc.yahoo.com hands out the cookie the crumb is
# derived from. That bootstrap 404s by design -- the cookie is the point.
COOKIE_BOOTSTRAP_URL = "https://fc.yahoo.com"
CRUMB_URL = "https://query1.finance.yahoo.com/v1/test/getcrumb"
QUOTE_URL = "https://query2.finance.yahoo.com/v7/finance/quote"
QUOTE_SUMMARY_URL = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/{ticker}"

# yahoo-finance2 relies on its own user agent; Yahoo rejects some clients
# without one. This does not change the data that comes back.
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}
# Express has no explicit timeout; a bounded one avoids hanging a worker.
REQUEST_TIMEOUT_SECONDS = 20

# The eight range/interval pairs from server/routes/instrumentRoutes.js.
CANDLE_RANGES = {
    "1D": (3, "1m"),
    "5D": (5, "5m"),
    "SPARK": (6, "1d"),
    "1M": (30, "30m"),
    "6M": (182, "60m"),
    "1Y": (365, "1d"),
    "5Y": (365 * 5, "1wk"),
    "ALL": (365 * 20, "1mo"),
}
# Anything unrecognised falls back to the Express default.
DEFAULT_CANDLE_RANGE = (30, "1d")

# One session for the process: the cookie and crumb are reused until Yahoo
# rejects them. A lock because the sync job runs in a worker thread while
# requests arrive on the event loop.
_session = None
_crumb = None
_session_lock = threading.Lock()


class MarketDataError(Exception):
    """The provider could not answer. The routes turn this into a 404 or a 503."""


def ticker_for(symbol):
    """NSE-only: indices keep Yahoo's own ``^`` symbol, stocks get ``.NS``."""
    return symbol if symbol.startswith("^") else f"{symbol}.NS"


def _yahoo_session(force_refresh=False):
    """Return a ``requests.Session`` holding a cookie and its crumb.

    Yahoo's quote endpoints answer 401 without both. The pair is cached for the
    process; ``force_refresh`` re-runs the handshake when a request is rejected,
    which is how an expired cookie is handled.
    """
    global _session, _crumb

    with _session_lock:
        if _session is not None and _crumb is not None and not force_refresh:
            return _session, _crumb

        session = requests.Session()
        session.headers.update(REQUEST_HEADERS)
        try:
            # 404 is the expected status; the Set-Cookie header is what matters.
            session.get(COOKIE_BOOTSTRAP_URL, timeout=REQUEST_TIMEOUT_SECONDS)
            response = session.get(CRUMB_URL, timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
            crumb = response.text.strip()
        except requests.RequestException as err:
            raise MarketDataError(f"could not obtain a Yahoo crumb: {err}") from err

        if not crumb or "<" in crumb:
            raise MarketDataError("Yahoo returned an unusable crumb")

        _session, _crumb = session, crumb
        return _session, _crumb


def _request_quotes(tickers):
    """Fetch raw quote rows for ``tickers``. Returns a list, possibly empty.

    One request for the whole batch, as ``marketSync`` does. A symbol Yahoo does
    not know is simply absent from the result; that is not an error.
    """
    for attempt in range(2):
        session, crumb = _yahoo_session(force_refresh=attempt > 0)
        try:
            response = session.get(
                QUOTE_URL,
                params={"symbols": ",".join(tickers), "crumb": crumb},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as err:
            raise MarketDataError(str(err)) from err

        # 401 means the crumb went stale; retry once with a fresh one.
        if response.status_code == 401 and attempt == 0:
            logger.info("Yahoo rejected the crumb, refreshing it")
            continue

        try:
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as err:
            raise MarketDataError(str(err)) from err
        except ValueError as err:
            raise MarketDataError(f"quote response was not JSON: {err}") from err

        quote_response = payload.get("quoteResponse") or {}
        if quote_response.get("error"):
            raise MarketDataError(str(quote_response["error"]))
        return quote_response.get("result") or []

    raise MarketDataError("Yahoo rejected the crumb twice")


def fetch_quote_row(symbol):
    """Return Yahoo's raw quote row for a symbol, or ``None``.

    The two instrument detail routes need fields ``fetch_quote`` drops, so they
    read the row directly. ``None`` means "Yahoo answered but has no such
    symbol"; a provider failure raises ``MarketDataError``, which is what the
    routes' bare ``catch`` turns into their 404.
    """
    ticker = ticker_for(symbol)
    rows = _request_quotes([ticker])
    for row in rows:
        if row.get("symbol") == ticker:
            return row
    return None


def fetch_quote(symbol):
    """Return ``{"ltp", "dayChangePct"}`` for a symbol, or ``None``.

    Port of ``fetchQuote`` in ``server/jobs/priceSync.js``: the callers only need
    the last price and the day's percentage move. ``None`` is the "no usable
    price" answer, which both callers already handle -- a MARKET order answers
    503 and a square-off falls back to the stored ``ltp``.

    Provider errors are swallowed into ``None`` rather than raised, because
    Express catches them inside ``fetchQuote`` itself. The callers have no
    handler of their own, so raising here would turn a documented 503 into a 500.
    """
    ticker = ticker_for(symbol)
    try:
        row = fetch_quote_row(symbol)
    except MarketDataError as err:
        logger.error("Price fetch failed for %s: %s", ticker, err)
        return None

    if row is None:
        return None

    price = row.get("regularMarketPrice")
    # Reject anything that is not a usable positive number, so a null, a zero
    # or a non-numeric value never becomes a fill price. Express uses
    # `if (!quote.regularMarketPrice)`, which rejects 0 and NaN too.
    if not _is_usable_number(price) or price <= 0:
        logger.error("No price returned for %s, skipping", ticker)
        return None

    change_pct = row.get("regularMarketChangePercent")
    if not _is_usable_number(change_pct):
        change_pct = 0
    return {"ltp": price, "dayChangePct": change_pct}


def _is_usable_number(value):
    """True for a real number, excluding ``bool`` and ``NaN``/``inf``."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(value)


def fetch_quotes(tickers):
    """Return ``{ticker: quote_row}`` for a batch of Yahoo tickers.

    Used by the market-cache sync, which needs the raw row rather than the
    reduced ``fetch_quote`` shape. Missing tickers are absent from the result,
    which is how ``marketSync`` detects dead symbols. Duplicate tickers are
    removed before the provider request.
    """
    rows = _request_quotes(list(dict.fromkeys(tickers)))
    found = {}
    for row in rows:
        ticker = row.get("symbol")
        if ticker:
            found[ticker] = row
    return found


def fetch_sector(symbol):
    """Return a symbol's sector, or ``""`` when Yahoo has none.

    Mirrors ``fetchSector`` in ``priceSync.js``: the one-time profile lookup, not
    part of the price cycle. Indices have no profile and answer 404, which is not
    an error for this caller.
    """
    ticker = ticker_for(symbol)
    for attempt in range(2):
        session, crumb = _yahoo_session(force_refresh=attempt > 0)
        try:
            response = session.get(
                QUOTE_SUMMARY_URL.format(ticker=ticker),
                params={"formatted": "false", "modules": "assetProfile", "crumb": crumb},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as err:
            raise MarketDataError(str(err)) from err

        if response.status_code == 401 and attempt == 0:
            continue
        # 404 is "no profile for this symbol" (every index), not a failure.
        if response.status_code == 404:
            return ""
        try:
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as err:
            raise MarketDataError(str(err)) from err
        except ValueError as err:
            raise MarketDataError(f"profile response was not JSON: {err}") from err

        results = (payload.get("quoteSummary") or {}).get("result") or []
        if not results:
            return ""
        profile = results[0].get("assetProfile") or {}
        return profile.get("sector") or ""

    raise MarketDataError("Yahoo rejected the crumb twice")


def fetch_candles(symbol, range_name):
    """Return ``[{"time", "open", "high", "low", "close"}]`` for one range.

    Mirrors the Express mapping: drop bars with no open price, keep OHLC only
    (no volume), and shift each timestamp by IST_OFFSET_SECONDS. A range with
    no trading data is an empty list, not an error.
    """
    days, interval = CANDLE_RANGES.get(range_name, DEFAULT_CANDLE_RANGE)
    now = datetime.now()
    period1 = int((now - timedelta(days=days)).timestamp())

    payload = _request_chart(
        ticker=ticker_for(symbol),
        interval=interval,
        period1=period1,
        period2=int(now.timestamp()),
    )
    return _candles_from_payload(payload)


def _request_chart(ticker, interval, period1, period2):
    """Call Yahoo's chart endpoint and return the decoded body.

    Isolated so tests can supply a canned payload without touching the network.
    """
    params = dict(YAHOO_PARAMS, interval=interval, period1=period1, period2=period2)
    try:
        response = requests.get(
            CHART_URL.format(ticker=ticker),
            params=params,
            headers=REQUEST_HEADERS,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as err:
        raise MarketDataError(str(err)) from err
    except ValueError as err:  # a non-JSON body
        raise MarketDataError(str(err)) from err


def _candles_from_payload(payload):
    """Map a chart payload the way the Express route does."""
    chart = payload.get("chart") or {}

    if chart.get("error"):
        raise MarketDataError(str(chart["error"]))

    results = chart.get("result") or []
    if not results:
        raise MarketDataError("chart returned no result")

    result = results[0]
    timestamps = result.get("timestamp") or []
    quotes = (result.get("indicators") or {}).get("quote") or [{}]
    quote = quotes[0] if quotes else {}
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []

    candles = []
    for index, stamp in enumerate(timestamps):
        if index >= len(opens) or opens[index] is None:
            continue
        candles.append(
            {
                "time": stamp + IST_OFFSET_SECONDS,
                "open": opens[index],
                "high": highs[index] if index < len(highs) else None,
                "low": lows[index] if index < len(lows) else None,
                "close": closes[index] if index < len(closes) else None,
            }
        )
    return candles
