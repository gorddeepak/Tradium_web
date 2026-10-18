import { Link } from "react-router-dom";
import { useMemo, useState } from "react";
import { MetricReadout, PageHeader, PnlValue, InstrumentCell, SideBadge, SortableHead, TD, TD_R, fmtMoney, positionPnl, rowFromPosition } from "@/utils/tradiumUtils";
import { usePositions } from "@/features/dashboard/hooks/usePositions";
import { useOrders } from "@/features/dashboard/hooks/useOrders";
import { useFunds } from "@/features/dashboard/FundsContext";
import { usePagination } from "@/features/dashboard/hooks/usePagination";
import { useSort } from "@/features/dashboard/hooks/useSort";
import { useTableRows } from "@/features/dashboard/hooks/useTableRows";
import { TableShell } from "@/features/dashboard/components/TableShell";
import { FilterToolbar } from "@/features/dashboard/components/FilterToolbar";
import { PageShell } from "@/features/dashboard/components/PageShell";
import { ExitRulesDialog } from "@/features/dashboard/components/ExitRulesDialog";
import { Button } from "@/components/ui/button";
import { ROUTES } from "@/pages/routes/routes";
import { squareOffPosition } from "@/services/api";
import { toast } from "sonner";
import { cn } from "@/utils/utils";
import PageInsight from "@/features/assistant/components/PageInsight";

/* No Product or P&L % columns — the book is MIS-only. */
const columns = [
  { key: "symbol", label: "Instrument" },
  { key: "side", label: "Side" },
  { key: "qty", label: "Qty", numeric: true },
  { key: "entry", label: "Entry", numeric: true },
  { key: "ltp", label: "LTP", numeric: true },
  { key: "value", label: "Market value", numeric: true },
  { key: "pnl", label: "P&L", numeric: true },
];

