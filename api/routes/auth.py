"""Port of server/routes/authRoutes.js and server/controllers/authController.js.

The Express routes are:
    router.post("/signup", authLimiter, signup)  // POST /api/auth/signup
    router.post("/login", authLimiter, login)    // POST /api/auth/login
    router.post("/logout", logout)               // POST /api/auth/logout
    router.get("/me", protect, getMe)            // GET  /api/auth/me

The controller catches its own errors and answers with a `error` field, which
the central handler does not, so these handlers reproduce that envelope.

Phase 3B1 moves only the user identity to PostgreSQL. The other routes still
read MongoDB; their `require_user` dependency and 24-hex user ids are unchanged.
"""

import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import create_token, hash_password, require_user, verify_password
from ..config import get_settings
from ..postgres.models import User
from ..postgres.session import get_session
from ..serialization import to_json_value

router = APIRouter()

COOKIE_NAME = "token"
COOKIE_MAX_AGE = 7 * 24 * 60 * 60  # 7 days, in seconds


def cookie_secure() -> bool:
    """The controller's `isProduction`: only NODE_ENV=production sets Secure."""
    return get_settings().node_env == "production"


def server_error(err: Exception) -> JSONResponse:
    """The auth controller's own 500 body, which includes the raw message."""
    return JSONResponse(status_code=500, content={"message": "Server error", "error": str(err)})


def set_token_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=COOKIE_MAX_AGE,
        path="/",
        httponly=True,
        secure=cookie_secure(),
        samesite="strict",
    )


def new_user_id() -> str:
    """A 24-character lowercase hex id, the external ObjectId-compatible shape."""
    return secrets.token_hex(12)


def utcnow_ms() -> datetime:
    """Current UTC time truncated to the millisecond precision of the column."""
    now = datetime.now(timezone.utc)
    return now.replace(microsecond=(now.microsecond // 1000) * 1000)


def compact_user(user: User) -> dict:
    """The login/signup response shape."""
    return {"id": user.id, "username": user.username, "email": user.email}


def full_user(user: User) -> dict:
    """The legacy /me document shape, without the password hash."""
    return {
        "_id": user.id,
        "username": user.username,
        "email": user.email,
        "createdAt": to_json_value(user.created_at),
        "updatedAt": to_json_value(user.updated_at),
        "__v": user.version,
    }


@router.post("/api/auth/signup", status_code=201)
def signup(
    response: Response,
    body: dict | None = Body(default=None),
    session: Session = Depends(get_session),
):
    payload = body or {}
    username = payload.get("username")
    email = payload.get("email")
    password = payload.get("password")

    try:
        if not username or not email or not password:
            raise HTTPException(
                status_code=400,
                detail="Username, email and password are required",
            )
        if not isinstance(password, str) or len(password) < 8:
            raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

        if session.scalar(select(User.id).where(User.email == email)) is not None:
            raise HTTPException(status_code=400, detail="User already exists")
        if session.scalar(select(User.id).where(User.username == username)) is not None:
            raise HTTPException(status_code=400, detail="User already exists")

        now = utcnow_ms()
        user = User(
            id=new_user_id(),
            username=username,
            email=email,
            password_hash=hash_password(password),
            created_at=now,
            updated_at=now,
            version=0,
        )
        session.add(user)
        try:
            session.commit()
        except IntegrityError:
            # The pre-checks are only a fast path; the unique constraints close
            # the race between two concurrent signups.
            session.rollback()
            raise HTTPException(status_code=400, detail="User already exists")

        set_token_cookie(response, create_token(user.id))
        return {
            "message": "Signup successful",
            "user": compact_user(user),
        }
    except HTTPException:
        raise
    except Exception as err:  # mirrors the controller's catch-all
        session.rollback()
        return server_error(err)


@router.post("/api/auth/login")
def login(
    response: Response,
    body: dict | None = Body(default=None),
    session: Session = Depends(get_session),
):
    payload = body or {}
    email = payload.get("email")
    password = payload.get("password")

    try:
        if not email or not password:
            raise HTTPException(status_code=400, detail="Email and password are required")

        user = session.scalar(select(User).where(User.email == email))
        if user is None or not verify_password(password, user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid credentials")

        set_token_cookie(response, create_token(user.id))
        return {
            "message": "Login successful",
            "user": compact_user(user),
        }
    except HTTPException:
        raise
    except Exception as err:  # mirrors the controller's catch-all
        return server_error(err)


@router.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie(
        COOKIE_NAME,
        path="/",
        httponly=True,
        secure=cookie_secure(),
        samesite="strict",
    )
    return {"message": "Logged out"}


@router.get("/api/auth/me")
def get_me(
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
):
    try:
        # A malformed or missing id simply matches no row: 404, not a 500.
        user = session.get(User, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")

        return {"user": full_user(user)}
    except HTTPException:
        raise
    except Exception as err:  # mirrors the controller's catch-all
        return server_error(err)
