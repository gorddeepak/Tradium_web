import { useCallback, useEffect, useState } from "react";

/* Shared fetch-state machine. fetcher must be stable; manual refresh() keeps
   the current data on screen instead of flashing the skeleton. */
export function useApiData(fetcher, initial = null) {
  const [data, setData] = useState(initial);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const refresh = useCallback(() => {
    return fetcher().then(setData).catch(setError).finally(() => setLoading(false));
  }, [fetcher]);

  useEffect(() => {
    setLoading(true);
    refresh();
  }, [refresh]);

  return { data, setData, loading, error, refresh };
}
