"""Focused tests for the two live-quote instrument routes.

`fetch_quote_row` is patched at the route module's seam, so no request reaches
Yahoo. Authentication behaviour is shared with the holdings suite and not
repeated; the unauthenticated case is checked once here because these routes
are new.
"""

import pytest

from api.market_data import MarketDataError


def _row(**overrides):
    row = {
        "symbol": "INFY.NS",
        "longName": "Infosys Limited",
        "shortName": "INFOSYS LTD",
        "regularMarketPrice": 1500.2,
        "regularMarketChange": 12.1,
        "regularMarketChangePercent": 0.81,
        "regularMarketOpen": 1490.0,
        "regularMarketDayHigh": 1505.0,
        "regularMarketDayLow": 1488.0,
        "regularMarketPreviousClose": 1488.1,
        "regularMarketVolume": 2057862,
        "fiftyTwoWeekHigh": 1900.0,
        "fiftyTwoWeekLow": 1200.0,
    }
    row.update(overrides)
    return row


@pytest.fixture
def serve_quote(monkeypatch):
    def _serve(row):
        monkeypatch.setattr("api.routes.instruments.fetch_quote_row", lambda symbol: row)

    return _serve


def test_lookup_returns_the_documented_contract(client, make_token, user_id, serve_quote):
    serve_quote(_row())

    response = client.get(
        "/api/instruments/lookup/infy", cookies={"token": make_token(user_id)}
    )

    assert response.status_code == 200
    assert response.json() == {
        "symbol": "INFY",  # uppercased, while the Yahoo ticker kept .NS
        "name": "Infosys Limited",
        "exchange": "NSE",
        "price": 1500.2,
        "change": 12.1,
        "changePct": 0.81,
    }


def test_lookup_falls_back_to_short_name_then_symbol(
    client, make_token, user_id, serve_quote
):
    serve_quote(_row(longName=None))

    body = client.get(
        "/api/instruments/lookup/INFY", cookies={"token": make_token(user_id)}
    ).json()
    assert body["name"] == "INFOSYS LTD"

    serve_quote(_row(longName=None, shortName=None))
    body = client.get(
        "/api/instruments/lookup/INFY", cookies={"token": make_token(user_id)}
    ).json()
    # `symbol` here is the request's own value, not the uppercased copy.
    assert body["name"] == "INFY"


def test_lookup_omits_fields_yahoo_does_not_supply(client, make_token, user_id, serve_quote):
    """Express serialises `undefined` by dropping the key, never as null."""
    row = _row()
    del row["regularMarketChangePercent"]
    serve_quote(row)

    body = client.get(
        "/api/instruments/lookup/INFY", cookies={"token": make_token(user_id)}
    ).json()

    assert "changePct" not in body
    assert body["price"] == 1500.2


def test_lookup_is_404_for_an_unknown_symbol(client, make_token, user_id, serve_quote):
    serve_quote(None)

    response = client.get(
        "/api/instruments/lookup/NOTAREALSYMBOL", cookies={"token": make_token(user_id)}
    )

    assert response.status_code == 404
    assert response.json() == {"message": "Instrument not found"}


def test_lookup_is_404_when_yahoo_returns_no_price(client, make_token, user_id, serve_quote):
    """`!quote?.regularMarketPrice` treats a zero price as not found."""
    serve_quote(_row(regularMarketPrice=0))

    response = client.get(
        "/api/instruments/lookup/INFY", cookies={"token": make_token(user_id)}
    )

    assert response.status_code == 404
    assert response.json() == {"message": "Instrument not found"}


def test_detail_returns_the_extended_quote(client, make_token, user_id, serve_quote):
    serve_quote(_row())

    response = client.get("/api/instruments/infy", cookies={"token": make_token(user_id)})

    assert response.status_code == 200
    assert response.json() == {
        "symbol": "INFY",
        "name": "Infosys Limited",
        "exchange": "NSE",
        "price": 1500.2,
        "change": 12.1,
        "changePct": 0.81,
        "open": 1490.0,
        "high": 1505.0,
        "low": 1488.0,
        "prevClose": 1488.1,
        "volume": 2057862,
        "week52High": 1900.0,
        "week52Low": 1200.0,
    }


def test_detail_omits_missing_fields_rather_than_nulling_them(
    client, make_token, user_id, serve_quote
):
    row = _row()
    del row["fiftyTwoWeekHigh"]
    del row["regularMarketVolume"]
    serve_quote(row)

    body = client.get("/api/instruments/INFY", cookies={"token": make_token(user_id)}).json()

    assert "week52High" not in body
    assert "volume" not in body
    assert "price" in body


def test_detail_keeps_a_zero_volume(client, make_token, user_id, serve_quote):
    """An index has volume 0; that is a value, not a missing one."""
    serve_quote(_row(symbol="^NSEI", regularMarketVolume=0))

    body = client.get("/api/instruments/^NSEI", cookies={"token": make_token(user_id)}).json()

    assert body["volume"] == 0


def test_detail_is_404_for_an_unknown_symbol(client, make_token, user_id, serve_quote):
    serve_quote(None)

    response = client.get(
        "/api/instruments/NOTAREALSYMBOL", cookies={"token": make_token(user_id)}
    )

    assert response.status_code == 404
    assert response.json() == {"message": "Instrument not found"}


def test_detail_is_404_when_the_provider_fails(client, make_token, user_id, monkeypatch):
    def explode(symbol):
        raise MarketDataError("Yahoo is down")

    monkeypatch.setattr("api.routes.instruments.fetch_quote_row", explode)

    response = client.get("/api/instruments/INFY", cookies={"token": make_token(user_id)})

    # Express's try/catch has no re-raise, so a provider error is a 404 too.
    assert response.status_code == 404
    assert response.json() == {"message": "Instrument not found"}


def test_both_routes_require_authentication(client):
    assert client.get("/api/instruments/lookup/INFY").status_code == 401
    assert client.get("/api/instruments/INFY").status_code == 401
