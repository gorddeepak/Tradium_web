import { getHoldings } from "@/services/api";
import { useApiData } from "./useApiData";

export function useHoldings() {
  const { data: holdings, loading, error, refresh } = useApiData(getHoldings, []);
  return { holdings, loading, error, refresh };
}
