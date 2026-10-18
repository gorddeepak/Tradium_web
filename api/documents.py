"""Document helpers that mirror Mongoose's write behaviour.

Mongoose adds ``createdAt``, ``updatedAt`` and ``__v`` to every document and
refreshes ``updatedAt`` on every update. PyMongo does neither, so writes go
through these helpers to keep the stored documents — and the API responses
that read them back — identical to the Express app.
"""

from datetime import datetime, timezone

from bson import ObjectId
from pymongo import ReturnDocument


def utcnow():
    return datetime.now(timezone.utc)


def new_document(**fields):
    """Build a fresh document the way Mongoose's ``create()`` would."""
    document = {"_id": ObjectId()}
    document.update(fields)
    now = utcnow()
    document["createdAt"] = now
    document["updatedAt"] = now
    document["__v"] = 0
    return document


def inc_funds(db, user, amount):
    """Credit/debit funds, creating the row when the user has none.

    Port of ``FundsModel.findOneAndUpdate({ user }, { $inc }, { upsert: true,
    new: true })``: the increment runs in the server so concurrent updates
    can't be lost.
    """
    now = utcnow()
    return db["funds"].find_one_and_update(
        {"user": user},
        {
            "$inc": {"available": amount},
            "$set": {"updatedAt": now},
            "$setOnInsert": {"createdAt": now, "__v": 0},
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
