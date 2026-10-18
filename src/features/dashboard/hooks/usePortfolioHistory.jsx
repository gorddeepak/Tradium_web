import { useCallback } from "react";
import { getPortfolioHistory } from "@/services/api";
import { useApiData } from "./useApiData";

export function usePortfolioHistory(range) {
  const fetcher = useCallback(() => getPortfolioHistory(range), [range]);
  const { data: series, loading } = useApiData(fetcher, []);
  return { series, loading };
}
