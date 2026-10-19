"""Harness: the same read routes through the FastAPI port.

Seeds routes_scenario.json into a scratch database, injects it into the app and
captures the raw JSON body of each route with the same cookie token the Node
harness mints. Env: PARITY_MONGO, PARITY_OUT_DIR, PARITY_ROUTES_SCENARIO.
"""

import os
from datetime import datetime
from pathlib import Path

from harness_env import scratch_database, write_result

DB_NAME = "tradium_parity_fastapi_routes"
SCENARIO_PATH = Path(
    os.environ.get("PARITY_ROUTES_SCENARIO", Path(__file__).with_name("routes_scenario.json"))
)

COLLECTIONS = [
    "users",
    "holdings",
    "positions",
    "watchlists",
    "orders",
    "funds",
    "transactions",
    "portfoliosnapshots",
    "marketquotes",
]
DATE_KEYS = {"date", "createdAt", "updatedAt"}
ROUTES = [
    ("orders", "/api/orders"),
    ("watchlist", "/api/watchlist"),
    ("positions", "/api/positions"),
    ("funds", "/api/funds"),
    ("fundsTransactions", "/api/funds/transactions"),
    ("portfolioHistory1Y", "/api/portfolio/history?range=1Y"),
    ("marketOverview", "/api/market/overview"),
    ("instrumentsSearchIN", "/api/instruments/search?q=IN"),
    ("instrumentsSearchBlank", "/api/instruments/search?q="),
]


def convert(doc):
    import json

    from bson import ObjectId

    out = {}
    for key, value in doc.items():
        if isinstance(value, str) and len(value) == 24 and all(c in "0123456789abcdef" for c in value):
            out[key] = ObjectId(value)
        elif key in DATE_KEYS and isinstance(value, str):
            out[key] = datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            out[key] = value
    out.setdefault("__v", 0)
    return out


def main():
    import json

    import jwt
    from fastapi.testclient import TestClient

    from api.main import create_app

    scenario = json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))
    client_mongo, database = scratch_database(DB_NAME)

    for name in COLLECTIONS:
        docs = [convert(doc) for doc in scenario.get(name, [])]
        if docs:
            database[name].insert_many(docs)

    token = jwt.encode({"id": scenario["user"]}, os.environ["JWT_SECRET"], algorithm="HS256")

    results = []
    with TestClient(create_app(database=database), raise_server_exceptions=False) as client:
        for name, path in ROUTES:
            response = client.get(path, headers={"cookie": f"token={token}"})
            results.append(
                {
                    "name": name,
                    "path": path,
                    "status": response.status_code,
                    "contentType": response.headers.get("content-type"),
                    "bodyText": response.text,
                }
            )

    client_mongo.drop_database(DB_NAME)
    write_result("fastapi_routes.json", {"implementation": "fastapi", "routes": results})


if __name__ == "__main__":
    main()
