"""PostgreSQL-backed tests for the /api/auth routes.

Phase 3B1 moved user identity to PostgreSQL, so these replace the previous
mongomock assertions. Like test_postgres_migration.py they run only when
TEST_DATABASE_URL points at a disposable PostgreSQL database whose name ends
in "_test"; there is no SQLite fallback.

The rest of the API still reads MongoDB, so the client fixture pairs the real
PostgreSQL session with an in-memory mongomock database. That mixed state is
intentional for this phase.
"""

import os
import re
import secrets
from datetime import datetime, timezone

import bcrypt
import jwt
import mongomock
import pytest
from alembic import command
from alembic.config import Config
from bson import ObjectId
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from api.auth import hash_password, verify_password
from api.main import create_app
from api.postgres.base import Base
from api.postgres.models import User
from api.postgres.session import get_session
from api.rate_limit import AUTH_LIMIT
from api.routes import auth as auth_routes
from api.tests.conftest import TEST_SECRET

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "").strip()

PASSWORD = "hunter2hunter2"
NOW = datetime(2026, 10, 25, 12, 0, 0, 123000, tzinfo=timezone.utc)

# Produced by the npm `bcrypt` package (cost 10):
#   bcrypt.hash("correct horse battery staple", 10)
# Fixed here so the test proves Python's bcrypt reads hashes written by the
# Node app, which is the format existing user records contain.
NODE_BCRYPT_HASH = "$2b$10$ms7JrEUixd/kZ.vTmJ/ypOdTdD3tMUaA65XQW52UBInnEWMnJN.YC"
NODE_PASSWORD = "correct horse battery staple"

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL is not set; PostgreSQL auth tests skipped",
)


@pytest.fixture(scope="module")
def database_url():
    url = make_url(TEST_DATABASE_URL)
    if not url.drivername.startswith("postgresql"):
        pytest.fail("TEST_DATABASE_URL must use PostgreSQL; SQLite is not a substitute")
    if not (url.database or "").endswith("_test"):
        pytest.fail("TEST_DATABASE_URL must name a disposable database ending in _test")
    return TEST_DATABASE_URL


@pytest.fixture(scope="module")
def alembic_config(database_url):
    config = Config(os.path.join(ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(ROOT, "api", "migrations"))

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv("DIRECT_DATABASE_URL", database_url)
        yield config


@pytest.fixture(scope="module")
def engine(database_url):
    engine = create_engine(database_url)

    # Start from a fresh schema every run. This is a test-only drop guarded by
    # the "_test" database check; Alembic still owns every CREATE below.
    Base.metadata.drop_all(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))

    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def migrated_database(engine, alembic_config):
    command.upgrade(alembic_config, "head")
    return engine


@pytest.fixture
def session_factory(migrated_database):
    return sessionmaker(bind=migrated_database, expire_on_commit=False)


@pytest.fixture(autouse=True)
def clean_users(migrated_database):
    """Give every test an empty users table, including dependent rows."""
    with migrated_database.begin() as connection:
        connection.execute(text("TRUNCATE TABLE users CASCADE"))
    yield


@pytest.fixture
def client(session_factory):
    """The API with PostgreSQL auth and mongomock for the remaining routes."""
    app = create_app(database=mongomock.MongoClient()["tradium_test"])

    def override_get_session():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def insert_user(
    session_factory,
    username="deepak",
    email="deepak@example.com",
    stored_hash=None,
):
    """Insert a user row the way the signup route stores one."""
    user = User(
        id=secrets.token_hex(12),
        username=username,
        email=email,
        password_hash=stored_hash or hash_password(PASSWORD),
        created_at=NOW,
        updated_at=NOW,
        version=0,
    )
    with session_factory() as session:
        session.add(user)
        session.commit()
    return user


def test_hashes_are_readable_across_implementations():
    # Neither direction of the Node/Python bcrypt boundary is assumed.
    assert verify_password(NODE_PASSWORD, NODE_BCRYPT_HASH) is True
    assert verify_password("wrong password here", NODE_BCRYPT_HASH) is False


