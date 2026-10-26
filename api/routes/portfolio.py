"""Port of the read route in server/routes/portfolioRoutes.js.

The Express route is:
    router.get("/history", protect, async (req, res) => { ... });

The daily snapshots are canonical in PostgreSQL (Phase 3C1) and store the IST
calendar day. Since Phase 3C2B the live "today" point comes from the same
PostgreSQL book as the snapshot job, so the chart and the stored row share one
calculation (``trading_book.portfolio_totals``).

The Express code formatted labels with the server's local zone; IST is used
here so the labels are deterministic and match the intended environment.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import require_user
from ..postgres.models import PortfolioSnapshot
from ..postgres.session import get_session
from ..trading_book import portfolio_totals

router = APIRouter()

IST = timezone(timedelta(hours=5, minutes=30))

# Same windows as the Express route; any other range falls back to 30 days.
RANGE_DAYS = {"1D": 1, "1W": 7, "1M": 30, "1Y": 365, "ALL": 100000}


@router.get("/api/portfolio/history")
def portfolio_history(
    range: str = "1M",
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
):
    days = RANGE_DAYS.get(range, 30)
    today = datetime.now(timezone.utc).astimezone(IST).date()
    # Include today: `days` calendar points end at today, as the Express
    # instant-based cutoff did for a request made after the 05:30 UTC snapshot.
    since = today - timedelta(days=days - 1)

    snapshots = session.scalars(
        select(PortfolioSnapshot)
        .where(
            PortfolioSnapshot.user_id == user_id,
            PortfolioSnapshot.snapshot_date >= since,
        )
        .order_by(PortfolioSnapshot.snapshot_date.asc())
    ).all()

    series = [
        {
            "label": snapshot.snapshot_date.isoformat(),
            "value": float(snapshot.value) + float(snapshot.mis_value or 0),
            # null keeps the chart's gap for pre-`invested` snapshots.
            "invested": (
                float(snapshot.invested) + float(snapshot.mis_invested or 0)
            )
            if snapshot.invested
            else None,
        }
        for snapshot in snapshots
    ]

    # Today's live point: holdings plus open MIS legs, always shown.
    holdings_value, holdings_invested, mis_value, mis_invested = portfolio_totals(
        session, user_id
    )
    live_value = float(holdings_value + mis_value)
    live_invested = float(holdings_invested + mis_invested)

    today_label = today.isoformat()
    if not series or series[-1]["label"] != today_label:
        series.append(
            {
                "label": today_label,
                "value": live_value,
                "invested": live_invested,
            }
        )
    else:
        # Today's snapshot already exists — overwrite it with the freshest live value.
        series[-1]["value"] = live_value
        series[-1]["invested"] = live_invested

    return series
