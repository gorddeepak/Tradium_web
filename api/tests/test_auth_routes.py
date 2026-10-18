"""Tests for the /api/auth routes.

These supersede the need to re-check the `require_user` guard itself, which
test_auth.py already covers through GET /api/holdings.
"""

import bcrypt
import jwt
import pytest
from bson import ObjectId

from api.auth import hash_password, verify_password
from api.documents import new_document
from api.rate_limit import AUTH_LIMIT
from api.tests.conftest import TEST_SECRET

PASSWORD = "hunter2hunter2"

# Produced by the npm `bcrypt` package (cost 10):
#   bcrypt.hash("correct horse battery staple", 10)
# Fixed here so the test proves Python's bcrypt reads hashes written by the
# Node app, which is the format existing `users` rows contain.
NODE_BCRYPT_HASH = "$2b$10$ms7JrEUixd/kZ.vTmJ/ypOdTdD3tMUaA65XQW52UBInnEWMnJN.YC"
NODE_PASSWORD = "correct horse battery staple"


def insert_user(database, username="deepak", email="deepak@example.com", stored_hash=None):
    """Insert a user the way the signup route would have."""
    user = new_document(
        username=username,
        email=email,
        password=stored_hash or hash_password(PASSWORD),
    )
    database["users"].insert_one(user)
    return user


def test_hashes_are_readable_across_implementations():
    # Neither direction of the Node/Python bcrypt boundary is assumed.
    assert verify_password(NODE_PASSWORD, NODE_BCRYPT_HASH) is True
    assert verify_password("wrong password here", NODE_BCRYPT_HASH) is False


