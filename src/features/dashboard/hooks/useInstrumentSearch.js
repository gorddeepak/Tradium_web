import { useEffect, useState } from "react";
import { searchInstruments } from "@/services/api";

/* Debounced search shared by the watchlist add form and the Ctrl+K palette.
   Hits the server cache, not Gemini. */
export function useInstrumentSearch(query, enabled = true) {
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const trimmed = query.trim();
    if (!enabled || !trimmed) return;

    const timer = setTimeout(async () => {
      setLoading(true);
      try {
        setResults(await searchInstruments(trimmed));
      } catch {
        setResults([]);
      } finally {
        setLoading(false);
      }
    }, 300);

    return () => clearTimeout(timer);
  }, [query, enabled]);

  return { results, loading };
}
