const express = require("express");
const router = express.Router();
const { protect } = require("../middlewares/auth");
const { WatchlistModel } = require("../models/WatchlistModel");

router.get("/", protect, async (req, res) => {
  const items = await WatchlistModel.find({ user: req.userId });
  res.json(items);
});

router.post("/", protect, async (req, res) => {
  const { symbol, name, exchange } = req.body;
  // Validate the symbol shape — priceSync quotes it every 5 minutes, so junk burns Yahoo calls.
  // ^ is allowed as a leading char: Yahoo prefixes index tickers with it (^NSEI, ^BSESN).
  if (!symbol || !/^[\^A-Z0-9&-]{1,20}$/.test(symbol)) {
    return res.status(400).json({ message: "Invalid symbol" });
  }
  const exists = await WatchlistModel.findOne({ user: req.userId, symbol });
  if (exists) return res.status(409).json({ message: "Already in watchlist" });
  const item = await WatchlistModel.create({ user: req.userId, symbol, name, exchange });
  res.status(201).json(item);
});

router.delete("/:id", protect, async (req, res) => {
  await WatchlistModel.deleteOne({ _id: req.params.id, user: req.userId });
  res.status(204).end();
});

module.exports = router;