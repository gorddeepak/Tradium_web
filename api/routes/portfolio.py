"""Port of the read route in server/routes/portfolioRoutes.js.

The Express route is:
    router.get("/history", protect, async (req, res) => { ... });

Snapshots store the IST calendar day at UTC midnight (see
server/jobs/portfolioSnapshot.js), and API_CONTRACTS §0.5 says business-day
logic uses IST. The Express code formatted labels with the server's local
zone; IST is used here so the labels are deterministic and match the intended
environment.
"""

from datetime import datetime, timedelta, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends
from pymongo.database import Database

from ..auth import require_user
from ..db import get_database
from ..portfolio_math import mis_components

router = APIRouter()

IST = timezone(timedelta(hours=5, minutes=30))

# Same windows as the Express route; any other range falls back to 30 days.
RANGE_DAYS = {"1D": 1, "1W": 7, "1M": 30, "1Y": 365, "ALL": 100000}


def _local_date(value: datetime) -> str:
    # PyMongo returns naive UTC datetimes; `en-CA` formatting is YYYY-MM-DD.
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(IST).strftime("%Y-%m-%d")


@router.get("/api/portfolio/history")
def portfolio_history(
    range: str = "1M",
    user_id: str = Depends(require_user),
    db: Database = Depends(get_database),
):
    user = ObjectId(user_id)
    days = RANGE_DAYS.get(range, 30)
    since = datetime.now(timezone.utc) - timedelta(days=days)

    snapshots = list(
        db["portfoliosnapshots"].find({"user": user, "date": {"$gte": since}}).sort("date", 1)
    )

    series = [
        {
            "label": _local_date(snapshot["date"]),
            "value": snapshot["value"] + (snapshot.get("misValue") or 0),
            # null keeps the chart's gap for pre-`invested` snapshots.
            "invested": (snapshot["invested"] + (snapshot.get("misInvested") or 0))
            if snapshot.get("invested")
            else None,
        }
        for snapshot in snapshots
    ]

    # Today's live point: holdings plus open MIS legs, always shown.
    holdings = list(db["holdings"].find({"user": user}))
    current_value = sum(holding["qty"] * holding["ltp"] for holding in holdings)
    current_invested = sum(holding["qty"] * holding["avgPrice"] for holding in holdings)

    positions = list(db["positions"].find({"user": user, "product": "MIS"}))
    mis_value, mis_invested = mis_components(positions)

    today_label = datetime.now(timezone.utc).astimezone(IST).strftime("%Y-%m-%d")
    if not series or series[-1]["label"] != today_label:
        series.append(
            {
                "label": today_label,
                "value": current_value + mis_value,
                "invested": current_invested + mis_invested,
            }
        )
    else:
        # Today's snapshot already exists — overwrite it with the freshest live value.
        series[-1]["value"] = current_value + mis_value
        series[-1]["invested"] = current_invested + mis_invested

    return series
