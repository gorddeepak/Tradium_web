const { Schema, model } = require("mongoose");

const FundsSchema = new Schema({
  user: { type: Schema.Types.ObjectId, ref: "User", required: true, unique: true },
  available: { type: Number, default: 0 },
}, { timestamps: true });

const FundsModel = model("funds", FundsSchema);

module.exports = { FundsModel };
