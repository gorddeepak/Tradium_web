"""Nova assistant routes.

Mirrors server/routes/assistantRoutes.js:
    POST /api/assistant/chat       Vercel UI Message Stream (SSE)
    POST /api/assistant/insight    plain-text insight for one dashboard page
    POST /api/assistant/briefing   plain-text dashboard briefing
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic_ai.exceptions import ModelAPIError
from pydantic_ai.ui.vercel_ai import VercelAIAdapter
from pydantic_ai.usage import UsageLimits
from pymongo.database import Database

from ..assistant import (
    AINotConfigured,
    BRIEFING_SYSTEM_PROMPT,
    NovaDeps,
    briefing_user_prompt,
    chat_agent,
    get_ai_model,
    insight_system_prompt,
    insight_user_prompt,
    plain_agent,
)
from ..auth import require_user
from ..db import get_database

logger = logging.getLogger(__name__)

router = APIRouter()

# Express uses stepCountIs(5): at most five model requests in one chat turn.
CHAT_USAGE_LIMITS = UsageLimits(request_limit=5)


async def _json_body(request: Request):
    try:
        return await request.json()
    except Exception:
        return None


@router.post("/api/assistant/chat")
async def assistant_chat(
    request: Request,
    user_id: str = Depends(require_user),
):
    payload = await _json_body(request)
    messages = payload.get("messages") if isinstance(payload, dict) else None
    if not isinstance(messages, list):
        return JSONResponse(status_code=400, content={"error": "Invalid messages payload"})

    try:
        model = get_ai_model()
    except AINotConfigured:
        return JSONResponse(status_code=503, content={"error": "AI is not configured"})

    try:
        return await VercelAIAdapter.dispatch_request(
            request,
            agent=chat_agent,
            model=model,
            deps=NovaDeps(user_id=user_id),
            sdk_version=7,
            usage_limits=CHAT_USAGE_LIMITS,
        )
    except ModelAPIError:
        logger.exception("Gemini request failed for /api/assistant/chat")
        return JSONResponse(status_code=502, content={"error": "AI provider request failed"})
    except Exception:
        logger.exception("Assistant request failed for /api/assistant/chat")
        return JSONResponse(status_code=500, content={"error": "Assistant request failed"})


@router.post("/api/assistant/insight")
async def assistant_insight(
    request: Request,
    user_id: str = Depends(require_user),
    db: Database = Depends(get_database),
):
    payload = await _json_body(request)
    if not isinstance(payload, dict):
        return JSONResponse(status_code=400, content={"message": "Invalid request"})

    page = payload.get("page")
    data = payload.get("data")

    try:
        model = get_ai_model()
    except AINotConfigured:
        raise HTTPException(status_code=503, detail="AI is not configured")

    return await _text_response(
        model,
        insight_system_prompt(page),
        insight_user_prompt(page, data),
    )


@router.post("/api/assistant/briefing")
async def assistant_briefing(
    request: Request,
    user_id: str = Depends(require_user),
    db: Database = Depends(get_database),
):
    payload = await _json_body(request)
    if not isinstance(payload, dict):
        return JSONResponse(status_code=400, content={"message": "Invalid request"})

    try:
        model = get_ai_model()
    except AINotConfigured:
        raise HTTPException(status_code=503, detail="AI is not configured")

    return await _text_response(
        model,
        BRIEFING_SYSTEM_PROMPT,
        briefing_user_prompt(payload.get("data")),
    )


async def _text_response(model, system_prompt, prompt):
    """Stream plain text. All PydanticAI context stays in this one task."""
    async def body():
        try:
            async with plain_agent.run_stream(
                prompt, model=model, instructions=system_prompt
            ) as result:
                async for chunk in result.stream_text(delta=True, debounce_by=None):
                    yield chunk
        except ModelAPIError:
            # Headers are already sent once streaming starts, so the client's
            # only recovery is the same friendly line PageInsight uses.
            logger.exception("Gemini request failed for an insight/briefing")
            yield "Insight unavailable right now."
        except Exception:
            logger.exception("Insight/briefing request failed")
            yield "Insight unavailable right now."

    return StreamingResponse(body(), media_type="text/plain")
