import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { QUOTES_STREAM_URL } from "@/services/api";
import { mergeQuotesMap, normalizeSymbol } from "./quoteMerge";

/* One shared quote socket for the whole dashboard.

   Pages still paint from REST; this store only keeps the newest streamed
   price for each symbol. A page subscribes to the symbols it is showing and
   receives the merged quote, so Markets, Holdings, Positions, the watchlist
   and the instrument pane all read the same value.

   A dropped socket retries with backoff, except for 1008: the server rejected
   the token, so retrying would loop forever. */
const QuoteContext = createContext(null);

const RETRY_MS = 3000;
const MAX_RETRY_MS = 30000;
const EMPTY = {};

export function QuoteProvider({ children }) {
  const [quotes, setQuotes] = useState(EMPTY);
  const [connected, setConnected] = useState(false);
  const [status, setStatus] = useState({
    enabled: false,
    state: "connecting",
    streaming: false,
    staleAfterSeconds: 60,
  });

  const socketRef = useRef(null);
  // symbol -> number of mounted pages watching it
  const countsRef = useRef(new Map());

  const send = useCallback((message) => {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    socket.send(JSON.stringify(message));
  }, []);

  /* Ref-counted subscription: two pages showing INFY keep one subscription,
     and only the first/last mount sends a message. */
  const subscribe = useCallback(
    (symbols) => {
      const added = [];
      for (const raw of symbols || []) {
        const symbol = normalizeSymbol(raw);
        if (!symbol) continue;
        const count = countsRef.current.get(symbol) || 0;
        countsRef.current.set(symbol, count + 1);
        if (count === 0) added.push(symbol);
      }
      if (added.length > 0) send({ type: "subscribe", symbols: added });

      return () => {
        const removed = [];
        for (const raw of symbols || []) {
          const symbol = normalizeSymbol(raw);
          if (!symbol) continue;
          const count = countsRef.current.get(symbol) || 0;
          if (count <= 1) {
            countsRef.current.delete(symbol);
            removed.push(symbol);
          } else {
            countsRef.current.set(symbol, count - 1);
          }
        }
        if (removed.length > 0) send({ type: "unsubscribe", symbols: removed });
      };
    },
    [send]
  );

  useEffect(() => {
    let stopped = false;
    let retry = null;
    let attempts = 0;

    function connect() {
      const socket = new WebSocket(QUOTES_STREAM_URL);
      socketRef.current = socket;

      socket.onopen = () => {
        attempts = 0;
        setConnected(true);
        // Everything subscribed while the socket was down is sent now. The
        // server answers with a snapshot, so a reconnect catches up.
        const symbols = [...countsRef.current.keys()];
        if (symbols.length > 0) {
          socket.send(JSON.stringify({ type: "subscribe", symbols }));
        }
      };

      socket.onmessage = (event) => {
        let message;
        try {
          message = JSON.parse(event.data);
        } catch {
          // A malformed frame is ignored; the next tick replaces it.
          return;
        }

        if (message.type === "quotes" && Array.isArray(message.quotes)) {
          setQuotes((current) => mergeQuotesMap(current, message.quotes));
        } else if (message.type === "status") {
          setStatus({
            enabled: message.enabled ?? false,
            state: message.state ?? "unknown",
            streaming: message.streaming ?? false,
            staleAfterSeconds: message.staleAfterSeconds ?? 60,
          });
        }
      };

      socket.onerror = () => socket.close();

      socket.onclose = (event) => {
        if (socketRef.current === socket) socketRef.current = null;
        setConnected(false);
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
      const socket = socketRef.current;
      socketRef.current = null;
      if (socket) socket.close();
    };
  }, []);

  const value = useMemo(
    () => ({ quotes, status, connected, subscribe }),
    [quotes, status, connected, subscribe]
  );

  return <QuoteContext.Provider value={value}>{children}</QuoteContext.Provider>;
}

/* The header badge reads this. Without a provider it reports "unavailable"
   instead of crashing, so a page can render outside the dashboard shell. */
export function useQuoteStatus() {
  const context = useContext(QuoteContext);
  if (!context) {
    return {
      status: {
        enabled: false,
        state: "unavailable",
        streaming: false,
        staleAfterSeconds: 60,
      },
      connected: false,
    };
  }
  return { status: context.status, connected: context.connected };
}

/* Subscribe to `symbols` and return the live quotes this page has received,
   keyed by symbol. The key is a sorted string so a new array with the same
   symbols does not reconnect or resubscribe. */
export function useLiveQuotes(symbols) {
  const context = useContext(QuoteContext);
  const subscribe = context?.subscribe;
  const quoteMap = context?.quotes;

  const key = useMemo(
    () =>
      [...new Set((symbols || []).map(normalizeSymbol).filter(Boolean))]
        .sort()
        .join(","),
    [symbols]
  );

  useEffect(() => {
    if (!subscribe || !key) return;
    return subscribe(key.split(","));
  }, [subscribe, key]);

  return useMemo(() => {
    if (!quoteMap || !key) return EMPTY;
    let found = null;
    for (const symbol of key.split(",")) {
      const quote = quoteMap[symbol];
      if (!quote) continue;
      if (!found) found = {};
      found[symbol] = quote;
    }
    return found || EMPTY;
  }, [quoteMap, key]);
}
