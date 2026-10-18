const { Schema, model } = require("mongoose");

const HoldingsSchema = new Schema({
  user: { type: Schema.Types.ObjectId, ref: "User", required: true },
  symbol: { type: String, required: true },       // e.g. "RELIANCE"
  name: { type: String, required: true },          // e.g. "Reliance Industries"
  exchange: { type: String, enum: ["NSE"], default: "NSE" },
  qty: { type: Number, required: true },
  avgPrice: { type: Number, required: true },
  ltp: { type: Number, default: 0 },                // updated by the sync job
  dayChangePct: { type: Number, default: 0 },
  sector: { type: String, default: "" },             // backfilled once by the sync job
}, { timestamps: true });

// one holdings row per user+symbol — the unique index stops racing first buys duplicating
HoldingsSchema.index({ user: 1, symbol: 1, exchange: 1 }, { unique: true });

const HoldingsModel = model("holding", HoldingsSchema);

module.exports = { HoldingsModel };
