import { useEffect } from "react";
import { WATCHLIST_STREAM_URL } from "@/services/api";

/* Live watchlist prices. The REST fetch still owns the first paint; this only
   applies frames after a successful connect. A dropped socket retries with a
   short backoff, except for 1008 (the server rejected the token). */
const RETRY_MS = 5000;
const MAX_RETRY_MS = 30000;

export function useWatchlistStream(onQuotes, enabled) {
  useEffect(() => {
    if (!enabled) return;

    let socket = null;
    let retry = null;
    let stopped = false;
    let attempts = 0;

    function connect() {
      const ws = new WebSocket(WATCHLIST_STREAM_URL);
      socket = ws;

      ws.onopen = () => {
        attempts = 0;
      };

      ws.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);
          if (message.type === "quotes" && Array.isArray(message.quotes)) {
            onQuotes(message.quotes);
          }
        } catch {
          // A malformed frame is ignored; the next price tick replaces it.
        }
      };

      ws.onerror = () => {
        ws.close();
      };

      ws.onclose = (event) => {
        if (stopped || event.code === 1008) return;
        const delay = Math.min(RETRY_MS * 2 ** attempts, MAX_RETRY_MS);
        attempts += 1;
        retry = setTimeout(connect, delay);
      };
    }

    connect();

    return () => {
      stopped = true;
      if (retry) clearTimeout(retry);
      if (socket) socket.close();
    };
  }, [enabled, onQuotes]);
}
