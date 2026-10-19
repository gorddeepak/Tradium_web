"""FastAPI application entry point.

Run locally:
    uvicorn api.main:app --reload --port 8000
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import db
from .rate_limit import AuthRateLimitMiddleware
from .routes import auth, funds, health, holdings, instruments, market, orders, portfolio, positions, watchlist
from .scheduler import MarketSyncScheduler, market_sync_enabled

logger = logging.getLogger(__name__)


def create_app(database=None) -> FastAPI:
    """Build the app. Tests pass a fake database to skip the real connection."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if database is not None:
            app.state.db = database
        else:
            app.state.db = db.connect()

        # Off unless MARKET_SYNC_ENABLED is set: only one process may own the
        # cache refresh. See api/scheduler.py.
        app.state.market_sync = None
        if database is None and market_sync_enabled():
            app.state.market_sync = MarketSyncScheduler(app.state.db)
            app.state.market_sync.start()

        yield

        if app.state.market_sync is not None:
            app.state.market_sync.stop()
        if database is None:
            db.close()

    app = FastAPI(lifespan=lifespan)

    # Per-process counters, like express-rate-limit's default in-memory store.
    # Built with the app, so tests get a fresh limiter for each app instance.
    app.add_middleware(AuthRateLimitMiddleware)

    @app.exception_handler(StarletteHTTPException)
    async def error_envelope(request: Request, exc: StarletteHTTPException):
        # Express always answers with { message }, never FastAPI's { detail }.
        if exc.status_code == 404 and exc.detail == "Not Found":
            return JSONResponse(status_code=404, content={"message": "Route not found"})
        # Exceptions may carry headers (the rate limiter's RateLimit-* set).
        return JSONResponse(
            status_code=exc.status_code,
            content={"message": exc.detail},
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # Reached when a body is not the expected shape (e.g. an array where an
        # object is required). Express's parser also answers 400, so keep the
        # generic Express-shaped body rather than FastAPI's `detail` list.
        return JSONResponse(status_code=400, content={"message": "Invalid request"})

    @app.exception_handler(Exception)
    async def unhandled_error(request: Request, exc: Exception):
        # Match the Express central handler: log, then hide details.
        logger.exception("Unhandled error on %s", request.url.path)
        return JSONResponse(status_code=500, content={"message": "Something went wrong"})

    app.include_router(health.router)
    app.include_router(holdings.router)
    app.include_router(orders.router)
    app.include_router(watchlist.router)
    app.include_router(positions.router)
    app.include_router(funds.router)
    app.include_router(portfolio.router)
    app.include_router(instruments.router)
    app.include_router(market.router)
    app.include_router(auth.router)
    return app


app = create_app()

