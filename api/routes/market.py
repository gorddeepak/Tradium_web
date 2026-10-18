"""Port of the cache-backed read route in server/routes/marketRoutes.js.

The Express route is:
    router.get("/overview", protect, async (req, res) => {
      const rows = await MarketQuoteModel.find({}).lean();
      ...
    });

It reads only the local MarketQuote cache — no Yahoo call. The index display
order mirrors the `indices` list in server/data/nifty50.js.
"""

from fastapi import APIRouter, Depends
from pymongo.database import Database

from ..auth import require_user
from ..db import get_database
from ..serialization import to_json_value

router = APIRouter()

# server/data/nifty50.js `indices`, in declaration order.
INDEX_ORDER = ["^NSEI", "^NSEBANK", "^BSESN"]


@router.get("/api/market/overview")
def market_overview(
    user_id: str = Depends(require_user),
    db: Database = Depends(get_database),
):
    rows = list(db["marketquotes"].find({}))

    # find() promises no order, so indices are sorted by the seed order.
    # Unknown symbols sort to the front, matching indexOf(...) == -1.
    indices = [row for row in rows if row.get("kind") == "index"]
    indices.sort(
        key=lambda row: INDEX_ORDER.index(row["symbol"]) if row["symbol"] in INDEX_ORDER else -1
    )

    stocks = [row for row in rows if row.get("kind") == "stock"]

    # Freshest row's time, so the page can show the cache age (null = cold cache).
    as_of = None
    for row in rows:
        updated = row.get("updatedAt")
        if updated is not None and (as_of is None or updated > as_of):
            as_of = updated

    return to_json_value({"asOf": as_of, "indices": indices, "stocks": stocks})
