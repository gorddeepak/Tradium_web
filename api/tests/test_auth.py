"""Authentication tests for GET /api/holdings."""

from datetime import datetime, timedelta, timezone

import jwt

from api.tests.conftest import TEST_SECRET


def test_missing_cookie_returns_not_authenticated(client):
    response = client.get("/api/holdings")
    assert response.status_code == 401
    assert response.json() == {"message": "Not authenticated"}


def test_empty_cookie_returns_not_authenticated(client):
    response = client.get("/api/holdings", cookies={"token": ""})
    assert response.status_code == 401
    assert response.json() == {"message": "Not authenticated"}


def test_token_signed_with_wrong_secret_is_rejected(client, user_id):
    token = jwt.encode({"id": str(user_id)}, "the-wrong-secret", algorithm="HS256")
    response = client.get("/api/holdings", cookies={"token": token})
    assert response.status_code == 401
    assert response.json() == {"message": "Invalid or expired token"}


def test_expired_token_is_rejected(client, user_id):
    expired = int((datetime.now(timezone.utc) - timedelta(minutes=1)).timestamp())
    token = jwt.encode({"id": str(user_id), "exp": expired}, TEST_SECRET, algorithm="HS256")
    response = client.get("/api/holdings", cookies={"token": token})
    assert response.status_code == 401
    assert response.json() == {"message": "Invalid or expired token"}


def test_malformed_token_is_rejected(client):
    response = client.get("/api/holdings", cookies={"token": "not-a-jwt"})
    assert response.status_code == 401
    assert response.json() == {"message": "Invalid or expired token"}


def test_token_without_user_id_is_rejected(client):
    token = jwt.encode({"sub": "someone"}, TEST_SECRET, algorithm="HS256")
    response = client.get("/api/holdings", cookies={"token": token})
    assert response.status_code == 401
    assert response.json() == {"message": "Invalid or expired token"}


def test_valid_cookie_is_accepted(book_client, book_user, make_token):
    response = book_client.get(
        "/api/holdings", cookies={"token": make_token(book_user)}
    )
    assert response.status_code == 200
    assert response.json() == []
