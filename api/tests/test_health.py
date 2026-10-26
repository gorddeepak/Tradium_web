"""Startup and health endpoint tests."""

from fastapi.testclient import TestClient

from api.main import create_app


def test_health_returns_ok_without_auth(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_app_starts_without_mongodb(monkeypatch):
    monkeypatch.delenv("MONGO_URL", raising=False)

    app = create_app()
    with TestClient(app) as started:
        assert started.get("/api/health").status_code == 200

    # The FastAPI runtime is PostgreSQL-only: startup opens no MongoDB handle.
    assert not hasattr(app.state, "db")


def test_unknown_route_matches_express_404_shape(client):
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    # Express: app.use((req, res) => res.status(404).json({ message: "Route not found" }))
    assert response.json() == {"message": "Route not found"}
