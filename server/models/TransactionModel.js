const { Schema, model, models } = require("mongoose");

const TransactionSchema = new Schema({
  user: { type: Schema.Types.ObjectId, ref: "User", required: true },
  kind: { type: String, enum: ["DEPOSIT", "WITHDRAWAL", "SETTLEMENT", "FEE"], required: true },
  method: { type: String, default: "Bank transfer" },
  amount: { type: Number, required: true },
  // only SETTLEMENT rows carry this — the symbol the closed trade was in
  symbol: { type: String, default: "" },
  status: { type: String, enum: ["COMPLETED", "PROCESSING"], default: "PROCESSING" },
}, { timestamps: true });

const TransactionModel = models.transaction || model("transaction", TransactionSchema);

module.exports = { TransactionModel };
