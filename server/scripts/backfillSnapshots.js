/* Backfills the MIS components of existing portfolio snapshots from each user's
   open MIS positions and Yahoo daily closes. Only writes the mis* fields — safe to re-run.
   Run with:  npm run backfill        (from server/) */

require("dotenv").config({ path: require("path").join(__dirname, "..", ".env") });

const mongoose = require("mongoose");
const YahooFinance = require("yahoo-finance2").default;

const User = require("../models/User");
const { PositionsModel } = require("../models/PositionsModel");
const { PortfolioSnapshotModel } = require("../models/PortfolioSnapshotModel");

const yahooFinance = new YahooFinance();
const { tickerFor } = require("./../utils/symbol");

// One chart call per symbol covering the whole lookback, keyed by IST date.
async function dailyCloses(symbol, sinceDate) {
  try {
    const result = await yahooFinance.chart(tickerFor(symbol), {
      period1: sinceDate,
      interval: "1d",
    });
    const closes = {};
    for (const q of result.quotes || []) {
      if (q.close == null) continue;
      const ist = new Date(new Date(q.date).getTime() + 5.5 * 60 * 60 * 1000);
      closes[ist.toISOString().slice(0, 10)] = q.close;
    }
    return closes;
  } catch (err) {
    console.error(`  candle fetch failed for ${symbol}: ${err.message}`);
    return {};
  }
}

async function main() {
  await mongoose.connect(process.env.MONGO_URL);

  const users = await User.find({}).select("_id username");
  for (const user of users) {
    const positions = await PositionsModel.find({ user: user._id, product: "MIS" });
    const snapshots = await PortfolioSnapshotModel.find({ user: user._id }).sort({ date: 1 });
    if (!snapshots.length) continue;

    if (!positions.length) {
      console.log(`${user.username}: no open MIS positions, nothing to backfill`);
      continue;
    }

    // earliest date we need prices for: the first snapshot, or the oldest leg's open
    const earliest = positions.reduce(
      (min, p) => (p.createdAt < min ? p.createdAt : min),
      snapshots[0].date
    );

    // one candle fetch per distinct symbol
    const closesBySymbol = {};
    for (const symbol of [...new Set(positions.map((p) => p.symbol))]) {
      closesBySymbol[symbol] = await dailyCloses(symbol, earliest);
    }

    let touched = 0;
    for (const snap of snapshots) {
      const label = snap.date.toISOString().slice(0, 10);
      let misValue = 0;
      let misInvested = 0;

      for (const p of positions) {
        // the leg didn't exist on this snapshot's date yet
        if (p.createdAt > snap.date) continue;
        const dir = p.side === "SHORT" ? -1 : 1;
        // no close for that day (holiday or fetch gap) — fall back to entry, P&L 0
        const price = closesBySymbol[p.symbol]?.[label] ?? p.entry;
        const pnl = (price - p.entry) * p.qty * dir;
        misInvested += p.qty * p.entry;
        misValue += p.qty * p.entry + pnl;
      }

      if (misValue || misInvested) {
        await PortfolioSnapshotModel.updateOne(
          { _id: snap._id },
          { misValue, misInvested }
        );
        touched++;
      }
    }
    console.log(`${user.username}: ${touched} snapshots updated with MIS components`);
  }

  await mongoose.disconnect();
  console.log("Backfill complete");
}

main().catch((err) => {
  console.error("Backfill failed:", err);
  process.exit(1);
});
