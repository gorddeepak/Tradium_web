import { useState } from "react";

/* Splits an already-filtered, already-sorted row array into pages. */
export function usePagination(rows, pageSize = 6) {
  const [page, setPage] = useState(1);

  // Math.max avoids "page 1 of 0" on empty tables.
  const totalPages = Math.max(1, Math.ceil(rows.length / pageSize));

  // Clamps the page when filtering shrinks the rows.
  const safePage = Math.min(page, totalPages);
  const start = (safePage - 1) * pageSize;

  return {
    page: safePage,
    setPage,
    totalPages,
    pageRows: rows.slice(start, start + pageSize),
    // Returned so callers can jump to the page holding a given row.
    pageSize,
  };
}
