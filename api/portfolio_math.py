"""Port of server/utils/portfolioMath.js.

The snapshot job needs ``misComponents``. The portfolio-history route used to
keep a private copy; both now import this one, so the open-MIS value can never
drift between the live chart and the stored snapshot.

The readers pass PostgreSQL ``Decimal`` values since Phase 3C2B, so the money
helpers below stay generic: they keep whatever numeric type they are given.
"""

from decimal import Decimal


def day_change_rupees(holding):
    """Turn a day % change into rupees, the way the Express helper does."""
    denominator = 100 + (holding.get("dayChangePct") or 0)
    if not denominator:
        return 0  # a -100% change would divide by zero

    return (
        (holding.get("qty") or 0)
        * (holding.get("ltp") or 0)
        * ((holding.get("dayChangePct") or 0) / denominator)
    )


def calculate_portfolio_summary(holdings):
    """Port of ``calculatePortfolioSummary`` in portfolioMath.js."""
    invested = sum(
        (holding.get("qty") or 0) * (holding.get("avgPrice") or 0) for holding in holdings
    )
    value = sum((holding.get("qty") or 0) * (holding.get("ltp") or 0) for holding in holdings)
    day_pnl = sum(day_change_rupees(holding) for holding in holdings)

    # What these same holdings were worth at yesterday's close.
    previous_value = value - day_pnl
    pnl = value - invested

    return {
        "invested": invested,
        "value": value,
        "pnl": pnl,
        "pnlPct": (pnl / invested * 100) if invested else 0,
        "dayPnl": day_pnl,
        "dayPnlPct": (day_pnl / previous_value * 100) if previous_value else 0,
    }


def mis_components(positions):
    """Value of open MIS legs; an ``ltp`` of 0 falls back to the entry price.

    The terms are ``Decimal`` because the PostgreSQL book is: a float
    accumulator added to a numeric column would raise, and both callers now
    price the legs from ``Decimal`` rows.
    """
    mis_value = Decimal(0)
    mis_invested = Decimal(0)

    for position in positions:
        if position.get("product") != "MIS":
            continue
        qty = Decimal(str(position["qty"]))
        entry = Decimal(str(position["entry"]))
        direction = -1 if position.get("side") == "SHORT" else 1
        price = position.get("ltp") or entry
        pnl = (price - entry) * qty * direction
        mis_invested += qty * entry
        mis_value += qty * entry + pnl

    return mis_value, mis_invested
