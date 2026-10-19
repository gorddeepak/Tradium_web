"""Port of server/utils/portfolioMath.js.

The snapshot job needs ``misComponents``. The portfolio-history route used to
keep a private copy; both now import this one, so the open-MIS value can never
drift between the live chart and the stored snapshot.
"""


def mis_components(positions):
    """Value of open MIS legs; an ``ltp`` of 0 falls back to the entry price."""
    mis_value = 0.0
    mis_invested = 0.0

    for position in positions:
        if position.get("product") != "MIS":
            continue
        direction = -1 if position.get("side") == "SHORT" else 1
        price = position.get("ltp") or position["entry"]
        pnl = (price - position["entry"]) * position["qty"] * direction
        mis_invested += position["qty"] * position["entry"]
        mis_value += position["qty"] * position["entry"] + pnl

    return mis_value, mis_invested
