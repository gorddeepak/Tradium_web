"""Harness: the same scenario through the FastAPI port.

Seeds scenario.json into a scratch database, patches the provider seams, runs
``sync_prices()`` + ``record_daily_snapshot()``, then dumps every collection with
BSON types preserved. The scheduler is not involved.
Env: PARITY_MONGO, PARITY_OUT_DIR, PARITY_SCENARIO.
"""

import json
from datetime import datetime
from pathlib import Path

import harness_env
from harness_env import load_scenario, normalize, scratch_database, write_result

DB_NAME = "tradium_parity_fastapi_jobs"

COLLECTIONS = [
    "users",
    "holdings",
    "positions",
    "watchlists",
    "orders",
    "funds",
    "transactions",
    "portfoliosnapshots",
]


def main():
    from bson import ObjectId

    from api.jobs import portfolio_snapshot, price_sync

    scenario = load_scenario()
    seeded = frozenset(scenario["seededIds"])

    client, database = scratch_database(DB_NAME)

    stamp = datetime.fromisoformat(scenario["now"].replace("Z", "+00:00"))
    for name in ("users", "holdings", "positions", "watchlists", "orders", "funds"):
        documents = []
        for source in scenario.get(name, []):
            document = dict(source)
            document["_id"] = ObjectId(document["_id"])
            if "user" in document:
                document["user"] = ObjectId(document["user"])
            document["createdAt"] = stamp
            document["updatedAt"] = stamp
            document["__v"] = 0
            documents.append(document)
        if documents:
            database[name].insert_many(documents)

    # Patch the provider seams exactly where run_sync looks them up.
    def fake_fetch_quote(symbol):
        quote = scenario["quotes"].get(symbol)
        if quote is None:
            return None
        return {"ltp": quote["ltp"], "dayChangePct": quote["dayChangePct"]}

    def fake_fetch_sector(symbol):
        return scenario["sectors"].get(symbol, "")

    price_sync.fetch_quote = fake_fetch_quote
    price_sync.fetch_sector = fake_fetch_sector
    price_sync.is_market_open = lambda: True

    price_sync.sync_prices(database)
    portfolio_snapshot.record_daily_snapshot(database)

    collections = {}
    for name in COLLECTIONS:
        documents = [normalize(doc, seeded=seeded) for doc in database[name].find({})]
        documents.sort(key=lambda doc: json.dumps(doc, sort_keys=True))
        collections[name] = documents

    client.drop_database(DB_NAME)
    write_result(
        "fastapi_jobs.json",
        {"implementation": "fastapi", "collections": collections},
    )


if __name__ == "__main__":
    main()
