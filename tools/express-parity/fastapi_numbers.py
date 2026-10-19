"""Harness: the real FastAPI ``GET /api/holdings`` route, same seeded document.

Writes the same JSON shape as express_numbers.js.
Env: PARITY_MONGO, PARITY_OUT_DIR.
"""

import os
from datetime import datetime, timezone

from harness_env import scratch_database, write_result

DB_NAME = "tradium_parity_fastapi_numbers"
USER_ID = "652f1c9b8a1e4d3c2b1a0f99"


def main():
    import jwt
    from bson import ObjectId
    from fastapi.testclient import TestClient

    from api.main import create_app

    client_mongo, database = scratch_database(DB_NAME)

    now = datetime(2026, 9, 1, 4, 15, 30, 123000, tzinfo=timezone.utc)

    def row(symbol, suffix, **fields):
        return dict(
            _id=ObjectId(f"652f1c9b8a1e4d3c2b1b000{suffix}"),
            user=ObjectId(USER_ID),
            exchange="NSE",
            createdAt=now,
            updatedAt=now,
            __v=0,
            symbol=symbol,
            **fields,
        )

    database["holdings"].insert_many(
        [
            row("WHOLE", 1, name="Whole float", qty=10, avgPrice=2400.5, ltp=2500.0,
                dayChangePct=0.0, sector="Energy"),
            row("EDGE", 2, name="Edge values", qty=3, avgPrice=0.1 + 0.2, ltp=1e21,
                dayChangePct=-0.0, sector=""),
            row("INTZERO", 3, name="Integer zeros", qty=7, avgPrice=100, ltp=0,
                dayChangePct=0, sector=""),
        ]
    )

    token = jwt.encode({"id": USER_ID}, os.environ["JWT_SECRET"], algorithm="HS256")
    with TestClient(create_app(database=database), raise_server_exceptions=False) as client:
        response = client.get("/api/holdings", headers={"cookie": f"token={token}"})

    client_mongo.drop_database(DB_NAME)
    write_result(
        "fastapi_numbers.json",
        {
            "implementation": "fastapi",
            "status": response.status_code,
            "contentType": response.headers.get("content-type"),
            "bodyText": response.text,
        },
    )


if __name__ == "__main__":
    main()
