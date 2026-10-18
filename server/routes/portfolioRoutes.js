const express = require("express");
const router = express.Router();
const { protect } = require("../middlewares/auth");
const { PortfolioSnapshotModel } = require("../models/PortfolioSnapshotModel");
const { HoldingsModel } = require("../models/HoldingsModel");
const { PositionsModel } = require("../models/PositionsModel");
const { misComponents } = require("../utils/portfolioMath");

router.get("/history", protect, async (req, res) => {
  const range = req.query.range || "1M";
  const days = { "1D": 1, "1W": 7, "1M": 30, "1Y": 365, ALL: 100000 }[range] ?? 30;
  const since = new Date();
  since.setDate(since.getDate() - days);

  const snapshots = await PortfolioSnapshotModel.find({
    user: req.userId,
    date: { $gte: since },
  }).sort({ date: 1 });

  // en-CA formats dates as YYYY-MM-DD.
  const localDate = (d) => d.toLocaleDateString("en-CA");

  // Chart shows holdings + MIS combined.
  const series = snapshots.map((s) => ({
    label: localDate(s.date),
    value: s.value + (s.misValue || 0),
    // send null for pre-`invested` snapshots so the chart leaves a gap, not a drop to zero
    invested: s.invested ? s.invested + (s.misInvested || 0) : null,
  }));

  // append today's live value so the chart reflects current holdings, not just the last snapshot
  const holdings = await HoldingsModel.find({ user: req.userId });
  const currentValue = holdings.reduce((sum, h) => sum + h.qty * h.ltp, 0);
  const currentInvested = holdings.reduce((sum, h) => sum + h.qty * h.avgPrice, 0);
  const positions = await PositionsModel.find({ user: req.userId, product: "MIS" });
  const { misValue, misInvested } = misComponents(positions);
  const todayLabel = localDate(new Date());

  if (series.length === 0 || series[series.length - 1].label !== todayLabel) {
    series.push({ label: todayLabel, value: currentValue + misValue, invested: currentInvested + misInvested });
  } else {
    // today's snapshot already exists — just overwrite it with the freshest live value
    series[series.length - 1].value = currentValue + misValue;
    series[series.length - 1].invested = currentInvested + misInvested;
  }

  res.json(series);
});

module.exports = router;