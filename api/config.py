"""Configuration read from the environment.

The FastAPI runtime is PostgreSQL-only: it needs ``DATABASE_URL`` and
``JWT_SECRET``. The Express reference under ``server/`` still reads
``MONGO_URL`` for its own process.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Load api/.env explicitly, whatever the working directory. Without a path,
# python-dotenv searches from the caller's directory and falls back to the
# cwd in some launch modes, which is easy to get wrong. override=False keeps
# real environment variables (e.g. a deployment's) ahead of this file.
load_dotenv(Path(__file__).with_name(".env"))

# The Vite dev server's origins, matching server/index.js. In production the
# frontend is served by the API itself, so CORS_ORIGINS only needs to list
# additional origins when the two are deployed separately.
VITE_DEV_ORIGINS = (
    "http://localhost:5173",
    "http://localhost:5174",
    "http://localhost:5175",
    "http://localhost:5176",
    "http://localhost:5177",
)


def get_cors_origins() -> list[str]:
    """Read CORS_ORIGINS, falling back to the Vite development origins.

    The value is a comma-separated list, e.g.
    CORS_ORIGINS=https://app.example.com,https://admin.example.com
    """
    configured = os.getenv("CORS_ORIGINS", "")
    origins = [origin.strip() for origin in configured.split(",") if origin.strip()]
    return origins or list(VITE_DEV_ORIGINS)


def serve_static_enabled() -> bool:
    """Whether to serve the built frontend from ``dist/``.

    Express serves ``dist/`` only when ``NODE_ENV=production``. The same default
    applies here, but ``SERVE_STATIC`` can override it either way: a local run
    can serve the real build without also turning on the ``Secure`` cookie flag,
    which an http:// browser would otherwise drop.
    """
    override = os.getenv("SERVE_STATIC", "").strip().lower()
    if override:
        return override in {"1", "true", "yes", "on"}
    return os.getenv("NODE_ENV", "").strip() == "production"


@dataclass(frozen=True)
class Settings:
    jwt_secret: str
    host: str
    port: int
    # NODE_ENV controls the `Secure` flag on the auth cookie, exactly as the
    # Express controller's isProduction check does.
    node_env: str
    # PostgreSQL backs authentication (Phase 3B1). The pooled connection is
    # read when the session module asks for it.
    database_url: str


def get_settings() -> Settings:
    """Read settings at call time so tests can patch the environment."""
    return Settings(
        jwt_secret=os.getenv("JWT_SECRET", ""),
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        node_env=os.getenv("NODE_ENV", ""),
        database_url=os.getenv("DATABASE_URL", ""),
    )


def get_direct_database_url() -> str:
    """Read the direct (non-pooled) URL used by Alembic and the loader."""
    return os.getenv("DIRECT_DATABASE_URL", "").strip()


# The same model as server/config/ai.js. GEMINI_MODEL is an escape hatch for
# deployments, not a second source of truth.
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"


@dataclass(frozen=True)
class AISettings:
    api_key: str
    model: str


def get_ai_settings() -> AISettings:
    """Read Nova's configuration at call time so tests can patch it."""
    return AISettings(
        api_key=os.getenv("GOOGLE_GENERATIVE_AI_API_KEY", "").strip(),
        model=os.getenv("GEMINI_MODEL", "").strip() or DEFAULT_GEMINI_MODEL,
    )
