"""Port of the cache-backed search route in server/routes/instrumentRoutes.js.

The Express route is:
    router.get("/search", protect, async (req, res) => {
      // regex over the local MarketQuote cache; no Yahoo call
    });

The other instrument routes (`/lookup/:symbol`, `/:symbol`,
`/:symbol/candles`) call Yahoo Finance live and are deferred to the
market-data phase.
"""

import re

from fastapi import APIRouter, Depends
from pymongo.database import Database

from ..auth import require_user
from ..db import get_database

router = APIRouter()


@router.get("/api/instruments/search")
def search_instruments(
    q: str = "",
    user_id: str = Depends(require_user),
    db: Database = Depends(get_database),
):
    query = q.strip()
    if not query:
        return []

    # Escape user input so regex metacharacters match literally.
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    rows = list(
        db["marketquotes"].find({"$or": [{"symbol": pattern}, {"name": pattern}]}).limit(10)
    )

    # Field names are renamed for the client: price <- ltp, changePct <- dayChangePct.
    return [
        {
            "symbol": row["symbol"],
            "name": row["name"],
            "kind": row.get("kind"),
            "price": row.get("ltp"),
            "changePct": row.get("dayChangePct"),
        }
        for row in rows
    ]