def test_signup_creates_user_and_sets_cookie(client, database):
    response = client.post(
        "/api/auth/signup",
        json={"username": "deepak", "email": "deepak@example.com", "password": PASSWORD},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["message"] == "Signup successful"
    assert body["user"]["username"] == "deepak"
    assert body["user"]["email"] == "deepak@example.com"
    assert set(body["user"]) == {"id", "username", "email"}

    stored = database["users"].find_one({"email": "deepak@example.com"})
    assert stored["password"] != PASSWORD
    assert stored["password"].startswith("$2b$10$")
    assert bcrypt.checkpw(PASSWORD.encode(), stored["password"].encode())

    cookie = response.headers["set-cookie"]
    assert cookie.startswith("token=")
    assert "HttpOnly" in cookie
    assert "Max-Age=604800" in cookie
    assert "Path=/" in cookie
    # Starlette writes "SameSite=strict"; the value is case-insensitive per
    # RFC 6265, so only the attribute is asserted here.
    assert "samesite=strict" in cookie.lower()
    assert "secure" not in cookie.lower()  # only when NODE_ENV=production


def test_signup_writes_mongoose_style_document(client, database):
    client.post(
        "/api/auth/signup",
        json={"username": "deepak", "email": "deepak@example.com", "password": PASSWORD},
    )

    stored = database["users"].find_one({"email": "deepak@example.com"})
    assert set(stored) == {"_id", "username", "email", "password", "createdAt", "updatedAt", "__v"}
    assert stored["__v"] == 0


def test_signup_token_opens_protected_routes(client):
    client.post(
        "/api/auth/signup",
        json={"username": "deepak", "email": "deepak@example.com", "password": PASSWORD},
    )

    # TestClient keeps the cookie, so this is a real cookie round-trip.
    assert client.get("/api/holdings").status_code == 200


def test_signup_token_has_the_jsonwebtoken_claims(client):
    response = client.post(
        "/api/auth/signup",
        json={"username": "deepak", "email": "deepak@example.com", "password": PASSWORD},
    )

    token = client.cookies["token"]
    payload = jwt.decode(token, TEST_SECRET, algorithms=["HS256"])
    assert payload["id"] == response.json()["user"]["id"]
    assert payload["exp"] - payload["iat"] == 7 * 24 * 60 * 60


@pytest.mark.parametrize(
    "payload,message",
    [
        ({}, "Username, email and password are required"),
        ({"username": "deepak", "email": "deepak@example.com"}, "Username, email and password are required"),
        (
            {"username": "deepak", "email": "deepak@example.com", "password": "short"},
            "Password must be at least 8 characters",
        ),
        (
            {"username": "deepak", "email": "deepak@example.com", "password": 12345678},
            "Password must be at least 8 characters",
        ),
    ],
)
def test_signup_validation(client, payload, message):
    response = client.post("/api/auth/signup", json=payload)

    assert response.status_code == 400
    assert response.json() == {"message": message}


@pytest.mark.parametrize(
    "existing,payload",
    [
        ({"username": "somebody", "email": "deepak@example.com"},
         {"username": "deepak", "email": "deepak@example.com", "password": PASSWORD}),
        ({"username": "deepak", "email": "somebody@example.com"},
         {"username": "deepak", "email": "deepak@example.com", "password": PASSWORD}),
    ],
)
def test_signup_rejects_duplicates(client, database, existing, payload):
    insert_user(database, **existing)

    response = client.post("/api/auth/signup", json=payload)

    assert response.status_code == 400
    assert response.json() == {"message": "User already exists"}


def test_login_sets_cookie_and_returns_user(client, database):
    user = insert_user(database)

    response = client.post(
        "/api/auth/login",
        json={"email": "deepak@example.com", "password": PASSWORD},
    )

    assert response.status_code == 200
    assert response.json() == {
        "message": "Login successful",
        "user": {"id": str(user["_id"]), "username": "deepak", "email": "deepak@example.com"},
    }
    assert response.headers["set-cookie"].startswith("token=")


def test_login_token_opens_protected_routes(client, database):
    insert_user(database)

    client.post("/api/auth/login", json={"email": "deepak@example.com", "password": PASSWORD})

    assert client.get("/api/holdings").status_code == 200


@pytest.mark.parametrize(
    "email,password",
    [
        ("nobody@example.com", PASSWORD),
        ("deepak@example.com", "not-the-password"),
    ],
)
def test_login_rejects_bad_credentials(client, database, email, password):
    insert_user(database)

    response = client.post("/api/auth/login", json={"email": email, "password": password})

    assert response.status_code == 401
    assert response.json() == {"message": "Invalid credentials"}


def test_login_requires_email_and_password(client):
    response = client.post("/api/auth/login", json={})

    assert response.status_code == 400
    assert response.json() == {"message": "Email and password are required"}


def test_me_returns_the_user_without_password(client, database):
    user = insert_user(database)
    client.post("/api/auth/login", json={"email": "deepak@example.com", "password": PASSWORD})

    response = client.get("/api/auth/me")

    assert response.status_code == 200
    returned = response.json()["user"]
    assert set(returned) == {"_id", "username", "email", "createdAt", "updatedAt", "__v"}
    assert returned["_id"] == str(user["_id"])
    assert returned["createdAt"].endswith("Z")


def test_me_requires_a_cookie(client):
    response = client.get("/api/auth/me")

    assert response.status_code == 401
    assert response.json() == {"message": "Not authenticated"}


def test_me_returns_404_when_the_user_is_gone(client, make_token):
    response = client.get("/api/auth/me", cookies={"token": make_token(ObjectId())})

    assert response.status_code == 404
    assert response.json() == {"message": "User not found"}


def test_me_uses_the_auth_500_envelope_for_a_malformed_id(client, make_token):
    # Express's User.findById throws a CastError here and the controller answers
    # with its own body, which the central handler would not.
    response = client.get("/api/auth/me", cookies={"token": make_token("not-an-object-id")})

    assert response.status_code == 500
    body = response.json()
    assert body["message"] == "Server error"
    assert isinstance(body["error"], str) and body["error"]


def test_cookie_is_secure_when_node_env_is_production(client, monkeypatch):
    monkeypatch.setenv("NODE_ENV", "production")

    response = client.post(
        "/api/auth/signup",
        json={"username": "deepak", "email": "deepak@example.com", "password": PASSWORD},
    )

    assert "secure" in response.headers["set-cookie"].lower()


def test_logout_clears_the_cookie(client):
    response = client.post("/api/auth/logout")

    assert response.status_code == 200
    assert response.json() == {"message": "Logged out"}
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("token=")
    assert "Max-Age=0" in cookie
    assert "HttpOnly" in cookie


def test_signup_sets_the_draft7_rate_limit_headers(client):
    response = client.post("/api/auth/signup", json={})

    assert response.headers["ratelimit-policy"] == f"{AUTH_LIMIT};w=900"
    assert response.headers["ratelimit"].startswith(f"limit={AUTH_LIMIT}, remaining=")


def test_signup_and_login_share_one_limiter(client):
    # Express mounts a single limiter instance on both routes, so attempts
    # across the two add up.
    for _ in range(AUTH_LIMIT):
        assert client.post("/api/auth/login", json={}).status_code == 400

    blocked = client.post("/api/auth/signup", json={})

    assert blocked.status_code == 429
    assert blocked.json() == {"message": "Too many attempts. Try again in a few minutes."}
    assert "Retry-After" in blocked.headers


def test_logout_is_not_rate_limited(client):
    for _ in range(AUTH_LIMIT + 5):
        assert client.post("/api/auth/logout").status_code == 200
