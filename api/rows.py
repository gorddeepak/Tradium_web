"""Identifiers and timestamps shared by PostgreSQL row writes."""

import secrets
from datetime import datetime, timezone


def new_id() -> str:
    """A 24-character lowercase hex id, the ObjectId-compatible external shape."""
    return secrets.token_hex(12)


def utcnow() -> datetime:
    """Current UTC time truncated to the millisecond precision of the columns."""
    now = datetime.now(timezone.utc)
    return now.replace(microsecond=(now.microsecond // 1000) * 1000)
