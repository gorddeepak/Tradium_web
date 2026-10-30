import { getHoldings } from "@/services/api";
import { useApiData } from "./useApiData";
import { useLiveQuotes } from "../quotes/QuoteContext";
import { mergeQuoteRows } from "../quotes/quoteMerge";

export function useHoldings() {
  const { data, loading, error, refresh } = useApiData(getHoldings, []);
  const holdings = data || [];

  // The REST fetch paints the rows; streamed ticks only replace prices on
  // rows that already exist.
  const live = useLiveQuotes(holdings.map((row) => row.symbol));

  return {
    holdings: mergeQuoteRows(holdings, Object.values(live)),
    loading,
    error,
    refresh,
  };
}
