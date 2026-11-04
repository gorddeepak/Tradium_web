"""Metadata tests for the approved PostgreSQL schema.

These run without a database. They pin the column types, IDs, constraints, and
indexes so the models cannot drift from the Alembic migrations.
"""

from decimal import Decimal

import pytest
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from api.postgres.base import ID_PATTERN, Base
from api.postgres import models  # noqa: F401  (register tables)

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
}

NUMERIC_COLUMNS = [
    ("funds", "available", 20, 2),
    ("holdings", "avg_price", 20, 6),
    ("positions", "entry", 20, 6),
    ("orders", "price", 20, 4),
    ("orders", "trigger_price", 20, 4),
    ("orders", "sl_trigger", 20, 4),
    ("orders", "tp_price", 20, 4),
    ("transactions", "amount", 20, 2),
    ("latest_quotes", "ltp", 20, 4),
    ("latest_quotes", "day_change", 20, 4),
    ("latest_quotes", "day_change_pct", 12, 6),
    ("latest_quotes", "prev_close", 20, 4),
    ("latest_quotes", "market_cap", 24, 2),
    ("portfolio_snapshots", "value", 20, 4),
    ("portfolio_snapshots", "invested", 20, 4),
    ("portfolio_snapshots", "mis_invested", 20, 4),
    ("portfolio_snapshots", "mis_value", 20, 4),
]

EXPECTED_UNIQUES = {
    "users": {"uq_users_username", "uq_users_email"},
    "funds": {"uq_funds_user"},
    "holdings": {"uq_holdings_user_symbol_exchange"},
    "positions": {"uq_positions_user_symbol_exchange_side_product"},
    "watchlists": {"uq_watchlists_user_symbol"},
    "instruments": {"uq_instruments_symbol"},
    "portfolio_snapshots": {"uq_portfolio_snapshots_user_date"},
}

EXPECTED_INDEXES = {
    "holdings": {"ix_holdings_user_created"},
    "positions": {"ix_positions_user_product", "ix_positions_user_created"},
    "orders": {
        "ix_orders_user_created",
        "ix_orders_user_status",
        "ix_orders_open",
        "ix_orders_group_open",
        "ix_orders_exit_lookup",
    },
    "transactions": {"ix_transactions_user_created", "ix_transactions_user_kind"},
    "watchlists": {"ix_watchlists_user_created"},
    "instruments": {"ix_instruments_sector_pending"},
}


def _checks(table_name: str) -> dict[str, str]:
    table = Base.metadata.tables[table_name]
    return {
        constraint.name: str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }


def test_all_approved_tables_are_declared():
    assert set(Base.metadata.tables) == EXPECTED_TABLES


@pytest.mark.parametrize("table_name", sorted(EXPECTED_TABLES))
def test_id_columns_are_varchar_24_with_hex_check(table_name):
    table = Base.metadata.tables[table_name]
    checks = _checks(table_name)

    for column_name in ("id", "user_id", "instrument_id"):
        if column_name not in table.c:
            continue

        column = table.c[column_name]
        assert isinstance(column.type, String)
        assert column.type.length == 24
        assert column.nullable is False

        expected_check = f"{column_name} ~ '{ID_PATTERN}'"
        assert expected_check in checks.values()


def test_common_columns_are_application_supplied():
    for table_name in EXPECTED_TABLES - {"latest_quotes"}:
        table = Base.metadata.tables[table_name]
        assert {"id", "created_at", "updated_at", "version"} <= set(table.c.keys())
        assert table.c.id.server_default is None
        assert table.c.created_at.server_default is None
        assert table.c.updated_at.server_default is None
        assert table.c.version.server_default is not None


def test_latest_quotes_has_no_created_at_or_version():
    table = Base.metadata.tables["latest_quotes"]
    assert "created_at" not in table.c
    assert "version" not in table.c
    assert table.c.instrument_id.primary_key
    assert table.c.updated_at.nullable is False
    assert table.c.source_time.nullable is True


def test_latest_quotes_cascades_from_instruments():
    table = Base.metadata.tables["latest_quotes"]
    foreign_key = next(iter(table.c.instrument_id.foreign_keys))
    assert foreign_key.target_fullname == "instruments.id"
    assert foreign_key.ondelete == "CASCADE"

    other_tables = EXPECTED_TABLES - {"latest_quotes", "instruments"}
    for table_name in other_tables:
        for foreign_key in Base.metadata.tables[table_name].foreign_keys:
            assert foreign_key.target_fullname == "users.id"
            assert foreign_key.ondelete == "RESTRICT"


@pytest.mark.parametrize(
    "table_name,column_name,precision,scale", NUMERIC_COLUMNS
)
def test_numeric_precision_and_scale(
    table_name, column_name, precision, scale
):
    column = Base.metadata.tables[table_name].c[column_name]
    assert isinstance(column.type, Numeric)
    assert column.type.precision == precision
    assert column.type.scale == scale
    assert column.nullable is False


