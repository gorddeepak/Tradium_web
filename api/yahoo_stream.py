"""Decoder for Yahoo's streamer wire format.

Nothing here opens a socket. This module only turns one frame into a dict, so
the wire format stays testable without a network or a market session. The live
feed (``api/quote_feed.py``) is the only caller that reads real frames.

The format, as observed from ``wss://streamer.finance.yahoo.com/?version=2``:

- Each WebSocket message is JSON: ``{"type": "pricing", "message": "<base64>"}``.
- ``message`` is base64 of a protobuf ``PricingData`` (yfinance ships the same
  ``pricing.proto``; the field numbers below come from it).
- Two of the fields we need are declared ``sint64``, which protobuf encodes as
  **zigzag** varints. Reading ``time`` as a plain varint yields a timestamp in
  the year 2083 — the failure is silent, so it is decoded explicitly here.

Evidence and measurements are in docs/migration/MARKET_DATA_PLAN.md §3.2.
"""

import base64
import json
import struct
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

# Field numbers -> names, from yfinance's pricing.proto.
FIELD_NAMES = {
    1: "id",
    2: "price",
    3: "time",
    4: "currency",
    5: "exchange",
    6: "quote_type",
    7: "market_hours",
    8: "change_percent",
    9: "day_volume",
    10: "day_high",
    11: "day_low",
    12: "change",
    13: "short_name",
    15: "open_price",
    16: "previous_close",
    22: "last_size",
    23: "bid",
    25: "ask",
    27: "price_hint",
    32: "circulating_supply",
    33: "market_cap",
}

# sint64 in the .proto: zigzag-encoded, not plain varints.
ZIGZAG_FIELDS = {3, 9, 14, 19, 20, 21, 22, 24, 26, 27, 28, 29}
# float (wire type 5) and double (wire type 1) fields.
FLOAT_FIELDS = {2, 8, 10, 11, 12, 15, 16, 17, 23, 25}
DOUBLE_FIELDS = {32, 33}


class StreamDecodeError(Exception):
    """A frame could not be decoded. Callers should skip the frame, not guess."""


def decode_frame(raw_message):
    """Decode one WebSocket text message into a pricing dict.

    Returns ``{"id": "RELIANCE.NS", "price": ..., "time": <epoch ms>, ...}`` with
    only the fields the provider actually sent. Raises StreamDecodeError when
    the frame is not a usable pricing message.
    """
    try:
        envelope = json.loads(raw_message)
    except (TypeError, ValueError) as err:
        raise StreamDecodeError(f"frame is not JSON: {err}") from err

    if not isinstance(envelope, dict):
        raise StreamDecodeError("frame is not a JSON object")

    # Anything other than "pricing" carries no quote; treat it as unusable
    # rather than inventing a price.
    if envelope.get("type") != "pricing":
        raise StreamDecodeError(f"unexpected frame type {envelope.get('type')!r}")

    encoded = envelope.get("message")
    if not encoded:
        raise StreamDecodeError("frame has no message payload")

    try:
        payload = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as err:
        raise StreamDecodeError(f"payload is not base64: {err}") from err

    fields = _parse_message(payload)
    quote = {FIELD_NAMES[number]: value for number, value in fields.items() if number in FIELD_NAMES}

    # A frame without a symbol or a price cannot update anything.
    if not quote.get("id"):
        raise StreamDecodeError("frame has no symbol")
    if quote.get("price") is None:
        raise StreamDecodeError(f"frame for {quote['id']} has no price")

    return quote


def quote_time(quote):
    """Return the message time as a timezone-aware IST datetime, or None."""
    stamp = quote.get("time")
    if not isinstance(stamp, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(stamp / 1000, IST)
    except (OverflowError, OSError, ValueError):
        return None


def _read_varint(buf, index):
    shift = 0
    result = 0
    while True:
        byte = buf[index]
        index += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, index
        shift += 7
        if shift > 63:
            raise StreamDecodeError("varint too long")


def _zigzag(value):
    return (value >> 1) ^ -(value & 1)


def _parse_message(buf):
    """Return {field_number: value} for a flat protobuf message."""
    fields = {}
    index = 0
    length = len(buf)
    try:
        while index < length:
            key, index = _read_varint(buf, index)
            number = key >> 3
            wire_type = key & 7

            if wire_type == 0:
                value, index = _read_varint(buf, index)
                fields[number] = _zigzag(value) if number in ZIGZAG_FIELDS else value
            elif wire_type == 1:
                fields[number] = struct.unpack("<d", buf[index:index + 8])[0]
                index += 8
            elif wire_type == 2:
                size, index = _read_varint(buf, index)
                raw = buf[index:index + size]
                index += size
                fields[number] = raw.decode("utf-8", "replace")
            elif wire_type == 5:
                fields[number] = struct.unpack("<f", buf[index:index + 4])[0]
                index += 4
            else:
                raise StreamDecodeError(f"unsupported wire type {wire_type}")
    except (IndexError, struct.error) as err:
        raise StreamDecodeError(f"truncated protobuf payload: {err}") from err

    return fields
