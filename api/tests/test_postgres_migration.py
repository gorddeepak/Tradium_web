"""PostgreSQL migration tests.

These run only when TEST_DATABASE_URL points at a disposable PostgreSQL
database whose name ends in "_test". If it is unset the module is skipped;
there is no SQLite fallback. The fixture drops the known tables, then Alembic
creates the schema from revision 0001.
"""

import os
from datetime import datetime, timezone

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from api.postgres.base import Base
from api.postgres.models import (
    Holding,
    Instrument,
    LatestQuote,
    Order,
    User,
)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "").strip()

EXPECTED_TABLES = {
    "users",
    "funds",
    "holdings",
    "positions",
    "orders",
    "transactions",
    "watchlists",
    "instruments",
    "latest_quotes",
    "portfolio_snapshots",
    "alembic_version",
}

USER_ID = "0123456789abcdef01234567"
OTHER_USER_ID = "1123456789abcdef01234567"
INSTRUMENT_ID = "89abcdef0123456789abcdef"
NOW = datetime(2026, 10, 25, 12, 0, 0, 123000, tzinfo=timezone.utc)

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL is not set; PostgreSQL migration tests skipped",
)


@pytest.fixture(scope="module")
def database_url():
    url = make_url(TEST_DATABASE_URL)
    if not url.drivername.startswith("postgresql"):
        pytest.fail(
            "TEST_DATABASE_URL must use PostgreSQL; SQLite is not a substitute"
        )
    if not (url.database or "").endswith("_test"):
        pytest.fail(
            "TEST_DATABASE_URL must name a disposable database ending in _test"
        )
    return TEST_DATABASE_URL


@pytest.fixture(scope="module")
def alembic_config(database_url):
    config = Config(os.path.join(ROOT, "alembic.ini"))
    config.set_main_option(
        "script_location", os.path.join(ROOT, "api", "migrations")
    )

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv("DIRECT_DATABASE_URL", database_url)
        yield config


@pytest.fixture(scope="module")
def engine(database_url):
    engine = create_engine(database_url)

    # Start from an empty database. This is a test-only drop; Alembic still
    # owns every CREATE in the upgrade.
    Base.metadata.drop_all(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))

    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def migrated_database(engine, alembic_config):
    command.upgrade(alembic_config, "head")
    return engine


def _schema_snapshot(engine):
    with engine.connect() as connection:
        tables = {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname = 'public'"
                )
            )
        }
        indexes = {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE schemaname = 'public'"
                )
            )
        }
        constraints = {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT conname FROM pg_constraint "
                    "WHERE connamespace = 'public'::regnamespace"
                )
            )
        }
    return tables, indexes, constraints


