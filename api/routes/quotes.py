"""WebSocket route for the shared quote hub.

The watchlist stream keeps its own endpoint and frame shape; this one is the
general channel a page opens for the symbols it is showing:

    /api/quotes/stream?symbols=INFY,TCS,^NSEI

``symbols`` is optional. A client may also send
``{"type": "subscribe", "symbols": [...]}`` or ``{"type": "unsubscribe",
"symbols": [...]}`` while connected, which is how a page can extend its set
without reconnecting.

The first two frames are a ``status`` frame (whether the upstream feed is
live, disabled or reconnecting) and a ``quotes`` snapshot from the in-memory
cache. REST still paints the page; the snapshot only removes the wait for the
next tick and carries the persisted values loaded at startup.

Authentication is the same ``token`` cookie as the REST routes. An invalid
token is closed with 1008 after accepting, because a browser cannot read a
close code from a rejected handshake and would otherwise retry forever.
"""

import json
import logging

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from ..auth import user_from_token
from ..quote_service import quote_service
from ..quote_stream import hub, normalize_symbols

logger = logging.getLogger(__name__)

router = APIRouter()


def _message_symbols(message):
    """The symbol list from a client message, tolerating a malformed one."""
    if not isinstance(message, dict):
        return []
    symbols = message.get("symbols")
    if not isinstance(symbols, list):
        return []
    return normalize_symbols(symbols)


async def _send_snapshot(websocket, symbols):
    """Send cached quotes for ``symbols`` when there is anything to send."""
    frames = quote_service.frames_for(symbols)
    if frames:
        await websocket.send_json({"type": "quotes", "quotes": frames})
    return frames


@router.websocket("/api/quotes/stream")
async def stream_quotes(websocket: WebSocket):
    """Push quote changes for the symbols this connection watches."""
    try:
        user_id = user_from_token(websocket.cookies.get("token"))
    except HTTPException:
        await websocket.accept()
        await websocket.close(code=1008, reason="Not authenticated")
        return

    requested = normalize_symbols(
        (websocket.query_params.get("symbols") or "").split(",")
    )

    await websocket.accept()
    try:
        await websocket.send_json({"type": "status", **quote_service.status()})
        await _send_snapshot(websocket, requested)
        # Register after accept and the snapshot, so a hub publish can never
        # try to send on a socket that is still completing its handshake.
        await hub.connect(websocket, user_id, requested)

        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except ValueError:
                continue
            kind = message.get("type") if isinstance(message, dict) else None
            if kind == "subscribe":
                symbols = _message_symbols(message)
                hub.subscribe(websocket, user_id, symbols)
                await _send_snapshot(websocket, symbols)
            elif kind == "unsubscribe":
                hub.unsubscribe(websocket, user_id, _message_symbols(message))
            # Anything else is ignored: this channel is push-only.
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(websocket, user_id)
