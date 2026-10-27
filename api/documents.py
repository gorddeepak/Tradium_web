"""Small time helper shared by the daily snapshot job.

The trading book writes its own timestamps in PostgreSQL; the snapshot job uses
``utcnow`` for the row it upserts.
"""

from datetime import datetime, timezone


def utcnow():
    return datetime.now(timezone.utc)
