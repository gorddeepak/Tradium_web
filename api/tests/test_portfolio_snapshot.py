"""Focused tests for the daily portfolio snapshot.

User identity, the snapshot rows and the book are all canonical in PostgreSQL
since Phase 3C2B, so these tests use a real disposable PostgreSQL database and
the shared book fixtures. They are skipped when TEST_DATABASE_URL is not set,
through the shared `postgres_session_factory` fixture.

The job is called directly with synthetic users and holdings — no scheduler and
no wall clock — plus scheduler tests that prove the 18:00 IST delay and the
tick.
"""

import time
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select, update

from api import scheduler
from api.jobs import portfolio_snapshot
from api.market_hours import IST
from api.postgres.models import LatestQuote, PortfolioSnapshot

NOW = datetime(2026, 10, 25, 12, 0, 0, 123000, tzinfo=timezone.utc)


def _ist(year, month, day, hour, minute, second=0):
    return datetime(year, month, day, hour, minute, second, tzinfo=IST)


def _snapshots(session_factory):
    with session_factory() as session:
        return session.scalars(select(PortfolioSnapshot)).all()


def _set_quote(session_factory, instrument_id, ltp):
    with session_factory() as session:
        session.execute(
            update(LatestQuote)
            .where(LatestQuote.instrument_id == instrument_id)
            .values(ltp=Decimal(str(ltp)))
        )
        session.commit()


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
    book_session_factory,
    book_user_factory,
    book_holding_factory,
    book_position_factory,
    market_instrument_factory,
):
    holder = book_user_factory()
    empty = book_user_factory()
    market_instrument_factory(symbol="RELIANCE", ltp=2500.0)
    market_instrument_factory(symbol="INFY", ltp=1520.0)

    book_holding_factory(holder)
    book_position_factory(holder)

    portfolio_snapshot.record_daily_snapshot(book_session_factory)

    rows = {row.user_id: row for row in _snapshots(book_session_factory)}
    assert len(rows) == 2

    snapshot = rows[holder]
    assert snapshot.snapshot_date == portfolio_snapshot.snapshot_date().date()
    # Holdings only: 10 * 2500 and 10 * 2400.5.
    assert snapshot.value == Decimal("25000")
    assert snapshot.invested == Decimal("24005")
    # Open MIS leg: 5 * 1500 entry + (1520 - 1500) * 5.
    assert snapshot.mis_value == Decimal("7600")
    assert snapshot.mis_invested == Decimal("7500")
    assert snapshot.version == 0
    assert snapshot.created_at == snapshot.updated_at

    blank = rows[empty]
    assert blank.value == Decimal("0")
    assert blank.invested == Decimal("0")
    assert blank.mis_value == Decimal("0")
    assert blank.mis_invested == Decimal("0")


def test_zero_postgres_users_writes_no_snapshots(book_session_factory):
    # A user that only exists in the retired MongoDB collection is not part of
    # the canonical identity population any more.
    portfolio_snapshot.record_daily_snapshot(book_session_factory)

    assert _snapshots(book_session_factory) == []


def test_a_holding_without_a_quote_is_valued_at_zero(
    book_session_factory, book_user, book_holding_factory
):
    book_holding_factory(book_user, symbol="RELIANCE", qty=10, avg_price="2400.5")

    portfolio_snapshot.record_daily_snapshot(book_session_factory)

    snapshot = _snapshots(book_session_factory)[0]
    assert snapshot.value == Decimal("0")
    assert snapshot.invested == Decimal("24005")


def test_short_legs_reduce_the_mis_value(
    book_session_factory,
    book_user,
    book_holding_factory,
    book_position_factory,
    market_instrument_factory,
):
    market_instrument_factory(symbol="RELIANCE", ltp=2500.0)
    market_instrument_factory(symbol="INFY", ltp=1520.0)
    book_holding_factory(book_user)
    # Short 5 at 1500, now 1520 -> a 100 loss.
    book_position_factory(book_user, side="SHORT", qty=5, entry="1500.0")

    portfolio_snapshot.record_daily_snapshot(book_session_factory)

    snapshot = _snapshots(book_session_factory)[0]
    assert snapshot.mis_invested == Decimal("7500")
    assert snapshot.mis_value == Decimal("7400")


def test_a_second_run_on_the_same_day_overwrites_in_place(
    book_session_factory,
    book_user,
    book_holding_factory,
    market_instrument_factory,
):
    instrument_id = market_instrument_factory(symbol="RELIANCE", ltp=2500.0)
    book_holding_factory(book_user)

    portfolio_snapshot.record_daily_snapshot(book_session_factory)
    first = _snapshots(book_session_factory)[0]

    _set_quote(book_session_factory, instrument_id, 2600.0)
    time.sleep(0.02)  # PostgreSQL timestamps have millisecond resolution
    portfolio_snapshot.record_daily_snapshot(book_session_factory)

    rows = _snapshots(book_session_factory)
    assert len(rows) == 1
    second = rows[0]
    assert second.id == first.id
    assert second.created_at == first.created_at
    assert second.value == Decimal("26000")
    assert second.updated_at > first.updated_at


def test_a_failure_does_not_raise_and_stops_the_rest(
    book_session_factory,
    book_user_factory,
    book_holding_factory,
    market_instrument_factory,
    monkeypatch,
):
    first = book_user_factory()
    broken = book_user_factory(
        created_at=datetime(2026, 10, 25, 12, 0, 1, tzinfo=timezone.utc)
    )
    market_instrument_factory(symbol="RELIANCE", ltp=2500.0)
    book_holding_factory(first)

    real_totals = portfolio_snapshot.portfolio_totals

    def failing_totals(session, user_id):
        if user_id == broken:
            raise RuntimeError("book read failed")
        return real_totals(session, user_id)

    monkeypatch.setattr(portfolio_snapshot, "portfolio_totals", failing_totals)

    # must not raise
    portfolio_snapshot.record_daily_snapshot(book_session_factory)

    rows = {row.user_id: row for row in _snapshots(book_session_factory)}
    assert first in rows
    assert broken not in rows


def test_a_postgres_enumeration_failure_is_logged_and_writes_nothing(
    book_session_factory, caplog
):
    def broken_factory():
        raise RuntimeError("postgres unavailable")

    portfolio_snapshot.record_daily_snapshot(broken_factory)

    assert _snapshots(book_session_factory) == []
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


def test_snapshot_scheduler_ticks_when_due_and_stops(monkeypatch):
    ticks = []
    session_factory = object()
    monkeypatch.setattr(
        scheduler,
        "record_daily_snapshot",
        lambda factory: ticks.append(factory),
    )
    monkeypatch.setattr(scheduler, "seconds_until_snapshot", lambda hour: 0.01)

    instance = scheduler.PortfolioSnapshotScheduler(
        session_factory=session_factory
    )
    instance.start()
    time.sleep(0.2)
    instance.stop()

    assert ticks  # at least one tick ran
    assert ticks[0] is session_factory
    assert instance._thread is None


def test_snapshot_scheduler_survives_a_failing_tick(monkeypatch):
    calls = []

    def flaky(factory):
        calls.append(factory)
        raise RuntimeError("boom")

    monkeypatch.setattr(scheduler, "record_daily_snapshot", flaky)
    monkeypatch.setattr(scheduler, "seconds_until_snapshot", lambda hour: 0.01)

    instance = scheduler.PortfolioSnapshotScheduler(session_factory=object())
    instance.start()
    time.sleep(0.1)
    instance.stop()

    assert calls
    assert instance._thread is None
