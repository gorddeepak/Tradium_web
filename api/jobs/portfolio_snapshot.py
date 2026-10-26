"""Port of server/jobs/portfolioSnapshot.js.

Once a day, after the close, every user gets one snapshot row holding the day's
portfolio value, cost basis and the value of any open MIS legs. The row is
keyed on ``(user, date)``, so a second run on the same IST day overwrites the
numbers rather than creating a duplicate.

User identity is canonical in PostgreSQL (Phase 3B1), so the user list comes
from the ``users`` table through the shared session factory. The snapshot rows
and the book data read to build them are still MongoDB documents, keyed by the
same 24-hex id cast to an ObjectId.

The date is the **IST calendar day stored at UTC midnight**, exactly as the
Express job computes it (``Date.now() + 5.5h`` then a UTC midnight). The chart
route formats that date back in IST.
"""

import logging
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from sqlalchemy import select

from ..documents import utcnow
from ..portfolio_math import mis_components
from ..postgres.models import User
from ..postgres.session import get_session_factory

logger = logging.getLogger(__name__)

# India has no daylight saving, so a fixed offset is exact (same reasoning as
# api/market_hours.py; `tzdata` is not installed).
IST = timezone(timedelta(hours=5, minutes=30))


def snapshot_date(now=None):
    """Return the IST calendar day of ``now`` as a UTC-midnight datetime."""
    moment = now or datetime.now(timezone.utc)
    day = moment.astimezone(IST).date()
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


def record_daily_snapshot(db, session_factory=None):
    """Snapshot every PostgreSQL user — even one who sold everything.

    A failure aborts the rest of the run, which is what the Express ``try``
    around the whole loop does; the scheduler keeps ticking tomorrow.
    """
    try:
        today = snapshot_date()
        factory = session_factory or get_session_factory()

        # The canonical user list lives in PostgreSQL. Cast the text id back
        # to an ObjectId because the snapshot and book collections still store
        # MongoDB's ObjectId in their `user` fields.
        with factory() as session:
            user_ids = session.scalars(select(User.id)).all()

        # Snapshot every user, including users with no rows left.
        for raw_user_id in user_ids:
            user_id = ObjectId(raw_user_id)

            holdings = list(db["holdings"].find({"user": user_id}))
            value = sum(holding["qty"] * holding["ltp"] for holding in holdings)
            invested = sum(holding["qty"] * holding["avgPrice"] for holding in holdings)

            # Whole-account view: snapshot open MIS legs alongside holdings.
            positions = list(db["positions"].find({"user": user_id, "product": "MIS"}))
            mis_value, mis_invested = mis_components(positions)

            # Observed from Mongoose: the upsert sets the numbers and
            # `updatedAt` every run, and supplies `createdAt`/`__v` on insert.
            now = utcnow()
            db["portfoliosnapshots"].find_one_and_update(
                {"user": user_id, "date": today},
                {
                    "$set": {
                        "value": value,
                        "invested": invested,
                        "misValue": mis_value,
                        "misInvested": mis_invested,
                        "updatedAt": now,
                    },
                    "$setOnInsert": {"createdAt": now, "__v": 0},
                },
                upsert=True,
            )

        logger.info("Portfolio snapshot recorded")
    except Exception:  # noqa: BLE001 - an unhandled error would kill the thread
        logger.exception("Portfolio snapshot failed")
