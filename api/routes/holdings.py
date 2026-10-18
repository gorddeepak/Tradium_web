"""Port of server/routes/holdingsRoutes.js.

The Express route is:
    router.get("/", protect, async (req, res) => {
      const holdings = await HoldingsModel.find({ user: req.userId });
      res.json(holdings);
    });

It returns a plain JSON array in natural order with no sort, and the
documents keep `_id`, `__v`, `createdAt` and `updatedAt`.
"""

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends
from pymongo.database import Database

from ..auth import require_user
from ..db import get_database
from ..serialization import to_json_value

router = APIRouter()


@router.get("/api/holdings")
def list_holdings(
    user_id: str = Depends(require_user),
    db: Database = Depends(get_database),
):
    # The user field is stored as an ObjectId, so cast the token claim.
    # Casting outside the find() also rejects a malformed id explicitly
    # instead of silently returning an empty list.
    user = ObjectId(user_id)
    holdings = list(db["holdings"].find({"user": user}))
    return [to_json_value(holding) for holding in holdings]
