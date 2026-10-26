"""Initial PostgreSQL schema.

Revision ID: 0001
Revises:
Create Date: 2026-10-25

Creates every table, constraint, and index in
docs/migration/POSTGRES_SCHEMA_DESIGN.md. migration.quarantine is deliberately
not created here: it belongs to the one-shot loader in a separate schema.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ID_PATTERN = "^[0-9a-f]{24}$"
TIMESTAMPTZ_MS = postgresql.TIMESTAMP(timezone=True, precision=3)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(24), nullable=False),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("created_at", TIMESTAMPTZ_MS, nullable=False),
        sa.Column("updated_at", TIMESTAMPTZ_MS, nullable=False),
        sa.Column(
            "version", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.CheckConstraint(f"id ~ '{ID_PATTERN}'", name="ck_users_id_hex"),
        sa.CheckConstraint(
            "username <> ''", name="ck_users_username_not_empty"
        ),
        sa.CheckConstraint("email <> ''", name="ck_users_email_not_empty"),
        sa.UniqueConstraint("username", name="uq_users_username"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    op.create_table(
        "funds",
        sa.Column("id", sa.String(24), nullable=False),
        sa.Column("user_id", sa.String(24), nullable=False),
        sa.Column(
            "available",
            sa.Numeric(20, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("created_at", TIMESTAMPTZ_MS, nullable=False),
        sa.Column("updated_at", TIMESTAMPTZ_MS, nullable=False),
        sa.Column(
            "version", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.PrimaryKeyConstraint("id", name="pk_funds"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_funds_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(f"id ~ '{ID_PATTERN}'", name="ck_funds_id_hex"),
        sa.CheckConstraint(
            f"user_id ~ '{ID_PATTERN}'", name="ck_funds_user_id_hex"
        ),
        sa.UniqueConstraint("user_id", name="uq_funds_user"),
    )

    op.create_table(
        "holdings",
        sa.Column("id", sa.String(24), nullable=False),
        sa.Column("user_id", sa.String(24), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "exchange",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'NSE'"),
        ),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("avg_price", sa.Numeric(20, 6), nullable=False),
        sa.Column("created_at", TIMESTAMPTZ_MS, nullable=False),
        sa.Column("updated_at", TIMESTAMPTZ_MS, nullable=False),
        sa.Column(
            "version", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.PrimaryKeyConstraint("id", name="pk_holdings"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_holdings_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(f"id ~ '{ID_PATTERN}'", name="ck_holdings_id_hex"),
        sa.CheckConstraint(
            f"user_id ~ '{ID_PATTERN}'", name="ck_holdings_user_id_hex"
        ),
        sa.CheckConstraint("symbol <> ''", name="ck_holdings_symbol_not_empty"),
        sa.CheckConstraint("exchange = 'NSE'", name="ck_holdings_exchange_nse"),
        sa.CheckConstraint("qty > 0", name="ck_holdings_qty_positive"),
        sa.CheckConstraint(
            "avg_price >= 0", name="ck_holdings_avg_price_non_negative"
        ),
        sa.UniqueConstraint(
            "user_id",
            "symbol",
            "exchange",
            name="uq_holdings_user_symbol_exchange",
        ),
    )
    op.create_index(
        "ix_holdings_user_created", "holdings", ["user_id", "created_at", "id"]
    )

    op.create_table(
        "positions",
        sa.Column("id", sa.String(24), nullable=False),
        sa.Column("user_id", sa.String(24), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "exchange",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'NSE'"),
        ),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("product", sa.Text(), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("entry", sa.Numeric(20, 6), nullable=False),
        sa.Column("created_at", TIMESTAMPTZ_MS, nullable=False),
        sa.Column("updated_at", TIMESTAMPTZ_MS, nullable=False),
        sa.Column(
            "version", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.PrimaryKeyConstraint("id", name="pk_positions"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_positions_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(f"id ~ '{ID_PATTERN}'", name="ck_positions_id_hex"),
        sa.CheckConstraint(
            f"user_id ~ '{ID_PATTERN}'", name="ck_positions_user_id_hex"
        ),
        sa.CheckConstraint("symbol <> ''", name="ck_positions_symbol_not_empty"),
        sa.CheckConstraint("exchange = 'NSE'", name="ck_positions_exchange_nse"),
        sa.CheckConstraint("side IN ('LONG','SHORT')", name="ck_positions_side"),
        sa.CheckConstraint(
            "product IN ('CNC','MIS')", name="ck_positions_product"
        ),
        sa.CheckConstraint("qty > 0", name="ck_positions_qty_positive"),
        sa.CheckConstraint(
            "entry >= 0", name="ck_positions_entry_non_negative"
        ),
        sa.UniqueConstraint(
            "user_id",
            "symbol",
            "exchange",
            "side",
            "product",
            name="uq_positions_user_symbol_exchange_side_product",
        ),
    )
    op.create_index("ix_positions_user_product", "positions", ["user_id", "product"])
    op.create_index(
        "ix_positions_user_created", "positions", ["user_id", "created_at", "id"]
    )

    op.create_table(
        "orders",
        sa.Column("id", sa.String(24), nullable=False),
        sa.Column("user_id", sa.String(24), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "exchange",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'NSE'"),
        ),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("product", sa.Text(), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column(
            "filled", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("price", sa.Numeric(20, 4), nullable=False),
        sa.Column(
            "trigger_price",
            sa.Numeric(20, 4),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "sl_trigger",
            sa.Numeric(20, 4),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "tp_price",
            sa.Numeric(20, 4),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "group_id", sa.String(36), nullable=False, server_default=sa.text("''")
        ),
        sa.Column(
            "is_exit",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "status", sa.Text(), nullable=False, server_default=sa.text("'OPEN'")
        ),
        sa.Column("created_at", TIMESTAMPTZ_MS, nullable=False),
        sa.Column("updated_at", TIMESTAMPTZ_MS, nullable=False),
        sa.Column(
            "version", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.PrimaryKeyConstraint("id", name="pk_orders"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_orders_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(f"id ~ '{ID_PATTERN}'", name="ck_orders_id_hex"),
        sa.CheckConstraint(
            f"user_id ~ '{ID_PATTERN}'", name="ck_orders_user_id_hex"
        ),
        sa.CheckConstraint("symbol <> ''", name="ck_orders_symbol_not_empty"),
        sa.CheckConstraint("exchange = 'NSE'", name="ck_orders_exchange_nse"),
        sa.CheckConstraint("side IN ('BUY','SELL')", name="ck_orders_side"),
        sa.CheckConstraint(
            "type IN ('MARKET','LIMIT','SL','SL-M')", name="ck_orders_type"
        ),
        sa.CheckConstraint("product IN ('CNC','MIS')", name="ck_orders_product"),
        sa.CheckConstraint("qty > 0", name="ck_orders_qty_positive"),
        sa.CheckConstraint(
            "filled >= 0 AND filled <= qty", name="ck_orders_filled_range"
        ),
        sa.CheckConstraint("price >= 0", name="ck_orders_price_non_negative"),
        sa.CheckConstraint(
            "trigger_price >= 0", name="ck_orders_trigger_price_non_negative"
        ),
        sa.CheckConstraint(
            "sl_trigger >= 0", name="ck_orders_sl_trigger_non_negative"
        ),
        sa.CheckConstraint(
            "tp_price >= 0", name="ck_orders_tp_price_non_negative"
        ),
        sa.CheckConstraint(
            "status IN ('OPEN','EXECUTED','CANCELLED','REJECTED')",
            name="ck_orders_status",
        ),
    )
    op.create_index(
        "ix_orders_user_created",
        "orders",
        ["user_id", sa.desc("created_at"), sa.desc("id")],
    )
    op.create_index("ix_orders_user_status", "orders", ["user_id", "status"])
    op.create_index(
        "ix_orders_open",
        "orders",
        ["symbol", "exchange"],
        postgresql_where=sa.text("status = 'OPEN'"),
    )
    op.create_index(
        "ix_orders_group_open",
        "orders",
        ["group_id"],
        postgresql_where=sa.text("is_exit AND status = 'OPEN'"),
    )
    op.create_index(
        "ix_orders_exit_lookup",
        "orders",
        [
            "user_id",
            "symbol",
            "exchange",
            "product",
            "is_exit",
            "status",
        ],
    )

    op.create_table(
        "transactions",
        sa.Column("id", sa.String(24), nullable=False),
        sa.Column("user_id", sa.String(24), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column(
            "method",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'Bank transfer'"),
        ),
        sa.Column("amount", sa.Numeric(20, 2), nullable=False),
        sa.Column(
            "symbol", sa.Text(), nullable=False, server_default=sa.text("''")
        ),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'PROCESSING'"),
        ),
        sa.Column("created_at", TIMESTAMPTZ_MS, nullable=False),
        sa.Column("updated_at", TIMESTAMPTZ_MS, nullable=False),
        sa.Column(
            "version", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.PrimaryKeyConstraint("id", name="pk_transactions"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_transactions_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            f"id ~ '{ID_PATTERN}'", name="ck_transactions_id_hex"
        ),
        sa.CheckConstraint(
            f"user_id ~ '{ID_PATTERN}'", name="ck_transactions_user_id_hex"
        ),
        sa.CheckConstraint(
            "kind IN ('DEPOSIT','WITHDRAWAL','SETTLEMENT','FEE')",
            name="ck_transactions_kind",
        ),
        sa.CheckConstraint(
            "status IN ('COMPLETED','PROCESSING')",
            name="ck_transactions_status",
        ),
    )
    op.create_index(
        "ix_transactions_user_created",
        "transactions",
        ["user_id", sa.desc("created_at"), sa.desc("id")],
    )
    op.create_index(
        "ix_transactions_user_kind", "transactions", ["user_id", "kind"]
    )

    op.create_table(
        "watchlists",
        sa.Column("id", sa.String(24), nullable=False),
        sa.Column("user_id", sa.String(24), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "exchange",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'NSE'"),
        ),
        sa.Column("created_at", TIMESTAMPTZ_MS, nullable=False),
        sa.Column("updated_at", TIMESTAMPTZ_MS, nullable=False),
        sa.Column(
            "version", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.PrimaryKeyConstraint("id", name="pk_watchlists"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_watchlists_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(f"id ~ '{ID_PATTERN}'", name="ck_watchlists_id_hex"),
        sa.CheckConstraint(
            f"user_id ~ '{ID_PATTERN}'", name="ck_watchlists_user_id_hex"
        ),
        sa.CheckConstraint(
            "symbol <> ''", name="ck_watchlists_symbol_not_empty"
        ),
        sa.CheckConstraint("exchange = 'NSE'", name="ck_watchlists_exchange_nse"),
        sa.UniqueConstraint("user_id", "symbol", name="uq_watchlists_user_symbol"),
    )
    op.create_index(
        "ix_watchlists_user_created", "watchlists", ["user_id", "created_at", "id"]
    )

    op.create_table(
        "instruments",
        sa.Column("id", sa.String(24), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "kind",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'stock'"),
        ),
        sa.Column(
            "sector", sa.Text(), nullable=False, server_default=sa.text("''")
        ),
        sa.Column(
            "in_market_universe",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("created_at", TIMESTAMPTZ_MS, nullable=False),
        sa.Column("updated_at", TIMESTAMPTZ_MS, nullable=False),
        sa.Column(
            "version", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.PrimaryKeyConstraint("id", name="pk_instruments"),
        sa.CheckConstraint(f"id ~ '{ID_PATTERN}'", name="ck_instruments_id_hex"),
        sa.CheckConstraint(
            "symbol <> ''", name="ck_instruments_symbol_not_empty"
        ),
        sa.CheckConstraint("kind IN ('stock','index')", name="ck_instruments_kind"),
        sa.UniqueConstraint("symbol", name="uq_instruments_symbol"),
    )
    op.create_index(
        "ix_instruments_sector_pending",
        "instruments",
        ["kind"],
        postgresql_where=sa.text("sector = ''"),
    )

    op.create_table(
        "latest_quotes",
        sa.Column("instrument_id", sa.String(24), nullable=False),
        sa.Column(
            "ltp", sa.Numeric(20, 4), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "day_change",
            sa.Numeric(20, 4),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "day_change_pct",
            sa.Numeric(12, 6),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "prev_close",
            sa.Numeric(20, 4),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "volume", sa.BigInteger(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "market_cap",
            sa.Numeric(24, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("updated_at", TIMESTAMPTZ_MS, nullable=False),
        sa.Column("source_time", TIMESTAMPTZ_MS, nullable=True),
        sa.PrimaryKeyConstraint("instrument_id", name="pk_latest_quotes"),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name="fk_latest_quotes_instrument_id_instruments",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            f"instrument_id ~ '{ID_PATTERN}'",
            name="ck_latest_quotes_instrument_id_hex",
        ),
        sa.CheckConstraint(
            "ltp >= 0", name="ck_latest_quotes_ltp_non_negative"
        ),
        sa.CheckConstraint(
            "prev_close >= 0", name="ck_latest_quotes_prev_close_non_negative"
        ),
        sa.CheckConstraint(
            "volume >= 0", name="ck_latest_quotes_volume_non_negative"
        ),
        sa.CheckConstraint(
            "market_cap >= 0", name="ck_latest_quotes_market_cap_non_negative"
        ),
    )

    op.create_table(
        "portfolio_snapshots",
        sa.Column("id", sa.String(24), nullable=False),
        sa.Column("user_id", sa.String(24), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(20, 4), nullable=False),
        sa.Column(
            "invested",
            sa.Numeric(20, 4),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "mis_invested",
            sa.Numeric(20, 4),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "mis_value",
            sa.Numeric(20, 4),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("created_at", TIMESTAMPTZ_MS, nullable=False),
        sa.Column("updated_at", TIMESTAMPTZ_MS, nullable=False),
        sa.Column(
            "version", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.PrimaryKeyConstraint("id", name="pk_portfolio_snapshots"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_portfolio_snapshots_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            f"id ~ '{ID_PATTERN}'", name="ck_portfolio_snapshots_id_hex"
        ),
        sa.CheckConstraint(
            f"user_id ~ '{ID_PATTERN}'",
            name="ck_portfolio_snapshots_user_id_hex",
        ),
        sa.UniqueConstraint(
            "user_id",
            "snapshot_date",
            name="uq_portfolio_snapshots_user_date",
        ),
    )


def downgrade() -> None:
    op.drop_table("portfolio_snapshots")
    op.drop_table("latest_quotes")
    op.drop_table("instruments")
    op.drop_table("watchlists")
    op.drop_table("transactions")
    op.drop_table("orders")
    op.drop_table("positions")
    op.drop_table("holdings")
    op.drop_table("funds")
    op.drop_table("users")
