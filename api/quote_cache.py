"""The in-memory latest-quote cache used by the live feed.

One dictionary keyed by the application's canonical symbol (``INFY``,
``^NSEI``), shared by every FastAPI task and thread in the process. It is not
a source of truth: PostgreSQL's ``latest_quotes`` still owns persistence and
the REST reads. The cache exists so a browser can receive a tick before the
coalesced database write happens.

Two rules keep an older price from beating a newer one:

- A live tick is only accepted when its provider ``source_time`` is strictly
  newer than the cached one. Equal times are ignored, which also absorbs the
  duplicate frame a reconnect can deliver.
- ``restore`` never overwrites a live tick. A value loaded from PostgreSQL is
  marked ``live=False`` so a frame can never claim it was freshly received.

``source_time`` (the provider's market time) and ``received_at`` (when this
process saw the frame) stay separate. ``received_at`` is ``None`` for restored
rows, which is how the frontend tells a persisted quote from a live tick.
"""

import math
import threading
from dataclasses import dataclass
from datetime import datetime, timezone

# A provider timestamp this far ahead is treated as broken, not as "fresh".
MAX_FUTURE_SKEW_SECONDS = 120


@dataclass(frozen=True)
class CachedQuote:
    """One symbol's newest known price."""

    symbol: str
    ltp: float
    day_change: float
    day_change_pct: float
    source_time: datetime | None
    received_at: datetime | None
    live: bool
    volume: int | None = None
    updated_at: datetime | None = None


def usable_price(value):
    """True for a real, positive price, excluding ``bool`` and NaN/inf."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(value) and value > 0


def _aware(value):
    """Return a timezone-aware UTC datetime, or ``None``."""
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _number(value, default=0.0):
    """A finite float for a display field, falling back to ``default``."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return float(value) if math.isfinite(value) else default


def is_stale(quote, now, stale_after_seconds):
    """True when the quote's provider time is missing, old or in the future."""
    source_time = _aware(quote.source_time)
    if source_time is None:
        return True
    age = (now - source_time).total_seconds()
    return age > stale_after_seconds or age < -MAX_FUTURE_SKEW_SECONDS


class QuoteCache:
    """Thread-safe symbol -> ``CachedQuote`` map with freshness guards."""

    def __init__(self):
        self._lock = threading.Lock()
        self._quotes = {}

    def record(
        self,
        symbol,
        ltp,
        day_change,
        day_change_pct,
        source_time,
        received_at,
        volume=None,
    ):
        """Store a live tick. Returns the new quote, or ``None`` if rejected."""
        name = str(symbol or "").strip().upper()
        moment = _aware(source_time)
        if not name or not usable_price(ltp) or moment is None:
            return None

        quote = CachedQuote(
            symbol=name,
            ltp=float(ltp),
            day_change=_number(day_change),
            day_change_pct=_number(day_change_pct),
            source_time=moment,
            received_at=_aware(received_at),
            live=True,
            volume=int(volume) if isinstance(volume, (int, float)) and volume >= 0 else None,
            updated_at=_aware(received_at),
        )

        with self._lock:
            current = self._quotes.get(name)
            if current is not None and current.source_time is not None:
                if quote.source_time <= current.source_time:
                    return None
            self._quotes[name] = quote
            return quote

    def restore(
        self,
        symbol,
        ltp,
        day_change,
        day_change_pct,
        source_time,
        updated_at,
    ):
        """Load one persisted quote without pretending it is a live tick.

        A live cached quote always wins; a persisted row only replaces another
        persisted row when its provider time is newer.
        """
        name = str(symbol or "").strip().upper()
        if not name or not usable_price(ltp):
            return None

        moment = _aware(source_time)
        quote = CachedQuote(
            symbol=name,
            ltp=float(ltp),
            day_change=_number(day_change),
            day_change_pct=_number(day_change_pct),
            source_time=moment,
            received_at=None,
            live=False,
            updated_at=_aware(updated_at),
        )

        with self._lock:
            current = self._quotes.get(name)
            if current is not None:
                if current.live:
                    return None
                if (
                    current.source_time is not None
                    and quote.source_time is not None
                    and quote.source_time <= current.source_time
                ):
                    return None
            self._quotes[name] = quote
            return quote

    def get(self, symbol):
        name = str(symbol or "").strip().upper()
        with self._lock:
            return self._quotes.get(name)

    def snapshot(self, symbols=None):
        """Return quotes for ``symbols`` (or all), newest symbol order stable."""
        wanted = None
        if symbols is not None:
            wanted = {
                str(symbol or "").strip().upper()
                for symbol in symbols
                if str(symbol or "").strip()
            }
        with self._lock:
            if wanted is None:
                return list(self._quotes.values())
            return [
                quote
                for symbol, quote in self._quotes.items()
                if symbol in wanted
            ]

    def clear(self):
        with self._lock:
            self._quotes.clear()

    def __len__(self):
        with self._lock:
            return len(self._quotes)
