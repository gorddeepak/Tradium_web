"""Unit tests for the document-to-JSON conversion."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from bson import ObjectId

from api.serialization import to_json_value


def test_object_id_becomes_hex_string():
    value = ObjectId("64b7f1c2a1b2c3d4e5f60718")
    assert to_json_value(value) == "64b7f1c2a1b2c3d4e5f60718"


def test_datetime_becomes_iso_string_with_three_decimals():
    moment = datetime(2026, 10, 18, 9, 30, 0, 123000, tzinfo=timezone.utc)
    assert to_json_value(moment) == "2026-10-18T09:30:00.123Z"


def test_datetime_with_zero_microseconds_keeps_milliseconds():
    moment = datetime(2026, 10, 18, 9, 30, 0, tzinfo=timezone.utc)
    assert to_json_value(moment) == "2026-10-18T09:30:00.000Z"


def test_naive_datetime_is_treated_as_utc():
    moment = datetime(2026, 10, 18, 9, 30, 0, tzinfo=None)
    assert to_json_value(moment) == "2026-10-18T09:30:00.000Z"


def test_aware_datetime_is_converted_to_utc():
    ist = timezone(timedelta(hours=5, minutes=30))
    moment = datetime(2026, 10, 18, 15, 0, 0, tzinfo=ist)
    assert to_json_value(moment) == "2026-10-18T09:30:00.000Z"


def test_nested_documents_and_lists_are_converted():
    document = {
        "_id": ObjectId(),
        "items": [{"_id": ObjectId(), "when": datetime(2026, 1, 1, tzinfo=timezone.utc)}],
        "count": 2,
        "label": "x",
    }
    converted = to_json_value(document)
    assert isinstance(converted["_id"], str)
    assert isinstance(converted["items"][0]["_id"], str)
    assert converted["items"][0]["when"] == "2026-01-01T00:00:00.000Z"
    assert converted["count"] == 2


def test_decimal_integral_values_become_json_integers():
    assert to_json_value(Decimal("500.0000")) == 500
    assert type(to_json_value(Decimal("500.0000"))) is int
    assert to_json_value(Decimal("16276858601472.00")) == 16276858601472


def test_decimal_fractional_values_keep_their_decimal_text():
    # This is the design's documented float fallback without simplejson.
    assert to_json_value(Decimal("1202.8000")) == 1202.8
    assert to_json_value(Decimal("-0.690000")) == -0.69
