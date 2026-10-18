const { HoldingsModel } = require("../models/HoldingsModel");
const { PositionsModel } = require("../models/PositionsModel");
const { FundsModel } = require("../models/FundsModel");
const { OrdersModel } = require("../models/OrdersModel");
const { TransactionModel } = require("../models/TransactionModel");

/* What happens when an order fills. Shared by the orders route and priceSync. */
async function applyFill(order) {
  // Bracket exits spawn now — the entry has actually filled.
  if (!order.isExit && (order.slTrigger > 0 || order.tpPrice > 0)) {
    await spawnBracketExits(order);
  }

  // Intraday: goes to the positions book, cash was already blocked at placement.
  if (order.product === "MIS") {
    const side = order.side === "BUY" ? "LONG" : "SHORT";
    const existing = await PositionsModel.findOne({
      user: order.user,
      symbol: order.symbol,
      exchange: order.exchange,
      product: "MIS",
      side,
    });

    if (existing) {
      // Atomic merge: computes the new average server-side so concurrent updates can't be lost.
      await PositionsModel.updateOne(
        { _id: existing._id },
        [{
          $set: {
            qty: { $add: ["$qty", order.qty] },
            entry: {
              $divide: [
                { $add: [{ $multiply: ["$qty", "$entry"] }, order.qty * order.price] },
                { $add: ["$qty", order.qty] },
              ],
            },
            ltp: order.price,
          },
        }],
        // Mongoose 9 refuses an array update unless the pipeline is declared
        { updatePipeline: true },
      );
    } else {
      await PositionsModel.create({
        user: order.user,
        exchange: order.exchange,
        symbol: order.symbol,
        name: order.name,
        side,
        product: "MIS",
        qty: order.qty,
        entry: order.price,
        ltp: order.price,
      });
    }
    return;
  }

  /* Delivery, unchanged. */
  const existing = await HoldingsModel.findOne({
    user: order.user,
    symbol: order.symbol,
    exchange: order.exchange,
  });

  if (order.side === "BUY") {
    if (existing) {
      // Same atomic merge as the MIS path above, on avgPrice.
      await HoldingsModel.updateOne(
        { _id: existing._id },
        [{
          $set: {
            qty: { $add: ["$qty", order.qty] },
            avgPrice: {
              $divide: [
                { $add: [{ $multiply: ["$qty", "$avgPrice"] }, order.qty * order.price] },
                { $add: ["$qty", order.qty] },
              ],
            },
          },
        }],
        // Mongoose 9 refuses an array update unless the pipeline is declared
        { updatePipeline: true },
      );
    } else {
      await HoldingsModel.create({
        user: order.user,
        exchange: order.exchange,
        symbol: order.symbol,
        name: order.name,
        qty: order.qty,
        avgPrice: order.price,
        ltp: order.price,
        dayChangePct: 0,
      });
    }
  } else if (order.side === "SELL") {
    // Check shares at fill time: the qty guard makes this an atomic compare-and-swap.
    const updated = await HoldingsModel.findOneAndUpdate(
      { user: order.user, symbol: order.symbol, exchange: order.exchange, qty: { $gte: order.qty } },
      { $inc: { qty: -order.qty } },
      { new: true },
    );
    if (!updated) {
      // REJECTED (not cancelled): there was nothing left to sell.
      order.status = "REJECTED";
      await order.save();
      // the sibling exit leg has nothing to fill against
      await cancelSiblingExits(order);
      return;
    }
    if (updated.qty <= 0) await HoldingsModel.deleteOne({ _id: updated._id });

    // the sell's proceeds land only now that the trade actually happened
    await FundsModel.findOneAndUpdate(
      { user: order.user },
      { $inc: { available: order.qty * order.price } },
      { upsert: true, new: true },
    );

    // Record the realized P&L so closed trades show up in the funds history.
    await TransactionModel.create({
      user: order.user,
      kind: "SETTLEMENT",
      method: `${order.symbol} sell`,
      amount: (order.price - updated.avgPrice) * order.qty,
      symbol: order.symbol,
      status: "COMPLETED",
    });
  }
}

