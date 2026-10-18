const express = require("express");
const { randomUUID } = require("crypto");
const router = express.Router();
const { protect } = require("../middlewares/auth");
const { OrdersModel } = require("../models/OrdersModel");
const { HoldingsModel } = require("../models/HoldingsModel");
const { PositionsModel } = require("../models/PositionsModel");
const { FundsModel } = require("../models/FundsModel");
const { applyFill, createExitPair } = require("../utils/executeOrder");
// fetchQuote is shared with the price-sync job.
const { fetchQuote } = require("../jobs/priceSync");

router.get("/", protect, async (req, res) => {
  const orders = await OrdersModel.find({ user: req.userId }).sort({ createdAt: -1 });
  res.json(orders);
});

router.post("/", protect, async (req, res) => {
  const { symbol, name, exchange, side, type, product } = req.body;

  // coerce to numbers so a string qty can't break the math
  const qty = Number(req.body.qty);
  const price = Number(req.body.price);
  const triggerPrice = Number(req.body.triggerPrice) || 0;
  // optional bracket: stop-loss trigger and target price for this entry
  const slTrigger = Number(req.body.slTrigger) || 0;
  const tpPrice = Number(req.body.tpPrice) || 0;

  if (!symbol || !side || !type || !name) {
    return res.status(400).json({ message: "symbol, name, side and type are required" });
  }
  // Validate enums before debiting funds.
  if (!["BUY", "SELL"].includes(side)) {
    return res.status(400).json({ message: "side must be BUY or SELL" });
  }
  if (!["LIMIT", "MARKET", "SL", "SL-M"].includes(type)) {
    return res.status(400).json({ message: "type must be LIMIT, MARKET, SL or SL-M" });
  }
  if (!["CNC", "MIS"].includes(product)) {
    return res.status(400).json({ message: "product must be CNC or MIS" });
  }
  if (!qty || qty <= 0) {
    return res.status(400).json({ message: "Quantity must be greater than zero" });
  }
  if (!Number.isInteger(qty)) {
    return res.status(400).json({ message: "Quantity must be a whole number" });
  }
  if (!price || price <= 0) {
    if (type !== "MARKET") {
      return res.status(400).json({ message: "Price must be greater than zero" });
    }
  }

  // MARKET orders fill at the live price; LIMIT/SL keep the client's price.
  let execPrice = price;
  if (type === "MARKET") {
    const q = await fetchQuote(symbol);
    if (!q || !q.ltp) {
      return res.status(503).json({ message: `No live price available for ${symbol}, try again in a moment` });
    }
    execPrice = q.ltp;
  }
  // a stop order needs a trigger to ever fire
  if ((type === "SL" || type === "SL-M") && triggerPrice <= 0) {
    return res.status(400).json({ message: "SL and SL-M orders need a trigger price" });
  }
  // bracket: SL on the losing side, TP on the winning side
  if (slTrigger > 0 && tpPrice > 0) {
    const ok = side === "BUY" ? slTrigger < tpPrice : slTrigger > tpPrice;
    if (!ok) {
      return res.status(400).json({
        message: side === "BUY"
          ? "Stop-loss trigger must be below the target price for a buy"
          : "Stop-loss trigger must be above the target price for a sell",
      });
    }
  }

  // Check the user can afford this order.
  if (side === "BUY" || product === "MIS") {
    const debited = await FundsModel.findOneAndUpdate(
      { user: req.userId, available: { $gte: qty * execPrice } },
      { $inc: { available: -qty * execPrice } },
      { new: true },
    );
    if (!debited) {
      const funds = await FundsModel.findOne({ user: req.userId });
      const available = funds ? funds.available : 0;
      return res.status(400).json({
        message: `Insufficient funds: order needs ₹${(qty * execPrice).toLocaleString("en-IN")} but only ₹${available.toLocaleString("en-IN")} is available`,
      });
    }
  }

  // CNC sells need real holdings; MIS shorts are allowed.
  if (side === "SELL" && product !== "MIS") {
    const held = await HoldingsModel.findOne({ user: req.userId, symbol, exchange });
    const heldQty = held ? held.qty : 0;
    if (qty > heldQty) {
      return res.status(400).json({
        message: `Insufficient holdings: you hold ${heldQty} ${symbol} but tried to sell ${qty}`,
      });
    }
  }

  // Cash was blocked above; refunded on cancel or fill.

  const order = await OrdersModel.create({
    user: req.userId,
    symbol, name, exchange, side, type, product,
    qty, price: execPrice, triggerPrice,
    slTrigger, tpPrice,
    filled: type === "MARKET" ? qty : 0,
    status: type === "MARKET" ? "EXECUTED" : "OPEN",
  });

  // bracket entries anchor their own group; the exits copy this groupId for the OCO cancel
  if (slTrigger > 0 || tpPrice > 0) {
    order.groupId = String(order._id);
    await order.save();
  }

  // market orders fill now; limit orders wait for priceSync.
  if (order.status === "EXECUTED") {
    await applyFill(order);
  }

  res.status(201).json(order);
});

