const { Schema, model } = require("mongoose");

const PositionsSchema = new Schema({
  user: { type: Schema.Types.ObjectId, ref: "User", required: true },
  symbol: { type: String, required: true },
  name: { type: String, required: true },
  exchange: { type: String, enum: ["NSE"], default: "NSE" },
  side: { type: String, enum: ["LONG", "SHORT"], required: true },
  product: { type: String, enum: ["CNC", "MIS"], required: true },
  qty: { type: Number, required: true },
  entry: { type: Number, required: true },
  ltp: { type: Number, default: 0 },
}, { timestamps: true });

// one position per user+symbol+side+product — long and short coexist, but no duplicates
PositionsSchema.index({ user: 1, symbol: 1, exchange: 1, side: 1, product: 1 }, { unique: true });

const PositionsModel = model("position", PositionsSchema);

module.exports = { PositionsModel };
