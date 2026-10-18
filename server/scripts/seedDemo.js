/* Seeds one demo account with a realistic NSE portfolio for the landing-page
   screenshots — live prices plus cost ratios so splits can't break the numbers.
   Run with:  npm run seed        (from server/) */

require("dotenv").config({ path: require("path").join(__dirname, "..", ".env") });

const mongoose = require("mongoose");
const YahooFinance = require("yahoo-finance2").default;

const User = require("../models/User");
const { HoldingsModel } = require("../models/HoldingsModel");
const { PositionsModel } = require("../models/PositionsModel");
const { OrdersModel } = require("../models/OrdersModel");
const { WatchlistModel } = require("../models/WatchlistModel");
const { FundsModel } = require("../models/FundsModel");
const { TransactionModel } = require("../models/TransactionModel");
const { PortfolioSnapshotModel } = require("../models/PortfolioSnapshotModel");
const { misComponents } = require("../utils/portfolioMath");

const yahooFinance = new YahooFinance();

/* The only accounts this script will ever touch. The email is the identity —
   login and the safety guard below both key on it. */
const ACCOUNTS = [
  { email: "demo@tradium.local", name: "Deepak", password: "demo1234", rename: true },
  { email: "deepak@gmail.com",   name: "Deepak", password: null,       rename: false },
];

// costFactor = avgPrice / live price: below 1 a gain, above 1 a loss.
// Six rows (the donut's cap), mostly green with one red — sized to fit the
// 1440x900 screenshot. Quantities are balanced so the allocation donut shows
// no slice above ~1/4 of the ring.
const holdings = [
  { symbol: "SBIN",       name: "State Bank of India",    qty: 120, costFactor: 0.872, fallback: 1008.00 },
  { symbol: "HINDUNILVR", name: "Hindustan Unilever",     qty: 50,  costFactor: 0.968, fallback: 1980.00 },
  { symbol: "BHARTIARTL", name: "Bharti Airtel",          qty: 35,  costFactor: 0.931, fallback: 1844.00 },
  { symbol: "HDFCBANK",   name: "HDFC Bank",              qty: 70,  costFactor: 1.062, fallback: 703.00 },
  { symbol: "RELIANCE",   name: "Reliance Industries",    qty: 40,  costFactor: 0.918, fallback: 1294.90 },
  { symbol: "ITC",        name: "ITC",                    qty: 150, costFactor: 0.955, fallback: 412.00 },
];

/* MIS-only, long and short on both sides, so every P&L sign combination shows. */
const positions = [
  { symbol: "KOTAKBANK",  name: "Kotak Mahindra Bank",       side: "LONG",  product: "MIS",  qty: 300, entryFactor: 0.982, fallback: 392.70 },
  { symbol: "TCS",        name: "Tata Consultancy Services", side: "SHORT", product: "MIS",  qty: 20,  entryFactor: 0.994, fallback: 2313.20 },
  { symbol: "NTPC",       name: "NTPC",                      side: "LONG",  product: "MIS",  qty: 250, entryFactor: 0.943, fallback: 341.90 },
  { symbol: "CIPLA",      name: "Cipla",                     side: "LONG",  product: "MIS",  qty: 55,  entryFactor: 1.019, fallback: 1548.70 },
  { symbol: "ASIANPAINT", name: "Asian Paints",              side: "SHORT", product: "MIS",  qty: 40,  entryFactor: 1.022, fallback: 2456.30 },
];

/* Staggered times and all four statuses so the orders tabs all show data. */
const orders = [
  { symbol: "AXISBANK",   name: "Axis Bank",                 side: "BUY",  type: "MARKET", product: "CNC",  qty: 38,  filled: 38,  priceFactor: 0.998, fallback: 1227.30,  status: "EXECUTED",  minutesAgo: 18 },
  { symbol: "POWERGRID",  name: "Power Grid Corporation",    side: "BUY",  type: "LIMIT",  product: "CNC",  qty: 300, filled: 120, priceFactor: 0.977, fallback: 284.60,   status: "OPEN",      minutesAgo: 95 },
  { symbol: "INFY",       name: "Infosys",                   side: "SELL", type: "MARKET", product: "CNC",  qty: 15,  filled: 15,  priceFactor: 1.001, fallback: 1139.90,  status: "EXECUTED",  minutesAgo: 210 },
  { symbol: "ICICIBANK",  name: "ICICI Bank",                side: "BUY",  type: "LIMIT",  product: "CNC",  qty: 50,  filled: 0,   priceFactor: 0.970, fallback: 1415.30,  status: "CANCELLED", minutesAgo: 620 },
  { symbol: "GRASIM",     name: "Grasim Industries",         side: "SELL", type: "LIMIT",  product: "MIS",  qty: 60,  filled: 0,   priceFactor: 1.031, fallback: 2764.80,  status: "REJECTED",  minutesAgo: 1408 },
];

