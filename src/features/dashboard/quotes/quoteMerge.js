/* Pure quote-merging rules, shared by every page and by the unit tests.

   Price updates arrive from two sources: the REST poll and the WebSocket
   stream. The stream is newer while it runs, so an update without a provider
   `sourceTime` must never replace a live quote that has one. A restored cache
   value (`restored: true`) is only a seed, so it must never block the REST row
   that polling keeps refreshing. Everything here is a plain function with no
   React or network dependency. */

export function normalizeSymbol(value) {
  return String(value || "").trim().toUpperCase();
}

export function isUsablePrice(value) {
  return typeof value === "number" && Number.isFinite(value) && value > 0;
}

// Provider market time is the only ordering key. `updatedAt` is a database
// write time for REST rows and is deliberately not used to compare sources.
function quoteTime(quote) {
  if (!quote || !quote.sourceTime) return null;
  const value = Date.parse(quote.sourceTime);
  return Number.isFinite(value) ? value : null;
}

function ageTime(quote) {
  if (!quote) return null;
  for (const field of ["sourceTime", "updatedAt", "receivedAt"]) {
    if (!quote[field]) continue;
    const value = Date.parse(quote[field]);
    if (Number.isFinite(value)) return value;
  }
  return null;
}

export function isOlderQuote(current, update) {
  const currentTime = quoteTime(current);
  if (update?.restored === true && currentTime === null) {
    // A restored cache value is a fast first paint of the same table the REST
    // row came from. Letting it overwrite the row would freeze a page after
    // the feed drops, when polling is the only source that still moves.
    return true;
  }

  if (currentTime === null) return false;
  const updateTime = quoteTime(update);
  if (updateTime === null) {
    // A REST snapshot has no provider time. It may refill a restored or
    // persisted row, but it must never replace a live tick.
    return current.live !== false;
  }
  return updateTime <= currentTime;
}

export function isQuoteStale(quote, nowMs = Date.now(), staleAfterSeconds = 60) {
  const time = ageTime(quote);
  if (time === null) return true;
  const age = (nowMs - time) / 1000;
  return age > staleAfterSeconds || age < -120;
}

/* Keep every field the update does not carry (name, qty, volume, ...). */
export function mergeQuote(current, update) {
  if (!update) return current;
  if (!current) return { ...update };
  if (update.ltp !== undefined && !isUsablePrice(update.ltp)) return current;
  if (isOlderQuote(current, update)) return current;

  return {
    ...current,
    ltp: update.ltp ?? current.ltp,
    dayChange: update.dayChange ?? current.dayChange,
    dayChangePct: update.dayChangePct ?? current.dayChangePct,
    updatedAt: update.updatedAt ?? current.updatedAt,
    sourceTime: update.sourceTime ?? current.sourceTime,
    receivedAt: update.receivedAt ?? current.receivedAt,
    live: update.live ?? current.live,
    restored: update.restored ?? current.restored,
    stale: update.stale ?? current.stale,
  };
}

/* Update rows in place, never append or reorder. Unknown symbols are ignored
   so a stream frame can never invent a line in a book table. */
export function mergeQuoteRows(rows, updates, key = "symbol") {
  const list = Array.isArray(rows) ? rows : [];
  if (list.length === 0 || !Array.isArray(updates) || updates.length === 0) {
    return list;
  }

  const byKey = new Map();
  for (const update of updates) {
    const name = normalizeSymbol(update?.[key]);
    if (name) byKey.set(name, update);
  }
  if (byKey.size === 0) return list;

  let changed = false;
  const merged = list.map((row) => {
    const update = byKey.get(normalizeSymbol(row?.[key]));
    if (!update) return row;
    const next = mergeQuote(row, update);
    if (next !== row) changed = true;
    return next;
  });
  return changed ? merged : list;
}

/* The quote store: a symbol -> quote map, modernised one update at a time. */
export function mergeQuotesMap(previous, updates) {
  const current = previous || {};
  if (!Array.isArray(updates) || updates.length === 0) return current;

  let changed = false;
  const next = { ...current };
  for (const update of updates) {
    if (!update) continue;
    const symbol = normalizeSymbol(update.symbol);
    if (!symbol) continue;
    const merged = mergeQuote(current[symbol], update);
    if (merged !== current[symbol]) {
      next[symbol] = merged;
      changed = true;
    }
  }
  return changed ? next : current;
}

/* The instrument detail route calls the price `price`, not `ltp`. */
export function mergeInstrumentQuote(current, update) {
  if (!current || !update) return current;
  if (!isUsablePrice(update.ltp)) return current;
  if (isOlderQuote(current, update)) return current;

  return {
    ...current,
    price: update.ltp,
    change: update.dayChange ?? current.change,
    changePct: update.dayChangePct ?? current.changePct,
    updatedAt: update.updatedAt ?? current.updatedAt,
    sourceTime: update.sourceTime ?? current.sourceTime,
    receivedAt: update.receivedAt ?? current.receivedAt,
    live: update.live ?? current.live,
    restored: update.restored ?? current.restored,
    stale: update.stale ?? current.stale,
  };
}
