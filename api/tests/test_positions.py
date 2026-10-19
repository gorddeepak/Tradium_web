"""Focused tests for /api/positions: isolation, shape, and the MIS square-off.

The read route returns natural order with no sort, so ordering is not
asserted. Authentication and database-failure behaviour are shared with the
holdings suite and not repeated here.
"""

from bson import ObjectId


def test_returns_only_the_cookie_users_positions(
    client, database, make_token, user_id, other_user_id, positions_factory
):
    database["positions"].insert_many(
        [
            positions_factory(user_id, symbol="INFY"),
            positions_factory(user_id, symbol="RELIANCE", name="Reliance Industries", side="SHORT"),
            positions_factory(other_user_id, symbol="TCS", name="Tata Consultancy"),
        ]
    )

    response = client.get("/api/positions", cookies={"token": make_token(user_id)})

    assert response.status_code == 200
    symbols = [position["symbol"] for position in response.json()]
    assert symbols == ["INFY", "RELIANCE"]
    assert "TCS" not in symbols


def test_response_shape_matches_mongoose_serialization(
    client, database, make_token, user_id, positions_factory
):
    position_id = ObjectId()
    database["positions"].insert_one(positions_factory(user_id, _id=position_id))

    body = client.get("/api/positions", cookies={"token": make_token(user_id)}).json()

    assert len(body) == 1
    position = body[0]
    assert set(position) == {
        "_id",
        "user",
        "symbol",
        "name",
        "exchange",
        "side",
        "product",
        "qty",
        "entry",
        "ltp",
        "createdAt",
        "updatedAt",
        "__v",
    }
    assert position["_id"] == str(position_id)
    assert position["user"] == str(user_id)
    assert type(position["_id"]) is str and len(position["_id"]) == 24
    assert position["createdAt"] == "2026-09-01T04:15:30.123Z"


def test_empty_positions_returns_empty_list(client, make_token, user_id):
    response = client.get("/api/positions", cookies={"token": make_token(user_id)})
    assert response.status_code == 200
    assert response.json() == []


def test_square_off_long_releases_cash_and_records_settlement(
    client, database, make_token, user_id, positions_factory, orders_factory, monkeypatch
):
    cookie = {"token": make_token(user_id)}
    # No live quote, so the stored ltp is the exit price.
    monkeypatch.setattr("api.routes.positions.fetch_quote", lambda symbol: None)
    position_id = ObjectId()
    exit_id = ObjectId()
    database["positions"].insert_one(
        positions_factory(
            user_id,
            _id=position_id,
            symbol="INFY",
            name="Infosys",
            side="LONG",
            product="MIS",
            qty=10,
            entry=1500.0,
            ltp=1550.0,
        )
    )
    database["orders"].insert_one(
        orders_factory(
            user_id,
            _id=exit_id,
            symbol="INFY",
            exchange="NSE",
            product="MIS",
            isExit=True,
            status="OPEN",
            groupId="group-1",
        )
    )

    response = client.post(f"/api/positions/{position_id}/square-off", cookies=cookie)

    assert response.status_code == 200
    assert response.json() == {"message": "Squared off INFY", "pnl": 500}
    assert database["positions"].count_documents({"_id": position_id}) == 0

    # The upsert creates the funds row: entry*qty + pnl.
    assert database["funds"].find_one({"user": user_id})["available"] == 15500
    settlement = database["transactions"].find_one({"user": user_id, "kind": "SETTLEMENT"})
    assert settlement["amount"] == 500
    assert settlement["method"] == "INFY MIS square-off"
    assert settlement["symbol"] == "INFY"

    closing = database["orders"].find_one({"user": user_id, "isExit": False})
    assert closing["side"] == "SELL"
    assert closing["type"] == "MARKET"
    assert closing["status"] == "EXECUTED"
    assert closing["filled"] == 10
    assert closing["price"] == 1550.0

    # The live exit pair is cancelled so it can't fire afterwards.
    assert database["orders"].find_one({"_id": exit_id})["status"] == "CANCELLED"


def test_square_off_short_pnl_sign(
    client, database, make_token, user_id, positions_factory, monkeypatch
):
    cookie = {"token": make_token(user_id)}
    monkeypatch.setattr("api.routes.positions.fetch_quote", lambda symbol: None)
    position_id = ObjectId()
    database["positions"].insert_one(
        positions_factory(
            user_id,
            _id=position_id,
            side="SHORT",
            product="MIS",
            qty=5,
            entry=200.0,
            ltp=190.0,
        )
    )

    response = client.post(f"/api/positions/{position_id}/square-off", cookies=cookie)

    assert response.status_code == 200
    # A short profits when the exit is below entry: (190-200)*5*-1.
    assert response.json()["pnl"] == 50
    assert database["funds"].find_one({"user": user_id})["available"] == 1050


def test_square_off_errors(
    client, database, make_token, user_id, other_user_id, positions_factory
):
    cookie = {"token": make_token(user_id)}

    missing = client.post(f"/api/positions/{ObjectId()}/square-off", cookies=cookie)
    assert missing.status_code == 404
    assert missing.json() == {"message": "Position not found"}

    # Another user's position is not visible to this caller.
    foreign_id = ObjectId()
    database["positions"].insert_one(
        positions_factory(other_user_id, _id=foreign_id, product="MIS", ltp=1500.0)
    )
    foreign = client.post(f"/api/positions/{foreign_id}/square-off", cookies=cookie)
    assert foreign.status_code == 404
    assert database["positions"].count_documents({"_id": foreign_id}) == 1

    cnc_id = ObjectId()
    database["positions"].insert_one(
        positions_factory(user_id, _id=cnc_id, product="CNC", ltp=1500.0)
    )
    not_mis = client.post(f"/api/positions/{cnc_id}/square-off", cookies=cookie)
    assert not_mis.status_code == 400
    assert not_mis.json() == {"message": "Only MIS positions can be squared off here"}

    no_price_id = ObjectId()
    database["positions"].insert_one(
        positions_factory(user_id, _id=no_price_id, product="MIS", ltp=0)
    )
    no_price = client.post(f"/api/positions/{no_price_id}/square-off", cookies=cookie)
    assert no_price.status_code == 400
    assert no_price.json() == {
        "message": "No live price for this position yet — try again shortly"
    }
