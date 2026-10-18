const { Schema, model } = require("mongoose");

// Shared cache — same market data for everyone.
const MarketQuoteSchema = new Schema({
  // Symbol; unique because the sync job upserts on it.
  symbol: { type: String, required: true, unique: true },
  name: { type: String, required: true },
  // Indices have no .NS suffix and no sector.
  kind: { type: String, enum: ["stock", "index"], default: "stock" },

  ltp: { type: Number, default: 0 },
  dayChange: { type: Number, default: 0 },
  dayChangePct: { type: Number, default: 0 },
  prevClose: { type: Number, default: 0 },
  volume: { type: Number, default: 0 },
  // Used to size the treemap tiles.
  marketCap: { type: Number, default: 0 },

  // Filled by a one-time backfill; may stay empty.
  sector: { type: String, default: "" },
  // No asOf field — updatedAt already reports the cache's age.
}, { timestamps: true });

const MarketQuoteModel = model("MarketQuote", MarketQuoteSchema);

module.exports = { MarketQuoteModel };
