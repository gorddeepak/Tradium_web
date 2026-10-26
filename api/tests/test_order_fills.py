"""PostgreSQL-backed tests for scheduled order fills and MIS settlement.

The provider seam is patched, and ``run_sync`` takes a fixed clock, so the
quote-freshness boundary is deterministic. Each order fills in its own
transaction; these tests assert the resulting book, not just the status.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from api.jobs import price_sync
from api.order_engine import fill_order
from api.postgres.models import Fund, Holding, Order, Position, Transaction

NOW = datetime(2026, 10, 25, 10, 0, 0, tzinfo=timezone.utc)


def _row(ltp, day_change_pct=0.0, source_time=NOW, **overrides):
    row = {
        "regularMarketPrice": ltp,
        "regularMarketChangePercent": day_change_pct,
        "regularMarketTime": None if source_time is None else source_time.timestamp(),
    }
    row.update(overrides)
    return row


def _quotes(monkeypatch, mapping):
    """Patch the batch seam. ``mapping`` is keyed by Yahoo ticker."""
    calls = []

    def fetch(tickers):
        calls.append(tickers)
        return {ticker: mapping[ticker] for ticker in tickers if ticker in mapping}

    monkeypatch.setattr(price_sync, "fetch_quotes", fetch)
    return calls


def _run(session_factory, monkeypatch, mapping, now=NOW):
    calls = _quotes(monkeypatch, mapping)
    price_sync.run_sync(session_factory, now=now)
    return calls


def _copy_sync_prices(monkeypatch, value):
    monkeypatch.setattr(price_sync, "fetch_quotes", lambda tickers: value)


def _fund(session_factory, user_id):
    with session_factory() as session:
        return session.scalar(select(Fund).where(Fund.user_id == user_id))


def _holding(session_factory, user_id, symbol="INFY"):
    with session_factory() as session:
        return session.scalar(
            select(Holding).where(
                Holding.user_id == user_id, Holding.symbol == symbol
            )
        )


# --------------------------------------------------------------------------
# Limit and stop matching
# --------------------------------------------------------------------------


def test_limit_buy_fills_at_its_limit_price_not_the_quote(
    book_session_factory, book_user, book_order_factory, monkeypatch
):
    order = book_order_factory(
        book_user, side="BUY", type="LIMIT", product="CNC", qty=5, price=100
    )

    _run(book_session_factory, monkeypatch, {"INFY.NS": _row(99.5, -1.0)})

    with book_session_factory() as session:
        claimed = session.get(Order, order.id)
    assert claimed.status == "EXECUTED"
    assert claimed.filled == 5
    assert claimed.price == Decimal("100.0000")  # the limit, not the 99.5 quote
    holding = _holding(book_session_factory, book_user)
    assert holding.qty == 5
    assert holding.avg_price == Decimal("100.000000")


def test_an_order_that_has_not_crossed_stays_open(
    book_session_factory, book_user, book_order_factory, monkeypatch
):
    order = book_order_factory(
        book_user, side="BUY", type="LIMIT", product="CNC", qty=5, price=100
    )

    _run(book_session_factory, monkeypatch, {"INFY.NS": _row(100.5)})

    with book_session_factory() as session:
        assert session.get(Order, order.id).status == "OPEN"
        assert session.scalar(select(func.count()).select_from(Holding)) == 0


def test_limit_sell_credits_funds_and_records_the_settlement(
    book_session_factory,
    book_user,
    book_holding_factory,
    book_order_factory,
    book_funds_factory,
    monkeypatch,
):
    book_holding_factory(
        book_user, symbol="INFY", qty=5, avg_price=Decimal("1400")
    )
    book_funds_factory(book_user, available=0)
    order = book_order_factory(
        book_user, side="SELL", type="LIMIT", product="CNC", qty=5, price=1500
    )

    _run(book_session_factory, monkeypatch, {"INFY.NS": _row(1510.0, 1.0)})

    with book_session_factory() as session:
        assert session.get(Order, order.id).status == "EXECUTED"
        assert session.get(Holding, order.id) is None
        assert (
            session.scalar(
                select(func.count()).select_from(Holding).where(
                    Holding.user_id == book_user
                )
            )
            == 0
        )
        settlement = session.scalar(
            select(Transaction).where(Transaction.user_id == book_user)
        )
    assert _fund(book_session_factory, book_user).available == Decimal("7500.00")
    assert settlement.method == "INFY sell"
    assert settlement.amount == Decimal("500.00")  # (1500 - 1400) * 5


def test_slm_fills_at_the_live_price_and_adjusts_the_blocked_cash(
    book_session_factory, book_user, book_order_factory, book_funds_factory, monkeypatch
):
    # 5 * 100 was blocked at placement; the fill at 106 needs 30 more.
    book_funds_factory(book_user, available=0)
    order = book_order_factory(
        book_user,
        side="BUY",
        type="SL-M",
        product="CNC",
        qty=5,
        price=100,
        trigger_price=105,
    )

    _run(book_session_factory, monkeypatch, {"INFY.NS": _row(106.0)})

    with book_session_factory() as session:
        claimed = session.get(Order, order.id)
    assert claimed.status == "EXECUTED"
    assert claimed.price == Decimal("106.0000")
    assert _fund(book_session_factory, book_user).available == Decimal("-30.00")


def test_slm_mis_exit_does_not_touch_the_blocked_cash_adjustment(
    book_session_factory,
    book_user,
    book_order_factory,
    book_funds_factory,
    book_position_factory,
    monkeypatch,
):
    book_funds_factory(book_user, available=1000)
    book_position_factory(
        book_user, symbol="INFY", side="SHORT", qty=5, entry=Decimal("1500")
    )
    order = book_order_factory(
        book_user,
        side="BUY",
        type="SL-M",
        product="MIS",
        qty=5,
        price=1500,
        trigger_price=1500,
        is_exit=True,
        group_id="group-1",
    )

    _run(book_session_factory, monkeypatch, {"INFY.NS": _row(1520.0)})

    # Only the MIS release lands: 1500*5 - 20*5 = 7400.
    assert _fund(book_session_factory, book_user).available == Decimal("8400.00")


def test_mis_exit_fill_settles_the_position_and_cancels_its_sibling(
    book_session_factory,
    book_user,
    book_position_factory,
    book_order_factory,
    book_funds_factory,
    monkeypatch,
):
    book_funds_factory(book_user, available=500)
    book_position_factory(
        book_user, symbol="INFY", side="LONG", qty=10, entry=Decimal("100")
    )
    exit_order = book_order_factory(
        book_user,
        side="SELL",
        type="LIMIT",
        product="MIS",
        qty=10,
        price=120,
        is_exit=True,
        group_id="group-1",
    )
    sibling = book_order_factory(
        book_user,
        side="SELL",
        type="LIMIT",
        product="MIS",
        qty=10,
        price=130,
        is_exit=True,
        group_id="group-1",
    )

    _run(book_session_factory, monkeypatch, {"INFY.NS": _row(120.0)})

    with book_session_factory() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(Position).where(
                    Position.user_id == book_user
                )
            )
            == 0
        )
        settlement = session.scalar(
            select(Transaction).where(Transaction.user_id == book_user)
        )
        assert session.get(Order, exit_order.id).status == "EXECUTED"
        assert session.get(Order, sibling.id).status == "CANCELLED"
    # 500 + (100*10 + (120-100)*10)
    assert _fund(book_session_factory, book_user).available == Decimal("1700.00")
    assert settlement.method == "INFY MIS exit"
    assert settlement.amount == Decimal("200.00")


def test_a_partial_mis_exit_keeps_the_remaining_position(
    book_session_factory,
    book_user,
    book_position_factory,
    book_order_factory,
    book_funds_factory,
    monkeypatch,
):
    book_funds_factory(book_user, available=0)
    position = book_position_factory(
        book_user, symbol="INFY", side="LONG", qty=10, entry=Decimal("100")
    )
    order = book_order_factory(
        book_user,
        side="SELL",
        type="LIMIT",
        product="MIS",
        qty=4,
        price=120,
        is_exit=True,
        group_id="group-1",
    )

    _run(book_session_factory, monkeypatch, {"INFY.NS": _row(120.0)})

    with book_session_factory() as session:
        remaining = session.get(Position, position.id)
        assert remaining.qty == 6
        assert session.get(Order, order.id).status == "EXECUTED"
    # 100*4 + (120-100)*4 = 480, and only 4 of the 10 were released.
    assert _fund(book_session_factory, book_user).available == Decimal("480.00")


def test_an_oversized_mis_exit_is_rejected_without_mutating_the_book(
    book_session_factory,
    book_user,
    book_position_factory,
    book_order_factory,
    monkeypatch,
):
    position = book_position_factory(
        book_user, symbol="INFY", side="LONG", qty=2, entry=Decimal("100")
    )
    order = book_order_factory(
        book_user,
        side="SELL",
        type="LIMIT",
        product="MIS",
        qty=5,
        price=100,
        is_exit=True,
        group_id="group-1",
    )

    _run(book_session_factory, monkeypatch, {"INFY.NS": _row(100.0)})

    with book_session_factory() as session:
        claimed = session.get(Order, order.id)
        assert claimed.status == "REJECTED"
        assert claimed.filled == 0
        assert claimed.price == Decimal("100.0000")
        assert session.get(Position, position.id).qty == 2
        assert session.scalar(select(func.count()).select_from(Transaction)) == 0
        assert session.scalar(select(func.count()).select_from(Fund)) == 0


def test_an_exit_without_a_position_is_cancelled_with_its_sibling(
    book_session_factory, book_user, book_order_factory, monkeypatch
):
    order = book_order_factory(
        book_user,
        side="SELL",
        type="LIMIT",
        product="MIS",
        qty=5,
        price=100,
        is_exit=True,
        group_id="group-1",
    )
    sibling = book_order_factory(
        book_user,
        side="SELL",
        type="LIMIT",
        product="MIS",
        qty=5,
        price=110,
        is_exit=True,
        group_id="group-1",
    )

    _run(book_session_factory, monkeypatch, {"INFY.NS": _row(100.0)})

    with book_session_factory() as session:
        assert session.get(Order, order.id).status == "CANCELLED"
        assert session.get(Order, sibling.id).status == "CANCELLED"
        assert session.scalar(select(func.count()).select_from(Fund)) == 0


def test_a_filled_order_is_not_filled_again_on_the_next_tick(
    book_session_factory,
    book_user,
    book_holding_factory,
    book_order_factory,
    book_funds_factory,
    monkeypatch,
):
    book_holding_factory(
        book_user, symbol="INFY", qty=5, avg_price=Decimal("100")
    )
    book_funds_factory(book_user, available=0)
    book_order_factory(
        book_user, side="SELL", type="LIMIT", product="CNC", qty=5, price=100
    )

    _run(book_session_factory, monkeypatch, {"INFY.NS": _row(100.0)})
    _run(book_session_factory, monkeypatch, {"INFY.NS": _row(100.0)})

    # The guarded OPEN -> EXECUTED transition means the second tick finds no
    # open order, so the proceeds and ledger entry are booked exactly once.
    assert _fund(book_session_factory, book_user).available == Decimal("500.00")
    with book_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Transaction)) == 1
        assert session.scalar(select(Order)).status == "EXECUTED"


def test_a_delivery_sell_without_enough_holding_is_rejected_untouched(
    book_session_factory,
    book_user,
    book_holding_factory,
    book_order_factory,
    monkeypatch,
):
    holding = book_holding_factory(
        book_user, symbol="INFY", qty=2, avg_price=Decimal("1400")
    )
    order = book_order_factory(
        book_user, side="SELL", type="LIMIT", product="CNC", qty=5, price=100
    )

    _run(book_session_factory, monkeypatch, {"INFY.NS": _row(100.0)})

    with book_session_factory() as session:
        claimed = session.get(Order, order.id)
        assert claimed.status == "REJECTED"
        assert claimed.filled == 0
        assert claimed.price == Decimal("100.0000")
        assert session.get(Holding, holding.id).qty == 2
        assert session.scalar(select(func.count()).select_from(Transaction)) == 0


def test_a_bracket_entry_spawns_open_exits(
    book_session_factory, book_user, book_order_factory, monkeypatch
):
    order = book_order_factory(
        book_user,
        side="BUY",
        type="LIMIT",
        product="CNC",
        qty=5,
        price=100,
        sl_trigger=90,
        tp_price=110,
        group_id="group-1",
    )

    _run(book_session_factory, monkeypatch, {"INFY.NS": _row(99.0)})

    with book_session_factory() as session:
        assert session.get(Order, order.id).status == "EXECUTED"
        exits = session.scalars(
            select(Order).where(
                Order.user_id == book_user,
                Order.is_exit.is_(True),
                Order.group_id == "group-1",
            )
        ).all()
    assert [leg.type for leg in exits] == ["SL-M", "LIMIT"]
    # The entry anchors the group; its exits must survive the entry's fill.
    assert all(leg.status == "OPEN" for leg in exits)
    assert _holding(book_session_factory, book_user).qty == 5


def test_one_bad_order_does_not_stop_the_others(
    book_session_factory, book_user, book_order_factory, monkeypatch
):
    first = book_order_factory(
        book_user, symbol="INFY", side="BUY", type="LIMIT", qty=1, price=100
    )
    second = book_order_factory(
        book_user, symbol="TCS", side="BUY", type="LIMIT", qty=1, price=200
    )

    def flaky(session, order, fill_price, now):
        if order.symbol == "INFY":
            raise RuntimeError("boom")
        return fill_order(session, order, fill_price, now)

    monkeypatch.setattr(price_sync, "fill_order", flaky)
    _run(
        book_session_factory,
        monkeypatch,
        {"INFY.NS": _row(90.0), "TCS.NS": _row(190.0)},
    )

    with book_session_factory() as session:
        assert session.get(Order, first.id).status == "OPEN"
        assert session.get(Order, second.id).status == "EXECUTED"
    assert _holding(book_session_factory, book_user, "TCS").qty == 1
    assert _holding(book_session_factory, book_user, "INFY") is None


# --------------------------------------------------------------------------
# Quote freshness
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source_time", "expected"),
    [
        (NOW - timedelta(minutes=10), "EXECUTED"),
        (NOW - timedelta(minutes=10, seconds=1), "OPEN"),
        (NOW + timedelta(minutes=2), "EXECUTED"),
        (NOW + timedelta(minutes=2, seconds=1), "OPEN"),
        (None, "OPEN"),
    ],
)
def test_a_fill_needs_a_trustworthy_provider_time(
    book_session_factory,
    book_user,
    book_order_factory,
    market_instrument_factory,
    monkeypatch,
    source_time,
    expected,
):
    market_instrument_factory(
        symbol="INFY", ltp=90.0, source_time=source_time, updated_at=NOW
    )
    order = book_order_factory(
        book_user, side="BUY", type="LIMIT", product="CNC", qty=1, price=100
    )
    # No provider answer this tick: the fill must use the cached quote.
    _copy_sync_prices(monkeypatch, {})

    price_sync.run_sync(book_session_factory, now=NOW)

    with book_session_factory() as session:
        assert session.get(Order, order.id).status == expected


def test_a_fresh_quote_is_used_from_the_canonical_cache(
    book_session_factory,
    book_user,
    book_order_factory,
    market_instrument_factory,
    monkeypatch,
):
    market_instrument_factory(
        symbol="INFY", ltp=90.0, source_time=NOW - timedelta(minutes=1), updated_at=NOW
    )
    order = book_order_factory(
        book_user, side="BUY", type="LIMIT", product="CNC", qty=2, price=100
    )
    _copy_sync_prices(monkeypatch, {})

    price_sync.run_sync(book_session_factory, now=NOW)

    with book_session_factory() as session:
        assert session.get(Order, order.id).status == "EXECUTED"
    assert _holding(book_session_factory, book_user).qty == 2


# --------------------------------------------------------------------------
# settle_mis_exit directly
# --------------------------------------------------------------------------


def _settle(session_factory, order_id, fill_price, user_id):
    with session_factory() as session:
        with session.begin():
            order = session.get(Order, order_id, with_for_update=True)
            from api.order_engine import settle_mis_exit

            return settle_mis_exit(session, order, Decimal(str(fill_price)), NOW)


def test_settle_long_releases_entry_plus_profit(
    book_session_factory,
    book_user,
    book_position_factory,
    book_order_factory,
    book_funds_factory,
):
    position = book_position_factory(
        book_user, symbol="INFY", side="LONG", qty=10, entry=Decimal("100")
    )
    book_funds_factory(book_user, available=0)
    order = book_order_factory(
        book_user,
        side="SELL",
        type="SL-M",
        product="MIS",
        qty=10,
        price=110,
        is_exit=True,
    )

    assert _settle(book_session_factory, order.id, "110", book_user) == "settled"

    with book_session_factory() as session:
        assert session.get(Position, position.id) is None
        settlement = session.scalar(select(Transaction))
    assert _fund(book_session_factory, book_user).available == Decimal("1100.00")
    assert settlement.amount == Decimal("100.00")


def test_settle_short_pnl_sign_is_inverted(
    book_session_factory,
    book_user,
    book_position_factory,
    book_order_factory,
    book_funds_factory,
):
    book_position_factory(
        book_user, symbol="INFY", side="SHORT", qty=10, entry=Decimal("100")
    )
    book_funds_factory(book_user, available=0)
    order = book_order_factory(
        book_user,
        side="BUY",
        type="SL-M",
        product="MIS",
        qty=10,
        price=90,
        is_exit=True,
    )

    assert _settle(book_session_factory, order.id, "90", book_user) == "settled"

    # Short 10 at 100, covered at 90 -> +100 profit.
    assert _fund(book_session_factory, book_user).available == Decimal("1100.00")
    with book_session_factory() as session:
        assert session.scalar(select(Transaction)).amount == Decimal("100.00")


def test_settle_rejects_an_oversized_exit(
    book_session_factory,
    book_user,
    book_position_factory,
    book_order_factory,
    book_funds_factory,
):
    position = book_position_factory(
        book_user, symbol="INFY", side="LONG", qty=4, entry=Decimal("100")
    )
    book_funds_factory(book_user, available=0)
    order = book_order_factory(
        book_user,
        side="SELL",
        type="SL-M",
        product="MIS",
        qty=10,
        price=110,
        is_exit=True,
    )

    assert _settle(book_session_factory, order.id, "110", book_user) == "rejected"

    with book_session_factory() as session:
        assert session.get(Position, position.id).qty == 4
        assert session.scalar(select(func.count()).select_from(Transaction)) == 0
    assert _fund(book_session_factory, book_user).available == Decimal("0.00")


def test_settle_a_full_exit_deletes_the_position_row(
    book_session_factory,
    book_user,
    book_position_factory,
    book_order_factory,
    book_funds_factory,
):
    # A qty of exactly zero would violate the qty > 0 constraint, so the
    # full-exit path must delete rather than write zero.
    position = book_position_factory(
        book_user, symbol="INFY", side="LONG", qty=3, entry=Decimal("50")
    )
    book_funds_factory(book_user, available=0)
    order = book_order_factory(
        book_user,
        side="SELL",
        type="SL-M",
        product="MIS",
        qty=3,
        price=60,
        is_exit=True,
    )

    assert _settle(book_session_factory, order.id, "60", book_user) == "settled"

    with book_session_factory() as session:
        assert session.get(Position, position.id) is None
    assert _fund(book_session_factory, book_user).available == Decimal("180.00")
