import { getMarketOverview } from "@/services/api";
import { useApiData } from "./useApiData";
import { useLiveQuotes } from "../quotes/QuoteContext";
import { mergeQuoteRows } from "../quotes/quoteMerge";

/* One fetch on mount — the server refreshes its cache every five minutes.
   Live quotes then overlay the fetched rows, so prices move without a refetch. */
export function useMarketOverview() {
  const { data, loading, error } = useApiData(getMarketOverview);

  const overview = data || {};
  const indices = overview.indices || [];
  const stocks = overview.stocks || [];

  const live = useLiveQuotes([...indices, ...stocks].map((row) => row.symbol));
  const updates = Object.values(live);

  return {
    indices: mergeQuoteRows(indices, updates),
    stocks: mergeQuoteRows(stocks, updates),
    asOf: overview.asOf ?? null,
    loading,
    error,
  };
}
