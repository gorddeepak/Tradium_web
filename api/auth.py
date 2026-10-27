"""Cookie-based JWT authentication.

Port of server/middlewares/auth.js and the credential handling in
server/controllers/authController.js. The token is read from the `token`
cookie, verified with JWT_SECRET, and the `id` claim becomes the
authenticated user id. The caller never supplies a user id.

The token factory and the bcrypt helpers live here too, so signing and
verifying always share one secret and one password algorithm.
"""

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import HTTPException, Request

from .config import get_settings

# jsonwebtoken signs for 7 days by default in the Express controller.
TOKEN_LIFETIME = timedelta(days=7)

# bcrypt cost used by the User model's pre-save hook.
BCRYPT_ROUNDS = 10

# bcrypt only reads the first 72 bytes of a password. Node's bcrypt package
# truncates silently; Python's raises instead, so truncate to match.
BCRYPT_MAX_BYTES = 72


def create_token(user_id) -> str:
    """Sign the cookie token the way jsonwebtoken's sign({ id }) does.

    jsonwebtoken adds `iat` and derives `exp` from `expiresIn`, so the
    payload is { id, iat, exp } and the signature is HS256.
    """
    issued_at = datetime.now(timezone.utc)
    payload = {
        "id": str(user_id),
        "iat": int(issued_at.timestamp()),
        "exp": int((issued_at + TOKEN_LIFETIME).timestamp()),
    }
    return jwt.encode(payload, get_settings().jwt_secret, algorithm="HS256")


def hash_password(password: str) -> str:
    """Hash a password with the same algorithm and cost as the User model."""
    raw = password.encode("utf-8")[:BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("utf-8")


def verify_password(candidate: str, stored: str) -> bool:
    """Compare a plaintext password against a stored bcrypt hash."""
    if not isinstance(candidate, str) or not isinstance(stored, str):
        return False
    raw = candidate.encode("utf-8")[:BCRYPT_MAX_BYTES]
    try:
        return bcrypt.checkpw(raw, stored.encode("utf-8"))
    except ValueError:
        # A malformed hash in the database can only be a failed login.
        return False


def user_from_token(token: str | None) -> str:
    """Return the user id in a cookie token, or raise 401.

    Shared by the HTTP guard and the WebSocket handshake, which reads the same
    ``token`` cookie but cannot use a ``Request`` dependency.
    """
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


def require_user(request: Request) -> str:
    return user_from_token(request.cookies.get("token"))
