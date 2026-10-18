import { getMarketOverview } from "@/services/api";
import { useApiData } from "./useApiData";

/* One fetch on mount — the server refreshes its cache every five minutes. */
export function useMarketOverview() {
  const { data, loading, error } = useApiData(getMarketOverview);

  const overview = data || {};
  // null until the first sync writes a row, which the page shows as
  // "awaiting first sync" rather than a misleading timestamp.
  return { indices: overview.indices || [], stocks: overview.stocks || [], asOf: overview.asOf ?? null, loading, error };
}
