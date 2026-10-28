"""PostgreSQL persistence and reads for instruments and latest quotes.

Phase 3B2 moves the canonical market cache out of MongoDB's ``marketquotes``
collection. Market sync owns the 53-symbol universe; price sync may add
book-only instruments (``in_market_universe = false``) for symbols held or
ordered but outside that universe.

Two quote timestamps are kept separate:

- ``updated_at`` is when this service persisted the quote. It is what the API
  has always exposed as ``updatedAt`` and what market overview's ``asOf`` uses.
- ``source_time`` is the provider's ``regularMarketTime``, or ``NULL`` when the
  provider did not send one. A missing source time never falls back to the
  database write time.

An incoming quote whose ``source_time`` is older than the stored one is dropped,
so a late provider response cannot overwrite a newer price.
"""

import logging
import math
import secrets
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from sqlalchemy import case, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from .postgres.models import Instrument, LatestQuote
from .rows import utcnow as _utcnow

logger = logging.getLogger(__name__)

SECTOR_BATCH_SIZE = 10


def provider_decimal(value):
    """Convert a provider value to ``Decimal``, or ``None`` when unusable."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, Decimal):
        number = value
    else:
        try:
            number = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
    if not number.is_finite():
        return None
    return number


def _quantized(value, places):
    """Quantize a signed provider value, treating a missing value as zero."""
    scale = Decimal(1).scaleb(-places)
    number = provider_decimal(value)
    if number is None:
        return Decimal(0).quantize(scale)
    return number.quantize(scale, rounding=ROUND_HALF_UP)


def _non_negative(value, places):
    """Quantize a field that has a non-negative database constraint."""
    number = provider_decimal(value)
    if number is None or number < 0:
        number = Decimal(0)
    return _quantized(number, places)


def _volume(value):
    """Volumes are stored as integers; a missing or negative one becomes 0."""
    number = provider_decimal(value)
    if number is None or number < 0:
        return 0
    return int(number)


def provider_source_time(value):
    """Convert provider epoch seconds to a UTC datetime, or ``None``.

    ``regularMarketTime`` is optional. A missing, malformed or out-of-range
    value stays ``None``; the quote receipt time is never substituted.
    """
    if isinstance(value, bool) or value is None:
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(seconds) or seconds < 0:
        return None
    try:
        moment = datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return moment.replace(microsecond=(moment.microsecond // 1000) * 1000)


def is_usable_quote(row):
    """True when a provider row carries a positive, finite price."""
    price = provider_decimal((row or {}).get("regularMarketPrice"))
    return price is not None and price > 0


def _unique_entries(entries):
    """Keep the first entry for each symbol, before any provider-to-DB write."""
    seen = set()
    unique = []
    for entry in entries:
        symbol = entry["symbol"]
        if symbol in seen:
            continue
        seen.add(symbol)
        unique.append(entry)
    return unique


def _instrument_rows(entries, now, in_market_universe):
    return [
        {
            "id": secrets.token_hex(12),
            "symbol": entry["symbol"],
            "name": entry.get("name") or entry["symbol"],
            "kind": entry.get("kind") or "stock",
            "sector": "",
            "in_market_universe": in_market_universe,
            "created_at": now,
            "updated_at": now,
            "version": 0,
        }
        for entry in entries
    ]


def _upsert_instruments(session, entries, now, in_market_universe, update_metadata):
    if not entries:
        return

    statement = insert(Instrument).values(
        _instrument_rows(entries, now, in_market_universe)
    )
    if update_metadata:
        # A quote cycle refreshes identity fields but leaves sector to the
        # backfill and never moves the instrument's own updated_at.
        statement = statement.on_conflict_do_update(
            index_elements=[Instrument.symbol],
            set_={
                "name": statement.excluded.name,
                "kind": statement.excluded.kind,
                "in_market_universe": statement.excluded.in_market_universe,
            },
        )
    else:
        # Price sync only supplies a book-only row; an existing universe row
        # keeps its identity and market-universe membership.
        statement = statement.on_conflict_do_nothing(
            index_elements=[Instrument.symbol]
        )
    session.execute(statement)


def _instrument_ids(session, symbols):
    if not symbols:
        return {}
    rows = session.execute(
        select(Instrument.symbol, Instrument.id).where(
            Instrument.symbol.in_(symbols)
        )
    )
    return {symbol: instrument_id for symbol, instrument_id in rows}


def _quote_row(entry, instrument_id, now, full_row):
    row = entry.get("row") or {}
    values = {
        "instrument_id": instrument_id,
        "ltp": _quantized(row.get("regularMarketPrice"), 4),
        "day_change_pct": _quantized(row.get("regularMarketChangePercent"), 6),
        "updated_at": now,
        "source_time": provider_source_time(row.get("regularMarketTime")),
    }
    if full_row:
        values.update(
            {
                "day_change": _quantized(row.get("regularMarketChange"), 4),
                "prev_close": _non_negative(row.get("regularMarketPreviousClose"), 4),
                "volume": _volume(row.get("regularMarketVolume")),
                "market_cap": _non_negative(row.get("marketCap"), 2),
            }
        )
    return values


def _upsert_quotes(session, quote_rows, full_row):
    if not quote_rows:
        return

    statement = insert(LatestQuote).values(quote_rows)
    set_values = {
        "ltp": statement.excluded.ltp,
        "day_change_pct": statement.excluded.day_change_pct,
        "updated_at": statement.excluded.updated_at,
        "source_time": statement.excluded.source_time,
    }
    if full_row:
        set_values.update(
            {
                "day_change": statement.excluded.day_change,
                "prev_close": statement.excluded.prev_close,
                "volume": statement.excluded.volume,
                "market_cap": statement.excluded.market_cap,
            }
        )

    statement = statement.on_conflict_do_update(
        index_elements=[LatestQuote.instrument_id],
        set_=set_values,
        where=or_(
            statement.excluded.source_time.is_(None),
            LatestQuote.source_time.is_(None),
            statement.excluded.source_time >= LatestQuote.source_time,
        ),
    )
    session.execute(statement)


def persist_market_quotes(session_factory, entries, now=None):
    """Upsert market-sync instruments and full quotes.

    ``entries`` are ``{"symbol", "name", "kind", "row"}`` dicts from the 53
    symbol universe. Rows without a usable price still refresh instrument
    metadata but never create or overwrite a quote.
    """
    unique = _unique_entries(entries)
    if not unique:
        return 0

    now = now or _utcnow()
    valid = [entry for entry in unique if is_usable_quote(entry["row"])]

    with session_factory() as session:
        with session.begin():
            _upsert_instruments(
                session,
                unique,
                now,
                in_market_universe=True,
                update_metadata=True,
            )
            ids = _instrument_ids(session, [entry["symbol"] for entry in unique])
            quote_rows = [
                _quote_row(entry, ids[entry["symbol"]], now, full_row=True)
                for entry in valid
            ]
            _upsert_quotes(session, quote_rows, full_row=True)

    return len(quote_rows)


def persist_price_quotes(session_factory, entries, now=None):
    """Upsert price-sync instruments and the fields price sync owns.

    A symbol outside the universe gets a book-only instrument. Existing
    instruments keep their metadata and ``in_market_universe`` value. Only
    ``ltp``, ``day_change_pct``, ``source_time`` and ``updated_at`` are written,
    so the richer market-sync columns survive a price tick.
    """
    unique = _unique_entries(entries)
    valid = [entry for entry in unique if is_usable_quote(entry["row"])]
    if not valid:
        return 0

    now = now or _utcnow()
    with session_factory() as session:
        with session.begin():
            _upsert_instruments(
                session,
                valid,
                now,
                in_market_universe=False,
                update_metadata=False,
            )
            ids = _instrument_ids(session, [entry["symbol"] for entry in valid])
            quote_rows = [
                _quote_row(entry, ids[entry["symbol"]], now, full_row=False)
                for entry in valid
            ]
            _upsert_quotes(session, quote_rows, full_row=False)

    return len(quote_rows)


def count_market_quotes(session):
    """Number of quote rows in the visible 53-symbol universe."""
    return session.scalar(
        select(func.count())
        .select_from(LatestQuote)
        .join(Instrument, Instrument.id == LatestQuote.instrument_id)
        .where(Instrument.in_market_universe.is_(True))
    )


def read_market_overview(session):
    """Rows for ``GET /api/market/overview`` in the approved order.

    Only universe instruments with a persisted quote are returned. Indices use
    the seed rank (unknown first), then symbol; stocks use symbol. ``asOf`` is
    the freshest quote receipt time, or ``None`` on a cold cache.
    """
    columns = (
        Instrument.id.label("_id"),
        Instrument.symbol,
        Instrument.name,
        Instrument.kind,
        Instrument.sector,
        LatestQuote.ltp,
        LatestQuote.day_change.label("dayChange"),
        LatestQuote.day_change_pct.label("dayChangePct"),
        LatestQuote.prev_close.label("prevClose"),
        LatestQuote.volume,
        LatestQuote.market_cap.label("marketCap"),
        Instrument.created_at.label("createdAt"),
        LatestQuote.updated_at.label("updatedAt"),
        Instrument.version.label("__v"),
    )
    base = (
        select(*columns)
        .join(LatestQuote, LatestQuote.instrument_id == Instrument.id)
        .where(Instrument.in_market_universe.is_(True))
    )

    index_rank = case(
        (Instrument.symbol == "^NSEI", 0),
        (Instrument.symbol == "^NSEBANK", 1),
        (Instrument.symbol == "^BSESN", 2),
        else_=-1,
    )
    indices = session.execute(
        base.where(Instrument.kind == "index").order_by(
            index_rank, Instrument.symbol
        )
    ).mappings()
    stocks = session.execute(
        base.where(Instrument.kind == "stock").order_by(Instrument.symbol)
    ).mappings()
    as_of = session.scalar(
        select(func.max(LatestQuote.updated_at))
        .select_from(LatestQuote)
        .join(Instrument, Instrument.id == LatestQuote.instrument_id)
        .where(Instrument.in_market_universe.is_(True))
    )

    return {
        "asOf": as_of,
        "indices": [dict(row) for row in indices],
        "stocks": [dict(row) for row in stocks],
    }


def _escape_like(value):
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search_market_instruments(session, query, limit=10):
    """Search the visible universe with the approved relevance order.

    Exact symbol, symbol prefix, name prefix, then any substring; ties break by
    symbol so repeated calls are deterministic.
    """
    text = query.strip()
    if not text:
        return []

    lowered = text.lower()
    escaped = _escape_like(lowered)
    contains = f"%{escaped}%"
    prefix = f"{escaped}%"
    match = or_(
        func.lower(Instrument.symbol).like(contains, escape="\\"),
        func.lower(Instrument.name).like(contains, escape="\\"),
    )
    relevance = case(
        (func.lower(Instrument.symbol) == lowered, 0),
        (func.lower(Instrument.symbol).like(prefix, escape="\\"), 1),
        (func.lower(Instrument.name).like(prefix, escape="\\"), 2),
        else_=3,
    )

    statement = (
        select(
            Instrument.symbol,
            Instrument.name,
            Instrument.kind,
            LatestQuote.ltp.label("price"),
            LatestQuote.day_change_pct.label("changePct"),
        )
        .join(LatestQuote, LatestQuote.instrument_id == Instrument.id)
        .where(Instrument.in_market_universe.is_(True), match)
        .order_by(relevance, Instrument.symbol)
        .limit(limit)
    )
    return [dict(row) for row in session.execute(statement).mappings()]


def backfill_sectors(session_factory, fetch_sector, limit=SECTOR_BATCH_SIZE):
    """Resolve missing sectors on instruments, without touching quote freshness.

    Provider calls happen outside the database transaction. The update is
    conditional on ``sector = ''`` so a concurrent resolver cannot undo a
    value. ``latest_quotes.updated_at`` is deliberately untouched.
    """
    with session_factory() as session:
        pending = session.execute(
            select(Instrument.id, Instrument.symbol)
            .where(Instrument.kind == "stock", Instrument.sector == "")
            .order_by(Instrument.symbol)
            .limit(limit)
        ).all()

    resolved = []
    for instrument_id, symbol in pending:
        try:
            sector = fetch_sector(symbol)
        except Exception as err:  # noqa: BLE001 - one profile failure must not stop the run
            logger.error("Sector fetch failed for %s: %s", symbol, err)
            continue
        if not sector:
            continue
        resolved.append((instrument_id, symbol, sector))

    if not resolved:
        return 0

    now = _utcnow()
    with session_factory() as session:
        with session.begin():
            filled = 0
            for instrument_id, symbol, sector in resolved:
                result = session.execute(
                    update(Instrument)
                    .where(Instrument.id == instrument_id, Instrument.sector == "")
                    .values(sector=sector, updated_at=now)
                )
                if result.rowcount:
                    logger.info("Sector backfill: %s -> %s", symbol, sector)
                    filled += 1

    return filled

