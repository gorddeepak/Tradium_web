const { Schema, model } = require("mongoose");

const WatchlistSchema = new Schema({
  user: { type: Schema.Types.ObjectId, ref: "User", required: true },
  symbol: { type: String, required: true },
  name: { type: String, required: true },
  exchange: { type: String, enum: ["NSE"], default: "NSE" },
  ltp: { type: Number, default: 0 },
  dayChangePct: { type: Number, default: 0 },
}, { timestamps: true });

// one row per user+symbol — stops a double-click duplicating before this index existed
WatchlistSchema.index({ user: 1, symbol: 1, exchange: 1 }, { unique: true });

const WatchlistModel = model("watchlist", WatchlistSchema);

module.exports = { WatchlistModel };
