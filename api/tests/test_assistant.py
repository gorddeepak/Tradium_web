"""Focused tests for Nova: tool data, auth, configuration and streaming.

The model is replaced with PydanticAI's FunctionModel, so no test contacts
Gemini. The browser E2E in the migration log is the live-provider check.
"""

import json

from pydantic_ai.messages import ToolReturnPart
from pydantic_ai.models.function import DeltaToolCall, FunctionModel

from api import assistant
from api.routes import assistant as assistant_routes
from api.serialization import to_json_value


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


def test_chat_requires_authentication(client):
    response = client.post("/api/assistant/chat", json=_chat_payload())
    assert response.status_code == 401
    assert response.json() == {"message": "Not authenticated"}


def test_chat_rejects_non_array_messages(client, make_token, user_id):
    client.cookies.set("token", make_token(user_id))
    response = client.post(
        "/api/assistant/chat",
        json={"id": "chat-1", "messages": "not-a-list"},
    )
    assert response.status_code == 400
    assert response.json() == {"error": "Invalid messages payload"}


def test_chat_returns_503_without_gemini_key(client, make_token, user_id, monkeypatch):
    monkeypatch.delenv("GOOGLE_GENERATIVE_AI_API_KEY", raising=False)
    client.cookies.set("token", make_token(user_id))

    response = client.post("/api/assistant/chat", json=_chat_payload())

    assert response.status_code == 503
    assert response.json() == {"error": "AI is not configured"}


def test_chat_streams_text_with_the_vercel_protocol(
    client, make_token, user_id, monkeypatch
):
    async def stream_text(messages, info):
        yield "Your portfolio is up."

    monkeypatch.setattr(
        assistant_routes,
        "get_ai_model",
        lambda: FunctionModel(stream_function=stream_text),
    )
    client.cookies.set("token", make_token(user_id))

    response = client.post("/api/assistant/chat", json=_chat_payload())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    chunks = list(_sse_chunks(response))
    kinds = [chunk["type"] for chunk in chunks]
    assert "text-delta" in kinds
    text = "".join(
        chunk.get("delta", "") for chunk in chunks if chunk["type"] == "text-delta"
    )
    assert text == "Your portfolio is up."
    assert "finish" in kinds


def test_chat_streams_a_tool_call_and_its_result(
    client, database, make_token, user_id, holdings_factory, monkeypatch
):
    database["holdings"].insert_one(holdings_factory(user_id, symbol="RELIANCE", qty=10))

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
    client.cookies.set("token", make_token(user_id))

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


def test_insight_streams_plain_text(client, make_token, user_id, monkeypatch):
    async def stream_text(messages, info):
        yield "Infosys is leading your holdings today."

    monkeypatch.setattr(
        assistant_routes,
        "get_ai_model",
        lambda: FunctionModel(stream_function=stream_text),
    )
    client.cookies.set("token", make_token(user_id))

    response = client.post(
        "/api/assistant/insight",
        json={"page": "holdings", "data": {"count": 1, "mover": "INFY"}},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == "Infosys is leading your holdings today."


def test_briefing_streams_plain_text(client, make_token, user_id, monkeypatch):
    async def stream_text(messages, info):
        yield "Your book is quiet today."

    monkeypatch.setattr(
        assistant_routes,
        "get_ai_model",
        lambda: FunctionModel(stream_function=stream_text),
    )
    client.cookies.set("token", make_token(user_id))

    response = client.post(
        "/api/assistant/briefing",
        json={"data": {"dayPnl": 0, "name": "Deepak"}},
    )

    assert response.status_code == 200
    assert response.text == "Your book is quiet today."


def test_insight_returns_503_without_gemini_key(client, make_token, user_id, monkeypatch):
    monkeypatch.delenv("GOOGLE_GENERATIVE_AI_API_KEY", raising=False)
    client.cookies.set("token", make_token(user_id))

    response = client.post(
        "/api/assistant/insight",
        json={"page": "holdings", "data": {}},
    )

    assert response.status_code == 503
    assert response.json() == {"message": "AI is not configured"}


def test_portfolio_snapshot_matches_the_shared_math(database, user_id, holdings_factory):
    database["holdings"].insert_many(
        [
            holdings_factory(user_id, symbol="RELIANCE", qty=10, avg_price=2400.5),
            holdings_factory(user_id, symbol="INFY", qty=5, avg_price=1400.0),
        ]
    )

    result = assistant.portfolio_snapshot(database, str(user_id))

    assert result["holdingsCount"] == 2
    assert result["data"]["invested"] == 31005.0
    assert result["data"]["value"] == 37500.0
    assert "Portfolio ₹37,500" in result["summary"]
    assert "RELIANCE" in result["summary"]


def test_orders_snapshot_maps_status_and_quantity(
    database, user_id, orders_factory
):
    database["orders"].insert_many(
        [
            orders_factory(user_id, symbol="OPEN1", status="OPEN", qty=5),
            orders_factory(user_id, symbol="DONE1", status="EXECUTED", qty=7),
        ]
    )

    pending = assistant.orders_snapshot(database, str(user_id), status="pending")
    executed = assistant.orders_snapshot(database, str(user_id), status="executed")

    assert [order["symbol"] for order in pending["data"]] == ["OPEN1"]
    assert pending["data"][0]["quantity"] == 5
    assert [order["symbol"] for order in executed["data"]] == ["DONE1"]
    assert executed["data"][0]["quantity"] == 7


def test_funds_snapshot_derives_used_margin(
    database, user_id, funds_factory, orders_factory, positions_factory
):
    database["funds"].insert_one(funds_factory(user_id, available=50000))
    database["orders"].insert_one(
        orders_factory(user_id, side="BUY", product="CNC", qty=10, filled=4, price=100)
    )
    database["positions"].insert_one(
        positions_factory(user_id, product="MIS", qty=5, entry=200)
    )
    database["transactions"].insert_one(
        {"user": user_id, "kind": "SETTLEMENT", "amount": 150}
    )

    result = assistant.funds_snapshot(database, str(user_id))

    assert result["data"]["available"] == 50000
    assert result["data"]["blockedInOrders"] == 600
    assert result["data"]["misMargin"] == 1000
    assert result["data"]["usedMargin"] == 1600
    assert result["data"]["realizedPnl"] == 150


def test_positions_snapshot_direction_and_cross_user_isolation(
    database, user_id, other_user_id, positions_factory, holdings_factory
):
    database["positions"].insert_one(
        positions_factory(user_id, side="SHORT", qty=5, entry=200, ltp=180)
    )
    database["positions"].insert_one(
        positions_factory(other_user_id, symbol="OTHER", side="LONG", qty=9)
    )
    database["holdings"].insert_one(
        holdings_factory(other_user_id, symbol="OTHER", qty=99)
    )

    positions = assistant.positions_snapshot(database, str(user_id))
    holdings = assistant.holdings_snapshot(database, str(user_id))

    assert positions["data"][0]["pnl"] == 100
    assert positions["data"][0]["side"] == "SHORT"
    assert len(positions["data"]) == 1
    assert holdings["data"] == []


def test_serialized_order_dates_match_the_api(database, user_id, orders_factory):
    order = orders_factory(user_id)
    database["orders"].insert_one(order)

    result = assistant.orders_snapshot(database, str(user_id))

    assert result["data"][0]["createdAt"] == to_json_value(order["createdAt"])
