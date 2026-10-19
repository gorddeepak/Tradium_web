// Read-only harness: loads the original Express auth router in an isolated
// process, on a scratch database and an ephemeral port. It never requires
// server/index.js, so no cron job, market sync or AI call is started.
//
// Env: ZERODHA_SERVER (required), PARITY_MONGO, PARITY_OUT_DIR.
"use strict";

const path = require("path");
const fs = require("fs");

const SERVER = process.env.ZERODHA_SERVER;
const MONGO = process.env.PARITY_MONGO || "mongodb://127.0.0.1:27017";
const OUT_DIR = process.env.PARITY_OUT_DIR || path.join(__dirname, "out");
const DB_NAME = "tradium_parity_express_auth";

if (!SERVER) {
  console.error("ZERODHA_SERVER must point at the original checkout's server/ directory");
  process.exit(2);
}
fs.mkdirSync(OUT_DIR, { recursive: true });

// Same local-only secret on both sides; never printed.
process.env.JWT_SECRET = "parity-harness-secret-not-a-real-key";
delete process.env.NODE_ENV;

const mongoose = require(path.join(SERVER, "node_modules", "mongoose"));
const express = require(path.join(SERVER, "node_modules", "express"));
const cookieParser = require(path.join(SERVER, "node_modules", "cookie-parser"));
const authRoutes = require(path.join(SERVER, "routes", "authRoutes"));

function parseSetCookie(line) {
  const parts = line.split(";").map((part) => part.trim());
  const [pair, ...attrs] = parts;
  const eq = pair.indexOf("=");
  const name = eq === -1 ? pair : pair.slice(0, eq);
  const value = eq === -1 ? "" : pair.slice(eq + 1);
  const attributes = {};
  for (const attr of attrs) {
    const i = attr.indexOf("=");
    if (i === -1) attributes[attr.toLowerCase()] = true;
    else attributes[attr.slice(0, i).toLowerCase()] = attr.slice(i + 1);
  }
  return { name, valueLength: value.length, attributes };
}

function decodeJwt(token) {
  try {
    const [header, payload] = token.split(".");
    return {
      header: JSON.parse(Buffer.from(header, "base64url").toString("utf8")),
      payload: JSON.parse(Buffer.from(payload, "base64url").toString("utf8")),
    };
  } catch {
    return null;
  }
}

function tokenValue(line) {
  const [pair] = line.split(";");
  const eq = pair.indexOf("=");
  if (eq === -1 || pair.slice(0, eq).trim() !== "token") return null;
  return pair.slice(eq + 1).trim();
}

(async () => {
  await mongoose.connect(`${MONGO}/${DB_NAME}?directConnection=true`);
  await mongoose.connection.dropDatabase();

  const app = express();
  app.use(express.json());
  app.use(cookieParser());
  app.use("/api/auth", authRoutes);

  const server = app.listen(0, "127.0.0.1");
  await new Promise((resolve) => server.once("listening", resolve));
  const base = `http://127.0.0.1:${server.address().port}`;

  const jar = {};
  async function call(method, endpoint, body) {
    const cookieHeader = Object.entries(jar)
      .map(([k, v]) => `${k}=${v}`)
      .join("; ");
    const headers = {};
    if (body !== undefined) headers["content-type"] = "application/json";
    if (cookieHeader) headers["cookie"] = cookieHeader;
    const response = await fetch(base + endpoint, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const text = await response.text();
    const rawCookies = response.headers.getSetCookie();
    const tokens = [];
    for (const line of rawCookies) {
      const [pair] = line.split(";");
      const eq = pair.indexOf("=");
      jar[pair.slice(0, eq).trim()] = pair.slice(eq + 1).trim();
      const token = tokenValue(line);
      if (token !== null) tokens.push(token);
    }
    return {
      method,
      path: endpoint,
      status: response.status,
      contentType: response.headers.get("content-type"),
      bodyText: text,
      setCookies: rawCookies.map(parseSetCookie),
      tokenCookies: tokens,
    };
  }

  const signup = await call("POST", "/api/auth/signup", {
    username: "parityuser",
    email: "parity@example.com",
    password: "password123",
  });
  const signupJwt = signup.tokenCookies[0] ? decodeJwt(signup.tokenCookies[0]) : null;

  const meAuthed = await call("GET", "/api/auth/me");
  const login = await call("POST", "/api/auth/login", {
    email: "parity@example.com",
    password: "password123",
  });
  const loginJwt = login.tokenCookies[0] ? decodeJwt(login.tokenCookies[0]) : null;

  const logout = await call("POST", "/api/auth/logout");
  const meAfterLogout = await call("GET", "/api/auth/me");
  const meAnonymous = await call("GET", "/api/auth/me");
  const badLogin = await call("POST", "/api/auth/login", {
    email: "parity@example.com",
    password: "wrong-password",
  });

  const result = {
    implementation: "express",
    dbName: DB_NAME,
    sequence: [
      { name: "signup", ...signup, jwt: signupJwt },
      { name: "meAuthed", ...meAuthed },
      { name: "login", ...login, jwt: loginJwt },
      { name: "logout", ...logout },
      { name: "meAfterLogout", ...meAfterLogout },
      { name: "meAnonymous", ...meAnonymous },
      { name: "badLogin", ...badLogin },
    ],
  };
  fs.writeFileSync(path.join(OUT_DIR, "express_auth.json"), JSON.stringify(result, null, 2), "utf8");

  await mongoose.connection.dropDatabase();
  await mongoose.disconnect();
  await new Promise((resolve) => server.close(resolve));
})().catch((err) => {
  console.error("harness failed:", err && err.message);
  process.exitCode = 1;
});
