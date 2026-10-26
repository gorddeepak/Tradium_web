"""Port of the cache-backed read route in server/routes/marketRoutes.js.

The Express route is:
    router.get("/overview", protect, async (req, res) => {
      const rows = await MarketQuoteModel.find({}).lean();
      ...
    });

It reads only the persisted market cache — no Yahoo call. Phase 3B2 moved that
cache from MongoDB's ``marketquotes`` collection to PostgreSQL's ``instruments``
and ``latest_quotes`` tables.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import require_user
from ..market_store import read_market_overview
from ..postgres.session import get_session
from ..serialization import to_json_value

router = APIRouter()


@router.get("/api/market/overview")
def market_overview(
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
):
    return to_json_value(read_market_overview(session))
