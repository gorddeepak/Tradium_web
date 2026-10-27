import { useCallback, useRef, useState } from "react";
import { getWatchlist, addToWatchlist, removeFromWatchlist } from "@/services/api";
import { usePolling } from "./usePolling";
import { useWatchlistStream } from "./useWatchlistStream";

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
  // ltp from the previous fetch, so each new one can be diffed
  const prevPrices = useRef({});

  const apply = useCallback((list) => {
    const changed = {};
    for (const w of list) {
      const flash = flashFor(prevPrices.current[w._id], w.ltp);
      if (flash) changed[w._id] = flash;
    }
    prevPrices.current = Object.fromEntries(list.map((w) => [w._id, w.ltp]));
    setWatchlist(list);
    setLoading(false);
    if (Object.keys(changed).length > 0) setFlashes(changed);
  }, []);

  const onFirstError = useCallback((err) => {
    setError(err);
    setLoading(false);
  }, []);

  usePolling(getWatchlist, apply, POLL_MS, onFirstError);

  /* WebSocket frames carry only the fields price_sync owns. The REST poll
     remains the fallback, so a missing socket degrades to the old behaviour. */
  const applyQuotes = useCallback((quotes) => {
    const byId = new Map(quotes.map((quote) => [quote._id, quote]));
    const changed = {};
    for (const quote of quotes) {
      const flash = flashFor(prevPrices.current[quote._id], quote.ltp);
      if (flash) changed[quote._id] = flash;
      if (quote.ltp !== undefined) prevPrices.current[quote._id] = quote.ltp;
    }

    setWatchlist((list) =>
      list.map((item) => {
        const quote = byId.get(item._id);
        if (!quote) return item;
        return {
          ...item,
          ltp: quote.ltp ?? item.ltp,
          dayChangePct: quote.dayChangePct ?? item.dayChangePct,
          updatedAt: quote.updatedAt ?? item.updatedAt,
        };
      })
    );
    if (Object.keys(changed).length > 0) setFlashes(changed);
  }, []);

  useWatchlistStream(applyQuotes, !loading);

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
