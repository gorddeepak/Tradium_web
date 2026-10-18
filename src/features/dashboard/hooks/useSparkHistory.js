import { useEffect, useState } from "react";
import { getCandles } from "@/services/api";

/* Fetches ~5 daily closes per watchlist symbol, once per page visit. A failure
   just skips that symbol's sparkline. */
export function useSparkHistory(watchlist) {
  const [history, setHistory] = useState({});

  const sparkSymbols = watchlist.map((w) => w.symbol).join(",");
  useEffect(() => {
    if (!sparkSymbols) return;
    let cancelled = false;
    watchlist.forEach(async (w) => {
      try {
        const candles = await getCandles(w.symbol, "SPARK", w.exchange);
        if (!cancelled) {
          setHistory((prev) => ({ ...prev, [w.symbol]: candles.map((c) => c.close) }));
        }
      } catch {
        /* no sparkline for this row */
      }
    });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sparkSymbols]);

  return history;
}
