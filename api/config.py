"""Configuration read from the environment.

Mirrors the Express server, which reads MONGO_URL and JWT_SECRET through
dotenv and exits when MONGO_URL is missing.
"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

# Load api/.env when running locally (gitignored, same idea as server/.env).
load_dotenv()


@dataclass(frozen=True)
class Settings:
    mongo_url: str
    jwt_secret: str
    host: str
    port: int


def get_settings() -> Settings:
    """Read settings at call time so tests can patch the environment."""
    return Settings(
        mongo_url=os.getenv("MONGO_URL", ""),
        jwt_secret=os.getenv("JWT_SECRET", ""),
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
    )
