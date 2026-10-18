const express = require("express");
const router = express.Router();
const { protect } = require("../middlewares/auth");
const { HoldingsModel } = require("../models/HoldingsModel");

router.get("/", protect, async (req, res) => {
  const holdings = await HoldingsModel.find({ user: req.userId });
  res.json(holdings);
});

module.exports = router;