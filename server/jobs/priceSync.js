const YahooFinance = require("yahoo-finance2").default;
const yahooFinance = new YahooFinance();

const { HoldingsModel } = require("../models/HoldingsModel");
const { PositionsModel } = require("../models/PositionsModel");
const { WatchlistModel } = require("../models/WatchlistModel");
const { OrdersModel } = require("../models/OrdersModel");
const { FundsModel } = require("../models/FundsModel");
const { applyFill, settleMisExit, cancelSiblingExits } = require("../utils/executeOrder");
const { tickerFor } = require("../utils/symbol");
const { isMarketOpen } = require("../utils/marketHours");

async function fetchQuote(symbol) {
  const ticker = tickerFor(symbol);
  try {
    const quote = await yahooFinance.quote(ticker);
    // No price means the fetch failed — skip this symbol.
    if (!quote.regularMarketPrice) {
      console.error(`No price returned for ${ticker}, skipping`);
      return null;
    }
    return {
      ltp: quote.regularMarketPrice,
      dayChangePct: quote.regularMarketChangePercent ?? 0,
    };
  } catch (err) {
    console.error(`Price fetch failed for ${ticker}:`, err.message);
    return null;
  }
}

// Look up a symbol's sector (slow call, done once per symbol).
async function fetchSector(symbol) {
  const ticker = tickerFor(symbol);
  try {
    const summary = await yahooFinance.quoteSummary(ticker, { modules: ["assetProfile"] });
    return summary.assetProfile?.sector ?? "";
  } catch (err) {
    console.error(`Sector fetch failed for ${ticker}:`, err.message);
    return "";
  }
}

// Flag so two runs can't happen at the same time.
let isSyncing = false;

async function syncPrices() {
  // Yahoo quotes don't move while the market is closed, so syncing is wasted
  // Yahoo calls — skip them. Open limit orders wait for the next open market.
  if (!isMarketOpen()) return;

  if (isSyncing) {
    console.log("Price sync still running, skipping this tick");
    return;
  }
  isSyncing = true;
  try {
    await runSync();
  } catch (err) {
    // Just log — an unhandled error would crash the server.
    console.error("Price sync failed:", err.message);
  } finally {
    isSyncing = false;
  }
}

async function runSync() {
  const holdings = await HoldingsModel.find({});
  const positions = await PositionsModel.find({});
  const watchlist = await WatchlistModel.find({});
  // open limit orders need quotes so they can fill
  const openOrders = await OrdersModel.find({ status: "OPEN" });

  const symbolMap = new Map();
  [...holdings, ...positions, ...watchlist, ...openOrders].forEach((doc) => {
    symbolMap.set(`${doc.symbol}-${doc.exchange}`, { symbol: doc.symbol, exchange: doc.exchange });
  });

  const quotes = {};
  for (const { symbol, exchange } of symbolMap.values()) {
    const q = await fetchQuote(symbol);
    if (q) quotes[`${symbol}-${exchange}`] = q;
  }

  await Promise.all(holdings.map((h) => {
    const q = quotes[`${h.symbol}-${h.exchange}`];
    if (!q) return null;
    h.ltp = q.ltp;
    h.dayChangePct = q.dayChangePct;
    return h.save();
  }));

  await Promise.all(positions.map((p) => {
    const q = quotes[`${p.symbol}-${p.exchange}`];
    if (!q) return null;
    p.ltp = q.ltp;
    return p.save();
  }));

  await Promise.all(watchlist.map((w) => {
    const q = quotes[`${w.symbol}-${w.exchange}`];
    if (!q) return null;
    w.ltp = q.ltp;
    w.dayChangePct = q.dayChangePct;
    return w.save();
  }));

  // sectors last — this call is slow
  let sectorsFilled = 0;
  for (const h of holdings) {
    if (h.sector) continue;
    const sector = await fetchSector(h.symbol);
    if (!sector) continue;
    h.sector = sector;
    await h.save();
    sectorsFilled += 1;
  }
  if (sectorsFilled > 0) {
    console.log(`Sector backfill: ${sectorsFilled} holdings updated`);
  }

  // Match limit and stop orders against the latest prices.
  let filledCount = 0;
  for (const order of openOrders) {
    try {
      const q = quotes[`${order.symbol}-${order.exchange}`];
      if (!q || !q.ltp) continue;
      const crossed =
        order.type === "SL" || order.type === "SL-M"
          ? order.side === "BUY"
            ? q.ltp >= order.triggerPrice
            : q.ltp <= order.triggerPrice
          : order.side === "BUY"
            ? q.ltp <= order.price
            : q.ltp >= order.price;
      if (!crossed) continue;

      // SL-M fills at the live market price, not the trigger price.
      const fillPrice = order.type === "SL-M" ? q.ltp : order.price;

      // Only grab the order if it is still OPEN.
      const claimed = await OrdersModel.findOneAndUpdate(
        { _id: order._id, status: "OPEN" },
        { status: "EXECUTED", filled: order.qty, price: fillPrice },
        { new: true },
      );
      if (!claimed) continue;

      // Fix the blocked cash if SL-M filled at a different price.
      if (order.type === "SL-M" && order.price !== fillPrice) {
        if (!order.isExit && (order.side === "BUY" || order.product === "MIS")) {
          await FundsModel.findOneAndUpdate(
            { user: order.user },
            { $inc: { available: (order.price - fillPrice) * order.qty } },
            { upsert: true, new: true },
          );
        }
      }

      // MIS exits close a position (and cancel their sibling, OCO); others are normal fills.
      if (claimed.isExit && claimed.product === "MIS") {
        await settleMisExit(claimed);
      } else {
        await applyFill(claimed);
      }
      if (claimed.isExit) {
        await cancelSiblingExits(claimed);
      }
      filledCount += 1;
    } catch (err) {
      // One bad order shouldn't stop the others.
      console.error(`Fill failed for order ${order._id}:`, err.message);
    }
  }
  if (filledCount > 0) {
    console.log(`Limit fills: ${filledCount} order(s) executed`);
  }

  console.log(`Price sync complete: ${Object.keys(quotes).length} symbols updated`);
}

// fetchSector and fetchQuote are shared with other files.
module.exports = { syncPrices, fetchSector, fetchQuote };