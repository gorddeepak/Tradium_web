const { HoldingsModel } = require("../models/HoldingsModel");
const { PositionsModel } = require("../models/PositionsModel");
const User = require("../models/User");
const { PortfolioSnapshotModel } = require("../models/PortfolioSnapshotModel");
const { misComponents } = require("../utils/portfolioMath");

async function recordDailySnapshot() {
  // Snapshot every user — even one who sold everything still has a chart.
  try {
    // Label each snapshot with the IST calendar day, stored at its UTC midnight.
    const ist = new Date(Date.now() + 5.5 * 60 * 60 * 1000);
    const today = new Date(ist.toISOString().slice(0, 10) + "T00:00:00.000Z");

    const userIds = await User.find({}).select("_id");
    for (const { _id: userId } of userIds) {
      const holdings = await HoldingsModel.find({ user: userId });
      const value = holdings.reduce((s, h) => s + h.qty * h.ltp, 0);
      const invested = holdings.reduce((s, h) => s + h.qty * h.avgPrice, 0);

      // Whole-account view: snapshot open MIS legs alongside holdings.
      const positions = await PositionsModel.find({ user: userId, product: "MIS" });
      const { misValue, misInvested } = misComponents(positions);

      await PortfolioSnapshotModel.findOneAndUpdate(
        { user: userId, date: today },
        { value, invested, misValue, misInvested },
        { upsert: true }
      );
    }
    console.log("Portfolio snapshot recorded");
  } catch (err) {
    console.error("Portfolio snapshot failed:", err.message);
  }
}

module.exports = { recordDailySnapshot };