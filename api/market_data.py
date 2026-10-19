"""Market-data provider seam.

The Express app reads live prices from Yahoo Finance
(``server/jobs/priceSync.js`` ``fetchQuote``). That integration is a separate
migration phase, so no quote provider is wired up yet: ``fetch_quote`` returns
``None``, which is exactly the "provider returned no price" branch the Express
code already handles.

The two consequences match the documented Express behaviour:

- ``POST /api/orders`` with ``type: "MARKET"`` answers
  503 ``"No live price available for <symbol>, try again in a moment"``.
- ``POST /api/positions/:id/square-off`` falls back to the stored ``ltp``.

Historical candles *are* implemented here, because
``GET /api/instruments/:symbol/candles`` only needs Yahoo's chart endpoint.
That endpoint is the same one ``yahoo-finance2``'s ``chart()`` reads in
``server/routes/instrumentRoutes.js``, and the query parameters below are the
ones that library actually sends (read from its request log), so the bars match
the Express app's. See ``MARKET_DATA_PLAN.md`` §3.1 for the measurements.
"""

from datetime import datetime, timedelta

import requests

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
# yahoo-finance2 relies on its own user agent; Yahoo rejects some clients
# without one. This does not change the bars that come back.
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


class MarketDataError(Exception):
    """The provider could not answer. The route turns this into a 404."""


def ticker_for(symbol):
    """NSE-only: indices keep Yahoo's own ``^`` symbol, stocks get ``.NS``."""
    return symbol if symbol.startswith("^") else f"{symbol}.NS"


def fetch_quote(symbol):
    """Return ``{"ltp", "dayChangePct"}`` for a symbol, or ``None``.

    Live quotes are a later phase. Callers only depend on the return shape.
    """
    return None


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
