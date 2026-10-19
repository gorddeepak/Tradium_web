"""Focused tests for the daily portfolio snapshot.

The job is called directly with synthetic users and holdings — no scheduler and
no wall clock — plus one scheduler test that proves the 18:00 IST delay and the
tick. mongomock runs the ``find_one_and_update`` upsert.
"""

import time
from datetime import datetime, timezone

from bson import ObjectId

from api import scheduler
from api.jobs import portfolio_snapshot
from api.market_hours import IST


def _ist(year, month, day, hour, minute, second=0):
    return datetime(year, month, day, hour, minute, second, tzinfo=IST)


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
    database, holdings_factory, positions_factory
):
    holder = ObjectId()
    empty = ObjectId()
    database["users"].insert_many([{"_id": holder}, {"_id": empty}])
    database["holdings"].insert_one(holdings_factory(holder))
    database["positions"].insert_one(positions_factory(holder))

    portfolio_snapshot.record_daily_snapshot(database)

    assert database["portfoliosnapshots"].count_documents({}) == 2

    snapshot = database["portfoliosnapshots"].find_one({"user": holder})
    assert snapshot["date"].replace(tzinfo=timezone.utc) == portfolio_snapshot.snapshot_date()
    # Holdings only: 10 * 2500 and 10 * 2400.5.
    assert snapshot["value"] == 25000.0
    assert snapshot["invested"] == 24005.0
    # Open MIS leg: 5 * 1500 entry + (1520 - 1500) * 5.
    assert snapshot["misValue"] == 7600.0
    assert snapshot["misInvested"] == 7500.0
    assert snapshot["__v"] == 0
    assert snapshot["createdAt"] == snapshot["updatedAt"]

    blank = database["portfoliosnapshots"].find_one({"user": empty})
    assert blank["value"] == 0.0
    assert blank["invested"] == 0.0
    assert blank["misValue"] == 0.0
    assert blank["misInvested"] == 0.0


def test_short_legs_reduce_the_mis_value(database, holdings_factory, positions_factory):
    user = ObjectId()
    database["users"].insert_one({"_id": user})
    database["holdings"].insert_one(holdings_factory(user))
    # Short 5 at 1500, now 1520 -> a 100 loss.
    database["positions"].insert_one(
        positions_factory(user, side="SHORT", qty=5, entry=1500.0, ltp=1520.0)
    )

    portfolio_snapshot.record_daily_snapshot(database)

    snapshot = database["portfoliosnapshots"].find_one({"user": user})
    assert snapshot["misInvested"] == 7500.0
    assert snapshot["misValue"] == 7400.0


def test_a_second_run_on_the_same_day_overwrites_in_place(
    database, holdings_factory, positions_factory
):
    user = ObjectId()
    database["users"].insert_one({"_id": user})
    holding = holdings_factory(user)
    database["holdings"].insert_one(holding)

    portfolio_snapshot.record_daily_snapshot(database)
    first = database["portfoliosnapshots"].find_one({"user": user})

    database["holdings"].update_one({"_id": holding["_id"]}, {"$set": {"ltp": 2600.0}})
    time.sleep(0.02)  # MongoDB dates have millisecond resolution
    portfolio_snapshot.record_daily_snapshot(database)

    assert database["portfoliosnapshots"].count_documents({"user": user}) == 1
    second = database["portfoliosnapshots"].find_one({"user": user})
    assert second["_id"] == first["_id"]
    assert second["createdAt"] == first["createdAt"]
    assert second["value"] == 26000.0
    assert second["updatedAt"] > first["updatedAt"]


def test_a_failure_does_not_raise_and_stops_the_rest(
    database, holdings_factory, monkeypatch
):
    first = ObjectId()
    broken = ObjectId()
    database["users"].insert_many([{"_id": first}, {"_id": broken}])
    database["holdings"].insert_one(holdings_factory(first))
    # No `ltp`, so the value sum raises for the second user.
    database["holdings"].insert_one(
        {"_id": ObjectId(), "user": broken, "symbol": "TCS", "qty": 1, "avgPrice": 1.0}
    )

    portfolio_snapshot.record_daily_snapshot(database)  # must not raise

    assert database["portfoliosnapshots"].count_documents({"user": first}) == 1
    assert database["portfoliosnapshots"].count_documents({"user": broken}) == 0


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
    monkeypatch.setattr(scheduler, "record_daily_snapshot", lambda db: ticks.append(db))
    monkeypatch.setattr(scheduler, "seconds_until_snapshot", lambda hour: 0.01)

    instance = scheduler.PortfolioSnapshotScheduler(database)
    instance.start()
    time.sleep(0.2)
    instance.stop()

    assert ticks  # at least one tick ran
    assert instance._thread is None


def test_snapshot_scheduler_survives_a_failing_tick(database, monkeypatch):
    calls = []

    def flaky(db):
        calls.append(db)
        raise RuntimeError("boom")

    monkeypatch.setattr(scheduler, "record_daily_snapshot", flaky)
    monkeypatch.setattr(scheduler, "seconds_until_snapshot", lambda hour: 0.01)

    instance = scheduler.PortfolioSnapshotScheduler(database)
    instance.start()
    time.sleep(0.1)
    instance.stop()

    assert calls
    assert instance._thread is None