def test_non_numeric_column_types():
    assert isinstance(
        Base.metadata.tables["latest_quotes"].c.volume.type, BigInteger
    )
    assert isinstance(
        Base.metadata.tables["portfolio_snapshots"].c.snapshot_date.type, Date
    )
    assert isinstance(
        Base.metadata.tables["orders"].c.is_exit.type, Boolean
    )
    assert isinstance(
        Base.metadata.tables["users"].c.password_hash.type, Text
    )
    assert isinstance(
        Base.metadata.tables["orders"].c.type.type, Text
    )


def test_timestamps_are_timestamptz_at_millisecond_precision():
    for table_name in EXPECTED_TABLES:
        table = Base.metadata.tables[table_name]
        for column_name in ("created_at", "updated_at", "source_time"):
            if column_name not in table.c:
                continue
            column_type = table.c[column_name].type
            assert isinstance(column_type, postgresql.TIMESTAMP)
            assert column_type.timezone is True
            assert column_type.precision == 3


def test_unique_constraints_match_the_design():
    for table_name, expected_names in EXPECTED_UNIQUES.items():
        actual = {
            constraint.name
            for constraint in Base.metadata.tables[table_name].constraints
            if isinstance(constraint, UniqueConstraint)
        }
        assert actual == expected_names


def test_indexes_match_the_design():
    for table_name, expected_names in EXPECTED_INDEXES.items():
        actual = {index.name for index in Base.metadata.tables[table_name].indexes}
        assert actual == expected_names


def test_partial_indexes_have_postgresql_predicates():
    predicates = {
        index.name: str(index.dialect_options["postgresql"]["where"])
        for table in Base.metadata.tables.values()
        for index in table.indexes
        if index.dialect_options["postgresql"].get("where") is not None
    }
    assert predicates == {
        "ix_orders_open": "status = 'OPEN'",
        "ix_orders_group_open": "is_exit AND status = 'OPEN'",
        "ix_instruments_sector_pending": "sector = ''",
    }


def test_created_indexes_compile_with_descending_columns():
    dialect = postgresql.dialect()

    orders_index = next(
        index
        for index in Base.metadata.tables["orders"].indexes
        if index.name == "ix_orders_user_created"
    )
    orders_sql = str(CreateIndex(orders_index).compile(dialect=dialect))
    assert "created_at DESC" in orders_sql
    assert "id DESC" in orders_sql

    transactions_index = next(
        index
        for index in Base.metadata.tables["transactions"].indexes
        if index.name == "ix_transactions_user_created"
    )
    transactions_sql = str(
        CreateIndex(transactions_index).compile(dialect=dialect)
    )
    assert "created_at DESC" in transactions_sql
    assert "id DESC" in transactions_sql


@pytest.mark.parametrize(
    "table_name,check_name,fragment",
    [
        ("users", "ck_users_username_not_empty", "username <> ''"),
        ("holdings", "ck_holdings_exchange_nse", "exchange = 'NSE'"),
        ("holdings", "ck_holdings_qty_positive", "qty > 0"),
        ("positions", "ck_positions_side", "side IN ('LONG','SHORT')"),
        ("positions", "ck_positions_product", "product IN ('CNC','MIS')"),
        ("orders", "ck_orders_side", "side IN ('BUY','SELL')"),
        (
            "orders",
            "ck_orders_type",
            "type IN ('MARKET','LIMIT','SL','SL-M')",
        ),
        ("orders", "ck_orders_filled_range", "filled <= qty"),
        ("orders", "ck_orders_exchange_nse", "exchange = 'NSE'"),
        (
            "transactions",
            "ck_transactions_kind",
            "kind IN ('DEPOSIT','WITHDRAWAL','SETTLEMENT','FEE')",
        ),
        (
            "transactions",
            "ck_transactions_status",
            "status IN ('COMPLETED','PROCESSING')",
        ),
        ("watchlists", "ck_watchlists_exchange_nse", "exchange = 'NSE'"),
        ("instruments", "ck_instruments_kind", "kind IN ('stock','index')"),
        (
            "latest_quotes",
            "ck_latest_quotes_volume_non_negative",
            "volume >= 0",
        ),
    ],
)
def test_check_constraints_match_the_design(table_name, check_name, fragment):
    checks = _checks(table_name)
    assert check_name in checks
    assert fragment in checks[check_name]


def test_metadata_ddl_compiles_for_postgresql():
    dialect = postgresql.dialect()
    for table in Base.metadata.sorted_tables:
        ddl = str(CreateTable(table).compile(dialect=dialect))
        assert "CREATE TABLE" in ddl
        assert "VARCHAR(24)" in ddl


def test_decimal_columns_use_numeric_not_float():
    for table_name, column_name, _precision, _scale in NUMERIC_COLUMNS:
        column = Base.metadata.tables[table_name].c[column_name]
        assert column.type.python_type is Decimal
