const YahooFinance = require("yahoo-finance2").default;
const yahooFinance = new YahooFinance();

const { MarketQuoteModel } = require("../models/MarketQuoteModel");
const { nifty50, indices } = require("../data/nifty50");
const { fetchSector } = require("./priceSync");
const { isMarketOpen } = require("../utils/marketHours");

// Yahoo ticker -> our row. Indices keep Yahoo's own ticker ("^NSEI"), stocks get ".NS".
const byTicker = new Map();
for (const { symbol, name } of indices) {
  byTicker.set(symbol, { symbol, name, kind: "index" });
}
for (const { symbol, name } of nifty50) {
  byTicker.set(`${symbol}.NS`, { symbol, name, kind: "stock" });
}
const tickers = [...byTicker.keys()];

// Only a few sectors resolved per run — quoteSummary is one call per symbol.
const SECTORS_PER_RUN = 10;

// One batched request for all 53 symbols; validateResult off so one odd row can't reject the batch.
async function syncQuotes() {
  let quotes;
  try {
    quotes = await yahooFinance.quote(tickers, {}, { validateResult: false });
  } catch (err) {
    // Keep the last good cache — stale prices beat an empty Markets page.
    console.error("Market sync failed, keeping previous cache:", err.message);
    return;
  }

  const ops = [];
  const seen = new Set();

  for (const q of quotes) {
    const row = byTicker.get(q.symbol);
    if (!row) continue; // Yahoo echoed something we didn't ask for
    seen.add(q.symbol);

    ops.push({
      updateOne: {
        filter: { symbol: row.symbol },
        // `sector` is left alone here — the backfill below owns it.
        update: {
          $set: {
            name: row.name,
            kind: row.kind,
            ltp: q.regularMarketPrice ?? 0,
            dayChange: q.regularMarketChange ?? 0,
            dayChangePct: q.regularMarketChangePercent ?? 0,
            prevClose: q.regularMarketPreviousClose ?? 0,
            volume: q.regularMarketVolume ?? 0,
            marketCap: q.marketCap ?? 0,
          },
        },
        upsert: true,
      },
    });
  }

  if (ops.length > 0) await MarketQuoteModel.bulkWrite(ops);

  const missing = tickers.filter((t) => !seen.has(t));
  console.log(`Market sync: ${ops.length}/${tickers.length} symbols cached`);
  if (missing.length > 0) {
    // Log the missing names — likely dead tickers after renames or demergers.
    console.warn(`Market sync: no quote for ${missing.join(", ")}`);
  }
}

// One-time fill: a stock's sector never changes, so it's outside the price cycle.
async function backfillSectors() {
  const pending = await MarketQuoteModel.find({ kind: "stock", sector: "" })
    .limit(SECTORS_PER_RUN);
  if (pending.length === 0) return;

  let filled = 0;
  for (const doc of pending) {
    const sector = await fetchSector(doc.symbol);
    if (!sector) continue;
    doc.sector = sector;
    await doc.save();
    filled += 1;
  }
  if (filled > 0) console.log(`Market sync: ${filled} sectors resolved`);
}

let isSyncing = false;
async function marketSync() {
  // Skip if the previous run is still going.
  if (isSyncing) return;
  isSyncing = true;
  // Catch errors here — node-cron ignores the promise, so a rejection would kill the server.
  try {
    const cached = await MarketQuoteModel.estimatedDocumentCount();

    // Only sync while the market is open (or if the cache is empty).
    if (isMarketOpen() || cached === 0) {
      await syncQuotes();
    }

    await backfillSectors();
  } catch (err) {
    console.error("Market sync failed:", err.message);
  } finally {
    isSyncing = false;
  }
}

module.exports = { marketSync };
