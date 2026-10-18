"""Port of the read route in server/routes/positionsRoutes.js.

The Express route is:
    router.get("/", protect, async (req, res) => {
      const positions = await PositionsModel.find({ user: req.userId });
      res.json(positions);
    });

It returns a plain JSON array in natural order with no sort. The collection
is `positions` (Mongoose pluralises model("position")).
"""

from bson import ObjectId
from fastapi import APIRouter, Depends
from pymongo.database import Database

from ..auth import require_user
from ..db import get_database
from ..serialization import to_json_value

router = APIRouter()


@router.get("/api/positions")
def list_positions(
    user_id: str = Depends(require_user),
    db: Database = Depends(get_database),
):
    # The user field is stored as an ObjectId, so cast the token claim.
    user = ObjectId(user_id)
    positions = list(db["positions"].find({"user": user}))
    return [to_json_value(position) for position in positions]
