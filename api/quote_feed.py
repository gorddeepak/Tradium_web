"""Upstream Yahoo streamer client.

One connection per FastAPI process. ``QuoteService`` owns the only instance;
browsers never talk to Yahoo directly.

The wire format is documented in ``api/yahoo_stream.py``. This module is only
the transport: connect, subscribe, decode, hand each pricing frame to a
callback, and reconnect with bounded exponential backoff.

The provider is **unofficial**. Yahoo does not publish this endpoint as a
supported market-data API, and its terms do not grant redistribution. Keep the
feed off unless the deployment use is acceptable for your own account; see
``docs/LIVE_MARKET_PRICES.md``.

No real socket is opened in tests: ``connect`` is injectable, so a fake
connector can drive every reconnect path deterministically.
"""

import asyncio
import json
import logging
import threading

from .rows import utcnow
from .yahoo_stream import StreamDecodeError, decode_frame

logger = logging.getLogger(__name__)

DEFAULT_URL = "wss://streamer.finance.yahoo.com/?version=2"
MIN_BACKOFF_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 30.0

# How often the receive loop wakes up so a shutdown is noticed promptly.
RECV_TIMEOUT_SECONDS = 0.5


class YahooQuoteFeed:
    """Connects to the Yahoo streamer and forwards decoded pricing frames."""

    def __init__(
        self,
        tickers,
        on_quote,
        *,
        url=DEFAULT_URL,
        connect=None,
        backoff_min=MIN_BACKOFF_SECONDS,
        backoff_max=MAX_BACKOFF_SECONDS,
    ):
        self.tickers = list(dict.fromkeys(ticker for ticker in tickers if ticker))
        self.on_quote = on_quote
        self.url = url
        self._connect = connect
        self.backoff_min = backoff_min
        self.backoff_max = backoff_max
        self._stop = threading.Event()
        self._state = "idle"
        self.connected_at = None
        self.last_tick_at = None
        self.connections = 0

    @property
    def state(self):
        return self._state

    def status(self):
        return {
            "state": self._state,
            "connectedAt": self.connected_at,
            "lastTickAt": self.last_tick_at,
            "symbols": len(self.tickers),
        }

    def stop(self):
        """Ask the run loop to exit. Safe to call from another thread."""
        self._stop.set()

    def _open(self):
        if self._connect is not None:
            return self._connect(self.url)

        # Imported lazily so this module imports without a websockets install.
        from websockets.asyncio.client import connect

        return connect(
            self.url,
            ping_interval=20,
            ping_timeout=20,
            open_timeout=10,
            close_timeout=5,
            max_queue=64,
        )

    async def run(self):
        """Connect forever until ``stop`` is called."""
        attempt = 0
        loop = asyncio.get_running_loop()

        while not self._stop.is_set():
            self._state = "connecting" if attempt == 0 else "reconnecting"
            try:
                async with self._open() as socket:
                    await socket.send(json.dumps({"subscribe": self.tickers}))
                    self.connections += 1
                    self.connected_at = utcnow()
                    self._state = "live"
                    attempt = 0
                    logger.info(
                        "Live quote feed connected (%s symbols)", len(self.tickers)
                    )
                    await self._receive(socket)
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001 - reconnect on any transport error
                if self._stop.is_set():
                    break
                delay = min(
                    self.backoff_max, self.backoff_min * (2 ** attempt)
                )
                attempt += 1
                self._state = "reconnecting"
                logger.warning(
                    "Live quote feed disconnected (%s); retrying in %.1fs",
                    err,
                    delay,
                )
                await self._sleep_or_stop(delay, loop)

        self._state = "stopped"
        logger.info("Live quote feed stopped")

    async def _receive(self, socket):
        while not self._stop.is_set():
            try:
                raw = await asyncio.wait_for(
                    socket.recv(), timeout=RECV_TIMEOUT_SECONDS
                )
            except asyncio.TimeoutError:
                continue
            self._handle(raw)

    def _handle(self, raw):
        try:
            quote = decode_frame(raw)
        except StreamDecodeError as err:
            # Unsupported symbols simply never send a frame; a malformed one is
            # skipped rather than guessed at.
            logger.debug("Skipping unusable Yahoo frame: %s", err)
            return

        self.last_tick_at = utcnow()
        try:
            self.on_quote(quote)
        except Exception:  # noqa: BLE001 - a callback bug must not drop the feed
            logger.exception("Live quote handler failed for %s", quote.get("id"))

    async def _sleep_or_stop(self, delay, loop):
        deadline = loop.time() + delay
        while not self._stop.is_set():
            remaining = deadline - loop.time()
            if remaining <= 0:
                return
            await asyncio.sleep(min(0.1, remaining))
