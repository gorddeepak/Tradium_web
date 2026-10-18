"""Focused tests for GET /api/portfolio/history.

Covers the window/filtering, the label format, the legacy `invested: null`
gap, and the live today point. Authentication and database-failure behaviour
are shared with the holdings suite and not repeated here.
"""

from datetime import datetime, timedelta, timezone

from bson import ObjectId

# Business-day labels are IST (API_CONTRACTS §0.5).
IST = timezone(timedelta(hours=5, minutes=30))


def _snapshot(user, date, value, invested=None, mis_value=None, mis_invested=None):
    document = {
        "_id": ObjectId(),
        "user": user,
        "date": date,
        "value": value,
        "createdAt": date,
        "updatedAt": date,
        "__v": 0,
    }
    if invested is not None:
        document["invested"] = invested
    if mis_value is not None:
        document["misValue"] = mis_value
    if mis_invested is not None:
        document["misInvested"] = mis_invested
    return document


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
    client, database, make_token, user_id, other_user_id
):
    database["portfoliosnapshots"].insert_many(
        [
            _snapshot(
                user_id,
                datetime(2026, 9, 1, tzinfo=timezone.utc),
                value=100.0,
                invested=90.0,
                mis_value=5.0,
            ),
            # legacy row: no `invested` field, so the chart draws a gap
            _snapshot(user_id, datetime(2026, 9, 2, tzinfo=timezone.utc), value=200.0),
            _snapshot(other_user_id, datetime(2026, 9, 1, tzinfo=timezone.utc), value=999.0, invested=1.0),
        ]
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
    client, database, make_token, user_id, holdings_factory
):
    today = datetime.now(timezone.utc).astimezone(IST)
    today_midnight_utc = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
    database["portfoliosnapshots"].insert_one(
        _snapshot(user_id, today_midnight_utc, value=12345.0, invested=1000.0)
    )
    database["holdings"].insert_one(holdings_factory(user_id, qty=2, ltp=50.0, avg_price=40.0))

    body = client.get(
        "/api/portfolio/history?range=ALL", cookies={"token": make_token(user_id)}
    ).json()

    assert len(body) == 1
    assert body[0]["label"] == _today_ist()
    assert body[0]["value"] == 100.0
    assert body[0]["invested"] == 80.0


def test_unknown_range_falls_back_to_thirty_days(client, database, make_token, user_id):
    recent = datetime.now(timezone.utc) - timedelta(days=10)
    old = datetime.now(timezone.utc) - timedelta(days=100)
    database["portfoliosnapshots"].insert_many(
        [
            _snapshot(user_id, recent, value=100.0, invested=90.0),
            _snapshot(user_id, old, value=1.0, invested=1.0),
        ]
    )

    body = client.get(
        "/api/portfolio/history?range=nonsense", cookies={"token": make_token(user_id)}
    ).json()

    # only the recent snapshot survives the 30-day fallback window, plus today's live point
    assert len(body) == 2
