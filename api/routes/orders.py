"""Port of the read route in server/routes/ordersRoutes.js.

The Express route is:
    router.get("/", protect, async (req, res) => {
      const orders = await OrdersModel.find({ user: req.userId }).sort({ createdAt: -1 });
      res.json(orders);
    });

It returns a plain JSON array, newest first, and the documents keep
`_id`, `__v`, `createdAt` and `updatedAt`.
"""

from bson import ObjectId
from fastapi import APIRouter, Depends
from pymongo.database import Database

from ..auth import require_user
from ..db import get_database
from ..serialization import to_json_value

router = APIRouter()


@router.get("/api/orders")
def list_orders(
    user_id: str = Depends(require_user),
    db: Database = Depends(get_database),
):
    # The user field is stored as an ObjectId, so cast the token claim, the
    # same way the holdings route does.
    user = ObjectId(user_id)
    # Express sorts newest first; the Orders page renders in this order.
    orders = list(db["orders"].find({"user": user}).sort("createdAt", -1))
    return [to_json_value(order) for order in orders]
