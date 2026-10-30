import { getPositions } from "@/services/api";
import { useApiData } from "./useApiData";
import { useLiveQuotes } from "../quotes/QuoteContext";
import { mergeQuoteRows } from "../quotes/quoteMerge";

export function usePositions() {
  const { data, loading, error, refresh } = useApiData(getPositions, []);
  const positions = data || [];

  const live = useLiveQuotes(positions.map((row) => row.symbol));

  return {
    positions: mergeQuoteRows(positions, Object.values(live)),
    loading,
    error,
    refresh,
  };
}
