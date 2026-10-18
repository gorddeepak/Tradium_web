import { Link } from "react-router-dom";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  TD, TD_R, InstrumentCell, MetricReadout, PageHeader, PnlValue,
  SortableHead, fmtMoney, fmtPct, holdingMetrics, portfolioSummary, rowFromHolding, toneClass, topMovers,
} from "@/utils/tradiumUtils";
import { useHoldings } from "@/features/dashboard/hooks/useHoldings";
import { useOrders } from "@/features/dashboard/hooks/useOrders";
import { usePagination } from "@/features/dashboard/hooks/usePagination";
import { useSort } from "@/features/dashboard/hooks/useSort";
import { useTableRows } from "@/features/dashboard/hooks/useTableRows";
import { TableShell } from "@/features/dashboard/components/TableShell";
import { FilterToolbar } from "@/features/dashboard/components/FilterToolbar";
import { PageShell } from "@/features/dashboard/components/PageShell";
import { PortfolioTreemap } from "@/features/dashboard/components/PortfolioTreemap";
import { ExitRulesDialog } from "@/features/dashboard/components/ExitRulesDialog";
import { Button } from "@/components/ui/button";
import { ROUTES } from "@/pages/routes/routes";
import { cn } from "@/utils/utils";
import PageInsight from "@/features/assistant/components/PageInsight";

const columns = [
  { key: "symbol", label: "Instrument" },
  { key: "qty", label: "Qty", numeric: true },
  { key: "avgPrice", label: "Avg price", numeric: true },
  { key: "ltp", label: "LTP", numeric: true },
  { key: "dayChangePct", label: "Day", numeric: true },
  { key: "value", label: "Market value", numeric: true },
  // The allocation donut as a sortable number.
  { key: "weight", label: "Weight", numeric: true },
  { key: "pnl", label: "P&L", numeric: true },
];

