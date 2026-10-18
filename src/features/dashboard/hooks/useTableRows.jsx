import { useMemo } from "react";
import { compareRows } from "@/features/dashboard/hooks/useSort";

/* Filter rows by search and the gainers/losers pills, then sort them. */
export function useTableRows(rows, { query, filter, sort, dir, pnlKey, zeroIsGainer }) {
  return useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = rows.filter((r) => {
      const matches = !q || r.symbol.toLowerCase().includes(q) || r.name.toLowerCase().includes(q);
      const isGainer = zeroIsGainer ? r[pnlKey] >= 0 : r[pnlKey] > 0;
      const side = filter === "all" || (filter === "gainers" ? isGainer : r[pnlKey] < 0);
      return matches && side;
    });
    // slice() so the sort never mutates the caller's array.
    return filtered.slice().sort((a, b) => compareRows(a, b, sort, dir));
  }, [rows, query, filter, sort, dir, pnlKey, zeroIsGainer]);
}