// Set or replace SL/target exits on a holding or open MIS position.
router.post("/exits", protect, async (req, res) => {
  const { symbol, exchange, product } = req.body;
  const slTrigger = Number(req.body.slTrigger) || 0;
  const tpPrice = Number(req.body.tpPrice) || 0;

  if (!symbol || !product) {
    return res.status(400).json({ message: "symbol and product are required" });
  }
  if (slTrigger <= 0 && tpPrice <= 0) {
    return res.status(400).json({ message: "Set at least a stop-loss trigger or a target price" });
  }

  let qty, side, name;
  if (product === "CNC") {
    const holding = await HoldingsModel.findOne({ user: req.userId, symbol, exchange });
    if (!holding) {
      return res.status(404).json({ message: `No holding found for ${symbol}` });
    }
    qty = holding.qty;
    name = holding.name;
    side = "SELL"; // a holding is always long — it exits by selling
    if (slTrigger > 0 && tpPrice > 0 && slTrigger >= tpPrice) {
      return res.status(400).json({ message: "Stop-loss trigger must be below the target price" });
    }
  } else if (product === "MIS") {
    const position = await PositionsModel.findOne({ user: req.userId, symbol, exchange, product: "MIS" });
    if (!position) {
      return res.status(404).json({ message: `No open MIS position found for ${symbol}` });
    }
    qty = position.qty;
    name = position.name;
    side = position.side === "LONG" ? "SELL" : "BUY";
    const slBelowTp = slTrigger < tpPrice;
    const longNeedsSlBelow = position.side === "LONG" ? slBelowTp : !slBelowTp;
    if (slTrigger > 0 && tpPrice > 0 && !longNeedsSlBelow) {
      return res.status(400).json({
        message: position.side === "LONG"
          ? "Stop-loss trigger must be below the target price for a long"
          : "Stop-loss trigger must be above the target price for a short",
      });
    }
  } else {
    return res.status(400).json({ message: "product must be CNC or MIS" });
  }

  // cancel the old exit pair first; only CNC BUY exits refund cash
  const oldExits = await OrdersModel.find({
    user: req.userId, symbol, exchange, product, isExit: true, status: "OPEN",
  });
  for (const old of oldExits) {
    old.status = "CANCELLED";
    await old.save();
    if (old.side === "BUY" && old.product === "CNC") {
      await FundsModel.findOneAndUpdate(
        { user: req.userId },
        { $inc: { available: old.qty * old.price } },
        { upsert: true, new: true },
      );
    }
  }

  // no entry order to anchor the group, so a fresh id plays that role
  const groupId = randomUUID();
  const orders = await createExitPair({
    user: req.userId, symbol, name, exchange, product, qty, side, slTrigger, tpPrice, groupId,
  });

  res.status(201).json({ message: `Exit rules set for ${symbol}`, orders });
});

// Cancel an OPEN order and refund its blocked cash.
router.delete("/:id", protect, async (req, res) => {
  // Only OPEN orders match, so a just-filled order never refunds.
  const order = await OrdersModel.findOneAndUpdate(
    { _id: req.params.id, user: req.userId, status: "OPEN" },
    { status: "CANCELLED" },
    { new: true },
  );

  if (!order) {
    const existing = await OrdersModel.findOne({ _id: req.params.id, user: req.userId });
    if (!existing) {
      return res.status(404).json({ message: "Order not found" });
    }
    return res.status(400).json({ message: `Order is already ${existing.status.toLowerCase()}` });
  }

  const unfilled = order.qty - order.filled;
  // refund blocked cash (bracket exits only if they were a CNC BUY)
  const blocks =
    order.isExit
      ? order.side === "BUY" && order.product === "CNC"
      : order.side === "BUY" || order.product === "MIS";
  if (unfilled > 0 && blocks) {
    await FundsModel.findOneAndUpdate(
      { user: req.userId },
      { $inc: { available: unfilled * order.price } },
      { upsert: true, new: true },
    );
  }

  res.json(order);
});

module.exports = router;
