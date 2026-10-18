const express = require("express");
const router = express.Router();
const { protect } = require("../middlewares/auth");
const { FundsModel } = require("../models/FundsModel");
const { TransactionModel } = require("../models/TransactionModel");

const { OrdersModel } = require("../models/OrdersModel");
const { PositionsModel } = require("../models/PositionsModel");

// usedMargin is computed on the fly, not stored.
async function derivedFunds(userId) {
  let funds = await FundsModel.findOne({ user: userId });
  if (!funds) {
    funds = await FundsModel.create({ user: userId, available: 0 });
  }

  const openOrders = await OrdersModel.find({ user: userId, status: "OPEN" });
  // Only entry orders block cash.
  const blockedInOrders = openOrders.reduce(
    (sum, o) =>
      !o.isExit && (o.side === "BUY" || o.product === "MIS") ? sum + (o.qty - o.filled) * o.price : sum,
    0,
  );
  const positions = await PositionsModel.find({ user: userId, product: "MIS" });
  const misMargin = positions.reduce((sum, p) => sum + p.entry * p.qty, 0);

  // realized P&L: sum of all SETTLEMENT transactions
  const settlements = await TransactionModel.find({ user: userId, kind: "SETTLEMENT" });
  const realizedPnl = settlements.reduce((sum, t) => sum + t.amount, 0);

  return {
    ...funds.toObject(),
    usedMargin: blockedInOrders + misMargin,
    blockedInOrders,
    misMargin,
    realizedPnl,
  };
}

router.get("/", protect, async (req, res) => {
  res.json(await derivedFunds(req.userId));
});

router.get("/transactions", protect, async (req, res) => {
  const transactions = await TransactionModel.find({ user: req.userId }).sort({ createdAt: -1 });
  res.json(transactions);
});

router.post("/transactions", protect, async (req, res) => {
  const { kind } = req.body;
  // coerce to a number, like qty in the orders route
  const amount = Number(req.body.amount);
  if (!["DEPOSIT", "WITHDRAWAL"].includes(kind) || !Number.isFinite(amount) || amount <= 0) {
    return res.status(400).json({ message: "Invalid transaction" });
  }

  let funds;
  if (kind === "DEPOSIT") {
    funds = await FundsModel.findOneAndUpdate(
      { user: req.userId },
      { $inc: { available: amount } },
      { upsert: true, new: true },
    );
  } else {
    // $gte check makes the debit atomic so the balance can't go negative.
    funds = await FundsModel.findOneAndUpdate(
      { user: req.userId, available: { $gte: amount } },
      { $inc: { available: -amount } },
      { new: true },
    );
    if (!funds) {
      return res.status(400).json({ message: "Amount exceeds available balance" });
    }
  }

  // only known payment-method labels are stored — anything else falls back to the generic text
  const ALLOWED_METHODS = ["Paper cash", "UPI", "Net banking", "Bank transfer", "Bank withdrawal"];
  const sentMethod = ALLOWED_METHODS.includes(req.body.method) ? req.body.method : null;

  const txn = await TransactionModel.create({
    user: req.userId,
    kind,
    method: sentMethod || (kind === "DEPOSIT" ? "Bank transfer" : "Bank withdrawal"),
    amount: kind === "DEPOSIT" ? amount : -amount,
    status: "COMPLETED",
  });

  res.status(201).json({ funds, transaction: txn });
});

module.exports = router;