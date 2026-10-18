"""Market-data provider seam.

The Express app reads live prices from Yahoo Finance
(``server/jobs/priceSync.js`` ``fetchQuote``). That integration is a separate
migration phase, so no provider is wired up yet: ``fetch_quote`` returns
``None``, which is exactly the "provider returned no price" branch the
Express code already handles.

The two consequences match the documented Express behaviour:

- ``POST /api/orders`` with ``type: "MARKET"`` answers
  503 ``"No live price available for <symbol>, try again in a moment"``.
- ``POST /api/positions/:id/square-off`` falls back to the stored ``ltp``.

No price is fabricated here.
"""


def fetch_quote(symbol):
    """Return ``{"ltp", "dayChangePct"}`` for a symbol, or ``None``.

    The market-data phase replaces the body of this function with the Yahoo
    call; callers only depend on the return shape above.
    """
    return None
