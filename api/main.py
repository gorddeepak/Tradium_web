"""FastAPI application entry point.

Run locally:
    uvicorn api.main:app --reload --port 8000
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import db
from .config import get_cors_origins, serve_static_enabled
from .rate_limit import AuthRateLimitMiddleware
from .routes import (
    assistant,
    auth,
    funds,
    health,
    holdings,
    instruments,
    market,
    orders,
    portfolio,
    positions,
    watchlist,
)
from .scheduler import (
    MarketSyncScheduler,
    PortfolioSnapshotScheduler,
    PriceSyncScheduler,
    market_sync_enabled,
    trading_jobs_enabled,
)

logger = logging.getLogger(__name__)

# The Vite build output. `npm run build` writes it here; it is gitignored.
DIST_DIR = Path(__file__).resolve().parents[1] / "dist"


def _serve_frontend(app: FastAPI) -> None:
    """Serve the Vite build with an SPA fallback, like Express in production.

    API routers are registered before this, so ``/api`` always reaches them and
    an unknown ``/api`` path gets the JSON 404 instead of index.html. Enabled by
    ``SERVE_STATIC`` or ``NODE_ENV=production`` (see ``serve_static_enabled``).
    """
    if not serve_static_enabled():
        return

    index_file = DIST_DIR / "index.html"
    if not index_file.is_file():
        # The API is still usable; the deployment is missing `npm run build`.
        logger.warning("Static serving is on but %s is missing; run `npm run build`", index_file)
        return

    assets_dir = DIST_DIR / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        # Reached only when no route or mount above matched.
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")

        # Any real file in dist/ (favicon.svg, icons) is returned as-is; a path
        # that is not a file is a client-side route, so send the app shell.
        candidate = (DIST_DIR / full_path).resolve()
        if full_path and candidate.is_file() and DIST_DIR in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index_file)


def create_app(database=None) -> FastAPI:
    """Build the app. Tests pass a fake database to skip the real connection."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if database is not None:
            app.state.db = database
        else:
            app.state.db = db.connect()

        # Off unless the matching switch is set: only one process may own each
        # job. See api/scheduler.py.
        app.state.market_sync = None
        app.state.price_sync = None
        app.state.portfolio_snapshot = None
        if database is None:
            if market_sync_enabled():
                app.state.market_sync = MarketSyncScheduler(app.state.db)
                app.state.market_sync.start()
            if trading_jobs_enabled():
                # Price sync fills orders and moves funds, so it shares one
                # owner switch with the daily snapshot.
                app.state.price_sync = PriceSyncScheduler(app.state.db)
                app.state.price_sync.start()
                app.state.portfolio_snapshot = PortfolioSnapshotScheduler()
                app.state.portfolio_snapshot.start()

        yield

        for name in ("market_sync", "price_sync", "portfolio_snapshot"):
            job = getattr(app.state, name)
            if job is not None:
                job.stop()
        if database is None:
            db.close()

    app = FastAPI(lifespan=lifespan)

    # Per-process counters, like express-rate-limit's default in-memory store.
    # Built with the app, so tests get a fresh limiter for each app instance.
    app.add_middleware(AuthRateLimitMiddleware)

    # Read at app-build time so a deployment's CORS_ORIGINS applies at startup.
    # Credentials are required because authentication is a cookie, and an
    # explicit origin list is required when credentials are enabled.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

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
    app.include_router(assistant.router)

    # Registered last so the SPA fallback never shadows an API route.
    _serve_frontend(app)
    return app


app = create_app()

