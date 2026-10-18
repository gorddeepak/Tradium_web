// routes/instrumentRoutes.js
const express = require("express");
const router = express.Router();
const { protect } = require("../middlewares/auth");
const YahooFinance = require("yahoo-finance2").default;
const yahooFinance = new YahooFinance();

const { MarketQuoteModel } = require("../models/MarketQuoteModel");
const { tickerFor } = require("../utils/symbol");

// Must come before /:symbol. Searches the local cache, not Yahoo.
router.get("/search", protect, async (req, res) => {
  const q = (req.query.q || "").trim();
  if (!q) return res.json([]);

  const escaped = q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const pattern = new RegExp(escaped, "i");

  const rows = await MarketQuoteModel.find({
    $or: [{ symbol: pattern }, { name: pattern }],
  })
    .limit(10)
    .lean();

  res.json(
    rows.map((r) => ({
      symbol: r.symbol,
      name: r.name,
      kind: r.kind,
      price: r.ltp,
      changePct: r.dayChangePct,
    }))
  );
});

router.get("/lookup/:symbol", protect, async (req, res) => {
  const { symbol } = req.params;
  try {
    const quote = await yahooFinance.quote(tickerFor(symbol));
    if (!quote?.regularMarketPrice) return res.status(404).json({ message: "Instrument not found" });
    res.json({
      symbol: symbol.toUpperCase(),
      name: quote.longName || quote.shortName || symbol,
      exchange: "NSE",
      price: quote.regularMarketPrice,
      change: quote.regularMarketChange,
      changePct: quote.regularMarketChangePercent,
    });
  } catch {
    res.status(404).json({ message: "Instrument not found" });
  }
});

router.get("/:symbol", protect, async (req, res) => {
  const { symbol } = req.params;
  try {
    const q = await yahooFinance.quote(tickerFor(symbol));
    if (!q?.regularMarketPrice) return res.status(404).json({ message: "Instrument not found" });
    res.json({
      symbol: symbol.toUpperCase(),
      name: q.longName || q.shortName || symbol,
      exchange: "NSE",
      price: q.regularMarketPrice,
      change: q.regularMarketChange,
      changePct: q.regularMarketChangePercent,
      open: q.regularMarketOpen,
      high: q.regularMarketDayHigh,
      low: q.regularMarketDayLow,
      prevClose: q.regularMarketPreviousClose,
      volume: q.regularMarketVolume,
      week52High: q.fiftyTwoWeekHigh,
      week52Low: q.fiftyTwoWeekLow,
    });
  } catch {
    res.status(404).json({ message: "Instrument not found" });
  }
});

router.get("/:symbol/candles", protect, async (req, res) => {
  const { symbol } = req.params;
  const { range = "1M" } = req.query;

  const config = {
  "1D": { days: 3, interval: "1m" },
  "5D": { days: 5, interval: "5m" },
  "SPARK": { days: 6, interval: "1d" },
  "1M": { days: 30, interval: "30m" },
  "6M": { days: 182, interval: "60m" }, 
  "1Y": { days: 365, interval: "1d" },
  "5Y": { days: 365 * 5, interval: "1wk" },
  "ALL": { days: 365 * 20, interval: "1mo" },
}[range] ?? { days: 30, interval: "1d" };

  const period1 = new Date();
  period1.setDate(period1.getDate() - config.days);

  try {
    const result = await yahooFinance.chart(tickerFor(symbol), {
      period1,
      interval: config.interval,
    });
    // Shift timestamps to IST so the chart shows local time.
    const IST_OFFSET = 5.5 * 60 * 60;
    const candles = result.quotes
      .filter((q) => q.open != null)
      .map((q) => ({
        time: Math.floor(new Date(q.date).getTime() / 1000) + IST_OFFSET,
        open: q.open,
        high: q.high,
        low: q.low,
        close: q.close,
      }));
    res.json(candles);
  } catch (err) {
    console.error(`Candle fetch failed for ${symbol}:`, err.message);
    res.status(404).json({ message: "Could not fetch candle data" });
  }
});

module.exports = router;