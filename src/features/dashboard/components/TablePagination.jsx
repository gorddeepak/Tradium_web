import { ChevronLeft, ChevronRight } from "lucide-react";
import {
  Pagination,
  PaginationContent,
  PaginationItem,
} from "@/components/ui/pagination";
import { Button } from "@/components/ui/button";
import { cn } from "@/utils/utils";

/* Windowed page numbers with gaps as ellipses: 1 … 18 19 20 … 40. */
function pageWindow(current, total) {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);

  const pages = [1];
  const from = Math.max(2, current - 1);
  const to = Math.min(total - 1, current + 1);

  if (from > 2) pages.push("gap-start");
  for (let p = from; p <= to; p++) pages.push(p);
  if (to < total - 1) pages.push("gap-end");

  pages.push(total);
  return pages;
}

/* shadcn gives the nav/ul/li semantics; the controls are our own Buttons. */
export function TablePagination({ page, totalPages, onPageChange }) {
  // One page (or none) needs no controls at all — this is why the demo's
  // five-row tables show no footer until a table grows past the page size.
  if (totalPages <= 1) return null;

  return (
    <Pagination className="justify-end border-t border-border px-4 py-3">
      <PaginationContent>
        <PaginationItem>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onPageChange(page - 1)}
            disabled={page === 1}
            aria-label="Go to previous page"
          >
            <ChevronLeft className="size-3.5" />
            <span className="hidden sm:block">Prev</span>
          </Button>
        </PaginationItem>

        {pageWindow(page, totalPages).map((p) =>
          typeof p === "string" ? (
            <PaginationItem key={p} className="px-1.5 text-sm text-muted-foreground select-none">
              &hellip;
            </PaginationItem>
          ) : (
            <PaginationItem key={p}>
              <Button
                variant={p === page ? "outline" : "ghost"}
                size="icon-sm"
                onClick={() => onPageChange(p)}
                aria-current={p === page ? "page" : undefined}
                className={cn("num", p === page && "pointer-events-none")}
              >
                {p}
              </Button>
            </PaginationItem>
          )
        )}

        <PaginationItem>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onPageChange(page + 1)}
            disabled={page === totalPages}
            aria-label="Go to next page"
          >
            <span className="hidden sm:block">Next</span>
            <ChevronRight className="size-3.5" />
          </Button>
        </PaginationItem>
      </PaginationContent>
    </Pagination>
  );
}
