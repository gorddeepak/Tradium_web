import { getPositions } from "@/services/api";
import { useApiData } from "./useApiData";

export function usePositions() {
  const { data: positions, loading, error, refresh } = useApiData(getPositions, []);
  return { positions, loading, error, refresh };
}
