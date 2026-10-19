"""Configuration read from the environment.

Mirrors the Express server, which reads MONGO_URL and JWT_SECRET through
dotenv and exits when MONGO_URL is missing.
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


@dataclass(frozen=True)
class Settings:
    mongo_url: str
    jwt_secret: str
    host: str
    port: int
    # NODE_ENV controls the `Secure` flag on the auth cookie, exactly as the
    # Express controller's isProduction check does.
    node_env: str


def get_settings() -> Settings:
    """Read settings at call time so tests can patch the environment."""
    return Settings(
        mongo_url=os.getenv("MONGO_URL", ""),
        jwt_secret=os.getenv("JWT_SECRET", ""),
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        node_env=os.getenv("NODE_ENV", ""),
    )
