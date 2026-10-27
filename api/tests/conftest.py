"""Shared test fixtures.

PostgreSQL tests use TEST_DATABASE_URL and are skipped when it is not set. The
FastAPI runtime has no MongoDB dependency.
"""

import os
import secrets
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
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
from api.postgres.models import (  # noqa: E402
    Fund,
    Holding,
    Instrument,
    LatestQuote,
    Order,
    Position,
    Transaction,
    User,
)
from api.postgres.session import get_session  # noqa: E402

TEST_SECRET = "test-secret-not-a-real-key"
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "").strip()


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)


@pytest.fixture
def client():
    # raise_server_exceptions=False lets the 500 handler run like production.
    with TestClient(create_app(), raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture
def make_token():
    def _make_token(user_id, secret=TEST_SECRET, expires_in=7 * 24 * 60 * 60):
        payload = {"id": str(user_id), "exp": int(datetime.now(timezone.utc).timestamp()) + expires_in}
        return jwt.encode(payload, secret, algorithm="HS256")

    return _make_token


@pytest.fixture
def user_id():
    return secrets.token_hex(12)


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


# --------------------------------------------------------------------------
# PostgreSQL trading-book fixtures (Phase 3C2)
# --------------------------------------------------------------------------

BOOK_CREATED = datetime(2026, 9, 1, 4, 15, 30, 123000, tzinfo=timezone.utc)


@pytest.fixture
def book_session_factory(postgres_session_factory, postgres_schema):
    """The shared PostgreSQL factory with an empty users/book for one test."""
    with postgres_schema.begin() as connection:
        connection.execute(text("TRUNCATE TABLE users CASCADE"))
    return postgres_session_factory


@pytest.fixture
def book_client(book_session_factory):
    """The API with PostgreSQL sessions; no MongoDB is involved."""
    app = create_app()

    def override_get_session():
        with book_session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def book_user_factory(book_session_factory):
    """Insert a 24-hex PostgreSQL user the book rows can reference."""

    def _make(user_id=None, created_at=BOOK_CREATED):
        user = User(
            id=user_id or secrets.token_hex(12),
            username=f"book-{secrets.token_hex(6)}",
            email=f"{secrets.token_hex(8)}@example.com",
            password_hash="not-used-in-book-tests",
            created_at=created_at,
            updated_at=created_at,
            version=0,
        )
        with book_session_factory() as session:
            session.add(user)
            session.commit()
        return user.id

    return _make


@pytest.fixture
def book_user(book_user_factory):
    """A 24-hex PostgreSQL user the book rows can reference."""
    return book_user_factory()


@pytest.fixture
def book_funds_factory(book_session_factory):
    def _make(user_id, available=0):
        fund = Fund(
            id=secrets.token_hex(12),
            user_id=user_id,
            available=Decimal(str(available)),
            created_at=BOOK_CREATED,
            updated_at=BOOK_CREATED,
            version=0,
        )
        with book_session_factory() as session:
            session.add(fund)
            session.commit()
        return fund

    return _make


@pytest.fixture
def book_holding_factory(book_session_factory):
    def _make(
        user_id,
        symbol="RELIANCE",
        name="Reliance Industries",
        exchange="NSE",
        qty=10,
        avg_price="2400.5",
        created_at=BOOK_CREATED,
    ):
        holding = Holding(
            id=secrets.token_hex(12),
            user_id=user_id,
            symbol=symbol,
            name=name,
            exchange=exchange,
            qty=qty,
            avg_price=Decimal(str(avg_price)),
            created_at=created_at,
            updated_at=created_at,
            version=0,
        )
        with book_session_factory() as session:
            session.add(holding)
            session.commit()
        return holding

    return _make


@pytest.fixture
def book_position_factory(book_session_factory):
    def _make(
        user_id,
        symbol="INFY",
        name="Infosys",
        exchange="NSE",
        side="LONG",
        product="MIS",
        qty=5,
        entry="1500.0",
        created_at=BOOK_CREATED,
    ):
        position = Position(
            id=secrets.token_hex(12),
            user_id=user_id,
            symbol=symbol,
            name=name,
            exchange=exchange,
            side=side,
            product=product,
            qty=qty,
            entry=Decimal(str(entry)),
            created_at=created_at,
            updated_at=created_at,
            version=0,
        )
        with book_session_factory() as session:
            session.add(position)
            session.commit()
        return position

    return _make


@pytest.fixture
def book_order_factory(book_session_factory):
    def _make(user_id, **overrides):
        values = {
            "id": secrets.token_hex(12),
            "user_id": user_id,
            "symbol": "INFY",
            "name": "Infosys",
            "exchange": "NSE",
            "side": "BUY",
            "type": "LIMIT",
            "product": "CNC",
            "qty": 5,
            "filled": 0,
            "price": Decimal("1500.0000"),
            "trigger_price": Decimal("0.0000"),
            "sl_trigger": Decimal("0.0000"),
            "tp_price": Decimal("0.0000"),
            "group_id": "",
            "is_exit": False,
            "status": "OPEN",
            "created_at": BOOK_CREATED,
            "updated_at": BOOK_CREATED,
            "version": 0,
        }
        for key, value in overrides.items():
            if key in ("price", "trigger_price", "sl_trigger", "tp_price"):
                value = Decimal(str(value))
            values[key] = value
        order = Order(**values)
        with book_session_factory() as session:
            session.add(order)
            session.commit()
        return order

    return _make


@pytest.fixture
def book_transaction_factory(book_session_factory):
    def _make(user_id, kind="DEPOSIT", amount="100", created_at=BOOK_CREATED):
        transaction = Transaction(
            id=secrets.token_hex(12),
            user_id=user_id,
            kind=kind,
            method="Bank transfer",
            amount=Decimal(str(amount)),
            symbol="",
            status="COMPLETED",
            created_at=created_at,
            updated_at=created_at,
            version=0,
        )
        with book_session_factory() as session:
            session.add(transaction)
            session.commit()
        return transaction

    return _make
