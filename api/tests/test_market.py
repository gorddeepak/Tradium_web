"""Focused tests for GET /api/market/overview (cache-backed).

Authentication behaviour is shared with the holdings suite and not repeated.
"""

from datetime import datetime, timezone

EARLIER = datetime(2026, 9, 1, 4, 0, 0, tzinfo=timezone.utc)
LATER = datetime(2026, 9, 2, 4, 0, 0, tzinfo=timezone.utc)


def test_indices_follow_seed_order_and_stocks_are_split_out(
    client, database, make_token, user_id, market_quote_factory
):
    database["marketquotes"].insert_many(
        [
            market_quote_factory(symbol="^BSESN", name="SENSEX", kind="index"),
            market_quote_factory(symbol="^NSEI", name="NIFTY 50", kind="index"),
            market_quote_factory(symbol="^NSEBANK", name="BANK NIFTY", kind="index"),
            market_quote_factory(symbol="INFY", name="Infosys", kind="stock"),
        ]
    )

    body = client.get("/api/market/overview", cookies={"token": make_token(user_id)}).json()

    assert [row["symbol"] for row in body["indices"]] == ["^NSEI", "^NSEBANK", "^BSESN"]
    assert [row["symbol"] for row in body["stocks"]] == ["INFY"]


def test_cold_cache_returns_nulls_and_empty_lists(client, make_token, user_id):
    body = client.get("/api/market/overview", cookies={"token": make_token(user_id)}).json()

    assert body == {"asOf": None, "indices": [], "stocks": []}


def test_as_of_is_the_freshest_row_and_rows_keep_mongoose_keys(
    client, database, make_token, user_id, market_quote_factory
):
    database["marketquotes"].insert_many(
        [
            market_quote_factory(symbol="INFY", updatedAt=EARLIER),
            market_quote_factory(symbol="TCS", updatedAt=LATER),
        ]
    )

    body = client.get("/api/market/overview", cookies={"token": make_token(user_id)}).json()

    assert body["asOf"] == "2026-09-02T04:00:00.000Z"
    row = body["stocks"][0]
    assert set(row) == {
        "_id",
        "symbol",
        "name",
        "kind",
        "ltp",
        "dayChange",
        "dayChangePct",
        "prevClose",
        "volume",
        "marketCap",
        "sector",
        "createdAt",
        "updatedAt",
        "__v",
    }
