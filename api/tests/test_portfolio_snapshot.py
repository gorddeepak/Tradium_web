"""Focused tests for the daily portfolio snapshot.

User identity and the snapshot rows are canonical in PostgreSQL since Phase
3C1, so these tests use a real disposable PostgreSQL database. The book data
read to build the values is still MongoDB (mongomock). The tests are skipped
when TEST_DATABASE_URL is not set, through the shared `postgres_session_factory`
fixture.

The job is called directly with synthetic users and holdings — no scheduler and
no wall clock — plus scheduler tests that prove the 18:00 IST delay and the
tick.
"""

import secrets
import time
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from bson import ObjectId
from sqlalchemy import select, text

from api import scheduler
from api.jobs import portfolio_snapshot
from api.market_hours import IST
from api.postgres.models import PortfolioSnapshot, User

NOW = datetime(2026, 10, 25, 12, 0, 0, 123000, tzinfo=timezone.utc)


def _ist(year, month, day, hour, minute, second=0):
    return datetime(year, month, day, hour, minute, second, tzinfo=IST)


# --------------------------------------------------------------------------
# PostgreSQL fixtures and helpers
# --------------------------------------------------------------------------


@pytest.fixture
def snapshot_factory(postgres_session_factory):
    """Start one test with no PostgreSQL users or snapshot rows."""
    with postgres_session_factory() as session:
        session.execute(text("TRUNCATE TABLE portfolio_snapshots, users CASCADE"))
        session.commit()
    return postgres_session_factory


def _insert_postgres_user(session_factory, created=NOW):
    """Insert one user row the way the signup route stores it."""
    user_id = secrets.token_hex(12)
    with session_factory() as session:
        session.add(
            User(
                id=user_id,
                username=f"snapshot-{user_id}",
                email=f"{user_id}@example.com",
                password_hash="unused-in-snapshot-tests",
                created_at=created,
                updated_at=created,
                version=0,
            )
        )
        session.commit()
    return ObjectId(user_id)


def _snapshots(session_factory):
    with session_factory() as session:
        return session.scalars(select(PortfolioSnapshot)).all()


# --------------------------------------------------------------------------
# The IST calendar day
# --------------------------------------------------------------------------


def test_snapshot_date_uses_the_ist_day_at_utc_midnight():
    # 18:29 UTC is 23:59 IST on the same day.
    assert portfolio_snapshot.snapshot_date(
        datetime(2026, 10, 19, 18, 29, tzinfo=timezone.utc)
    ) == datetime(2026, 10, 19, tzinfo=timezone.utc)

    # 18:30 UTC is 00:00 IST on the next day.
    assert portfolio_snapshot.snapshot_date(
        datetime(2026, 10, 19, 18, 30, tzinfo=timezone.utc)
    ) == datetime(2026, 10, 20, tzinfo=timezone.utc)


