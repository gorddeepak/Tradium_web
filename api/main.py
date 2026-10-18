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
from .routes import funds, health, holdings, instruments, market, orders, portfolio, positions, watchlist

logger = logging.getLogger(__name__)


def create_app(database=None) -> FastAPI:
    """Build the app. Tests pass a fake database to skip the real connection."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if database is not None:
            app.state.db = database
        else:
            app.state.db = db.connect()
        yield
        if database is None:
            db.close()

    app = FastAPI(lifespan=lifespan)

    @app.exception_handler(StarletteHTTPException)
    async def error_envelope(request: Request, exc: StarletteHTTPException):
        # Express always answers with { message }, never FastAPI's { detail }.
        if exc.status_code == 404 and exc.detail == "Not Found":
            return JSONResponse(status_code=404, content={"message": "Route not found"})
        return JSONResponse(status_code=exc.status_code, content={"message": exc.detail})

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # Phase 1a has no request bodies to validate; keep the Express shape
        # until real validation rules are ported.
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
    return app


app = create_app()

