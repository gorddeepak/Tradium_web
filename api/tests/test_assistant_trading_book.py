"""PostgreSQL-backed tests for Nova's trading-book tools.

Phase 3C2B moved `getPortfolioSummary`, `getHoldings`, `getPositions`,
`getFunds` and `getOrders` off MongoDB. These tests replace the previous
mongomock assertions: they seed the PostgreSQL book and quote cache, then call
the snapshot helpers that the tools return, plus one streamed turn that proves a
tool call still reaches PostgreSQL through the route.

They run only when TEST_DATABASE_URL names a disposable PostgreSQL database; the
chat turn points the assistant module's session factory at that database.
"""

import json
import os
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from pydantic_ai.messages import ToolReturnPart
from pydantic_ai.models.function import DeltaToolCall, FunctionModel

from api import assistant
from api.main import create_app
from api.routes import assistant as assistant_routes
from api.serialization import to_json_value

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL is not set; PostgreSQL Nova tests skipped",
)

OLDER = datetime(2026, 9, 1, 4, 15, 30, 123000, tzinfo=timezone.utc)


@pytest.fixture
def client():
    """The API with PostgreSQL sessions. The app needs no MongoDB."""
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def _chat_payload(text="How are my holdings?"):
    return {
        "id": "chat-1",
        "trigger": "submit-message",
        "messages": [
            {
                "id": "message-1",
                "role": "user",
                "parts": [{"type": "text", "text": text}],
            }
        ],
    }


def _sse_chunks(response):
    for line in response.text.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            continue
        yield json.loads(payload)


def test_portfolio_snapshot_matches_the_shared_math(
    book_user,
    book_session_factory,
    book_holding_factory,
    market_instrument_factory,
):
    market_instrument_factory(symbol="RELIANCE", ltp=2500.0, day_change_pct=1.25)
    market_instrument_factory(symbol="INFY", ltp=1500.0, day_change_pct=-0.5)
    book_holding_factory(book_user, symbol="RELIANCE", qty=10, avg_price="2400.5")
    book_holding_factory(book_user, symbol="INFY", qty=5, avg_price="1400")

    result = assistant.portfolio_snapshot(book_user, book_session_factory)

    assert result["holdingsCount"] == 2
    assert result["data"]["invested"] == 31005.0
    assert result["data"]["value"] == 32500.0
    assert result["data"]["pnl"] == 1495.0
    assert "Portfolio ₹32,500" in result["summary"]
    assert "RELIANCE" in result["summary"]


def test_portfolio_snapshot_for_an_empty_book(
    book_user, book_session_factory
):
    result = assistant.portfolio_snapshot(book_user, book_session_factory)

    assert result["holdingsCount"] == 0
    assert result["data"]["invested"] == 0
    assert result["data"]["value"] == 0
    assert result["summary"].endswith("Top mover: none.")


def test_holdings_snapshot_keeps_the_mongoose_field_names(
    book_user,
    book_session_factory,
    book_holding_factory,
    market_instrument_factory,
):
    market_instrument_factory(symbol="RELIANCE", ltp=2500.0, day_change_pct=1.25)
    # TCS is held but has no quote yet, exactly like a cold price cache.
    # Distinct timestamps keep creation order deterministic; the reader sorts by
    # created_at then id, and ids are random.
    book_holding_factory(
        book_user,
        symbol="RELIANCE",
        qty=10,
        avg_price="2400.5",
        created_at=OLDER,
    )
    book_holding_factory(
        book_user,
        symbol="TCS",
        name="Tata Consultancy",
        qty=1,
        avg_price="3000",
        created_at=OLDER.replace(minute=16),
    )

    snapshot = assistant.holdings_snapshot(book_user, book_session_factory)

    assert snapshot["data"] == [
        {
            "symbol": "RELIANCE",
            "name": "Reliance Industries",
            "exchange": "NSE",
            "quantity": 10,
            "avgPrice": 2400.5,
            "ltp": 2500.0,
            "dayChangePct": 1.25,
        },
        {
            "symbol": "TCS",
            "name": "Tata Consultancy",
            "exchange": "NSE",
            "quantity": 1,
            "avgPrice": 3000.0,
            "ltp": 0.0,
            "dayChangePct": 0.0,
        },
    ]
    assert snapshot["summary"].startswith("Holdings 2 items, total value ₹25,000")
    assert "top: RELIANCE 10@2500.0" in snapshot["summary"]


def test_positions_snapshot_direction_and_cross_user_isolation(
    book_user,
    book_user_factory,
    book_session_factory,
    book_position_factory,
    book_holding_factory,
    market_instrument_factory,
):
    other = book_user_factory()
    market_instrument_factory(symbol="INFY", ltp=180.0)
    book_position_factory(book_user, side="SHORT", qty=5, entry="200")
    book_position_factory(other, symbol="TCS", side="LONG", qty=9, entry="100")
    book_holding_factory(other, symbol="TCS", qty=99)

    positions = assistant.positions_snapshot(book_user, book_session_factory)
    holdings = assistant.holdings_snapshot(book_user, book_session_factory)

    assert positions["data"][0]["pnl"] == 100.0
    assert positions["data"][0]["side"] == "SHORT"
    assert positions["data"][0]["entryPrice"] == 200.0
    assert positions["data"][0]["currentPrice"] == 180.0
    assert len(positions["data"]) == 1
    assert holdings["data"] == []


