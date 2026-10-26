// Read-only harness: serves the real Express read routes (orders, watchlist,
// positions, funds, funds/transactions, market/overview and
// instruments/search) over an ephemeral port against a scratch database seeded
// from routes_scenario.json, then captures the raw JSON body of each.
//
// server/index.js is never required, so no cron job, market sync or AI call
// starts. The instrument lookup/detail routes are deliberately not called: they
// reach Yahoo, and the harness must stay offline.
//
// Env: ZERODHA_SERVER (required), PARITY_MONGO, PARITY_OUT_DIR, PARITY_ROUTES_SCENARIO.
"use strict";

const path = require("path");
const fs = require("fs");

const SERVER = process.env.ZERODHA_SERVER;
const MONGO = process.env.PARITY_MONGO || "mongodb://127.0.0.1:27017";
const OUT_DIR = process.env.PARITY_OUT_DIR || path.join(__dirname, "out");
const SCENARIO = process.env.PARITY_ROUTES_SCENARIO || path.join(__dirname, "routes_scenario.json");
const DB_NAME = "tradium_parity_express_routes";
const SECRET = "parity-harness-secret-not-a-real-key";

const DATE_KEYS = new Set(["date", "createdAt", "updatedAt"]);
const HEX24 = /^[0-9a-f]{24}$/;

if (!SERVER) {
  console.error("ZERODHA_SERVER must point at the original checkout's server/ directory");
  process.exit(2);
}
fs.mkdirSync(OUT_DIR, { recursive: true });

process.env.JWT_SECRET = SECRET;
delete process.env.NODE_ENV;

const mongoose = require(path.join(SERVER, "node_modules", "mongoose"));
const express = require(path.join(SERVER, "node_modules", "express"));
const cookieParser = require(path.join(SERVER, "node_modules", "cookie-parser"));
const jwt = require(path.join(SERVER, "node_modules", "jsonwebtoken"));

const ordersRoutes = require(path.join(SERVER, "routes", "ordersRoutes"));
const watchlistRoutes = require(path.join(SERVER, "routes", "watchlistRoutes"));
const positionsRoutes = require(path.join(SERVER, "routes", "positionsRoutes"));
const fundsRoutes = require(path.join(SERVER, "routes", "fundsRoutes"));
const portfolioRoutes = require(path.join(SERVER, "routes", "portfolioRoutes"));
const marketRoutes = require(path.join(SERVER, "routes", "marketRoutes"));
const instrumentRoutes = require(path.join(SERVER, "routes", "instrumentRoutes"));

const ROUTES = [
  { name: "orders", path: "/api/orders" },
  { name: "watchlist", path: "/api/watchlist" },
  { name: "positions", path: "/api/positions" },
  { name: "funds", path: "/api/funds" },
  { name: "fundsTransactions", path: "/api/funds/transactions" },
  { name: "marketOverview", path: "/api/market/overview" },
  { name: "instrumentsSearchIN", path: "/api/instruments/search?q=IN" },
  { name: "instrumentsSearchBlank", path: "/api/instruments/search?q=" },
];

function convert(doc) {
  const out = {};
  for (const [key, value] of Object.entries(doc)) {
    if (typeof value === "string" && HEX24.test(value)) out[key] = new mongoose.Types.ObjectId(value);
    else if (DATE_KEYS.has(key) && typeof value === "string") out[key] = new Date(value);
    else out[key] = value;
  }
  if (out.__v === undefined) out.__v = 0;
  return out;
}

(async () => {
  await mongoose.connect(`${MONGO}/${DB_NAME}?directConnection=true`);
  await mongoose.connection.dropDatabase();

  const scenario = JSON.parse(fs.readFileSync(SCENARIO, "utf8"));
  const collections = [
    "users",
    "holdings",
    "positions",
    "watchlists",
    "orders",
    "funds",
    "transactions",
    "portfoliosnapshots",
    "marketquotes",
  ];
  for (const name of collections) {
    const docs = (scenario[name] || []).map(convert);
    if (docs.length) await mongoose.connection.db.collection(name).insertMany(docs);
  }

  const app = express();
  app.use(express.json());
  app.use(cookieParser());
  app.use("/api/orders", ordersRoutes);
  app.use("/api/watchlist", watchlistRoutes);
  app.use("/api/positions", positionsRoutes);
  app.use("/api/funds", fundsRoutes);
  app.use("/api/portfolio", portfolioRoutes);
  app.use("/api/market", marketRoutes);
  app.use("/api/instruments", instrumentRoutes);

  const server = app.listen(0, "127.0.0.1");
  await new Promise((resolve) => server.once("listening", resolve));
  const base = `http://127.0.0.1:${server.address().port}`;

  const token = jwt.sign({ id: scenario.user }, SECRET);

  const results = [];
  for (const route of ROUTES) {
    const response = await fetch(base + route.path, { headers: { cookie: `token=${token}` } });
    const bodyText = await response.text();
    results.push({
      name: route.name,
      path: route.path,
      status: response.status,
      contentType: response.headers.get("content-type"),
      bodyText,
    });
  }

  fs.writeFileSync(
    path.join(OUT_DIR, "express_routes.json"),
    JSON.stringify({ implementation: "express", dbName: DB_NAME, routes: results }, null, 2),
    "utf8"
  );

  await mongoose.connection.dropDatabase();
  await mongoose.disconnect();
  await new Promise((resolve) => server.close(resolve));
})().catch((err) => {
  console.error("harness failed:", err && err.message);
  process.exitCode = 1;
});