def test_signup_creates_user_and_sets_cookie(client):
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

    cookie = response.headers["set-cookie"]
    assert cookie.startswith("token=")
    assert "HttpOnly" in cookie
    assert "Max-Age=604800" in cookie
    assert "Path=/" in cookie
    # Starlette writes "SameSite=strict"; the value is case-insensitive per
    # RFC 6265, so only the attribute is asserted here.
    assert "samesite=strict" in cookie.lower()
    assert "secure" not in cookie.lower()  # only when NODE_ENV=production


def test_signup_stores_a_bcrypt_hash_and_legacy_fields(client, session_factory):
    client.post(
        "/api/auth/signup",
        json={"username": "deepak", "email": "deepak@example.com", "password": PASSWORD},
    )

    with session_factory() as session:
        stored = session.scalar(select(User).where(User.email == "deepak@example.com"))

    assert stored.password_hash != PASSWORD
    assert stored.password_hash.startswith("$2b$10$")
    assert bcrypt.checkpw(PASSWORD.encode(), stored.password_hash.encode())
    assert stored.version == 0
    assert stored.created_at == stored.updated_at
    assert stored.created_at.microsecond % 1000 == 0


def test_signup_generates_object_id_compatible_hex_ids(client):
    response = client.post(
        "/api/auth/signup",
        json={"username": "deepak", "email": "deepak@example.com", "password": PASSWORD},
    )

    user_id = response.json()["user"]["id"]
    assert re.fullmatch(r"[0-9a-f]{24}", user_id)
    # Mongo-backed routes still cast the token claim with ObjectId(). The new
    # PostgreSQL id shape must keep working there.
    assert str(ObjectId(user_id)) == user_id


def test_signup_token_opens_mongo_backed_protected_routes(client):
    client.post(
        "/api/auth/signup",
        json={"username": "deepak", "email": "deepak@example.com", "password": PASSWORD},
    )

    # TestClient keeps the cookie, so this is a real cookie round-trip through
    # require_user and then the still-Mongo-backed holdings route.
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
        (
            {"username": "deepak", "email": "deepak@example.com"},
            "Username, email and password are required",
        ),
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
        (
            {"username": "somebody", "email": "deepak@example.com"},
            {"username": "deepak", "email": "deepak@example.com", "password": PASSWORD},
        ),
        (
            {"username": "deepak", "email": "somebody@example.com"},
            {"username": "deepak", "email": "deepak@example.com", "password": PASSWORD},
        ),
    ],
)
def test_signup_rejects_duplicates(client, session_factory, existing, payload):
    insert_user(session_factory, **existing)

    response = client.post("/api/auth/signup", json=payload)

    assert response.status_code == 400
    assert response.json() == {"message": "User already exists"}


def test_signup_maps_a_unique_constraint_race_to_duplicate(
    client, session_factory, monkeypatch
):
    """A competing insert between the pre-checks and this request's commit."""
    real_new_user_id = auth_routes.new_user_id

    def new_user_id_after_competing_signup():
        # This commits on another connection, so the route's own INSERT hits
        # the PostgreSQL unique constraint rather than its fast-path SELECT.
        insert_user(session_factory, username="racer", email="deepak@example.com")
        return real_new_user_id()

    monkeypatch.setattr(auth_routes, "new_user_id", new_user_id_after_competing_signup)

    response = client.post(
        "/api/auth/signup",
        json={"username": "deepak", "email": "deepak@example.com", "password": PASSWORD},
    )

    assert response.status_code == 400
    assert response.json() == {"message": "User already exists"}
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(User)) == 1


def test_login_sets_cookie_and_returns_user(client, session_factory):
    user = insert_user(session_factory)

    response = client.post(
        "/api/auth/login",
        json={"email": "deepak@example.com", "password": PASSWORD},
    )

    assert response.status_code == 200
    assert response.json() == {
        "message": "Login successful",
        "user": {"id": user.id, "username": "deepak", "email": "deepak@example.com"},
    }
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("token=")
    assert "Max-Age=604800" in cookie


def test_login_token_opens_mongo_backed_protected_routes(client, session_factory):
    insert_user(session_factory)

    client.post("/api/auth/login", json={"email": "deepak@example.com", "password": PASSWORD})

    assert client.get("/api/holdings").status_code == 200


def test_login_accepts_existing_node_bcrypt_hashes(client, session_factory):
    insert_user(session_factory, stored_hash=NODE_BCRYPT_HASH)

    response = client.post(
        "/api/auth/login",
        json={"email": "deepak@example.com", "password": NODE_PASSWORD},
    )

    assert response.status_code == 200
    assert response.json()["user"]["email"] == "deepak@example.com"


