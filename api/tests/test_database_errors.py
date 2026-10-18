"""Database failure handling."""

from fastapi.testclient import TestClient

from api.main import create_app


class BrokenDatabase:
    """Stands in for a database whose query fails at runtime."""

    def __getitem__(self, name):
        raise RuntimeError("connection lost")


def test_database_error_returns_generic_500():
    app = create_app(database=BrokenDatabase())
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(
            "/api/holdings",
            cookies={"token": _valid_token()},
        )

    assert response.status_code == 500
    # Express hides internal errors behind this exact message.
    assert response.json() == {"message": "Something went wrong"}
    # The real error text must not leak to the client.
    assert "connection lost" not in response.text


def _valid_token():
    import jwt

    from api.tests.conftest import TEST_SECRET

    return jwt.encode({"id": "64b7f1c2a1b2c3d4e5f60718"}, TEST_SECRET, algorithm="HS256")
