import { getTransactions } from "@/services/api";
import { useApiData } from "./useApiData";

export function useTransactions() {
  // setData is exposed on purpose: the Funds page appends a transaction
  // locally after a deposit/withdraw so the table updates without a refetch.
  const { data: transactions, setData: setTransactions, loading } = useApiData(
    getTransactions,
    [],
  );
  return { transactions, setTransactions, loading };
}
