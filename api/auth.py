"""Cookie-based JWT authentication.

Port of server/middlewares/auth.js. The token is read from the `token`
cookie, verified with JWT_SECRET, and the `id` claim becomes the
authenticated user id. The caller never supplies a user id.
"""

import jwt
from fastapi import Depends, HTTPException, Request

from .config import get_settings


def require_user(request: Request) -> str:
    token = request.cookies.get("token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        payload = jwt.decode(
            token,
            get_settings().jwt_secret,
            algorithms=["HS256"],
        )
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = payload.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return str(user_id)
