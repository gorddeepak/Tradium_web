/* Run with: npm run test:quotes

   These pin the rules that stop an older price from overwriting a newer one.
   They are plain functions, so no browser or React is involved. */

import test from "node:test";
import assert from "node:assert/strict";

import {
  isOlderQuote,
  isQuoteStale,
  isUsablePrice,
  mergeInstrumentQuote,
  mergeQuote,
  mergeQuoteRows,
  mergeQuotesMap,
  normalizeSymbol,
} from "./quoteMerge.js";

const NOW = "2026-10-30T10:00:00.000Z";
const LATER = "2026-10-30T10:00:05.000Z";

function stock(overrides = {}) {
  return {
    symbol: "INFY",
    name: "Infosys",
    qty: 10,
    ltp: 1500,
    dayChange: 10,
    dayChangePct: 0.67,
    updatedAt: "2026-10-30T09:59:00.000Z",
    ...overrides,
  };
}

function quote(overrides = {}) {
  return {
    symbol: "INFY",
    ltp: 1510,
    dayChange: 20,
    dayChangePct: 1.34,
    sourceTime: LATER,
    receivedAt: LATER,
    updatedAt: LATER,
    live: true,
    ...overrides,
  };
}

test("normalizeSymbol trims and uppercases", () => {
  assert.equal(normalizeSymbol(" infy "), "INFY");
  assert.equal(normalizeSymbol("^nsei"), "^NSEI");
  assert.equal(normalizeSymbol(null), "");
});

test("isUsablePrice only accepts a real positive number", () => {
  assert.equal(isUsablePrice(1500), true);
  for (const value of [0, -1, null, undefined, "1500", NaN, Infinity, true]) {
    assert.equal(isUsablePrice(value), false, String(value));
  }
});

test("mergeQuote updates price fields and keeps the rest of the row", () => {
  const merged = mergeQuote(stock(), quote());

  assert.equal(merged.ltp, 1510);
  assert.equal(merged.dayChange, 20);
  assert.equal(merged.dayChangePct, 1.34);
  assert.equal(merged.sourceTime, LATER);
  assert.equal(merged.live, true);
  // Fields the stream does not carry are untouched.
  assert.equal(merged.name, "Infosys");
  assert.equal(merged.qty, 10);
});

test("mergeQuote rejects an unusable price", () => {
  const current = stock();

  for (const price of [0, -5, null, "1510", NaN]) {
    assert.equal(mergeQuote(current, quote({ ltp: price })), current);
  }
});

test("an older or equal provider time cannot replace a newer quote", () => {
  const current = stock({ sourceTime: LATER, ltp: 1510 });

  assert.equal(
    mergeQuote(current, quote({ ltp: 1400, sourceTime: NOW })),
    current
  );
  assert.equal(mergeQuote(current, quote({ ltp: 1400, sourceTime: LATER })), current);
});

test("a REST row without a provider time cannot beat a streamed quote", () => {
  const current = stock({ sourceTime: LATER, ltp: 1510 });

  assert.equal(mergeQuote(current, stock({ ltp: 1400 })), current);
  assert.equal(isOlderQuote(current, stock({ ltp: 1400 })), true);
});

test("a streamed quote upgrades a REST row that has no provider time", () => {
  const current = stock();

  assert.equal(isOlderQuote(current, quote()), false);
  assert.equal(mergeQuote(current, quote()).ltp, 1510);
});

test("a restored cache value is a seed and cannot block a REST row", () => {
  const rest = stock();
  const restored = quote({
    ltp: 1400,
    live: false,
    restored: true,
    receivedAt: null,
  });

  assert.equal(isOlderQuote(rest, restored), true);
  assert.equal(mergeQuote(rest, restored), rest);
});

test("a persisted polling frame updates a REST row", () => {
  const rest = stock();
  const polling = quote({
    ltp: 1520,
    live: false,
    restored: false,
    receivedAt: null,
  });

  assert.equal(mergeQuote(rest, polling).ltp, 1520);
});