/* Builds the SL and TP exit orders for a bracket, shared by spawnBracketExits
   and the /orders/exits route. Only a CNC BUY exit blocks cash. */
async function createExitPair({ user, symbol, name, exchange, product, qty, side, slTrigger, tpPrice, groupId }) {
  const legs = [];
  if (slTrigger > 0) {
    legs.push({ type: "SL-M", triggerPrice: slTrigger, price: slTrigger });
  }
  if (tpPrice > 0) {
    legs.push({ type: "LIMIT", triggerPrice: 0, price: tpPrice });
  }

  const created = [];
  for (const leg of legs) {
    if (side === "BUY" && product === "CNC") {
      await FundsModel.findOneAndUpdate(
        { user },
        { $inc: { available: -qty * leg.price } },
        { upsert: true, new: true },
      );
    }
    created.push(await OrdersModel.create({
      user, symbol, name, exchange, side, type: leg.type, product,
      qty, filled: 0, price: leg.price, triggerPrice: leg.triggerPrice,
      groupId, isExit: true,
    }));
  }
  return created;
}

// A bracket entry just filled — spawn its exits with the opposite side.
async function spawnBracketExits(entry) {
  await createExitPair({
    user: entry.user,
    symbol: entry.symbol,
    name: entry.name,
    exchange: entry.exchange,
    product: entry.product,
    qty: entry.qty,
    side: entry.side === "BUY" ? "SELL" : "BUY",
    slTrigger: entry.slTrigger,
    tpPrice: entry.tpPrice,
    groupId: entry.groupId,
  });
}

// An MIS exit just filled — release the position's blocked cash plus P&L, then delete it.
async function settleMisExit(order) {
  const position = await PositionsModel.findOne({
    user: order.user,
    symbol: order.symbol,
    exchange: order.exchange,
    product: "MIS",
    side: order.side === "SELL" ? "LONG" : "SHORT",
  });
  if (!position) {
    order.status = "CANCELLED";
    await order.save();
    // the position is gone, so the sibling leg can never fill legitimately
    await cancelSiblingExits(order);
    return;
  }

  // The $gte guard releases the blocked cash exactly once, even if both exit legs fire together.
  const qty = Math.min(order.qty, position.qty);
  const dir = position.side === "LONG" ? 1 : -1;
  const pnl = (order.price - position.entry) * qty * dir;
  const release = position.entry * qty + pnl;
  const updated = await PositionsModel.findOneAndUpdate(
    { _id: position._id, qty: { $gte: qty } },
    { $inc: { qty: -qty } },
    { new: true },
  );
  if (!updated) {
    order.status = "REJECTED";
    await order.save();
    await cancelSiblingExits(order);
    return;
  }
  if (updated.qty <= 0) await PositionsModel.deleteOne({ _id: updated._id });

  await FundsModel.findOneAndUpdate(
    { user: order.user },
    { $inc: { available: release } },
    { upsert: true, new: true },
  );
  // an intraday trade's whole result is realized the moment it closes
  await TransactionModel.create({
    user: order.user,
    kind: "SETTLEMENT",
    method: `${order.symbol} MIS exit`,
    amount: pnl,
    symbol: order.symbol,
    status: "COMPLETED",
  });
  await PositionsModel.deleteOne({ _id: position._id });
}

/* OCO: one exit filled — cancel its still-open siblings. */
async function cancelSiblingExits(order) {
  const siblings = await OrdersModel.find({
    groupId: order.groupId,
    isExit: true,
    status: "OPEN",
    _id: { $ne: order._id },
  });
  for (const sib of siblings) {
    sib.status = "CANCELLED";
    await sib.save();
    if (sib.side === "BUY" && sib.product === "CNC") {
      await FundsModel.findOneAndUpdate(
        { user: sib.user },
        { $inc: { available: sib.qty * sib.price } },
        { upsert: true, new: true },
      );
    }
  }
}

module.exports = { applyFill, createExitPair, settleMisExit, cancelSiblingExits };
