const express = require("express");
const router = express.Router();
const { protect } = require("../middlewares/auth");
const { MarketQuoteModel } = require("../models/MarketQuoteModel");
const { indices: indexSeed } = require("../data/nifty50");

// Display order for the indices strip — find() makes no ordering promise, so it lives here.
const indexOrder = indexSeed.map((i) => i.symbol);

// Reads the cache only, no Yahoo call — the client slices the ~50 rows itself.
router.get("/overview", protect, async (req, res) => {
  const rows = await MarketQuoteModel.find({}).lean();

  const indices = rows
    .filter((r) => r.kind === "index")
    .sort((a, b) => indexOrder.indexOf(a.symbol) - indexOrder.indexOf(b.symbol));

  const stocks = rows.filter((r) => r.kind === "stock");

  // Freshest row's time, so the page can say when this was last refreshed (null = cold cache).
  const asOf = rows.reduce(
    (latest, r) => (!latest || r.updatedAt > latest ? r.updatedAt : latest),
    null
  );

  res.json({ asOf, indices, stocks });
});

module.exports = router;