// Watchlist shows only live prices, so no factors — and names the account doesn't hold.
// Pick symbols the demo account does NOT already hold (from holdings/positions) so
// the rail shows live prices for unfamiliar tickers.
const watchlist = [
  { symbol: "ULTRACEMCO", name: "UltraTech Cement",        fallback: 11681.00 },
  { symbol: "NESTLEIND",  name: "Nestle India",            fallback: 1189.40 },
  { symbol: "HCLTECH",    name: "HCL Technologies",        fallback: 1476.20 },
  { symbol: "ONGC",       name: "Oil & Natural Gas Corp",  fallback: 246.85 },
  { symbol: "ADANIENT",   name: "Adani Enterprises",       fallback: 2318.60 },
  { symbol: "INFY",       name: "Infosys",                 fallback: 1450.00 },
  { symbol: "MARUTI",     name: "Maruti Suzuki",           fallback: 9850.00 },
  { symbol: "SUNPHARMA",  name: "Sun Pharma",              fallback: 1120.00 },
  { symbol: "TITAN",      name: "Titan Company",           fallback: 3200.00 },
];

// Scaled to match the size of the book.
const funds = { available: 284650.40 };

// Signed like the funds route writes them: deposits/settlements positive, withdrawals/fees negative.
const transactions = [
  { kind: "DEPOSIT",    method: "Net banking",       amount:  35000.00, status: "PROCESSING", daysAgo: 1 },
  { kind: "DEPOSIT",    method: "Bank transfer",     amount:  50000.00, status: "COMPLETED",  daysAgo: 2 },
  { kind: "SETTLEMENT", method: "T+1 settlement",    amount:  18420.50, status: "COMPLETED",  daysAgo: 3 },
  { kind: "FEE",        method: "Brokerage & taxes", amount:   -284.30, status: "COMPLETED",  daysAgo: 4 },
  { kind: "WITHDRAWAL", method: "Bank withdrawal",   amount: -25000.00, status: "COMPLETED",  daysAgo: 6 },
];

// One quote per unique symbol, shared by everything below.
async function fetchPrices(symbols) {
  const prices = {};

  for (const symbol of symbols) {
    try {
      const quote = await yahooFinance.quote(`${symbol}.NS`);
      prices[symbol] = {
        ltp: quote.regularMarketPrice ?? 0,
        dayChangePct: quote.regularMarketChangePercent ?? 0,
      };
    } catch (err) {
      console.warn(`  ${symbol}: live quote failed (${err.message}) — using fallback`);
    }
  }

  return prices;
}

const round2 = (n) => Math.round(n * 100) / 100;

