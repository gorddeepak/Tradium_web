"""Shared setup for the FastAPI side of the parity harness.

Sets a harness-local ``JWT_SECRET`` before ``api`` is imported (``api/config.py``
loads ``api/.env`` with ``override=False``, so a real environment variable wins)
and provides the scratch-database and result helpers.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

MONGO = os.environ.get("PARITY_MONGO", "mongodb://127.0.0.1:27017")
OUT_DIR = Path(os.environ.get("PARITY_OUT_DIR", HERE / "out"))
SCENARIO_PATH = Path(os.environ.get("PARITY_SCENARIO", HERE / "scenario.json"))

# Same local-only secret the Node harnesses use; never printed.
os.environ["JWT_SECRET"] = "parity-harness-secret-not-a-real-key"
os.environ.pop("NODE_ENV", None)


def load_scenario():
    return json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))


def scratch_database(name):
    """Drop and return ``(client, database)`` for a ``tradium_parity_*`` name."""
    from pymongo import MongoClient

    if not name.startswith("tradium_parity_"):
        raise ValueError(f"refusing to touch a non-scratch database: {name}")
    client = MongoClient(MONGO, tz_aware=True)
    client.drop_database(name)
    return client, client[name]


def write_result(name, payload):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / name).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def iso_ms(value):
    value = value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + f"{value.microsecond // 1000:03d}Z"


def normalize(value, key=None, seeded=frozenset()):
    """Tag a BSON value with its type, so int32 and double are not conflated."""
    from bson import ObjectId
    from bson.int64 import Int64

    if value is None:
        return {"t": "null"}
    if isinstance(value, ObjectId):
        hex_id = str(value)
        return {"t": "oid", "v": hex_id if hex_id in seeded else "<oid>"}
    if isinstance(value, datetime):
        if key in ("createdAt", "updatedAt"):
            return {"t": "date"}
        return {"t": "date", "v": iso_ms(value)}
    if isinstance(value, bool):
        return {"t": "bool", "v": value}
    if isinstance(value, Int64):
        return {"t": "long", "v": int(value)}
    if isinstance(value, int):
        return {"t": "int", "v": value}
    if isinstance(value, float):
        return {"t": "double", "v": value}
    if isinstance(value, str):
        return {"t": "str", "v": value}
    if isinstance(value, list):
        return {"t": "array", "v": [normalize(item, seeded=seeded) for item in value]}
    if isinstance(value, dict):
        return {
            "t": "doc",
            "v": {k: normalize(value[k], k, seeded) for k in sorted(value)},
        }
    return {"t": "unknown", "v": str(value)}