/* No product tabs — every position is MIS. */
export default function PositionsPage() {
  const { positions, loading, refresh: refreshPositions } = usePositions();
  // also refresh orders so exit-rule saves show up there
  const { refresh: refreshOrders } = useOrders();
  // funds feeds the "Margin used" card and refreshes on square-off
  const { funds, refresh: refreshFunds } = useFunds();
  const { sort, dir, toggle } = useSort("pnl");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  // the row whose SL/TP dialog is open (one shared dialog)
  const [rulesRow, setRulesRow] = useState(null);

  const enriched = useMemo(
    () => positions.map((p) => ({ ...p, ...positionPnl(p), value: p.qty * p.ltp })),
    [positions]
  );

  const rows = useTableRows(enriched, { query, filter, sort, dir, pnlKey: "pnl", zeroIsGainer: true });

  const net = rows.reduce((s, r) => s + r.pnl, 0);
  const winners = rows.filter((r) => r.pnl >= 0).length;
  const exposure = rows.reduce((s, r) => s + r.qty * r.ltp, 0);
  /* Cash blocked at entry — what you PAID, not current value. */
  const marginUsed = funds?.misMargin ?? 0;

  // headline numbers use the full filtered rows, not the current page
  const { page, setPage, totalPages, pageRows } = usePagination(rows);

  return (
    <PageShell loading={loading}>
      <PageHeader
        eyebrow="Live book"
        title="Positions"
        description="Everything currently exposed to the market, netted by product type."
      >
        <div className="grid grid-cols-2 gap-x-6 gap-y-8 border-border pl-0 md:grid-cols-3 md:gap-x-8 md:border-l md:pl-10">
          <MetricReadout
            label="Net P&L"
            value={fmtMoney(net, { sign: true })}
            tone={net}
            sub={rows.length ? `${winners} of ${rows.length} in profit` : undefined}
            hint="Mark-to-market P&L of open MIS positions, measured from entry. Holdings are on the Holdings page"
          />
          {/* Same number as Holdings' "Current value", renamed to match. */}
          <MetricReadout
            label="Current value"
            value={fmtMoney(exposure)}
            sub={`${rows.length} open legs`}
            hint="Total notional at market — qty × LTP across all legs, both directions"
          />
          {/* Entry cost — the cash actually blocked. */}
          <MetricReadout
            label="Margin used"
            value={fmtMoney(marginUsed)}
            sub="cash blocked"
            hint="Entry cost of open positions, blocked from available funds until you square off. This demo charges full order value — real MIS margin is roughly a fifth of this"
          />
        </div>
      </PageHeader>

      {/* Same toolbar as Holdings. */}
      <FilterToolbar query={query} onQueryChange={setQuery} filter={filter} onFilterChange={setFilter} />

      <TableShell
        header={<SortableHead columns={columns} sort={sort} dir={dir} onSort={toggle} />}
        rows={rows}
        colSpan={8}
        empty={
          <div className="flex flex-col items-center gap-3">
            <p>No open positions.</p>
            {/* The order ticket lives on the instrument page. */}
            <Button asChild size="sm" variant="outline" className="text-muted-foreground">
              <Link to={ROUTES.watchlist}>New intraday trade →</Link>
            </Button>
          </div>
        }
        page={page}
        totalPages={totalPages}
        onPageChange={setPage}
      >
        {pageRows.map((p) => (
          <tr key={`${p.symbol}-${p.product}-${p.side}`} className="group relative transition-colors hover:bg-surface-sunken">
            <td className={cn("relative", TD)}>
              <span className={cn("absolute inset-y-0 left-0 w-[2px]", p.pnl >= 0 ? "bg-positive" : "bg-negative")} />
              <InstrumentCell symbol={p.symbol} name={p.name} />
            </td>
            <td className={TD}>
              <SideBadge value={p.side} accent={p.side === "LONG"} />
            </td>
            <td className={TD_R}>{p.qty}</td>
            <td className={TD_R}>{fmtMoney(p.entry)}</td>
            <td className={TD_R}>{fmtMoney(p.ltp)}</td>
            <td className={TD_R}>{fmtMoney(p.value)}</td>
            {/* PnlValue renders ₹ + % together (sign-flipped for shorts). */}
            <td className={TD_R}>
              <PnlValue value={p.pnl} pct={p.pnlPct} />
            </td>
            <td className={TD_R}>
              {/* MIS rows exit here; CNC rows exit on the instrument page. */}
              {p.product === "MIS" ? (
                <div className="flex items-center justify-end gap-2">
                  <Button
                    size="xs"
                    variant="outline"
                    onClick={() => setRulesRow(p)}
                    className="text-muted-foreground"
                  >
                    SL / TP
                  </Button>
                  <Button
                    size="xs"
                    onClick={async () => {
                      try {
                        await squareOffPosition(p._id);
                        toast.success(`Squared off ${p.symbol}`);
                        await Promise.all([refreshPositions(), refreshFunds()]);
                      } catch (err) {
                        toast.error(err.message || "Failed to square off");
                      }
                    }}
                    variant="contrast"
                  >
                    Square off
                  </Button>
                </div>
              ) : (
                <Button asChild size="xs" variant="outline" className="text-muted-foreground">
                  <Link to={ROUTES.instrument(p.symbol)}>Exit</Link>
                </Button>
              )}
            </td>
          </tr>
        ))}
      </TableShell>
      <ExitRulesDialog
        open={rulesRow !== null}
        onOpenChange={(o) => !o && setRulesRow(null)}
        row={rulesRow ? rowFromPosition(rulesRow) : null}
        onDone={() => {
          refreshPositions();
          refreshOrders();
        }}
      />
      <div className="animate-entry mt-6 [animation-delay:200ms]">
        <PageInsight
          page="positions"
          data={{
            netPnl: net,
            winners,
            exposure,
            openLegs: rows.length,
            selectedProduct: "MIS",
            biggestMover: rows.length
              ? rows.reduce((a, b) => (Math.abs(b.pnl) > Math.abs(a.pnl) ? b : a))
              : null,
          }}
        />
      </div>
    </PageShell>
  );
}
