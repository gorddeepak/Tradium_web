"""SQLAlchemy models for the approved PostgreSQL schema.

Source of truth: docs/migration/POSTGRES_SCHEMA_DESIGN.md. Authentication uses
these models from Phase 3B1; instruments/latest_quotes use them from Phase 3B2.
The remaining MongoDB path is intentionally still active until it migrates.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    desc,
    text,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from .base import ID_PATTERN, Base

# timestamptz(3): the database rounds to milliseconds, matching the API's
# three-decimal ISO timestamps.
TIMESTAMPTZ_MS = TIMESTAMP(timezone=True, precision=3)

ID_CHECK = f"id ~ '{ID_PATTERN}'"
USER_ID_CHECK = f"user_id ~ '{ID_PATTERN}'"
INSTRUMENT_ID_CHECK = f"instrument_id ~ '{ID_PATTERN}'"


class IdTimestampsMixin:
    """The shared columns for every table except latest_quotes."""

    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ_MS, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ_MS, nullable=False)
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )


class User(IdTimestampsMixin, Base):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint(ID_CHECK, name="ck_users_id_hex"),
        CheckConstraint("username <> ''", name="ck_users_username_not_empty"),
        CheckConstraint("email <> ''", name="ck_users_email_not_empty"),
        UniqueConstraint("username", name="uq_users_username"),
        UniqueConstraint("email", name="uq_users_email"),
    )


class Fund(IdTimestampsMixin, Base):
    __tablename__ = "funds"

    user_id: Mapped[str] = mapped_column(
        String(24), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    available: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, server_default=text("0")
    )

    __table_args__ = (
        CheckConstraint(ID_CHECK, name="ck_funds_id_hex"),
        CheckConstraint(USER_ID_CHECK, name="ck_funds_user_id_hex"),
        UniqueConstraint("user_id", name="uq_funds_user"),
    )


class Holding(IdTimestampsMixin, Base):
    __tablename__ = "holdings"

    user_id: Mapped[str] = mapped_column(
        String(24), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    exchange: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="NSE"
    )
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    avg_price: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)

    __table_args__ = (
        CheckConstraint(ID_CHECK, name="ck_holdings_id_hex"),
        CheckConstraint(USER_ID_CHECK, name="ck_holdings_user_id_hex"),
        CheckConstraint("symbol <> ''", name="ck_holdings_symbol_not_empty"),
        CheckConstraint("exchange = 'NSE'", name="ck_holdings_exchange_nse"),
        CheckConstraint("qty > 0", name="ck_holdings_qty_positive"),
        CheckConstraint("avg_price >= 0", name="ck_holdings_avg_price_non_negative"),
        UniqueConstraint(
            "user_id",
            "symbol",
            "exchange",
            name="uq_holdings_user_symbol_exchange",
        ),
        Index("ix_holdings_user_created", "user_id", "created_at", "id"),
    )


class Position(IdTimestampsMixin, Base):
    __tablename__ = "positions"

    user_id: Mapped[str] = mapped_column(
        String(24), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    exchange: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="NSE"
    )
    side: Mapped[str] = mapped_column(Text, nullable=False)
    product: Mapped[str] = mapped_column(Text, nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    entry: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)

    __table_args__ = (
        CheckConstraint(ID_CHECK, name="ck_positions_id_hex"),
        CheckConstraint(USER_ID_CHECK, name="ck_positions_user_id_hex"),
        CheckConstraint("symbol <> ''", name="ck_positions_symbol_not_empty"),
        CheckConstraint("exchange = 'NSE'", name="ck_positions_exchange_nse"),
        CheckConstraint("side IN ('LONG','SHORT')", name="ck_positions_side"),
        CheckConstraint("product IN ('CNC','MIS')", name="ck_positions_product"),
        CheckConstraint("qty > 0", name="ck_positions_qty_positive"),
        CheckConstraint("entry >= 0", name="ck_positions_entry_non_negative"),
        UniqueConstraint(
            "user_id",
            "symbol",
            "exchange",
            "side",
            "product",
            name="uq_positions_user_symbol_exchange_side_product",
        ),
        Index("ix_positions_user_product", "user_id", "product"),
        Index("ix_positions_user_created", "user_id", "created_at", "id"),
    )


class Order(IdTimestampsMixin, Base):
    __tablename__ = "orders"

    user_id: Mapped[str] = mapped_column(
        String(24), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    exchange: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="NSE"
    )
    side: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    product: Mapped[str] = mapped_column(Text, nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    filled: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    price: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    trigger_price: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, server_default=text("0")
    )
    sl_trigger: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, server_default=text("0")
    )
    tp_price: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, server_default=text("0")
    )
    group_id: Mapped[str] = mapped_column(
        String(36), nullable=False, server_default=""
    )
    is_exit: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="OPEN"
    )

    __table_args__ = (
        CheckConstraint(ID_CHECK, name="ck_orders_id_hex"),
        CheckConstraint(USER_ID_CHECK, name="ck_orders_user_id_hex"),
        CheckConstraint("symbol <> ''", name="ck_orders_symbol_not_empty"),
        CheckConstraint("exchange = 'NSE'", name="ck_orders_exchange_nse"),
        CheckConstraint("side IN ('BUY','SELL')", name="ck_orders_side"),
        CheckConstraint(
            "type IN ('MARKET','LIMIT','SL','SL-M')", name="ck_orders_type"
        ),
        CheckConstraint("product IN ('CNC','MIS')", name="ck_orders_product"),
        CheckConstraint("qty > 0", name="ck_orders_qty_positive"),
        CheckConstraint(
            "filled >= 0 AND filled <= qty", name="ck_orders_filled_range"
        ),
        CheckConstraint("price >= 0", name="ck_orders_price_non_negative"),
        CheckConstraint(
            "trigger_price >= 0", name="ck_orders_trigger_price_non_negative"
        ),
        CheckConstraint("sl_trigger >= 0", name="ck_orders_sl_trigger_non_negative"),
        CheckConstraint("tp_price >= 0", name="ck_orders_tp_price_non_negative"),
        CheckConstraint(
            "status IN ('OPEN','EXECUTED','CANCELLED','REJECTED')",
            name="ck_orders_status",
        ),
        Index(
            "ix_orders_user_created",
            "user_id",
            desc("created_at"),
            desc("id"),
        ),
        Index("ix_orders_user_status", "user_id", "status"),
        Index(
            "ix_orders_open",
            "symbol",
            "exchange",
            postgresql_where=text("status = 'OPEN'"),
        ),
        Index(
            "ix_orders_group_open",
            "group_id",
            postgresql_where=text("is_exit AND status = 'OPEN'"),
        ),
        Index(
            "ix_orders_exit_lookup",
            "user_id",
            "symbol",
            "exchange",
            "product",
            "is_exit",
            "status",
        ),
    )


class Transaction(IdTimestampsMixin, Base):
    __tablename__ = "transactions"

    user_id: Mapped[str] = mapped_column(
        String(24), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="Bank transfer"
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    symbol: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=""
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="PROCESSING"
    )

    __table_args__ = (
        CheckConstraint(ID_CHECK, name="ck_transactions_id_hex"),
        CheckConstraint(USER_ID_CHECK, name="ck_transactions_user_id_hex"),
        CheckConstraint(
            "kind IN ('DEPOSIT','WITHDRAWAL','SETTLEMENT','FEE')",
            name="ck_transactions_kind",
        ),
        CheckConstraint(
            "status IN ('COMPLETED','PROCESSING')",
            name="ck_transactions_status",
        ),
        Index(
            "ix_transactions_user_created",
            "user_id",
            desc("created_at"),
            desc("id"),
        ),
        Index("ix_transactions_user_kind", "user_id", "kind"),
    )


class Watchlist(IdTimestampsMixin, Base):
    __tablename__ = "watchlists"

    user_id: Mapped[str] = mapped_column(
        String(24), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    exchange: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="NSE"
    )

    __table_args__ = (
        CheckConstraint(ID_CHECK, name="ck_watchlists_id_hex"),
        CheckConstraint(USER_ID_CHECK, name="ck_watchlists_user_id_hex"),
        CheckConstraint("symbol <> ''", name="ck_watchlists_symbol_not_empty"),
        CheckConstraint("exchange = 'NSE'", name="ck_watchlists_exchange_nse"),
        UniqueConstraint("user_id", "symbol", name="uq_watchlists_user_symbol"),
        Index("ix_watchlists_user_created", "user_id", "created_at", "id"),
    )


class Instrument(IdTimestampsMixin, Base):
    __tablename__ = "instruments"

    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="stock"
    )
    sector: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    in_market_universe: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    __table_args__ = (
        CheckConstraint(ID_CHECK, name="ck_instruments_id_hex"),
        CheckConstraint("symbol <> ''", name="ck_instruments_symbol_not_empty"),
        CheckConstraint("kind IN ('stock','index')", name="ck_instruments_kind"),
        UniqueConstraint("symbol", name="uq_instruments_symbol"),
        Index(
            "ix_instruments_sector_pending",
            "kind",
            postgresql_where=text("sector = ''"),
        ),
    )


class LatestQuote(Base):
    __tablename__ = "latest_quotes"

    instrument_id: Mapped[str] = mapped_column(
        String(24),
        ForeignKey("instruments.id", ondelete="CASCADE"),
        primary_key=True,
    )
    ltp: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, server_default=text("0")
    )
    day_change: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, server_default=text("0")
    )
    day_change_pct: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), nullable=False, server_default=text("0")
    )
    prev_close: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, server_default=text("0")
    )
    volume: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    market_cap: Mapped[Decimal] = mapped_column(
        Numeric(24, 2), nullable=False, server_default=text("0")
    )
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ_MS, nullable=False)
    source_time: Mapped[datetime | None] = mapped_column(
        TIMESTAMPTZ_MS, nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            INSTRUMENT_ID_CHECK, name="ck_latest_quotes_instrument_id_hex"
        ),
        CheckConstraint("ltp >= 0", name="ck_latest_quotes_ltp_non_negative"),
        CheckConstraint(
            "prev_close >= 0", name="ck_latest_quotes_prev_close_non_negative"
        ),
        CheckConstraint(
            "volume >= 0", name="ck_latest_quotes_volume_non_negative"
        ),
        CheckConstraint(
            "market_cap >= 0", name="ck_latest_quotes_market_cap_non_negative"
        ),
    )


class PortfolioSnapshot(IdTimestampsMixin, Base):
    __tablename__ = "portfolio_snapshots"

    user_id: Mapped[str] = mapped_column(
        String(24), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    invested: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, server_default=text("0")
    )
    mis_invested: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, server_default=text("0")
    )
    mis_value: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, server_default=text("0")
    )

    __table_args__ = (
        CheckConstraint(ID_CHECK, name="ck_portfolio_snapshots_id_hex"),
        CheckConstraint(USER_ID_CHECK, name="ck_portfolio_snapshots_user_id_hex"),
        UniqueConstraint(
            "user_id",
            "snapshot_date",
            name="uq_portfolio_snapshots_user_date",
        ),
    )