@pytest.mark.parametrize(
    "email,password",
    [
        ("nobody@example.com", PASSWORD),
        ("deepak@example.com", "not-the-password"),
    ],
)
def test_login_rejects_bad_credentials(client, session_factory, email, password):
    insert_user(session_factory)

    response = client.post("/api/auth/login", json={"email": email, "password": password})

    assert response.status_code == 401
    assert response.json() == {"message": "Invalid credentials"}


def test_login_email_matching_is_case_sensitive(client, session_factory):
    insert_user(session_factory)

    response = client.post(
        "/api/auth/login",
        json={"email": "DEEPAK@example.com", "password": PASSWORD},
    )

    assert response.status_code == 401
    assert response.json() == {"message": "Invalid credentials"}


def test_login_requires_email_and_password(client):
    response = client.post("/api/auth/login", json={})

    assert response.status_code == 400
    assert response.json() == {"message": "Email and password are required"}


def test_me_returns_the_legacy_user_document(client, session_factory):
    user = insert_user(session_factory)
    client.post("/api/auth/login", json={"email": "deepak@example.com", "password": PASSWORD})

    response = client.get("/api/auth/me")

    assert response.status_code == 200
    returned = response.json()["user"]
    assert set(returned) == {"_id", "username", "email", "createdAt", "updatedAt", "__v"}
    assert returned["_id"] == user.id
    assert returned["username"] == "deepak"
    assert returned["email"] == "deepak@example.com"
    assert returned["__v"] == 0
    assert returned["createdAt"].endswith("Z")
    assert returned["updatedAt"].endswith("Z")
    assert "password" not in returned


def test_me_is_reachable_with_a_directly_issued_token(client, session_factory, make_token):
    user = insert_user(session_factory)

    response = client.get("/api/auth/me", cookies={"token": make_token(user.id)})

    assert response.status_code == 200
    assert response.json()["user"]["_id"] == user.id


def test_me_requires_a_cookie(client):
    response = client.get("/api/auth/me")

    assert response.status_code == 401
    assert response.json() == {"message": "Not authenticated"}


def test_me_returns_404_when_the_user_is_gone(client, make_token):
    response = client.get(
        "/api/auth/me",
        cookies={"token": make_token("0123456789abcdef01234567")},
    )

    assert response.status_code == 404
    assert response.json() == {"message": "User not found"}


def test_me_returns_404_for_a_malformed_id(client, make_token):
    # Approved design D13/F6: a malformed id is a 404, not the old CastError 500.
    response = client.get("/api/auth/me", cookies={"token": make_token("not-an-object-id")})

    assert response.status_code == 404
    assert response.json() == {"message": "User not found"}


def _expired_token(make_token, user_id):
    return make_token(user_id, expires_in=-60)


def _wrong_secret_token(make_token, user_id):
    return make_token(user_id, secret="the-wrong-secret")


def _missing_id_token():
    payload = {"exp": int(datetime.now(timezone.utc).timestamp()) + 60}
    return jwt.encode(payload, TEST_SECRET, algorithm="HS256")


@pytest.mark.parametrize(
    "token_factory",
    [
        pytest.param(lambda make_token: "not-a-jwt", id="malformed"),
        pytest.param(
            lambda make_token: _expired_token(make_token, "0123456789abcdef01234567"),
            id="expired",
        ),
        pytest.param(
            lambda make_token: _wrong_secret_token(make_token, "0123456789abcdef01234567"),
            id="wrong-secret",
        ),
        pytest.param(lambda make_token: _missing_id_token(), id="missing-id"),
    ],
)
def test_me_rejects_unusable_tokens(client, make_token, token_factory):
    response = client.get("/api/auth/me", cookies={"token": token_factory(make_token)})

    assert response.status_code == 401
    assert response.json() == {"message": "Invalid or expired token"}


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


def test_logout_ends_the_browser_session(client, session_factory):
    insert_user(session_factory)
    client.post("/api/auth/login", json={"email": "deepak@example.com", "password": PASSWORD})
    assert client.get("/api/auth/me").status_code == 200

    client.post("/api/auth/logout")

    assert client.get("/api/auth/me").status_code == 401


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
