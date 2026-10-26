"""Port of server/routes/holdingsRoutes.js, now backed by PostgreSQL.

The Express route is:
    router.get("/", protect, async (req, res) => {
      const holdings = await HoldingsModel.find({ user: req.userId });
      res.json(holdings);
    });

The book stores quantity and cost basis only. ``ltp``/``dayChangePct`` come
from ``latest_quotes`` and ``sector`` from ``instruments``, keeping the legacy
response keys without a second copy of the price.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import require_user
from ..postgres.models import Holding, Instrument, LatestQuote
from ..postgres.session import get_session
from ..serialization import to_json_value
from ..trading_book import holding_document

router = APIRouter()


@router.get("/api/holdings")
def list_holdings(
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
):
    rows = session.execute(
        select(
            Holding,
            func.coalesce(LatestQuote.ltp, 0),
            func.coalesce(LatestQuote.day_change_pct, 0),
            func.coalesce(Instrument.sector, ""),
        )
        .outerjoin(Instrument, Instrument.symbol == Holding.symbol)
        .outerjoin(LatestQuote, LatestQuote.instrument_id == Instrument.id)
        .where(Holding.user_id == user_id)
        .order_by(Holding.created_at.asc(), Holding.id.asc())
    ).all()

    return [
        to_json_value(holding_document(holding, ltp, day_change_pct, sector))
        for holding, ltp, day_change_pct, sector in rows
    ]
