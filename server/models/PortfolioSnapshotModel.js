const { Schema, model } = require("mongoose");

const PortfolioSnapshotSchema = new Schema({
  user: { type: Schema.Types.ObjectId, ref: "User", required: true },
  date: { type: Date, required: true },
  value: { type: Number, required: true },
  // cost basis on that date (older snapshots default to 0).
  invested: { type: Number, default: 0 },
  // value of open MIS legs, stored separately for the backfill.
  misInvested: { type: Number, default: 0 },
  misValue: { type: Number, default: 0 },
}, { timestamps: true });

// one snapshot per user per day
PortfolioSnapshotSchema.index({ user: 1, date: 1 }, { unique: true });

const PortfolioSnapshotModel = model("PortfolioSnapshot", PortfolioSnapshotSchema);

module.exports = { PortfolioSnapshotModel };
