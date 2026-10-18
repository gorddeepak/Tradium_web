"""Port of the read route in server/routes/watchlistRoutes.js.

The Express route is:
    router.get("/", protect, async (req, res) => {
      const items = await WatchlistModel.find({ user: req.userId });
      res.json(items);
    });

It returns a plain JSON array in natural order with no sort. The collection
is `watchlists` (Mongoose pluralises model("watchlist")).
"""

from bson import ObjectId
from fastapi import APIRouter, Depends
from pymongo.database import Database

from ..auth import require_user
from ..db import get_database
from ..serialization import to_json_value

router = APIRouter()


@router.get("/api/watchlist")
def list_watchlist(
    user_id: str = Depends(require_user),
    db: Database = Depends(get_database),
):
    # The user field is stored as an ObjectId, so cast the token claim.
    user = ObjectId(user_id)
    items = list(db["watchlists"].find({"user": user}))
    return [to_json_value(item) for item in items]
