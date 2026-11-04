"""Focused tests for GET /api/instruments/:symbol/candles.

The route reaches Yahoo through api.market_data, so these tests replace
api.market_data._request_chart with a canned payload and never touch the
network. The payload shape is the one a real Yahoo chart response has, and the
bar-by-bar mapping matches the Yahoo chart contract.
"""

import pytest
import requests

from api.market_data import (
    CANDLE_RANGES,
    IST_OFFSET_SECONDS,
    REQUEST_TIMEOUT_SECONDS,
    MarketDataError,
)


def chart_payload(timestamps, opens):
    """A minimal but realistically shaped chart response (OHLC rise together)."""
    return {
        "chart": {
            "result": [
                {
                    "meta": {"currency": "INR", "exchangeTimezoneName": "Asia/Kolkata"},
                    "timestamp": timestamps,
                    "indicators": {
                        "quote": [
                            {
                                "open": opens,
                                "high": [None if v is None else v + 1 for v in opens],
                                "low": [None if v is None else v - 1 for v in opens],
                                "close": opens,
                                "volume": [1 for _ in opens],
                            }
                        ]
                    },
                }
            ],
            "error": None,
        }
    }


@pytest.fixture
def stub_provider(monkeypatch):
    """Capture the call the route makes and answer with a canned payload."""

    def _stub(payload):
        calls = {}

        def fake_request_chart(**kwargs):
            calls.update(kwargs)
            return payload

        monkeypatch.setattr("api.market_data._request_chart", fake_request_chart)
        return calls

    return _stub


def test_returns_ohlc_only_and_shifts_timestamps_to_ist(
    client, make_token, user_id, stub_provider
):
    calls = stub_provider(chart_payload([1789982100], [1238.5]))

    response = client.get(
        "/api/instruments/RELIANCE/candles",
        params={"range": "1M"},
        cookies={"token": make_token(user_id)},
    )

    assert response.status_code == 200
    # Volume and the Yahoo-internal date are not part of the client contract.
    assert response.json() == [
        {
            "time": 1789982100 + IST_OFFSET_SECONDS,
            "open": 1238.5,
            "high": 1239.5,
            "low": 1237.5,
            "close": 1238.5,
        }
    ]
    assert calls["ticker"] == "RELIANCE.NS"
    assert calls["interval"] == "30m"


def test_index_symbols_keep_their_caret(client, make_token, user_id, stub_provider):
    calls = stub_provider(chart_payload([1], [100.0]))

    client.get(
        "/api/instruments/^NSEI/candles",
        params={"range": "1M"},
        cookies={"token": make_token(user_id)},
    )

    assert calls["ticker"] == "^NSEI"


def test_drops_bars_that_have_no_open_price(client, make_token, user_id, stub_provider):
    # Yahoo pads intraday sessions with placeholder bars that Express filters out.
    stub_provider(chart_payload([1, 2, 3], [100.0, None, 102.0]))

    body = client.get(
        "/api/instruments/RELIANCE/candles",
        params={"range": "1D"},
        cookies={"token": make_token(user_id)},
    ).json()

    assert [bar["time"] for bar in body] == [
        1 + IST_OFFSET_SECONDS,
        3 + IST_OFFSET_SECONDS,
    ]


def test_a_symbol_with_no_trading_data_is_an_empty_list(
    client, make_token, user_id, stub_provider
):
    stub_provider(chart_payload([], []))

    response = client.get(
        "/api/instruments/RELIANCE/candles",
        cookies={"token": make_token(user_id)},
    )

    assert response.status_code == 200
    assert response.json() == []


def test_defaults_to_the_one_month_range(client, make_token, user_id, stub_provider):
    calls = stub_provider(chart_payload([1], [100.0]))

    client.get("/api/instruments/RELIANCE/candles", cookies={"token": make_token(user_id)})

    assert calls["interval"] == "30m"
    assert abs((calls["period2"] - calls["period1"]) - 30 * 86400) <= 1


@pytest.mark.parametrize("range_name", sorted(CANDLE_RANGES))
def test_each_range_maps_to_the_express_interval(
    client, make_token, user_id, stub_provider, range_name
):
    days, interval = CANDLE_RANGES[range_name]
    calls = stub_provider(chart_payload([1], [100.0]))

    client.get(
        "/api/instruments/RELIANCE/candles",
        params={"range": range_name},
        cookies={"token": make_token(user_id)},
    )

    assert calls["interval"] == interval
    assert abs((calls["period2"] - calls["period1"]) - days * 86400) <= 1


