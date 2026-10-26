"""Small time helper shared by the remaining MongoDB-backed job.

Mongoose adds ``createdAt``/``updatedAt`` itself. The trading book now writes
its own timestamps in PostgreSQL, but the daily snapshot job still builds Mongo
dates, so ``utcnow`` stays here.
"""

from datetime import datetime, timezone


def utcnow():
    return datetime.now(timezone.utc)