def test_funds_snapshot_derives_used_margin(
    book_user,
    book_session_factory,
    book_funds_factory,
    book_order_factory,
    book_position_factory,
    book_transaction_factory,
):
    book_funds_factory(book_user, available=50000)
    book_order_factory(
        book_user, side="BUY", product="CNC", qty=10, filled=4, price=100
    )
    # An exit never blocks cash, so it must not move usedMargin.
    book_order_factory(
        book_user, side="SELL", product="MIS", qty=5, price=999, is_exit=True
    )
    book_position_factory(book_user, product="MIS", qty=5, entry="200")
    book_transaction_factory(book_user, kind="SETTLEMENT", amount="150")

    result = assistant.funds_snapshot(book_user, book_session_factory)

    assert result["data"]["available"] == 50000.0
    assert result["data"]["blockedInOrders"] == 600.0
    assert result["data"]["misMargin"] == 1000.0
    assert result["data"]["usedMargin"] == 1600.0
    assert result["data"]["realizedPnl"] == 150.0


def test_funds_snapshot_without_a_funds_row(
    book_user, book_session_factory
):
    result = assistant.funds_snapshot(book_user, book_session_factory)

    assert result["data"] == {
        "available": 0.0,
        "usedMargin": 0.0,
        "blockedInOrders": 0.0,
        "misMargin": 0.0,
        "realizedPnl": 0.0,
    }


def test_orders_snapshot_maps_status_and_quantity(
    book_user, book_session_factory, book_order_factory
):
    book_order_factory(book_user, symbol="OPEN1", status="OPEN", qty=5)
    book_order_factory(book_user, symbol="DONE1", status="EXECUTED", qty=7)

    pending = assistant.orders_snapshot(
        book_user, status="pending", session_factory=book_session_factory
    )
    executed = assistant.orders_snapshot(
        book_user, status="executed", session_factory=book_session_factory
    )

    assert [order["symbol"] for order in pending["data"]] == ["OPEN1"]
    assert pending["data"][0]["quantity"] == 5
    assert [order["symbol"] for order in executed["data"]] == ["DONE1"]
    assert executed["data"][0]["quantity"] == 7


def test_orders_snapshot_is_newest_first_and_limits(
    book_user, book_session_factory, book_order_factory
):
    book_order_factory(book_user, symbol="OLD", created_at=OLDER)
    book_order_factory(
        book_user,
        symbol="NEW",
        created_at=datetime(2026, 9, 2, 4, 15, 30, tzinfo=timezone.utc),
    )

    result = assistant.orders_snapshot(
        book_user, limit=1, session_factory=book_session_factory
    )

    assert [order["symbol"] for order in result["data"]] == ["NEW"]


def test_serialized_order_dates_match_the_api(
    book_user, book_session_factory, book_order_factory
):
    book_order_factory(book_user)

    result = assistant.orders_snapshot(book_user, session_factory=book_session_factory)

    assert result["data"][0]["createdAt"] == to_json_value(OLDER)


def test_chat_streams_a_tool_call_and_its_result(
    client,
    book_user,
    book_session_factory,
    book_holding_factory,
    market_instrument_factory,
    make_token,
    monkeypatch,
):
    market_instrument_factory(symbol="RELIANCE", ltp=2500.0)
    book_holding_factory(book_user, symbol="RELIANCE", qty=10)
    monkeypatch.setattr(assistant, "get_session_factory", lambda: book_session_factory)

    async def stream_text(messages, info):
        has_tool_result = any(
            isinstance(part, ToolReturnPart)
            for message in messages
            for part in message.parts
        )
        if not has_tool_result:
            yield {
                0: DeltaToolCall(
                    name="getHoldings", json_args="{}", tool_call_id="call-1"
                )
            }
        else:
            yield "You hold 10 RELIANCE."

    monkeypatch.setattr(
        assistant_routes,
        "get_ai_model",
        lambda: FunctionModel(stream_function=stream_text),
    )
    client.cookies.set("token", make_token(book_user))

    response = client.post("/api/assistant/chat", json=_chat_payload())

    assert response.status_code == 200
    chunks = list(_sse_chunks(response))
    kinds = [chunk["type"] for chunk in chunks]
    assert "tool-input-available" in kinds
    assert "tool-output-available" in kinds
    tool_output = next(
        chunk for chunk in chunks if chunk["type"] == "tool-output-available"
    )
    assert "RELIANCE" in json.dumps(tool_output["output"])