def test_an_unrecognised_range_falls_back_to_daily(
    client, make_token, user_id, stub_provider
):
    # Express does `RANGES[range] || { days: 30, interval: "1d" }`.
    calls = stub_provider(chart_payload([1], [100.0]))

    client.get(
        "/api/instruments/RELIANCE/candles",
        params={"range": "7D"},
        cookies={"token": make_token(user_id)},
    )

    assert calls["interval"] == "1d"
    assert abs((calls["period2"] - calls["period1"]) - 30 * 86400) <= 1


def test_the_client_exchange_parameter_is_ignored(
    client, make_token, user_id, stub_provider
):
    calls = stub_provider(chart_payload([1], [100.0]))

    response = client.get(
        "/api/instruments/RELIANCE/candles",
        params={"range": "1D", "exchange": "BSE"},
        cookies={"token": make_token(user_id)},
    )

    assert response.status_code == 200
    assert calls["ticker"] == "RELIANCE.NS"


def test_provider_failure_is_the_express_404(
    client, make_token, user_id, monkeypatch, caplog
):
    def fake_request_chart(**kwargs):
        raise MarketDataError("No data found, symbol may be delisted")

    monkeypatch.setattr("api.market_data._request_chart", fake_request_chart)

    with caplog.at_level("ERROR", logger="api.routes.instruments"):
        response = client.get(
            "/api/instruments/NOPE/candles",
            params={"range": "1M"},
            cookies={"token": make_token(user_id)},
        )

    assert response.status_code == 404
    assert response.json() == {"message": "Could not fetch candle data"}
    # Express console.errors the provider message but never returns it.
    assert "No data found, symbol may be delisted" in caplog.text
    assert "No data found" not in response.text


def test_provider_error_object_is_a_404(client, make_token, user_id, stub_provider):
    stub_provider(
        {"chart": {"result": None, "error": {"code": "Not Found", "description": "No data found"}}}
    )

    response = client.get(
        "/api/instruments/NOPE/candles",
        params={"range": "1M"},
        cookies={"token": make_token(user_id)},
    )

    assert response.status_code == 404
    assert response.json() == {"message": "Could not fetch candle data"}


def test_requires_authentication(client):
    assert client.get("/api/instruments/RELIANCE/candles").status_code == 401


class FakeResponse:
    def __init__(self, payload=None, error=None):
        self._payload = payload
        self._error = error

    def raise_for_status(self):
        if self._error is not None:
            raise self._error

    def json(self):
        if self._payload is JSON_ERROR:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return self._payload


JSON_ERROR = object()


@pytest.fixture
def record_request(monkeypatch):
    """Replace requests.get so the outgoing chart request can be inspected."""
    seen = {}

    def _record(response):
        def fake_get(url, **kwargs):
            seen["url"] = url
            seen.update(kwargs)
            return response

        monkeypatch.setattr("api.market_data.requests.get", fake_get)
        return seen

    return _record


def test_sends_the_same_query_parameters_as_yahoo_finance2(record_request):
    # These are the parameters yahoo-finance2 puts on the chart request; the
    # `includePrePost` default in particular decides which bars come back, so
    # it has to match or the index series differs (verified against Yahoo).
    from api.market_data import fetch_candles

    seen = record_request(FakeResponse(chart_payload([1], [100.0])))
    fetch_candles("RELIANCE", "1M")

    assert seen["url"] == "https://query2.finance.yahoo.com/v8/finance/chart/RELIANCE.NS"
    assert seen["params"]["useYfid"] == "true"
    assert seen["params"]["includePrePost"] == "true"
    assert seen["params"]["events"] == "div|split|earn"
    assert seen["params"]["lang"] == "en-US"
    assert seen["params"]["interval"] == "30m"
    assert seen["timeout"] == REQUEST_TIMEOUT_SECONDS
    assert "User-Agent" in seen["headers"]


def test_transport_failure_becomes_a_provider_error(record_request):
    from api.market_data import fetch_candles

    record_request(FakeResponse(error=requests.HTTPError("404 Client Error")))

    with pytest.raises(MarketDataError):
        fetch_candles("RELIANCE", "1M")


def test_non_json_body_becomes_a_provider_error(record_request):
    from api.market_data import fetch_candles

    record_request(FakeResponse(payload=JSON_ERROR))

    with pytest.raises(MarketDataError):
        fetch_candles("RELIANCE", "1M")


def test_a_result_without_timestamps_is_an_empty_list(record_request):
    from api.market_data import fetch_candles

    record_request(
        FakeResponse({"chart": {"result": [{"meta": {}}], "error": None}})
    )

    assert fetch_candles("RELIANCE", "1M") == []


def test_a_missing_result_is_a_provider_error(record_request):
    from api.market_data import fetch_candles

    record_request(FakeResponse({"chart": {"result": [], "error": None}}))

    with pytest.raises(MarketDataError):
        fetch_candles("RELIANCE", "1M")
