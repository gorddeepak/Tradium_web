import { createContext, useContext, useState, useEffect, useCallback } from "react";
import { getFunds } from "@/services/api";

/* One shared funds state for the whole dashboard — a trade updates every corner. */
const FundsContext = createContext();

export const FundsProvider = ({ children }) => {
  const [funds, setFunds] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    const data = await getFunds();
    setFunds(data);
    return data;
  }, []);

  useEffect(() => {
    refresh()
      .catch(setError)
      .finally(() => setLoading(false));
  }, [refresh]);

  return (
    <FundsContext.Provider value={{ funds, loading, error, refresh }}>
      {children}
    </FundsContext.Provider>
  );
};

export const useFunds = () => useContext(FundsContext);
