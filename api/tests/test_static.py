"""Phase 4a: production static serving of the Vite build and the SPA fallback.

These tests point ``api.main.DIST_DIR`` at a throwaway tree, so they never touch
the real build and never need a frontend build to run.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.main as main
from api.config import serve_static_enabled


def _build_dist(root: Path) -> Path:
    """A minimal Vite-shaped build: index.html, an assets bundle, a favicon."""
    dist = root / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text(
        "<!doctype html><title>tradium-shell</title>", encoding="utf-8"
    )
    (dist / "favicon.svg").write_text("<svg></svg>", encoding="utf-8")
    (assets / "app-abc123.js").write_text("console.log('app')", encoding="utf-8")
    return dist


@pytest.fixture
def static_client(tmp_path, monkeypatch, database):
    monkeypatch.setattr(main, "DIST_DIR", _build_dist(tmp_path))
    monkeypatch.setenv("SERVE_STATIC", "true")
    with TestClient(main.create_app(database=database), raise_server_exceptions=False) as client:
        yield client


def test_root_serves_the_app_shell(static_client):
    response = static_client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "tradium-shell" in response.text


def test_deep_links_serve_the_app_shell(static_client):
    for path in (
        "/dashboard",
        "/dashboard/holdings",
        "/dashboard/watchlist/RELIANCE",
        "/login",
    ):
        response = static_client.get(path)
        assert response.status_code == 200, path
        assert "tradium-shell" in response.text


def test_static_assets_and_root_files_are_served(static_client):
    bundle = static_client.get("/assets/app-abc123.js")
    assert bundle.status_code == 200
    assert "console.log('app')" in bundle.text

    favicon = static_client.get("/favicon.svg")
    assert favicon.status_code == 200
    assert "<svg" in favicon.text


def test_known_api_route_is_not_shadowed(static_client):
    response = static_client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_unknown_api_path_returns_json_not_html(static_client):
    response = static_client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"message": "Route not found"}


def test_bare_api_prefix_returns_json_not_html(static_client):
    response = static_client.get("/api")
    assert response.status_code == 404
    assert response.json() == {"message": "Route not found"}


def test_static_serving_is_off_by_default(client, monkeypatch):
    # The shared `client` fixture builds the app with neither SERVE_STATIC nor
    # NODE_ENV set, so a client-side route is just an unknown path.
    monkeypatch.delenv("SERVE_STATIC", raising=False)
    monkeypatch.delenv("NODE_ENV", raising=False)
    response = client.get("/dashboard")
    assert response.status_code == 404
    assert response.json() == {"message": "Route not found"}


def test_missing_build_does_not_break_the_api(tmp_path, monkeypatch, database):
    monkeypatch.setattr(main, "DIST_DIR", tmp_path / "absent")
    monkeypatch.setenv("SERVE_STATIC", "true")
    with TestClient(main.create_app(database=database), raise_server_exceptions=False) as client:
        assert client.get("/api/health").json() == {"ok": True}
        # No build means no fallback: the path stays a JSON 404.
        response = client.get("/dashboard")
        assert response.status_code == 404
        assert response.json() == {"message": "Route not found"}


def test_production_mode_serves_static_without_override(tmp_path, monkeypatch, database):
    # The real production configuration: only NODE_ENV=production is set, so the
    # NODE_ENV default (not SERVE_STATIC) is what enables the fallback.
    monkeypatch.setattr(main, "DIST_DIR", _build_dist(tmp_path))
    monkeypatch.delenv("SERVE_STATIC", raising=False)
    monkeypatch.setenv("NODE_ENV", "production")
    with TestClient(main.create_app(database=database), raise_server_exceptions=False) as client:
        assert client.get("/dashboard").status_code == 200
        assert "tradium-shell" in client.get("/dashboard/holdings").text
        assert client.get("/api/health").json() == {"ok": True}


def test_serve_static_flag_defaults_and_overrides(monkeypatch):
    monkeypatch.delenv("SERVE_STATIC", raising=False)
    monkeypatch.delenv("NODE_ENV", raising=False)
    assert serve_static_enabled() is False

    # Production mode serves the build, matching Express.
    monkeypatch.setenv("NODE_ENV", "production")
    assert serve_static_enabled() is True

    # An explicit value wins either way.
    monkeypatch.setenv("SERVE_STATIC", "false")
    assert serve_static_enabled() is False
    monkeypatch.delenv("NODE_ENV", raising=False)
    monkeypatch.setenv("SERVE_STATIC", "yes")
    assert serve_static_enabled() is True
