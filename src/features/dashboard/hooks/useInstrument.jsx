import { useCallback, useState } from "react";
import { getInstrument, getCandles } from "@/services/api";
import { usePolling } from "./usePolling";
import { useLiveQuotes } from "../quotes/QuoteContext";
import { mergeInstrumentQuote, normalizeSymbol } from "../quotes/quoteMerge";

/* Fetch quotes and candles on mount/symbol/range change, then every 30s while
   the market is open. */
const POLL_MS = 30000;

export function useInstrument(symbol, range) {
  const [instrument, setInstrument] = useState(null);
  const [candles, setCandles] = useState([]);
  const [instrumentLoading, setInstrumentLoading] = useState(true);
  const [candlesLoading, setCandlesLoading] = useState(true);
  const [candlesError, setCandlesError] = useState(false);

  const fetchQuoteAndCandles = useCallback(async (isInitial) => {
    // loading shows only for the mount / symbol / range fetch, not for polls
    if (isInitial) {
      setInstrumentLoading(true);
      setCandlesLoading(true);
    }
    // A chart outage must not hide the instrument, so each request settles on
    // its own instead of the pair rejecting together.
    const [quote, candleData] = await Promise.allSettled([
      getInstrument(symbol),
      getCandles(symbol, range),
    ]);
    return { quote, candleData, isInitial };
  }, [symbol, range]);

  const apply = useCallback(({ quote, candleData, isInitial }) => {
    if (quote.status === "fulfilled") setInstrument(quote.value);
    if (candleData.status === "fulfilled") {
      setCandles(candleData.value);
      setCandlesError(false);
    } else if (isInitial && quote.status === "fulfilled") {
      // The instrument loaded but its history did not; say so instead of
      // drawing the previous symbol's chart or an empty one.
      setCandles([]);
      setCandlesError(true);
    }
    setInstrumentLoading(false);
    setCandlesLoading(false);
  }, []);

  usePolling(fetchQuoteAndCandles, apply, POLL_MS);

  // The page's own quote wins over the poll, and the poll stays as fallback.
  const quoteSymbol = normalizeSymbol(instrument?.symbol || symbol);
  const live = useLiveQuotes([quoteSymbol]);
  const merged = mergeInstrumentQuote(instrument, live[quoteSymbol]);

  return { instrument: merged, candles, candlesError, instrumentLoading, candlesLoading };
}
