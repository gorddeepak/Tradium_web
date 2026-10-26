"""Port of server/jobs/portfolioSnapshot.js.

Once a day, after the close, every user gets one snapshot row holding the day's
portfolio value, cost basis and the value of any open MIS legs. The row is
keyed on ``(user_id, snapshot_date)``, so a second run on the same IST day
updates the numbers rather than creating a duplicate.

User identity and the book are both canonical in PostgreSQL, so the values are
built by ``trading_book.portfolio_totals`` — the same reader the live
portfolio-history point uses. The date is the **IST calendar day**, stored as a
``date``.

Each user is committed separately. A failure stops the rest of the run (the
Express ``try`` around the whole loop does the same), but users already
processed stay committed.
"""

import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from ..documents import utcnow
from ..postgres.models import PortfolioSnapshot, User
from ..postgres.session import get_session_factory
from ..trading_book import portfolio_totals

logger = logging.getLogger(__name__)

# India has no daylight saving, so a fixed offset is exact (same reasoning as
# api/market_hours.py; `tzdata` is not installed).
IST = timezone(timedelta(hours=5, minutes=30))


def snapshot_date(now=None):
    """Return the IST calendar day of ``now`` as a UTC-midnight datetime.

    The PostgreSQL column stores only the day (``snapshot_date``); ``.date()``
    turns this value into that day without changing the IST interpretation.
    """
    moment = now or datetime.now(timezone.utc)
    day = moment.astimezone(IST).date()
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


def record_daily_snapshot(session_factory=None):
    """Snapshot every PostgreSQL user — even one who sold everything.

    A failure aborts the rest of the run, which is what the Express ``try``
    around the whole loop does; the scheduler keeps ticking tomorrow.
    """
    try:
        today = snapshot_date()
        day = today.date()
        factory = session_factory or get_session_factory()

        # The canonical user list lives in PostgreSQL.
        with factory() as session:
            user_ids = session.scalars(
                select(User.id).order_by(User.created_at.asc(), User.id.asc())
            ).all()

        # Snapshot every user, including users with no rows left.
        for raw_user_id in user_ids:
            now = utcnow()
            with factory() as session:
                value, invested, mis_value, mis_invested = portfolio_totals(
                    session, raw_user_id
                )

                statement = insert(PortfolioSnapshot).values(
                    id=secrets.token_hex(12),
                    user_id=raw_user_id,
                    snapshot_date=day,
                    value=value,
                    invested=invested,
                    mis_invested=mis_invested,
                    mis_value=mis_value,
                    created_at=now,
                    updated_at=now,
                    version=0,
                )
                statement = statement.on_conflict_do_update(
                    index_elements=["user_id", "snapshot_date"],
                    set_={
                        "value": statement.excluded.value,
                        "invested": statement.excluded.invested,
                        "mis_invested": statement.excluded.mis_invested,
                        "mis_value": statement.excluded.mis_value,
                        "updated_at": now,
                    },
                )

                # One transaction per user: a later failure keeps the earlier rows.
                session.execute(statement)
                session.commit()

        logger.info("Portfolio snapshot recorded")
    except Exception:  # noqa: BLE001 - an unhandled error would kill the thread
        logger.exception("Portfolio snapshot failed")
