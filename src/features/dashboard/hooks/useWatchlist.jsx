import { useCallback, useEffect, useRef, useState } from "react";
import { getWatchlist, addToWatchlist, removeFromWatchlist } from "@/services/api";
import { usePolling } from "./usePolling";
import { useLiveQuotes } from "../quotes/QuoteContext";
import { mergeQuoteRows } from "../quotes/quoteMerge";

/* Poll the watchlist while the market is open; the backend refreshes ltp
   every minute. */
const POLL_MS = 30000;

// A row that moved gets a fresh stamp so a second move in the same direction
// replays the flash animation instead of being ignored.
function flashFor(previousPrice, price) {
  if (
    previousPrice === undefined ||
    price === undefined ||
    price === previousPrice
  ) {
    return null;
  }
  return { dir: price > previousPrice ? "up" : "down", stamp: Date.now() };
}

export function useWatchlist() {
  const [watchlist, setWatchlist] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  // id -> { dir, stamp } for rows whose ltp moved, so the rail can flash them
  const [flashes, setFlashes] = useState({});
  // ltp from the previous update, so each new one can be diffed
  const prevPrices = useRef({});
  // the newest streamed quotes, so a REST poll cannot regress a price
  const liveRef = useRef({});
  // the rows currently on screen, so a streamed quote can find its _id
  const rowsRef = useRef([]);

  const live = useLiveQuotes(watchlist.map((item) => item.symbol));

  useEffect(() => {
    rowsRef.current = watchlist;
  }, [watchlist]);

  /* Streamed quotes arrive by symbol; the rail is keyed by watchlist _id, so
     each tick is matched to its row before flashing and merging. */
  useEffect(() => {
    liveRef.current = live;
    const updates = Object.values(live);
    if (updates.length === 0) return;

    const changed = {};
    for (const quote of updates) {
      if (quote.ltp === undefined) continue;
      const item = rowsRef.current.find((row) => row.symbol === quote.symbol);
      if (!item) continue;
      const flash = flashFor(prevPrices.current[item._id], quote.ltp);
      if (flash) changed[item._id] = flash;
      prevPrices.current[item._id] = quote.ltp;
    }

    setWatchlist((list) => mergeQuoteRows(list, updates, "symbol"));
    if (Object.keys(changed).length > 0) setFlashes(changed);
  }, [live]);

  const apply = useCallback((list) => {
    // Re-apply the newest streamed quotes: a slower poll must not move a
    // price backwards while the socket is live.
    const merged = mergeQuoteRows(list, Object.values(liveRef.current), "symbol");
    const changed = {};
    for (const w of merged) {
      const flash = flashFor(prevPrices.current[w._id], w.ltp);
      if (flash) changed[w._id] = flash;
    }
    prevPrices.current = Object.fromEntries(merged.map((w) => [w._id, w.ltp]));
    setWatchlist(merged);
    setLoading(false);
    if (Object.keys(changed).length > 0) setFlashes(changed);
  }, []);

  const onFirstError = useCallback((err) => {
    setError(err);
    setLoading(false);
  }, []);

  usePolling(getWatchlist, apply, POLL_MS, onFirstError);

  async function add(item) {
    const created = await addToWatchlist(item);
    setWatchlist((w) => [...w, created]);
  }

  async function remove(id) {
    await removeFromWatchlist(id);
    setWatchlist((w) => w.filter((item) => item._id !== id));
  }

  return { watchlist, loading, error, add, remove, flashes };
}