test("REST polling refills a restored row but never a live one", () => {
  const restored = stock({ sourceTime: LATER, ltp: 1400, live: false, restored: true });
  const rest = stock({ ltp: 1401 });
  assert.equal(mergeQuote(restored, rest).ltp, 1401);

  const live = stock({ sourceTime: LATER, ltp: 1500, live: true, restored: false });
  assert.equal(mergeQuote(live, rest), live);
});

test("mergeQuoteRows updates in place and never appends or reorders", () => {
  const rows = [stock(), stock({ symbol: "TCS", ltp: 3000 })];
  const updates = [
    quote({ symbol: "TCS", ltp: 3050 }),
    quote({ symbol: "WIPRO", ltp: 250 }),
  ];

  const merged = mergeQuoteRows(rows, updates);

  assert.equal(merged.length, 2);
  assert.deepEqual(
    merged.map((row) => row.symbol),
    ["INFY", "TCS"]
  );
  assert.equal(merged[0], rows[0]);
  assert.equal(merged[1].ltp, 3050);
});

test("mergeQuoteRows returns the same array when nothing changed", () => {
  const rows = [stock({ sourceTime: LATER })];

  assert.equal(mergeQuoteRows(rows, []), rows);
  assert.equal(mergeQuoteRows(rows, [quote({ sourceTime: NOW })]), rows);

  const empty = [];
  assert.equal(mergeQuoteRows(empty, [quote()]), empty);
});

test("mergeQuotesMap keeps a symbol -> quote store and ignores junk", () => {
  const current = { INFY: stock({ sourceTime: NOW, ltp: 1500 }) };

  const next = mergeQuotesMap(current, [
    quote({ ltp: 1510 }),
    quote({ symbol: "", ltp: 10 }),
    null,
  ]);

  assert.equal(next.INFY.ltp, 1510);
  assert.equal(Object.keys(next).length, 1);
});

test("mergeQuotesMap rejects an older tick and keeps object identity", () => {
  const current = { INFY: stock({ sourceTime: LATER, ltp: 1510 }) };

  assert.equal(
    mergeQuotesMap(current, [quote({ ltp: 1400, sourceTime: NOW })]),
    current
  );
  assert.equal(mergeQuotesMap(current, []), current);
});

test("mergeInstrumentQuote maps ltp onto the detail page's price field", () => {
  const instrument = {
    symbol: "INFY",
    price: 1500,
    change: 10,
    changePct: 0.67,
    open: 1490,
    volume: 1000,
  };

  const merged = mergeInstrumentQuote(instrument, quote());

  assert.equal(merged.price, 1510);
  assert.equal(merged.change, 20);
  assert.equal(merged.changePct, 1.34);
  assert.equal(merged.open, 1490);
  assert.equal(merged.volume, 1000);
});

test("mergeInstrumentQuote ignores an older or unusable update", () => {
  const instrument = {
    symbol: "INFY",
    price: 1510,
    sourceTime: LATER,
  };

  assert.equal(
    mergeInstrumentQuote(instrument, quote({ ltp: 1400, sourceTime: NOW })),
    instrument
  );
  assert.equal(mergeInstrumentQuote(instrument, quote({ ltp: 0 })), instrument);
  assert.equal(mergeInstrumentQuote(null, quote()), null);
});

test("isQuoteStale uses the provider time and treats a missing one as stale", () => {
  const now = Date.parse(NOW);

  assert.equal(isQuoteStale({ sourceTime: NOW }, now, 60), false);
  assert.equal(isQuoteStale({ sourceTime: NOW }, now + 61_000, 60), true);
  assert.equal(isQuoteStale({ updatedAt: NOW }, now + 3600_000, 60), true);
  assert.equal(isQuoteStale({}, now, 60), true);
  assert.equal(
    isQuoteStale({ sourceTime: new Date(now + 3600_000).toISOString() }, now, 60),
    true
  );
});
