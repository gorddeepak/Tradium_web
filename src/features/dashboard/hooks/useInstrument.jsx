import { useCallback, useState } from "react";
import { getInstrument, getCandles } from "@/services/api";
import { usePolling } from "./usePolling";

/* Fetch quotes and candles on mount/symbol/range change, then every 30s while
   the market is open. */
const POLL_MS = 30000;

export function useInstrument(symbol, range) {
  const [instrument, setInstrument] = useState(null);
  const [candles, setCandles] = useState([]);
  const [instrumentLoading, setInstrumentLoading] = useState(true);
  const [candlesLoading, setCandlesLoading] = useState(true);

  const fetchQuoteAndCandles = useCallback(async (isInitial) => {
    // loading shows only for the mount / symbol / range fetch, not for polls
    if (isInitial) {
      setInstrumentLoading(true);
      setCandlesLoading(true);
    }
    const [quote, candleData] = await Promise.all([
      getInstrument(symbol),
      getCandles(symbol, range),
    ]);
    return { quote, candleData };
  }, [symbol, range]);

  const apply = useCallback(({ quote, candleData }) => {
    setInstrument(quote);
    setCandles(candleData);
    setInstrumentLoading(false);
    setCandlesLoading(false);
  }, []);

  const onError = useCallback(() => {
    // clear the skeletons even when the fetch fails
    setInstrumentLoading(false);
    setCandlesLoading(false);
  }, []);

  usePolling(fetchQuoteAndCandles, apply, POLL_MS, onError);

  return { instrument, candles, instrumentLoading, candlesLoading };
}
