import { useState } from "react";

/* Sort state for a sortable table; clicking the active column flips direction. */
export function useSort(initialKey, initialDir = "desc") {
  const [sort, setSort] = useState(initialKey);
  const [dir, setDir] = useState(initialDir);

  function toggle(key) {
    if (key === sort) setDir(dir === "asc" ? "desc" : "asc");
    else {
      setSort(key);
      setDir(key === "symbol" ? "asc" : "desc");
    }
  }

  return { sort, dir, toggle };
}

/* The comparator both table pages use: strings compare alphabetically,
   numbers numerically, and dir flips the result. */
export function compareRows(a, b, key, dir) {
  const av = a[key];
  const bv = b[key];
  const cmp = typeof av === "string" ? av.localeCompare(bv) : av - bv;
  return dir === "asc" ? cmp : -cmp;
}
