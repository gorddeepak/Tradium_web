"""Focused tests for Nova: auth, configuration and streaming.

The model is replaced with PydanticAI's FunctionModel, so no test contacts
Gemini. The browser E2E in the migration log is the live-provider check.

The tools themselves read the PostgreSQL trading book since Phase 3C2B, so
their data tests live in `test_assistant_trading_book.py`.
"""

import json

from pydantic_ai.models.function import FunctionModel

from api.routes import assistant as assistant_routes


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