def test_snapshot_date_handles_the_month_boundary():
    assert portfolio_snapshot.snapshot_date(
        datetime(2026, 10, 31, 19, 0, tzinfo=timezone.utc)
    ) == datetime(2026, 11, 1, tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# The snapshot itself
# --------------------------------------------------------------------------


def test_every_user_gets_one_row_even_with_no_holdings(
    database, holdings_factory, positions_factory, snapshot_factory
):
    holder = _insert_postgres_user(snapshot_factory)
    empty = _insert_postgres_user(snapshot_factory)
    database["holdings"].insert_one(holdings_factory(holder))
    database["positions"].insert_one(positions_factory(holder))

    portfolio_snapshot.record_daily_snapshot(database, snapshot_factory)

    rows = {row.user_id: row for row in _snapshots(snapshot_factory)}
    assert len(rows) == 2

    snapshot = rows[str(holder)]
    assert snapshot.snapshot_date == portfolio_snapshot.snapshot_date().date()
    # Holdings only: 10 * 2500 and 10 * 2400.5.
    assert snapshot.value == Decimal("25000")
    assert snapshot.invested == Decimal("24005")
    # Open MIS leg: 5 * 1500 entry + (1520 - 1500) * 5.
    assert snapshot.mis_value == Decimal("7600")
    assert snapshot.mis_invested == Decimal("7500")
    assert snapshot.version == 0
    assert snapshot.created_at == snapshot.updated_at

    blank = rows[str(empty)]
    assert blank.value == Decimal("0")
    assert blank.invested == Decimal("0")
    assert blank.mis_value == Decimal("0")
    assert blank.mis_invested == Decimal("0")


def test_zero_postgres_users_writes_no_snapshots(database, snapshot_factory):
    # A user that only exists in the legacy MongoDB collection is not part of
    # the canonical identity population any more.
    database["users"].insert_one({"_id": ObjectId()})

    portfolio_snapshot.record_daily_snapshot(database, snapshot_factory)

    assert _snapshots(snapshot_factory) == []


def test_postgres_users_are_the_snapshot_population(
    database, holdings_factory, snapshot_factory
):
    holder = _insert_postgres_user(snapshot_factory)
    empty = _insert_postgres_user(snapshot_factory)
    mongo_only = ObjectId()

    database["users"].insert_one({"_id": mongo_only})
    database["holdings"].insert_one(holdings_factory(holder))
    database["holdings"].insert_one(holdings_factory(mongo_only, symbol="TCS"))

    portfolio_snapshot.record_daily_snapshot(database, snapshot_factory)

    rows = {row.user_id: row for row in _snapshots(snapshot_factory)}
    assert rows[str(holder)].value == Decimal("25000")
    assert rows[str(holder)].invested == Decimal("24005")
    assert rows[str(empty)].value == Decimal("0")
    assert rows[str(empty)].invested == Decimal("0")

    # The MongoDB `users` collection is no longer the population source.
    assert str(mongo_only) not in rows


def test_short_legs_reduce_the_mis_value(
    database, holdings_factory, positions_factory, snapshot_factory
):
    user = _insert_postgres_user(snapshot_factory)
    database["holdings"].insert_one(holdings_factory(user))
    # Short 5 at 1500, now 1520 -> a 100 loss.
    database["positions"].insert_one(
        positions_factory(user, side="SHORT", qty=5, entry=1500.0, ltp=1520.0)
    )

    portfolio_snapshot.record_daily_snapshot(database, snapshot_factory)

    snapshot = _snapshots(snapshot_factory)[0]
    assert snapshot.mis_invested == Decimal("7500")
    assert snapshot.mis_value == Decimal("7400")


def test_a_second_run_on_the_same_day_overwrites_in_place(
    database, holdings_factory, snapshot_factory
):
    user = _insert_postgres_user(snapshot_factory)
    holding = holdings_factory(user)
    database["holdings"].insert_one(holding)

    portfolio_snapshot.record_daily_snapshot(database, snapshot_factory)
    first = _snapshots(snapshot_factory)[0]

    database["holdings"].update_one({"_id": holding["_id"]}, {"$set": {"ltp": 2600.0}})
    time.sleep(0.02)  # PostgreSQL timestamps have millisecond resolution
    portfolio_snapshot.record_daily_snapshot(database, snapshot_factory)

    rows = _snapshots(snapshot_factory)
    assert len(rows) == 1
    second = rows[0]
    assert second.id == first.id
    assert second.created_at == first.created_at
    assert second.value == Decimal("26000")
    assert second.updated_at > first.updated_at


def test_a_failure_does_not_raise_and_stops_the_rest(
    database, holdings_factory, snapshot_factory
):
    first = _insert_postgres_user(snapshot_factory)
    broken = _insert_postgres_user(
        snapshot_factory,
        created=datetime(2026, 10, 25, 12, 0, 1, tzinfo=timezone.utc),
    )
    database["holdings"].insert_one(holdings_factory(first))
    # No `ltp`, so the value sum raises for the second user.
    database["holdings"].insert_one(
        {"_id": ObjectId(), "user": broken, "symbol": "TCS", "qty": 1, "avgPrice": 1.0}
    )

    # must not raise
    portfolio_snapshot.record_daily_snapshot(database, snapshot_factory)

    rows = {row.user_id: row for row in _snapshots(snapshot_factory)}
    assert str(first) in rows
    assert str(broken) not in rows


def test_a_postgres_enumeration_failure_is_logged_and_writes_nothing(
    database, snapshot_factory, caplog
):
    def broken_factory():
        raise RuntimeError("postgres unavailable")

    portfolio_snapshot.record_daily_snapshot(database, broken_factory)

    assert _snapshots(snapshot_factory) == []
    assert "Portfolio snapshot failed" in caplog.text


# --------------------------------------------------------------------------
# The 18:00 IST schedule
# --------------------------------------------------------------------------


def test_seconds_until_snapshot_before_the_hour():
    # 17:30 IST -> 1800 seconds.
    assert scheduler.seconds_until_snapshot(now=_ist(2026, 10, 19, 17, 30)) == 1800


def test_seconds_until_snapshot_after_the_hour_waits_for_tomorrow():
    # 18:30 IST -> 23.5 hours.
    assert scheduler.seconds_until_snapshot(now=_ist(2026, 10, 19, 18, 30)) == 84600


def test_seconds_until_snapshot_exactly_at_the_hour_is_due_now():
    assert scheduler.seconds_until_snapshot(now=_ist(2026, 10, 19, 18, 0)) == 0


def test_snapshot_scheduler_ticks_when_due_and_stops(database, monkeypatch):
    ticks = []
    session_factory = object()
    monkeypatch.setattr(
        scheduler,
        "record_daily_snapshot",
        lambda db, factory: ticks.append((db, factory)),
    )
    monkeypatch.setattr(scheduler, "seconds_until_snapshot", lambda hour: 0.01)

    instance = scheduler.PortfolioSnapshotScheduler(
        database, session_factory=session_factory
    )
    instance.start()
    time.sleep(0.2)
    instance.stop()

    assert ticks  # at least one tick ran
    assert ticks[0][0] is database
    assert ticks[0][1] is session_factory
    assert instance._thread is None


def test_snapshot_scheduler_survives_a_failing_tick(database, monkeypatch):
    calls = []

    def flaky(db, factory):
        calls.append((db, factory))
        raise RuntimeError("boom")

    monkeypatch.setattr(scheduler, "record_daily_snapshot", flaky)
    monkeypatch.setattr(scheduler, "seconds_until_snapshot", lambda hour: 0.01)

    instance = scheduler.PortfolioSnapshotScheduler(
        database, session_factory=object()
    )
    instance.start()
    time.sleep(0.1)
    instance.stop()

    assert calls
    assert instance._thread is None
