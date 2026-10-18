const { Schema, model } = require("mongoose");

const OrdersSchema = new Schema({
  user: { type: Schema.Types.ObjectId, ref: "User", required: true },
  symbol: { type: String, required: true },
  name: { type: String, required: true },
  exchange: { type: String, enum: ["NSE"], default: "NSE" },
  side: { type: String, enum: ["BUY", "SELL"], required: true },
  // SL/SL-M use triggerPrice; for LIMIT/MARKET it stays 0
  type: { type: String, enum: ["MARKET", "LIMIT", "SL", "SL-M"], required: true },
  product: { type: String, enum: ["CNC", "MIS"], required: true },
  qty: { type: Number, required: true },
  filled: { type: Number, default: 0 },
  price: { type: Number, required: true },
  triggerPrice: { type: Number, default: 0 },
  // Bracket fields — the server spawns exit orders from these after the entry fills.
  slTrigger: { type: Number, default: 0 },
  tpPrice: { type: Number, default: 0 },
  // Exits share the entry's groupId; filling one cancels the other (OCO).
  groupId: { type: String, default: "" },
  // true for spawned exit legs (or a pair placed from Holdings/Positions)
  isExit: { type: Boolean, default: false },
  status: { type: String, enum: ["EXECUTED", "OPEN", "CANCELLED", "REJECTED"], default: "OPEN" },
}, { timestamps: true });  // createdAt gives you the order time automatically

const OrdersModel = model("order", OrdersSchema);

module.exports = { OrdersModel };