export default function HoldingsPage() {
  const { holdings, loading, refresh: refreshHoldings } = useHoldings();
  // refresh orders too, so exit-rule saves show up there
  const { refresh: refreshOrders } = useOrders();
  const { sort, dir, toggle } = useSort("value");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  // The symbol whose tile was last clicked in the allocation map
  const [highlighted, setHighlighted] = useState(null);
  // the holding whose SL/TP dialog is open — null means closed
  const [rulesRow, setRulesRow] = useState(null);
  const tableRef = useRef(null);

  const portfolio = useMemo(() => portfolioSummary(holdings), [holdings]);

  const enriched = useMemo(() => {
    // weight needs the portfolio total, so add it here
    const total = portfolio.value;
    return holdings.map((h) => {
      const m = holdingMetrics(h);
      return { ...h, ...m, weight: total ? (m.value / total) * 100 : 0 };
    });
  }, [holdings, portfolio.value]);

  const rows = useTableRows(enriched, { query, filter, sort, dir, pnlKey: "pnl", zeroIsGainer: true });

  // Paginate the filtered rows; header metrics still read the full set.
  const { page, setPage, totalPages, pageRows, pageSize } = usePagination(rows);

  /* Jump to the tile's row, even if it's on another page. */
  function selectSymbol(symbol) {
    const index = rows.findIndex((r) => r.symbol === symbol);
    // Guard so a -1 index can't set the pager to page 0
    if (index === -1) return;
    setPage(Math.floor(index / pageSize) + 1);
    setHighlighted(symbol);
  }

  // Scroll to the row once it's on screen.
  useEffect(() => {
    if (!highlighted) return;
    tableRef.current
      ?.querySelector(`[data-symbol="${highlighted}"]`)
      ?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [highlighted, page]);

  return (
    <PageShell loading={loading}>
      <PageHeader
        eyebrow="Portfolio"
        title="Holdings"
        description="Long-term equity positions settled to your demat account."
      >
        <div className="grid grid-cols-2 gap-x-6 gap-y-8 border-border pl-0 md:grid-cols-4 md:gap-x-8 md:border-l md:pl-10">
          <MetricReadout
            label="Invested"
            value={fmtMoney(portfolio.invested)}
            hint="Cost basis of all holdings — qty × average buy price"
          />
          <MetricReadout
            label="Current value"
            value={fmtMoney(portfolio.value)}
            hint="All holdings at the latest traded price. Cash and intraday positions excluded"
          />
          <MetricReadout
            label="Total P&L"
            value={fmtMoney(portfolio.pnl, { sign: true })}
            tone={portfolio.pnl}
            sub={fmtPct(portfolio.pnlPct)}
            hint="Current value minus invested — unrealized, before charges"
          />
          <MetricReadout
            label="Day's change"
            value={fmtMoney(portfolio.dayPnl, { sign: true })}
            tone={portfolio.dayPnl}
            sub={fmtPct(portfolio.dayPnlPct)}
            hint="Move since the previous close, holdings only — intraday positions are on the Positions page"
          />
        </div>
      </PageHeader>

      <FilterToolbar query={query} onQueryChange={setQuery} filter={filter} onFilterChange={setFilter} />

      {/* containerRef lets selectSymbol scroll to the tile's row. */}
      <TableShell
        header={<SortableHead columns={columns} sort={sort} dir={dir} onSort={toggle} />}
        rows={rows}
        colSpan={9}
        empty={
          holdings.length === 0 ? (
            <div className="flex flex-col items-center gap-3">
              <p>You don&apos;t own any stocks yet.</p>
              <Button asChild size="sm" variant="outline" className="text-muted-foreground">
                <Link to={ROUTES.markets}>Explore stocks →</Link>
              </Button>
            </div>
          ) : (
            "No holdings match that filter."
          )
        }
        page={page}
        totalPages={totalPages}
        onPageChange={setPage}
        containerRef={tableRef}
      >
        {pageRows.map((h) => (
          <tr
            key={h._id}
            data-symbol={h.symbol}
            className={cn(
              "group transition-colors",
              /* Highlight replaces hover styling. */
              h.symbol === highlighted ? "bg-accent/10" : "hover:bg-surface-sunken"
            )}
          >
            <td className={TD}>
              <InstrumentCell symbol={h.symbol} name={h.name} />
            </td>
            <td className={TD_R}>{h.qty}</td>
            <td className={TD_R}>{fmtMoney(h.avgPrice)}</td>
            <td className={TD_R}>{fmtMoney(h.ltp)}</td>
            <td className={cn(TD_R, toneClass(h.dayChangePct))}>{fmtPct(h.dayChangePct)}</td>
            <td className={TD_R}>{fmtMoney(h.value)}</td>
            <td className={cn(TD_R, "text-muted-foreground")}>{fmtPct(h.weight)}</td>
            <td className={TD_R}>
              <PnlValue value={h.pnl} pct={h.pnlPct} />
            </td>
            <td className={TD_R}>
              {/* asChild keeps Trade a real <Link>. */}
              <div className="flex items-center justify-end gap-2">
                <Button
                  size="xs"
                  variant="outline"
                  onClick={() => setRulesRow(h)}
                  className="text-muted-foreground"
                >
                  SL / TP
                </Button>
                <Button
                  asChild
                  size="xs"
                  variant="contrast"
                >
                  <Link to={ROUTES.instrument(h.symbol)}>Trade</Link>
                </Button>
              </div>
            </td>
          </tr>
        ))}
      </TableShell>
      {/* Holdings are always long, so exits are sell brackets. */}
      <ExitRulesDialog
        open={rulesRow !== null}
        onOpenChange={(o) => !o && setRulesRow(null)}
        row={rulesRow ? rowFromHolding(rulesRow) : null}
        onDone={() => {
          refreshHoldings();
          refreshOrders();
        }}
      />
      {/* items-start stops the insight card stretching to the map's height. */}
      <div className="animate-entry mt-6 grid grid-cols-1 items-start gap-6 [animation-delay:200ms] lg:grid-cols-3">
        <div className="lg:col-span-2">
          {/* Fed the filtered rows, so every tile has a table row. */}
          <PortfolioTreemap rows={rows} onSelectSymbol={selectSymbol} />
        </div>
        <PageInsight
          page="holdings"
          data={{
            invested: portfolio.invested,
            currentValue: portfolio.value,
            totalPnl: portfolio.pnl,
            dayPnl: portfolio.dayPnl,
            positions: rows.length,
            topMovers: topMovers(rows),
          }}
        />
      </div>
    </PageShell>
  );
}
