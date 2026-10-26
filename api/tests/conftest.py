"""Shared test fixtures.

The fast suite uses mongomock (in memory), so it never contacts a real
database. A separate optional suite can run against a scratch MongoDB
when TEST_MONGO_URL is set; see test_mongo_integration.py.
"""

import os
import secrets
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import mongomock
import pytest
from alembic import command
from alembic.config import Config
from bson import ObjectId
from fastapi.testclient import TestClient
import jwt
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

# Make the repository root importable so `api.main` resolves.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.main import create_app  # noqa: E402
from api.postgres.base import Base  # noqa: E402
from api.postgres.models import Instrument, LatestQuote  # noqa: E402

TEST_SECRET = "test-secret-not-a-real-key"
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "").strip()


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)


@pytest.fixture
def database():
    return mongomock.MongoClient()["tradium_test"]


@pytest.fixture
def client(database):
    # raise_server_exceptions=False lets the 500 handler run like production.
    with TestClient(create_app(database=database), raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture
def make_token():
    def _make_token(user_id, secret=TEST_SECRET, expires_in=7 * 24 * 60 * 60):
        payload = {"id": str(user_id), "exp": int(datetime.now(timezone.utc).timestamp()) + expires_in}
        return jwt.encode(payload, secret, algorithm="HS256")

    return _make_token


@pytest.fixture
def user_id():
    return ObjectId()


@pytest.fixture
def other_user_id():
    return ObjectId()


@pytest.fixture
def holdings_factory():
    """Build a holdings document shaped like the Mongoose model."""
    created = datetime(2026, 9, 1, 4, 15, 30, 123456, tzinfo=timezone.utc)

    def _make(user, symbol="RELIANCE", qty=10, avg_price=2400.5, **overrides):
        document = {
            "_id": ObjectId(),
            "user": user,
            "symbol": symbol,
            "name": "Reliance Industries",
            "exchange": "NSE",
            "qty": qty,
            "avgPrice": avg_price,
            "ltp": 2500.0,
            "dayChangePct": 1.25,
            "sector": "Energy",
            "createdAt": created,
            "updatedAt": created,
            "__v": 0,
        }
        document.update(overrides)
        return document

    return _make


@pytest.fixture
def orders_factory():
    """Build an order document shaped like the Mongoose model."""
    created = datetime(2026, 9, 1, 4, 15, 30, 123456, tzinfo=timezone.utc)

    def _make(user, **overrides):
        document = {
            "_id": ObjectId(),
            "user": user,
            "symbol": "INFY",
            "name": "Infosys",
            "exchange": "NSE",
            "side": "BUY",
            "type": "LIMIT",
            "product": "CNC",
            "qty": 5,
            "filled": 0,
            "price": 1500.0,
            "triggerPrice": 0,
            "slTrigger": 0,
            "tpPrice": 0,
            "groupId": "",
            "isExit": False,
            "status": "OPEN",
            "createdAt": created,
            "updatedAt": created,
            "__v": 0,
        }
        document.update(overrides)
        return document

    return _make


@pytest.fixture
def watchlist_factory():
    """Build a watchlist document shaped like the Mongoose model."""
    created = datetime(2026, 9, 1, 4, 15, 30, 123456, tzinfo=timezone.utc)

    def _make(user, **overrides):
        document = {
            "_id": ObjectId(),
            "user": user,
            "symbol": "INFY",
            "name": "Infosys",
            "exchange": "NSE",
            "ltp": 1500.0,
            "dayChangePct": 0.75,
            "createdAt": created,
            "updatedAt": created,
            "__v": 0,
        }
        document.update(overrides)
        return document

    return _make


@pytest.fixture
def positions_factory():
    """Build a position document shaped like the Mongoose model."""
    created = datetime(2026, 9, 1, 4, 15, 30, 123456, tzinfo=timezone.utc)

    def _make(user, **overrides):
        document = {
            "_id": ObjectId(),
            "user": user,
            "symbol": "INFY",
            "name": "Infosys",
            "exchange": "NSE",
            "side": "LONG",
            "product": "MIS",
            "qty": 5,
            "entry": 1500.0,
            "ltp": 1520.0,
            "createdAt": created,
            "updatedAt": created,
            "__v": 0,
        }
        document.update(overrides)
        return document

    return _make


@pytest.fixture
def market_quote_factory():
    """Build a market-quote cache document shaped like the Mongoose model."""
    created = datetime(2026, 9, 1, 4, 15, 30, 123456, tzinfo=timezone.utc)

    def _make(symbol="INFY", **overrides):
        document = {
            "_id": ObjectId(),
            "symbol": symbol,
            "name": "Infosys",
            "kind": "stock",
            "ltp": 1500.0,
            "dayChange": 12.0,
            "dayChangePct": 0.8,
            "prevClose": 1488.0,
            "volume": 10000,
            "marketCap": 0,
            "sector": "",
            "createdAt": created,
            "updatedAt": created,
            "__v": 0,
        }
        document.update(overrides)
        return document

    return _make


@pytest.fixture
def funds_factory():
    """Build a funds document shaped like the Mongoose model."""
    created = datetime(2026, 9, 1, 4, 15, 30, 123456, tzinfo=timezone.utc)

    def _make(user, available=0, **overrides):
        document = {
            "_id": ObjectId(),
            "user": user,
            "available": available,
            "createdAt": created,
            "updatedAt": created,
            "__v": 0,
        }
        document.update(overrides)
        return document

    return _make


# --------------------------------------------------------------------------
# PostgreSQL fixtures for market-data tests (Phase 3B2)
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def postgres_url():
    """Validate the disposable PostgreSQL URL, or skip this module."""
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is not set; PostgreSQL tests skipped")

    url = make_url(TEST_DATABASE_URL)
    if not url.drivername.startswith("postgresql"):
        pytest.fail("TEST_DATABASE_URL must use PostgreSQL; SQLite is not a substitute")
    if not (url.database or "").endswith("_test"):
        pytest.fail("TEST_DATABASE_URL must name a disposable database ending in _test")
    return TEST_DATABASE_URL


@pytest.fixture(scope="module")
def postgres_engine(postgres_url):
    engine = create_engine(postgres_url)
    Base.metadata.drop_all(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def postgres_schema(postgres_engine, postgres_url):
    config = Config(os.path.join(ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(ROOT, "api", "migrations"))
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv("DIRECT_DATABASE_URL", postgres_url)
        command.upgrade(config, "head")
    return postgres_engine


@pytest.fixture
def postgres_session_factory(postgres_schema):
    """An empty instruments/quotes pair for one test."""
    with postgres_schema.begin() as connection:
        connection.execute(text("TRUNCATE TABLE instruments CASCADE"))
    return sessionmaker(bind=postgres_schema, expire_on_commit=False)


@pytest.fixture
def market_instrument_factory(postgres_session_factory):
    """Insert one instrument and (by default) its latest quote."""
    created = datetime(2026, 9, 1, 4, 15, 30, 123000, tzinfo=timezone.utc)

    def _make(
        symbol="INFY",
        name="Infosys",
        kind="stock",
        sector="",
        in_market_universe=True,
        quote=True,
        ltp=1500.0,
        day_change=12.0,
        day_change_pct=0.8,
        prev_close=1488.0,
        volume=10000,
        market_cap=0,
        updated_at=created,
        source_time=None,
        created_at=created,
    ):
        instrument_id = secrets.token_hex(12)
        with postgres_session_factory() as session:
            session.add(
                Instrument(
                    id=instrument_id,
                    symbol=symbol,
                    name=name,
                    kind=kind,
                    sector=sector,
                    in_market_universe=in_market_universe,
                    created_at=created_at,
                    updated_at=created_at,
                    version=0,
                )
            )
            if quote:
                session.add(
                    LatestQuote(
                        instrument_id=instrument_id,
                        ltp=Decimal(str(ltp)),
                        day_change=Decimal(str(day_change)),
                        day_change_pct=Decimal(str(day_change_pct)),
                        prev_close=Decimal(str(prev_close)),
                        volume=volume,
                        market_cap=Decimal(str(market_cap)),
                        updated_at=updated_at,
                        source_time=source_time,
                    )
                )
            session.commit()
        return instrument_id

    return _make