// Deterministic PRNG (mulberry32): a fixed seed makes every re-seed identical.
function mulberry32(seed) {
  return function () {
    seed |= 0; seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// 370 days of daily snapshots so every chart range has data. The chart draws
// value AND invested, so the walk is on the P&L percent: value(i) is always
// investedOn(i) × (1 + pct), meaning the gap between the two lines is the
// running unrealized profit at every point — never a gap the headline numbers
// contradict. The walk is then nudged to end exactly at today's real P&L.
// Each tranche ramps in over ~3 weeks instead of stepping overnight, because
// a one-day ₹50k jump in both lines reads as fake on the chart.
const TRADES = [
  { day: 0,   fraction: 0.30 }, // opening tranche
  { day: 100, fraction: 0.50 },
  { day: 210, fraction: 0.70 },
  { day: 330, fraction: 0.80 }, // ~5 weeks back — visible in 1M
  { day: 341, fraction: 0.90 }, // ~4 weeks back
  { day: 351, fraction: 0.84 }, // a partial SELL — cost basis ramps DOWN
  { day: 361, fraction: 1.00 }, // final buy lands at today's real invested
];

const RAMP_DAYS = 20; // how long each tranche takes to land

function buildSnapshots(userId, endValue, invested) {
  const days = 370;
  const rand = mulberry32(42);

  // investedOn(i): piecewise-linear ramps. Each trade ramps from the previous
  // fraction to its own over min(RAMP_DAYS, gap to the next trade), ending
  // exactly on the trade day. Between ramps it's flat.
  const investedOn = (i) => {
    // Find the segment that day i falls into.
    let fraction = TRADES[0].fraction; // before any trade
    for (let k = 0; k < TRADES.length; k++) {
      const t = TRADES[k];
      if (t.day > i) {
        // i is before this trade, so fraction is the ramp from previous to this trade
        if (k === 0) {
          // before first trade, fraction stays at first fraction
          fraction = TRADES[0].fraction;
        } else {
          const prev = TRADES[k - 1];
          const from = prev.fraction;
          const to = t.fraction;
          const gap = t.day - prev.day;
          const rampLen = Math.min(RAMP_DAYS, gap);
          const rampStart = t.day - rampLen;
          if (i < rampStart) {
            fraction = from;
          } else {
            const t2 = (i - rampStart) / rampLen;
            fraction = from + (to - from) * t2;
          }
        }
        break;
      }
      // i is on or after this trade, move to next
      if (k === TRADES.length - 1) {
        // after last trade, fraction stays at last fraction
        fraction = t.fraction;
      }
    }
    return invested * fraction;
  };

  // today's real overall P&L percent — where the walk has to end up.
  const endPct = endValue / invested - 1;

  let pct = 0.04; // opened with a small early gain
  const path = [pct];

  for (let i = 1; i < days; i++) {
    let drift = 0.0005;
    if (i >= 210 && i <= 245) drift = -0.0032; // the mid-year correction
    if (i >= 246 && i <= 290) drift = 0.0018;  // recovery
    if (i >= 300) drift = 0.0009;              // a stronger final quarter
    if (i >= 344 && i <= 352) drift = -0.0035; // a late dip — the 1M window needs action
    if (i >= 353) drift = 0.0026;              // sharp recovery into today's real P&L
    pct += drift + (rand() - 0.5) * 0.014;
    path.push(pct);
  }

  // Blend out the difference linearly so the walk starts where it opened and
  // ends exactly at endPct (additive, so it also works if endPct is negative).
  const corrected = (i) => path[i] + (endPct - path[days - 1]) * (i / (days - 1));

  const rows = [];

  for (let i = 0; i < days; i++) {
    const date = new Date();
    date.setDate(date.getDate() - (days - i));
    date.setHours(0, 0, 0, 0);

    rows.push({
      user: userId,
      date,
      value: round2(investedOn(i) * (1 + corrected(i))),
      invested: round2(investedOn(i)),
    });
  }

  return rows;
}

async function seed() {
  if (process.env.NODE_ENV === "production") {
    console.error("Refusing to run: NODE_ENV is production.");
    process.exit(1);
  }

  if (!process.env.MONGO_URL) {
    console.error("MONGO_URL is missing. Copy server/.env.example to server/.env first.");
    process.exit(1);
  }

  const symbols = [...new Set([...holdings, ...positions, ...orders, ...watchlist].map((r) => r.symbol))];
  console.log(`Fetching live NSE quotes for ${symbols.length} symbols...`);
  const prices = await fetchPrices(symbols);
  console.log(`Got ${Object.keys(prices).length}/${symbols.length} live quotes`);

  // Live price when we have one, the row's own fallback when we don't.
  const priceOf = (row) => prices[row.symbol]?.ltp || row.fallback;
  const changeOf = (row) => prices[row.symbol]?.dayChangePct ?? 0;

  await mongoose.connect(process.env.MONGO_URL);
  console.log("Connected to MongoDB");

  for (const account of ACCOUNTS) {
    await seedAccount(account, prices, priceOf, changeOf);
  }

  await mongoose.disconnect();
}

async function seedAccount(account, prices, priceOf, changeOf) {
  let user = await User.findOne({ email: account.email });

  if (!user) {
    if (!account.password) {
      console.error(`User "${account.email}" does not exist and no password is set for it — skipping.`);
      return;
    }
    // new + save (not create/insertMany) so the password-hashing pre-save hook runs
    user = new User({ username: account.name, email: account.email, password: account.password });
    await user.save();
    console.log(`Created user "${account.name}" <${account.email}> / ${account.password}`);
  } else if (account.rename && user.username !== account.name) {
    /* Renaming is safe: the pre-save hash hook only runs when `password` changes. */
    const old = user.username;
    user.username = account.name;
    await user.save();
    console.log(`Renamed existing user "${old}" -> "${account.name}"`);
  } else {
    console.log(`Reusing existing user "${user.username}" <${account.email}>`);
  }

  // Second safety guard before wiping anything.
  if (user.email !== account.email) {
    console.error(`Refusing to wipe data for "${user.email}".`);
    process.exit(1);
  }

  console.log(`\n--- Seeding ${account.email} ---`);
  const scope = { user: user._id };

  await Promise.all([
    HoldingsModel.deleteMany(scope),
    PositionsModel.deleteMany(scope),
    OrdersModel.deleteMany(scope),
    WatchlistModel.deleteMany(scope),
    FundsModel.deleteMany(scope),
    TransactionModel.deleteMany(scope),
    PortfolioSnapshotModel.deleteMany(scope),
  ]);
  console.log("Cleared existing demo data");

  const holdingDocs = holdings.map((h) => ({
    user: user._id,
    exchange: "NSE",
    symbol: h.symbol,
    name: h.name,
    qty: h.qty,
    avgPrice: round2(priceOf(h) * h.costFactor),
    ltp: priceOf(h),
    dayChangePct: round2(changeOf(h)),
  }));

  const positionDocs = positions.map((p) => ({
    user: user._id,
    exchange: "NSE",
    symbol: p.symbol,
    name: p.name,
    side: p.side,
    product: p.product,
    qty: p.qty,
    entry: round2(priceOf(p) * p.entryFactor),
    ltp: priceOf(p),
  }));

  const watchlistDocs = watchlist.map((w) => ({
    user: user._id,
    exchange: "NSE",
    symbol: w.symbol,
    name: w.name,
    ltp: priceOf(w),
    dayChangePct: round2(changeOf(w)),
  }));

  await HoldingsModel.insertMany(holdingDocs);
  await PositionsModel.insertMany(positionDocs);
  await WatchlistModel.insertMany(watchlistDocs);
  await FundsModel.create({ ...funds, user: user._id });

  // timestamps: false keeps our staggered order times on insert.
  await OrdersModel.insertMany(
    orders.map((o) => {
      const at = new Date(Date.now() - o.minutesAgo * 60 * 1000);
      return {
        user: user._id,
        exchange: "NSE",
        symbol: o.symbol,
        name: o.name,
        side: o.side,
        type: o.type,
        product: o.product,
        qty: o.qty,
        filled: o.filled,
        price: round2(priceOf(o) * o.priceFactor),
        status: o.status,
        createdAt: at,
        updatedAt: at,
      };
    }),
    { timestamps: false },
  );

  // Same timestamps: false trick, so the ledger spans a month instead of one instant.
  await TransactionModel.insertMany(
    transactions.map((t) => {
      const at = new Date(Date.now() - t.daysAgo * 24 * 60 * 60 * 1000);
      return {
        user: user._id,
        kind: t.kind,
        method: t.method,
        amount: t.amount,
        status: t.status,
        createdAt: at,
        updatedAt: at,
      };
    }),
    { timestamps: false },
  );

  const currentValue = holdingDocs.reduce((sum, h) => sum + h.qty * h.ltp, 0);
  const invested = holdingDocs.reduce((sum, h) => sum + h.qty * h.avgPrice, 0);

  // Whole-account numbers, matching what the /history route appends as today's
  // live point (holdings + open MIS). Snapshots seeded without MIS made the
  // chart's last point jump ~2x the day the MIS legs appeared.
  const { misValue, misInvested } = misComponents(positionDocs);

  // MIS legs held flat across history — good enough for demo data and keeps
  // every point consistent with the live point the route stitches on.
  await PortfolioSnapshotModel.insertMany(buildSnapshots(user._id, currentValue + misValue, invested + misInvested));

  const pnl = currentValue - invested;

  // Print today's P&L too — the one figure the seed can't control.
  const dayPnl = holdingDocs.reduce((sum, h) => sum + h.qty * ((h.ltp * h.dayChangePct) / (100 + h.dayChangePct)), 0);

  const inr = (n) => `${n < 0 ? "-" : "+"}₹${Math.abs(Math.round(n)).toLocaleString("en-IN")}`;
  const plain = (n) => `₹${Math.round(n).toLocaleString("en-IN")}`;

  console.log(`
Seeded ${holdings.length} holdings, ${positions.length} positions, ${orders.length} orders, ${watchlist.length} watchlist rows, ${transactions.length} transactions, 370 snapshots.
  Invested     ${plain(invested)}
  Value        ${plain(currentValue)}
  Overall P&L  ${inr(pnl)}  (${((pnl / invested) * 100).toFixed(2)}%)   <- ours, via costFactor
  Today's P&L  ${inr(dayPnl)}  (${((dayPnl / (currentValue - dayPnl)) * 100).toFixed(2)}%)   <- live market, not ours
  Log in as    ${account.email}${account.password ? ` / ${account.password}` : " (existing password)"}
`);
}

seed().catch((err) => {
  console.error(err);
  process.exit(1);
});
