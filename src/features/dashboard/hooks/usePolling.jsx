import { useEffect } from "react";
import { isMarketOpen } from "@/services/marketStatus";

/* Shared poller: fetch on mount, then every intervalMs. Skips ticks when the
   market is shut or the tab is hidden. */
export function usePolling(fetcher, onData, intervalMs, onError) {
  useEffect(() => {
    let latest = 0;

    async function run(isInitial) {
      const id = ++latest;
      try {
        const data = await fetcher(isInitial);
        if (id === latest) onData(data);
      } catch (err) {
        if (isInitial && onError) onError(err);
      }
    }

    run(true);

    const timer = setInterval(() => {
      if (!isMarketOpen()) return;
      if (document.visibilityState === "hidden") return;
      run(false);
    }, intervalMs);

    return () => {
      latest++; // anything still in flight is now stale
      clearInterval(timer);
    };
  }, [fetcher, onData, intervalMs, onError]);
}
