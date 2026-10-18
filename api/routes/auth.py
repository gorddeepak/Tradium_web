"""Port of server/routes/authRoutes.js and server/controllers/authController.js.

The Express routes are:
    router.post("/signup", authLimiter, signup)  // POST /api/auth/signup
    router.post("/login", authLimiter, login)    // POST /api/auth/login
    router.post("/logout", logout)               // POST /api/auth/logout
    router.get("/me", protect, getMe)            // GET  /api/auth/me

The controller catches its own errors and answers with a `error` field, which
the central handler does not, so these handlers reproduce that envelope.
"""

from bson import ObjectId
from fastapi import APIRouter, Body, Depends, HTTPException, Response
from fastapi.responses import JSONResponse
from pymongo.database import Database

from ..auth import create_token, hash_password, require_user, verify_password
from ..config import get_settings
from ..db import get_database
from ..documents import new_document
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


@router.post("/api/auth/signup", status_code=201)
def signup(
    response: Response,
    body: dict | None = Body(default=None),
    db: Database = Depends(get_database),
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

        if db["users"].find_one({"email": email}) is not None:
            raise HTTPException(status_code=400, detail="User already exists")
        if db["users"].find_one({"username": username}) is not None:
            raise HTTPException(status_code=400, detail="User already exists")

        user = new_document(username=username, email=email, password=hash_password(password))
        db["users"].insert_one(user)

        set_token_cookie(response, create_token(user["_id"]))
        return {
            "message": "Signup successful",
            "user": {"id": str(user["_id"]), "username": user["username"], "email": user["email"]},
        }
    except HTTPException:
        raise
    except Exception as err:  # mirrors the controller's catch-all
        return server_error(err)


@router.post("/api/auth/login")
def login(
    response: Response,
    body: dict | None = Body(default=None),
    db: Database = Depends(get_database),
):
    payload = body or {}
    email = payload.get("email")
    password = payload.get("password")

    try:
        if not email or not password:
            raise HTTPException(status_code=400, detail="Email and password are required")

        user = db["users"].find_one({"email": email})
        if user is None or not verify_password(password, user.get("password", "")):
            raise HTTPException(status_code=401, detail="Invalid credentials")

        set_token_cookie(response, create_token(user["_id"]))
        return {
            "message": "Login successful",
            "user": {"id": str(user["_id"]), "username": user["username"], "email": user["email"]},
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
    db: Database = Depends(get_database),
):
    try:
        user = db["users"].find_one({"_id": ObjectId(user_id)})
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")

        user.pop("password", None)
        return {"user": to_json_value(user)}
    except HTTPException:
        raise
    except Exception as err:  # mirrors the controller's catch-all
        return server_error(err)
