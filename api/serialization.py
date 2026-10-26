"""Convert MongoDB documents into the JSON shape the Express API returns.

Mongoose (Express) serialises documents through JSON.stringify with its
toJSON transform, which produces:
  - ObjectId -> 24-character hex string
  - Date     -> "2026-10-18T12:34:56.789Z" (milliseconds, always UTC)
  - Decimal  -> a JSON number (PostgreSQL numeric columns)
Everything else passes through unchanged.
"""

from datetime import datetime, timezone
from decimal import Decimal

from bson import ObjectId


def to_json_value(value):
    """Recursively convert one value, or a whole document, to JSON-safe data."""
    if isinstance(value, ObjectId):
        return str(value)

    if isinstance(value, datetime):
        # Treat naive datetimes as UTC, which is how both drivers store them.
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        value = value.astimezone(timezone.utc)
        # Node's Date#toISOString always prints exactly three decimal places.
        return value.strftime("%Y-%m-%dT%H:%M:%S.") + f"{value.microsecond // 1000:03d}Z"

    if isinstance(value, Decimal):
        # The frontend expects JSON numbers. Integral values render as integers
        # (JSON.stringify(500.0) === "500"); the rest use the shortest float
        # representation, the design's documented fallback without simplejson.
        if value == value.to_integral_value():
            return int(value)
        return float(value)

    if isinstance(value, dict):
        return {key: to_json_value(item) for key, item in value.items()}

    if isinstance(value, list):
        return [to_json_value(item) for item in value]

    return value
