"""Focused tests for GET /api/portfolio/history.

Historical points come from PostgreSQL `portfolio_snapshots` (Phase 3C1); the
live today point still comes from the MongoDB holdings and positions. Covers
the window/filtering, the label format, the legacy `invested: null` gap, and
the live today point. Authentication and database-failure behaviour are shared
with the holdings suite and not repeated here.
"""

import os
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import mongomock
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from api.main import create_app
from api.postgres.models import PortfolioSnapshot, User
from api.postgres.session import get_session

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL is not set; PostgreSQL portfolio tests skipped",
)

# Business-day labels are IST (API_CONTRACTS §0.5).
IST = timezone(timedelta(hours=5, minutes=30))

NOW = datetime(2026, 9, 1, 4, 15, 30, 123000, tzinfo=timezone.utc)


@pytest.fixture
def database():
    return mongomock.MongoClient()["tradium_test"]


@pytest.fixture
def pg_users(postgres_session_factory, user_id, other_user_id):
    """Give the token users PostgreSQL rows for the snapshot foreign key."""
    with postgres_session_factory() as session:
        session.execute(text("TRUNCATE TABLE portfolio_snapshots, users CASCADE"))
        session.commit()
        session.add_all(
            [
                User(
                    id=str(user_id),
                    username="history-user",
                    email="history-user@example.com",
                    password_hash="unused-in-portfolio-tests",
                    created_at=NOW,
                    updated_at=NOW,
                    version=0,
                ),
                User(
                    id=str(other_user_id),
                    username="history-other",
                    email="history-other@example.com",
                    password_hash="unused-in-portfolio-tests",
                    created_at=NOW,
                    updated_at=NOW,
                    version=0,
                ),
            ]
        )
        session.commit()
    return postgres_session_factory


@pytest.fixture
def client(database, pg_users):
    app = create_app(database=database)

    def override_get_session():
        with pg_users() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _insert_snapshot(
    session_factory,
    user,
    day,
    value,
    invested=0,
    mis_value=0,
    mis_invested=0,
):
    with session_factory() as session:
        session.add(
            PortfolioSnapshot(
                id=secrets.token_hex(12),
                user_id=str(user),
                snapshot_date=day,
                value=Decimal(str(value)),
                invested=Decimal(str(invested)),
                mis_value=Decimal(str(mis_value)),
                mis_invested=Decimal(str(mis_invested)),
                created_at=NOW,
                updated_at=NOW,
                version=0,
            )
        )
        session.commit()


def _today_ist():
    return datetime.now(timezone.utc).astimezone(IST).strftime("%Y-%m-%d")


def test_live_point_only_when_no_snapshots(
    client, database, make_token, user_id, holdings_factory, positions_factory
):
    database["holdings"].insert_many(
        [
            holdings_factory(user_id, qty=10, ltp=2500.0, avg_price=2400.0),
            holdings_factory(user_id, qty=5, ltp=100.0, avg_price=90.0),
        ]
    )
    database["positions"].insert_one(
        positions_factory(user_id, product="MIS", side="LONG", qty=2, entry=100.0, ltp=110.0)
    )

    body = client.get(
        "/api/portfolio/history?range=1M", cookies={"token": make_token(user_id)}
    ).json()

    # holdings value 10*2500 + 5*100 = 25500; MIS value 200 + (110-100)*2 = 220
    # holdings invested 10*2400 + 5*90 = 24450; MIS invested 2*100 = 200
    assert body == [
        {"label": _today_ist(), "value": 25720.0, "invested": 24650.0}
    ]


def test_snapshots_ascending_with_null_invested_for_legacy_rows(
    client, pg_users, make_token, user_id, other_user_id
):
    _insert_snapshot(
        pg_users,
        user_id,
        datetime(2026, 9, 1, tzinfo=timezone.utc).date(),
        value=100.0,
        invested=90.0,
        mis_value=5.0,
    )
    # legacy row: invested is 0, so the chart draws a gap
    _insert_snapshot(
        pg_users,
        user_id,
        datetime(2026, 9, 2, tzinfo=timezone.utc).date(),
        value=200.0,
    )
    _insert_snapshot(
        pg_users,
        other_user_id,
        datetime(2026, 9, 1, tzinfo=timezone.utc).date(),
        value=999.0,
        invested=1.0,
    )

    body = client.get(
        "/api/portfolio/history?range=ALL", cookies={"token": make_token(user_id)}
    ).json()

    labels = [point["label"] for point in body]
    assert labels[:2] == ["2026-09-01", "2026-09-02"]
    assert labels[2] == _today_ist()
    assert body[0]["value"] == 105.0  # value + misValue
    assert body[0]["invested"] == 90.0  # invested + misInvested (0)
    assert body[1]["value"] == 200.0
    assert body[1]["invested"] is None


def test_todays_snapshot_is_overwritten_not_duplicated(
    client, pg_users, database, make_token, user_id, holdings_factory
):
    today = datetime.now(timezone.utc).astimezone(IST).date()
    _insert_snapshot(pg_users, user_id, today, value=12345.0, invested=1000.0)
    database["holdings"].insert_one(holdings_factory(user_id, qty=2, ltp=50.0, avg_price=40.0))

    body = client.get(
        "/api/portfolio/history?range=ALL", cookies={"token": make_token(user_id)}
    ).json()

    assert len(body) == 1
    assert body[0]["label"] == _today_ist()
    assert body[0]["value"] == 100.0
    assert body[0]["invested"] == 80.0


def test_unknown_range_falls_back_to_thirty_days(
    client, pg_users, make_token, user_id
):
    today = datetime.now(timezone.utc).astimezone(IST).date()
    _insert_snapshot(pg_users, user_id, today - timedelta(days=10), value=100.0, invested=90.0)
    _insert_snapshot(pg_users, user_id, today - timedelta(days=100), value=1.0, invested=1.0)

    body = client.get(
        "/api/portfolio/history?range=nonsense", cookies={"token": make_token(user_id)}
    ).json()

    # only the recent snapshot survives the 30-day fallback window, plus today's live point
    assert len(body) == 2
