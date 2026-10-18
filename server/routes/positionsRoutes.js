const express = require("express");
const router = express.Router();
const { protect } = require("../middlewares/auth");
const { PositionsModel } = require("../models/PositionsModel");
const { FundsModel } = require("../models/FundsModel");
const { OrdersModel } = require("../models/OrdersModel");
const { TransactionModel } = require("../models/TransactionModel");
const YahooFinance = require("yahoo-finance2").default;
const yahooFinance = new YahooFinance();
const { tickerFor } = require("../utils/symbol");

router.get("/", protect, async (req, res) => {
  const positions = await PositionsModel.find({ user: req.userId });
  res.json(positions);
});

// Square off an MIS position at a live quote (or the stored ltp).
router.post("/:id/square-off", protect, async (req, res) => {
  const position = await PositionsModel.findOne({ _id: req.params.id, user: req.userId });
  if (!position) {
    return res.status(404).json({ message: "Position not found" });
  }
  if (position.product !== "MIS") {
    return res.status(400).json({ message: "Only MIS positions can be squared off here" });
  }
  if (!position.ltp) {
    return res.status(400).json({ message: "No live price for this position yet — try again shortly" });
  }

  let exitPrice = position.ltp;
  try {
    const quote = await yahooFinance.quote(tickerFor(position.symbol));
    if (quote?.regularMarketPrice) exitPrice = quote.regularMarketPrice;
  } catch {
    // Yahoo failed — square off at the stored ltp rather than refusing
  }

  // P&L per share: LONG is exit - entry, SHORT is entry - exit.
  const dir = position.side === "LONG" ? 1 : -1;
  const pnl = (exitPrice - position.entry) * position.qty * dir;
  const release = position.entry * position.qty + pnl;

  // Claim the position first so only one square-off pays.
  const claimed = await PositionsModel.deleteOne({ _id: position._id });
  if (!claimed.deletedCount) {
    return res.status(409).json({ message: "Position was already squared off" });
  }

  await FundsModel.findOneAndUpdate(
    { user: req.userId },
    { $inc: { available: release } },
    { upsert: true, new: true },
  );

  // book the realized P&L in the ledger
  await TransactionModel.create({
    user: req.userId,
    kind: "SETTLEMENT",
    method: `${position.symbol} MIS square-off`,
    amount: pnl,
    symbol: position.symbol,
    status: "COMPLETED",
  });

  // the closing trade shows up in the orders book, so history stays honest
  await OrdersModel.create({
    user: req.userId,
    symbol: position.symbol,
    name: position.name,
    exchange: position.exchange,
    side: position.side === "LONG" ? "SELL" : "BUY",
    type: "MARKET",
    product: "MIS",
    qty: position.qty,
    filled: position.qty,
    price: exitPrice,
    status: "EXECUTED",
  });

  // cancel any live exit pair so it can't fire after square-off
  await OrdersModel.updateMany(
    { user: req.userId, symbol: position.symbol, exchange: position.exchange, product: "MIS", isExit: true, status: "OPEN" },
    { status: "CANCELLED" },
  );

  res.json({ message: `Squared off ${position.symbol}`, pnl });
});

module.exports = router;