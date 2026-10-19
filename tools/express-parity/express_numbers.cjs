// Read-only harness: serves the real Express `GET /api/holdings` route over an
// ephemeral port against a scratch database, then captures the raw JSON body of
// a seeded document. server/index.js is never required, so no cron job starts.
//
// Env: ZERODHA_SERVER (required), PARITY_MONGO, PARITY_OUT_DIR.
"use strict";

const path = require("path");
const fs = require("fs");

const SERVER = process.env.ZERODHA_SERVER;
const MONGO = process.env.PARITY_MONGO || "mongodb://127.0.0.1:27017";
const OUT_DIR = process.env.PARITY_OUT_DIR || path.join(__dirname, "out");
const DB_NAME = "tradium_parity_express_numbers";
const SECRET = "parity-harness-secret-not-a-real-key";

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
const jsonwebtoken = require(path.join(SERVER, "node_modules", "jsonwebtoken"));

const USER_ID = "652f1c9b8a1e4d3c2b1a0f99";

(async () => {
  await mongoose.connect(`${MONGO}/${DB_NAME}?directConnection=true`);
  await mongoose.connection.dropDatabase();
  const raw = mongoose.connection.db.collection("holdings");

  // Seeded with the Node driver directly, so the stored BSON types are exactly
  // what the values below imply (whole numbers -> int32, 2500.0 -> double).
  const now = new Date("2026-09-01T04:15:30.123Z");
  await raw.insertMany([
    {
      _id: new mongoose.Types.ObjectId("652f1c9b8a1e4d3c2b1b0001"),
      user: new mongoose.Types.ObjectId(USER_ID),
      symbol: "WHOLE",
      name: "Whole float",
      exchange: "NSE",
      qty: 10,
      avgPrice: 2400.5,
      ltp: 2500.0,
      dayChangePct: 0.0,
      sector: "Energy",
      createdAt: now,
      updatedAt: now,
      __v: 0,
    },
    {
      _id: new mongoose.Types.ObjectId("652f1c9b8a1e4d3c2b1b0002"),
      user: new mongoose.Types.ObjectId(USER_ID),
      symbol: "EDGE",
      name: "Edge values",
      exchange: "NSE",
      qty: 3,
      avgPrice: 0.1 + 0.2,
      ltp: 1e21,
      dayChangePct: -0.0,
      sector: "",
      createdAt: now,
      updatedAt: now,
      __v: 0,
    },
    {
      _id: new mongoose.Types.ObjectId("652f1c9b8a1e4d3c2b1b0003"),
      user: new mongoose.Types.ObjectId(USER_ID),
      symbol: "INTZERO",
      name: "Integer zeros",
      exchange: "NSE",
      qty: 7,
      avgPrice: 100,
      ltp: 0,
      dayChangePct: 0,
      sector: "",
      createdAt: now,
      updatedAt: now,
      __v: 0,
    },
  ]);

  const app = express();
  app.use(express.json());
  app.use(cookieParser());
  app.use("/api/holdings", require(path.join(SERVER, "routes", "holdingsRoutes")));

  const server = app.listen(0, "127.0.0.1");
  await new Promise((resolve) => server.once("listening", resolve));
  const base = `http://127.0.0.1:${server.address().port}`;

  const token = jsonwebtoken.sign({ id: USER_ID }, SECRET, { expiresIn: "7d" });
  const response = await fetch(`${base}/api/holdings`, {
    headers: { cookie: `token=${token}` },
  });
  const bodyText = await response.text();

  // Also record plain JSON.stringify on the hydrated documents, which is what
  // res.json() does for a non-document payload.
  const { HoldingsModel } = require(path.join(SERVER, "models", "HoldingsModel"));
  const hydrated = await HoldingsModel.find({ user: USER_ID }).lean(false);

  fs.writeFileSync(
    path.join(OUT_DIR, "express_numbers.json"),
    JSON.stringify(
      {
        implementation: "express",
        status: response.status,
        contentType: response.headers.get("content-type"),
        bodyText,
        stringifiedHydratedDocs: JSON.stringify(hydrated),
      },
      null,
      2,
    ),
    "utf8",
  );

  await mongoose.connection.dropDatabase();
  await mongoose.disconnect();
  await new Promise((resolve) => server.close(resolve));
})().catch((err) => {
  console.error("harness failed:", err && err.message);
  process.exitCode = 1;
});
