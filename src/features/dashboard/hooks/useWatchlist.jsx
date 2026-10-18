import { useCallback, useRef, useState } from "react";
import { getWatchlist, addToWatchlist, removeFromWatchlist } from "@/services/api";
import { usePolling } from "./usePolling";

/* Poll the watchlist while the market is open; the backend refreshes ltp
   every minute. */
const POLL_MS = 30000;

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
      const prev = prevPrices.current[w._id];
      if (prev !== undefined && w.ltp !== undefined && w.ltp !== prev) {
        // stamp gives the flash cell a fresh key, so a second move in the
        // same direction replays the animation instead of being ignored
        changed[w._id] = { dir: w.ltp > prev ? "up" : "down", stamp: Date.now() };
      }
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
