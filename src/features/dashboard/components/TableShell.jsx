import { TablePagination } from "@/features/dashboard/components/TablePagination";

/*
  The shared skeleton of the Holdings / Positions / Orders tables:
  the bordered box, the <table>, the empty state, and the pagination footer.
  `header` is the thead content — SortableHead on sortable pages, a plain <tr> on Orders.
  `children` is the page's own <tr> rows.
  `containerRef` lets Holdings' click-a-tile scroll-to-row reach the outer box.
*/
export function TableShell({ header, rows, colSpan, empty, page, totalPages, onPageChange, containerRef, children }) {
  return (
    <div
      ref={containerRef}
      className="animate-entry overflow-x-auto rounded-xl border border-border bg-surface shadow-xs [animation-delay:150ms]"
    >
      {/* min-w-max: table scrolls sideways on phones. */}
      <table className="w-full min-w-max border-collapse text-left">
        <thead>{header}</thead>
        <tbody className="num divide-y divide-border text-[13px]">
          {children}
          {/* `empty` is optional — tables with no empty state (DashboardHome's
              top holdings) pass nothing and get no row at all. */}
          {rows.length === 0 && empty && (
            <tr>
              <td colSpan={colSpan} className="px-4 py-12 text-center font-sans text-sm text-muted-foreground">
                {empty}
              </td>
            </tr>
          )}
        </tbody>
      </table>
      {/* No pagination props (DashboardHome's top holdings) means no footer.
          TablePagination itself can't guard this: totalPages <= 1 is false
          when totalPages is undefined, so the pager would render broken. */}
      {page !== undefined && (
        <TablePagination page={page} totalPages={totalPages} onPageChange={onPageChange} />
      )}
    </div>
  );
}
