"""CORS tests for the Vite frontend and configurable production origins."""

from fastapi.testclient import TestClient

from api.main import create_app


def test_vite_dev_origin_is_allowed_with_credentials():
    with TestClient(create_app()) as client:
        response = client.options(
            "/api/auth/login",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_every_vite_dev_port_is_allowed():
    with TestClient(create_app()) as client:
        for port in range(5173, 5178):
            origin = f"http://localhost:{port}"
            response = client.get("/api/health", headers={"Origin": origin})
            assert response.headers["access-control-allow-origin"] == origin


def test_unknown_origin_is_not_allowed():
    with TestClient(create_app()) as client:
        response = client.get("/api/health", headers={"Origin": "https://example.com"})

    assert "access-control-allow-origin" not in response.headers


def test_cors_origins_environment_overrides_the_default(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com, https://admin.example.com")

    with TestClient(create_app()) as client:
        response = client.get(
            "/api/health", headers={"Origin": "https://admin.example.com"}
        )
        old_dev_origin = client.get(
            "/api/health", headers={"Origin": "http://localhost:5173"}
        )

    assert response.headers["access-control-allow-origin"] == "https://admin.example.com"
    assert "access-control-allow-origin" not in old_dev_origin.headers
