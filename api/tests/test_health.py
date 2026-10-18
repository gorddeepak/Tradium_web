"""Startup and health endpoint tests."""

from fastapi.testclient import TestClient

from api.main import create_app


def test_health_returns_ok_without_auth(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_app_starts_when_database_is_injected(database):
    app = create_app(database=database)
    with TestClient(app) as started:
        assert started.get("/api/health").status_code == 200
    # The injected database is what the app used, so no real connection happened.
    assert app.state.db is database


def test_unknown_route_matches_express_404_shape(client):
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    # Express: app.use((req, res) => res.status(404).json({ message: "Route not found" }))
    assert response.json() == {"message": "Route not found"}
