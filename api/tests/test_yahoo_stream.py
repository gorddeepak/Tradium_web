"""Focused tests for the Yahoo streamer frame decoder (Phase 2b).

The frames in fixtures/yahoo_stream_frames.json were captured from the live
streamer during a market session, so these tests pin the real wire format
rather than a guess about it. No network is used.
"""

import base64
import json
from datetime import timedelta
from pathlib import Path

import pytest

from api.yahoo_stream import (
    IST,
    StreamDecodeError,
    decode_frame,
    quote_time,
)

FIXTURES = Path(__file__).parent / "fixtures" / "yahoo_stream_frames.json"


@pytest.fixture(scope="module")
def frames():
    with open(FIXTURES, encoding="utf-8") as handle:
        return json.load(handle)


def test_fixtures_are_real_pricing_frames(frames):
    assert len(frames) >= 6
    assert all(frame["type"] == "pricing" for frame in frames)
    assert all(frame["message"] for frame in frames)


def test_decodes_every_captured_frame(frames):
    quotes = [decode_frame(json.dumps(frame)) for frame in frames]
    symbols = {quote["id"] for quote in quotes}
    assert {"RELIANCE.NS", "INFY.NS", "^NSEI"} <= symbols


def test_decodes_the_fields_the_cache_needs(frames):
    quote = decode_frame(json.dumps(frames[0]))

    assert isinstance(quote["id"], str)
    assert isinstance(quote["price"], float) and quote["price"] > 0
    assert isinstance(quote["change_percent"], float)
    assert isinstance(quote["change"], float)
    assert isinstance(quote["time"], int)
    assert quote["exchange"] == "NSI"


def test_time_is_decoded_as_zigzag_milliseconds(frames):
    """A plain varint read would put `time` in 2083. This is the trap."""
    quote = decode_frame(json.dumps(frames[0]))
    stamp = quote_time(quote)

    assert stamp is not None
    assert stamp.tzinfo is not None
    assert stamp.utcoffset().total_seconds() == 5.5 * 3600
    # Any plausible trading timestamp, not a 2083 artefact.
    assert 2020 <= stamp.year <= 2030

    # And it is genuinely milliseconds, not seconds.
    assert quote["time"] > 10**12


def test_time_agrees_with_a_second_independent_frame(frames):
    """Two frames for one symbol must not produce absurd deltas."""
    quotes = [decode_frame(json.dumps(frame)) for frame in frames]
    by_symbol = {}
    for quote in quotes:
        by_symbol.setdefault(quote["id"], []).append(quote_time(quote))

    for symbol, stamps in by_symbol.items():
        assert all(stamp is not None for stamp in stamps), symbol
        assert max(stamps) - min(stamps) < timedelta(hours=1), symbol


def test_previous_close_is_derivable(frames):
    """price - change reproduces the previous close the UI shows."""
    quote = decode_frame(json.dumps(frames[0]))
    previous = quote["price"] - quote["change"]
    assert previous > 0
    assert abs((quote["change"] / previous) * 100 - quote["change_percent"]) < 0.1


def test_absent_optional_fields_are_not_invented(frames):
    """An index frame omits volume; the decoder must not fabricate a zero."""
    quotes = [decode_frame(json.dumps(frame)) for frame in frames]
    index_quote = next(quote for quote in quotes if quote["id"] == "^NSEI")

    assert "price" in index_quote
    # Whatever the provider omitted stays omitted; nothing is defaulted to 0.
    for optional in ("day_volume", "open_price", "previous_close", "market_cap"):
        if optional not in index_quote:
            assert optional not in index_quote


def test_market_cap_is_not_streamed(frames):
    """Streaming cannot fill the Markets page's marketCap column."""
    quotes = [decode_frame(json.dumps(frame)) for frame in frames]
    assert all("market_cap" not in quote for quote in quotes)


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "not json",
        "[]",
        '{"type":"pricing"}',
        '{"type":"unknown","message":"AAAA"}',
        '{"type":"pricing","message":"!!!not base64!!!"}',
        '{"type":"pricing","message":"AAAA"}',
    ],
)
def test_unusable_frames_raise_instead_of_returning_a_price(raw):
    with pytest.raises(StreamDecodeError):
        decode_frame(raw)


def test_truncated_payload_raises():
    payload = base64.b64encode(b"\x0a\x40").decode()  # string of length 64, no bytes
    with pytest.raises(StreamDecodeError):
        decode_frame(json.dumps({"type": "pricing", "message": payload}))


def test_quote_time_handles_a_missing_or_bad_timestamp():
    assert quote_time({}) is None
    assert quote_time({"time": "1792398777000"}) is None
    assert quote_time({"time": 10**30}) is None
