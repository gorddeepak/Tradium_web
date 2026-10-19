// Read-only harness: seeds scenario.json into a scratch database, runs the real
// Express syncPrices() + recordDailySnapshot() with the provider stubbed, then
// dumps every collection with BSON types preserved.
// server/index.js is never required, so no cron job is registered.
//
// Env: ZERODHA_SERVER (required), PARITY_MONGO, PARITY_OUT_DIR, PARITY_SCENARIO.
"use strict";

const path = require("path");
const fs = require("fs");

const SERVER = process.env.ZERODHA_SERVER;
const MONGO = process.env.PARITY_MONGO || "mongodb://127.0.0.1:27017";
const OUT_DIR = process.env.PARITY_OUT_DIR || path.join(__dirname, "out");
const SCENARIO = process.env.PARITY_SCENARIO || path.join(__dirname, "scenario.json");
const DB_NAME = "tradium_parity_express_jobs";

if (!SERVER) {
  console.error("ZERODHA_SERVER must point at the original checkout's server/ directory");
  process.exit(2);
}
fs.mkdirSync(OUT_DIR, { recursive: true });

const scenario = JSON.parse(fs.readFileSync(SCENARIO, "utf8"));
const SEEDED = new Set(scenario.seededIds);

process.env.JWT_SECRET = "parity-harness-secret-not-a-real-key";
delete process.env.NODE_ENV;

// --- stub the two seams priceSync reaches for, before it is required ---
const Module = require("module");
const originalLoad = Module._load;

function symbolOf(ticker) {
  return String(ticker).replace(/\.NS$/, "");
}

class FakeYahooFinance {
  async quote(ticker) {
    const symbol = symbolOf(ticker);
    const found = scenario.quotes[symbol];
    if (!found || scenario.missingQuoteSymbols.includes(symbol)) return {};
    return {
      regularMarketPrice: found.ltp,
      regularMarketChangePercent: found.dayChangePct,
    };
  }

  async quoteSummary(ticker) {
    const sector = scenario.sectors[symbolOf(ticker)];
    if (!sector) return {};
    return { assetProfile: { sector } };
  }
}

Module._load = function (request, parent, isMain) {
  if (request === "yahoo-finance2") return { default: FakeYahooFinance };
  if (request === "../utils/marketHours") return { isMarketOpen: () => true };
  return originalLoad.apply(this, arguments);
};

const mongoose = require(path.join(SERVER, "node_modules", "mongoose"));
const ObjectId = mongoose.Types.ObjectId;

const stamp = new Date(scenario.now);
function toTimestamped(doc) {
  const out = { ...doc, createdAt: stamp, updatedAt: stamp, __v: 0 };
  out._id = new ObjectId(out._id);
  if (out.user) out.user = new ObjectId(out.user);
  return out;
}

function normalize(value, key) {
  if (value === null || value === undefined) return { t: "null" };
  if (value instanceof mongoose.mongo.BSON.ObjectId) {
    const hex = value.toHexString();
    return { t: "oid", v: SEEDED.has(hex) ? hex : "<oid>" };
  }
  if (value instanceof Date) {
    if (key === "createdAt" || key === "updatedAt") return { t: "date" };
    return { t: "date", v: value.toISOString() };
  }
  if (value instanceof mongoose.mongo.BSON.Double) return { t: "double", v: value.value };
  if (value instanceof mongoose.mongo.BSON.Int32) return { t: "int", v: value.value };
  if (value instanceof mongoose.mongo.BSON.Long) return { t: "long", v: value.toNumber() };
  if (typeof value === "number") {
    return { t: Number.isInteger(value) ? "int" : "double", v: value };
  }
  if (typeof value === "string") return { t: "str", v: value };
  if (typeof value === "boolean") return { t: "bool", v: value };
  if (Array.isArray(value)) return { t: "array", v: value.map((item) => normalize(item)) };
  if (typeof value === "object") {
    const out = {};
    for (const nested of Object.keys(value).sort()) out[nested] = normalize(value[nested], nested);
    return { t: "doc", v: out };
  }
  return { t: "unknown", v: String(value) };
}

const COLLECTIONS = [
  "users",
  "holdings",
  "positions",
  "watchlists",
  "orders",
  "funds",
  "transactions",
  "portfoliosnapshots",
];

(async () => {
  await mongoose.connect(`${MONGO}/${DB_NAME}?directConnection=true`);
  await mongoose.connection.dropDatabase();
  const raw = mongoose.connection.db;

  for (const name of ["users", "holdings", "positions", "watchlists", "orders", "funds"]) {
    if (scenario[name] && scenario[name].length) {
      await raw.collection(name).insertMany(scenario[name].map(toTimestamped));
    }
  }

  const { syncPrices } = require(path.join(SERVER, "jobs", "priceSync"));
  const { recordDailySnapshot } = require(path.join(SERVER, "jobs", "portfolioSnapshot"));

  await syncPrices();
  await recordDailySnapshot();

  const collections = {};
  for (const name of COLLECTIONS) {
    const docs = await raw
      .collection(name)
      .find({}, { promoteValues: false, promoteLongs: false })
      .toArray();
    collections[name] = docs
      .map((doc) => normalize(doc))
      .sort((a, b) => (JSON.stringify(a) < JSON.stringify(b) ? -1 : 1));
  }

  fs.writeFileSync(
    path.join(OUT_DIR, "express_jobs.json"),
    JSON.stringify({ implementation: "express", collections }, null, 2),
    "utf8",
  );

  await mongoose.connection.dropDatabase();
  await mongoose.disconnect();
})().catch((err) => {
  console.error("harness failed:", err && err.stack);
  process.exitCode = 1;
});
