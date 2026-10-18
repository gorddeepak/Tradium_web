import { getOrders } from "@/services/api";
import { useApiData } from "./useApiData";
import { usePolling } from "./usePolling";

export function useOrders() {
  const { data: orders, setData, loading, error, refresh } = useApiData(getOrders, []);

  // while the market is open the backend's priceSync job may fill OPEN limit
  // orders at any minute, so poll for status changes
  usePolling(getOrders, setData, 30000);

  return { orders, loading, error, refresh };
}
