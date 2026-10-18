"""Focused tests for GET /api/instruments/search (cache-backed).

Authentication behaviour is shared with the holdings suite and not repeated.
"""


def test_matches_symbol_or_name_case_insensitively(
    client, database, make_token, user_id, market_quote_factory
):
    database["marketquotes"].insert_many(
        [
            market_quote_factory(symbol="INFY", name="Infosys"),
            market_quote_factory(symbol="RELIANCE", name="Reliance Industries"),
            market_quote_factory(symbol="TCS", name="Tata Consultancy Services"),
        ]
    )

    body = client.get(
        "/api/instruments/search", params={"q": "inf"}, cookies={"token": make_token(user_id)}
    ).json()

    assert [row["symbol"] for row in body] == ["INFY"]


def test_renames_fields_for_the_client(
    client, database, make_token, user_id, market_quote_factory
):
    database["marketquotes"].insert_one(
        market_quote_factory(symbol="INFY", name="Infosys", kind="stock", ltp=1500.0, dayChangePct=0.8)
    )

    body = client.get(
        "/api/instruments/search", params={"q": "INFY"}, cookies={"token": make_token(user_id)}
    ).json()

    assert body == [
        {"symbol": "INFY", "name": "Infosys", "kind": "stock", "price": 1500.0, "changePct": 0.8}
    ]


def test_empty_query_returns_empty_list(client, make_token, user_id):
    token_cookie = {"token": make_token(user_id)}

    assert client.get("/api/instruments/search", cookies=token_cookie).json() == []
    assert client.get("/api/instruments/search", params={"q": "   "}, cookies=token_cookie).json() == []


def test_limits_to_ten_and_treats_regex_characters_literally(
    client, database, make_token, user_id, market_quote_factory
):
    database["marketquotes"].insert_many(
        [market_quote_factory(symbol=f"TCK{i}", name="Tick") for i in range(12)]
        + [market_quote_factory(symbol="ITC", name="ITC")]
    )

    capped = client.get(
        "/api/instruments/search", params={"q": "Tick"}, cookies={"token": make_token(user_id)}
    ).json()
    assert len(capped) == 10

    # a regex dot would match "ITC" if it were not escaped
    literal = client.get(
        "/api/instruments/search", params={"q": "I.C"}, cookies={"token": make_token(user_id)}
    ).json()
    assert literal == []
