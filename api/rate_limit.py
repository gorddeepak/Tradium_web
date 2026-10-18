"""Rate limiting for the auth endpoints.

Port of the express-rate-limit middleware in server/routes/authRoutes.js:
20 requests per 15 minutes per client IP on signup and login, with the
draft-7 `RateLimit-*` response headers and the same 429 body.

Like the Express default store, counters live in memory in this process, so
the limit is per worker rather than shared across a cluster.

This is middleware rather than a route dependency on purpose: Express sets
the headers on every response the limiter guards, including the 400s the
controller returns, and a dependency's Response is dropped when a handler
raises.
"""

import math
import threading
import time

from starlette.responses import JSONResponse

AUTH_LIMIT = 20
AUTH_WINDOW_SECONDS = 15 * 60
TOO_MANY_ATTEMPTS = "Too many attempts. Try again in a few minutes."

# The routes the Express limiter is mounted on.
LIMITED_ROUTES = frozenset({("POST", "/api/auth/signup"), ("POST", "/api/auth/login")})


class FixedWindowLimiter:
    """One fixed window per key, matching express-rate-limit's MemoryStore."""

    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window_seconds = window_seconds
        self._window_start: dict[str, float] = {}
        self._count: dict[str, int] = {}
        self._lock = threading.Lock()

    def hit(self, key: str) -> tuple[bool, int, int]:
        """Count one request and return (allowed, remaining, reset_seconds)."""
        now = time.monotonic()
        with self._lock:
            start = self._window_start.get(key)
            if start is None or now - start >= self.window_seconds:
                start = now
                count = 0
            else:
                count = self._count[key]
            count += 1
            self._window_start[key] = start
            self._count[key] = count

        remaining = max(0, self.limit - count)
        reset = max(1, math.ceil(start + self.window_seconds - now))
        return count <= self.limit, remaining, reset


class AuthRateLimitMiddleware:
    """Apply the limiter to signup/login and stamp the draft-7 headers."""

    def __init__(self, app, limit: int = AUTH_LIMIT, window_seconds: int = AUTH_WINDOW_SECONDS):
        self.app = app
        self.limiter = FixedWindowLimiter(limit=limit, window_seconds=window_seconds)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or (scope["method"], scope["path"]) not in LIMITED_ROUTES:
            await self.app(scope, receive, send)
            return

        client = scope.get("client")
        key = client[0] if client else "unknown"
        allowed, remaining, reset = self.limiter.hit(key)

        headers = {
            "RateLimit-Policy": f"{self.limiter.limit};w={self.limiter.window_seconds}",
            "RateLimit": f"limit={self.limiter.limit}, remaining={remaining}, reset={reset}",
        }

        if not allowed:
            # Retry-After accompanies the 429 only, as in express-rate-limit.
            response = JSONResponse(
                status_code=429,
                content={"message": TOO_MANY_ATTEMPTS},
                headers={**headers, "Retry-After": str(reset)},
            )
            await response(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                message["headers"].extend(
                    (name.lower().encode("latin-1"), value.encode("latin-1"))
                    for name, value in headers.items()
                )
            await send(message)

        await self.app(scope, receive, send_with_headers)