def _column_rows(engine):
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT table_name, column_name, data_type,
                       character_maximum_length, numeric_precision,
                       numeric_scale, datetime_precision, is_nullable,
                       column_default
                FROM information_schema.columns
                WHERE table_schema = 'public'
                """
            )
        ).mappings()
        return {(row["table_name"], row["column_name"]): row for row in rows}


def _assert_rejected(engine, statement):
    with engine.connect() as connection:
        transaction = connection.begin()
        with pytest.raises(IntegrityError):
            connection.execute(statement)
        transaction.rollback()


def _assert_rejected_with_parents(engine, statement):
    """Reject a child row after satisfying its foreign keys."""
    with engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(
            User.__table__.insert().values(
                id=USER_ID,
                username="parent",
                email="parent@example.com",
                password_hash="$2b$12$not-a-real-hash",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        connection.execute(
            Instrument.__table__.insert().values(
                id=INSTRUMENT_ID,
                symbol="INFY",
                name="Infosys",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        with pytest.raises(IntegrityError):
            connection.execute(statement)
        transaction.rollback()


def test_upgrade_creates_every_table(migrated_database):
    assert set(inspect(migrated_database).get_table_names()) == EXPECTED_TABLES


def test_upgrade_is_repeatable(migrated_database, alembic_config):
    before = _schema_snapshot(migrated_database)

    command.upgrade(alembic_config, "head")

    assert _schema_snapshot(migrated_database) == before
    with migrated_database.connect() as connection:
        version_count = connection.scalar(
            text("SELECT count(*) FROM alembic_version")
        )
        versions = connection.scalar(text("SELECT version_num FROM alembic_version"))
    assert version_count == 1
    assert versions == "0001"


def test_primary_keys_foreign_keys_and_uniques(migrated_database):
    inspector = inspect(migrated_database)

    primary_keys = {
        table: inspector.get_pk_constraint(table)
        for table in EXPECTED_TABLES - {"alembic_version"}
    }
    assert primary_keys["latest_quotes"]["constrained_columns"] == [
        "instrument_id"
    ]
    assert primary_keys["latest_quotes"]["name"] == "pk_latest_quotes"
    assert primary_keys["users"]["constrained_columns"] == ["id"]
    assert primary_keys["users"]["name"] == "pk_users"

    latest_quote_fk = inspector.get_foreign_keys("latest_quotes")[0]
    assert latest_quote_fk["name"] == "fk_latest_quotes_instrument_id_instruments"
    assert latest_quote_fk["referred_table"] == "instruments"
    assert latest_quote_fk["options"]["ondelete"] == "CASCADE"

    holdings_fk = inspector.get_foreign_keys("holdings")[0]
    assert holdings_fk["name"] == "fk_holdings_user_id_users"
    assert holdings_fk["referred_table"] == "users"
    assert holdings_fk["options"]["ondelete"] == "RESTRICT"

    uniques = {
        table: {
            unique["name"]: unique["column_names"]
            for unique in inspector.get_unique_constraints(table)
        }
        for table in EXPECTED_TABLES - {"alembic_version"}
    }
    assert uniques["funds"]["uq_funds_user"] == ["user_id"]
    assert uniques["holdings"]["uq_holdings_user_symbol_exchange"] == [
        "user_id",
        "symbol",
        "exchange",
    ]
    assert uniques["positions"][
        "uq_positions_user_symbol_exchange_side_product"
    ] == ["user_id", "symbol", "exchange", "side", "product"]
    assert uniques["watchlists"]["uq_watchlists_user_symbol"] == [
        "user_id",
        "symbol",
    ]
    assert uniques["instruments"]["uq_instruments_symbol"] == ["symbol"]
    assert uniques["portfolio_snapshots"][
        "uq_portfolio_snapshots_user_date"
    ] == ["user_id", "snapshot_date"]


def test_column_types_match_the_design(migrated_database):
    columns = _column_rows(migrated_database)

    for table, column_name in [
        ("users", "id"),
        ("funds", "user_id"),
        ("latest_quotes", "instrument_id"),
    ]:
        row = columns[(table, column_name)]
        assert row["data_type"] == "character varying"
        assert row["character_maximum_length"] == 24

    for table, column_name, precision, scale in [
        ("funds", "available", 20, 2),
        ("holdings", "avg_price", 20, 6),
        ("positions", "entry", 20, 6),
        ("orders", "price", 20, 4),
        ("transactions", "amount", 20, 2),
        ("latest_quotes", "day_change_pct", 12, 6),
        ("latest_quotes", "market_cap", 24, 2),
        ("portfolio_snapshots", "value", 20, 4),
    ]:
        row = columns[(table, column_name)]
        assert row["data_type"] == "numeric"
        assert row["numeric_precision"] == precision
        assert row["numeric_scale"] == scale

    assert columns[("latest_quotes", "volume")]["data_type"] == "bigint"
    assert (
        columns[("portfolio_snapshots", "snapshot_date")]["data_type"]
        == "date"
    )

    for table in EXPECTED_TABLES - {"alembic_version"}:
        for column_name in ("created_at", "updated_at", "source_time"):
            if (table, column_name) not in columns:
                continue
            row = columns[(table, column_name)]
            assert row["data_type"] == "timestamp with time zone"
            assert row["datetime_precision"] == 3

    assert columns[("latest_quotes", "source_time")]["is_nullable"] == "YES"
    assert columns[("latest_quotes", "updated_at")]["is_nullable"] == "NO"
    assert "created_at" not in {
        column for table, column in columns if table == "latest_quotes"
    }
    assert "version" not in {
        column for table, column in columns if table == "latest_quotes"
    }


def test_check_constraints_exist(migrated_database):
    inspector = inspect(migrated_database)
    checks = {
        table: {
            check["name"]
            for check in inspector.get_check_constraints(table)
        }
        for table in EXPECTED_TABLES - {"alembic_version"}
    }

    assert "ck_users_id_hex" in checks["users"]
    assert "ck_holdings_exchange_nse" in checks["holdings"]
    assert "ck_positions_side" in checks["positions"]
    assert "ck_orders_filled_range" in checks["orders"]
    assert "ck_orders_status" in checks["orders"]
    assert "ck_transactions_kind" in checks["transactions"]
    assert "ck_watchlists_exchange_nse" in checks["watchlists"]
    assert "ck_instruments_kind" in checks["instruments"]
    assert "ck_latest_quotes_instrument_id_hex" in checks["latest_quotes"]
    assert "ck_portfolio_snapshots_user_id_hex" in checks["portfolio_snapshots"]


def test_indexes_include_partial_and_descending_definitions(migrated_database):
    inspector = inspect(migrated_database)
    order_indexes = {
        index["name"] for index in inspector.get_indexes("orders")
    }
    assert order_indexes == {
        "ix_orders_user_created",
        "ix_orders_user_status",
        "ix_orders_open",
        "ix_orders_group_open",
        "ix_orders_exit_lookup",
    }

    with migrated_database.connect() as connection:
        definitions = dict(
            connection.execute(
                text(
                    "SELECT indexname, indexdef FROM pg_indexes "
                    "WHERE schemaname = 'public'"
                )
            ).all()
        )

    assert "created_at DESC" in definitions["ix_orders_user_created"]
    assert "id DESC" in definitions["ix_orders_user_created"]
    assert "created_at DESC" in definitions["ix_transactions_user_created"]
    assert "WHERE" in definitions["ix_orders_open"]
    assert "status = 'OPEN'" in definitions["ix_orders_open"]
    assert "WHERE" in definitions["ix_orders_group_open"]
    assert "is_exit" in definitions["ix_orders_group_open"]
    assert "WHERE" in definitions["ix_instruments_sector_pending"]
    assert "sector = ''" in definitions["ix_instruments_sector_pending"]


def test_constraints_reject_invalid_rows(migrated_database):
    user_values = dict(
        id=USER_ID,
        username="phase3a",
        email="phase3a@example.com",
        password_hash="$2b$12$not-a-real-hash",
        created_at=NOW,
        updated_at=NOW,
    )

    _assert_rejected(
        migrated_database,
        User.__table__.insert().values(**{**user_values, "id": "not-an-id"}),
    )
    _assert_rejected(
        migrated_database,
        User.__table__.insert().values(**{**user_values, "username": ""}),
    )

    with migrated_database.connect() as connection:
        transaction = connection.begin()
        connection.execute(User.__table__.insert().values(**user_values))
        connection.execute(
            Instrument.__table__.insert().values(
                id=INSTRUMENT_ID,
                symbol="INFY",
                name="Infosys",
                created_at=NOW,
                updated_at=NOW,
            )
        )

        with pytest.raises(IntegrityError):
            connection.execute(
                Holding.__table__.insert().values(
                    id=OTHER_USER_ID,
                    user_id=USER_ID,
                    symbol="INFY",
                    name="Infosys",
                    exchange="BSE",
                    qty=1,
                    avg_price=1500,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
        transaction.rollback()

    _assert_rejected_with_parents(
        migrated_database,
        Order.__table__.insert().values(
            id=OTHER_USER_ID,
            user_id=USER_ID,
            symbol="INFY",
            name="Infosys",
            side="BUY",
            type="LIMIT",
            product="CNC",
            qty=10,
            filled=11,
            price=1500,
            created_at=NOW,
            updated_at=NOW,
        ),
    )
    _assert_rejected_with_parents(
        migrated_database,
        Order.__table__.insert().values(
            id=OTHER_USER_ID,
            user_id=USER_ID,
            symbol="INFY",
            name="Infosys",
            side="BUY",
            type="LIMIT",
            product="CNC",
            qty=10,
            filled=0,
            price=1500,
            status="FILLED",
            created_at=NOW,
            updated_at=NOW,
        ),
    )


def test_nullable_source_time_and_quote_cascade(migrated_database):
    with migrated_database.connect() as connection:
        transaction = connection.begin()
        connection.execute(
            Instrument.__table__.insert().values(
                id=INSTRUMENT_ID,
                symbol="INFY",
                name="Infosys",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        connection.execute(
            LatestQuote.__table__.insert().values(
                instrument_id=INSTRUMENT_ID,
                ltp=1500,
                day_change=12,
                day_change_pct=0.8,
                prev_close=1488,
                volume=10000,
                market_cap=0,
                updated_at=NOW,
                source_time=None,
            )
        )
        assert connection.scalar(
            select(func.count()).select_from(LatestQuote.__table__)
        ) == 1

        connection.execute(
            delete(Instrument.__table__).where(
                Instrument.__table__.c.id == INSTRUMENT_ID
            )
        )
        assert connection.scalar(
            select(func.count()).select_from(LatestQuote.__table__)
        ) == 0
        transaction.rollback()
