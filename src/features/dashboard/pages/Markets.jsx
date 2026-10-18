import { Link, useNavigate } from "react-router-dom";
import { useMemo, useState } from "react";
import {
  TD, TD_R, InstrumentCell, MetricReadout, PageHeader, SortableHead,
  fmtLargeNumber, fmtMoney, fmtPct, fmtVolume, toneClass, topMovers,
} from "@/utils/tradiumUtils";
import { useMarketOverview } from "@/features/dashboard/hooks/useMarketOverview";
import { usePagination } from "@/features/dashboard/hooks/usePagination";
import { useSort } from "@/features/dashboard/hooks/useSort";
import { useTableRows } from "@/features/dashboard/hooks/useTableRows";
import { TableShell } from "@/features/dashboard/components/TableShell";
import { FilterToolbar } from "@/features/dashboard/components/FilterToolbar";
import { PageShell } from "@/features/dashboard/components/PageShell";
import { SectorHeatmap } from "@/features/dashboard/components/SectorHeatmap";
import { Button } from "@/components/ui/button";
import { ROUTES } from "@/pages/routes/routes";
import { cn } from "@/utils/utils";
import PageInsight from "@/features/assistant/components/PageInsight";

const columns = [
  { key: "symbol", label: "Instrument" },
  { key: "ltp", label: "LTP", numeric: true },
  { key: "dayChangePct", label: "Day change", numeric: true },
  { key: "volume", label: "Volume", numeric: true },
  { key: "marketCap", label: "Mkt cap", numeric: true },
];

/* Index levels are points, not money — so no ₹ symbol. */
function fmtLevel(v) {
  return v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// Matches SectorHeatmap's tile readout: every NIFTY 50 constituent is north of
// ₹0.97 lakh crore, so lakh crore is the unit that reads naturally.
const fmtCap = fmtLargeNumber;

export default function MarketsPage() {
  const { indices, stocks, asOf, loading } = useMarketOverview();
  const navigate = useNavigate();
  const { sort, dir, toggle } = useSort("marketCap");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");

  /* Breadth over the whole 50, not the filtered set. */
  const breadth = useMemo(() => {
    let up = 0;
    let down = 0;
    for (const s of stocks) {
      if (s.dayChangePct > 0) up += 1;
      else if (s.dayChangePct < 0) down += 1;
    }
    return { up, down, flat: stocks.length - up - down };
  }, [stocks]);

  const rows = useTableRows(stocks, { query, filter, sort, dir, pnlKey: "dayChangePct", zeroIsGainer: false });

  const { page, setPage, totalPages, pageRows } = usePagination(rows);

  /* The heatmap click opens the instrument route — the chart and order form
     are what you want next. */
  function openSymbol(symbol) {
    navigate(ROUTES.instrument(symbol));
  }

  return (
    <PageShell loading={loading}>
      <PageHeader
        title="Markets"
        description={
          asOf
            ? "Live NIFTY 50 constituents, refreshed every five minutes."
            : "Live NIFTY 50 constituents. Awaiting the first market sync."
        }
      >
        {/* Three indices plus breadth, in the same four-up grid the other pages
            use for their headline metrics. */}
        <div className="grid grid-cols-2 gap-x-6 gap-y-8 border-border pl-0 md:grid-cols-4 md:gap-x-8 md:border-l md:pl-10">
          {indices.map((i) => (
            <MetricReadout
              key={i.symbol}
              label={i.name}
              value={fmtLevel(i.ltp)}
              tone={i.dayChange}
              sub={fmtPct(i.dayChangePct)}
            />
          ))}
          <MetricReadout
            label="Breadth"
            /* Green advances, red declines — the convention every trading
               terminal uses, so the number reads without a label. */
            value={
              <>
                <span className="text-positive">{breadth.up} ↑</span>
                <span className="text-muted-foreground"> / </span>
                <span className="text-negative">{breadth.down} ↓</span>
              </>
            }
            /* NIFTY's own move gives the breadth number context. indices[0] is NIFTY 50. */
            sub={
              indices.length
                ? `NIFTY 50 ${fmtPct(indices[0].dayChangePct)}${breadth.flat > 0 ? ` · ${breadth.flat} unchanged` : ""}`
                : undefined
            }
            hint="NIFTY 50 constituents advancing vs declining today, regardless of the filter above"
          />
        </div>
      </PageHeader>

      {/* Same three filter pills as Holdings; no "most active" — the Volume
          column already sorts. */}
      <FilterToolbar query={query} onQueryChange={setQuery} filter={filter} onFilterChange={setFilter} />

      <TableShell
        header={<SortableHead columns={columns} sort={sort} dir={dir} onSort={toggle} />}
        rows={rows}
        colSpan={7}
        empty={stocks.length === 0 ? "Awaiting the first market sync." : "No constituents match that filter."}
        page={page}
        totalPages={totalPages}
        onPageChange={setPage}
      >
        {pageRows.map((s) => (
          <tr key={s.symbol} className="group transition-colors hover:bg-surface-sunken">
            <td className={TD}>
              <InstrumentCell symbol={s.symbol} name={s.name} />
            </td>
            <td className={TD_R}>{fmtMoney(s.ltp)}</td>
            <td className={cn(TD_R, toneClass(s.dayChangePct))}>
              {fmtMoney(s.dayChange, { sign: true })} ({fmtPct(s.dayChangePct)})
            </td>
            <td className={TD_R}>{fmtVolume(s.volume)}</td>
            <td className={TD_R}>{fmtCap(s.marketCap)}</td>
            <td className={TD_R}>
              <Button asChild size="xs" variant="contrast">
                <Link to={ROUTES.instrument(s.symbol)}>Trade</Link>
              </Button>
            </td>
          </tr>
        ))}
      </TableShell>

      {/* items-start stops the shorter insight card stretching to the heatmap's height. */}
      <div className="animate-entry mt-6 grid grid-cols-1 items-start gap-6 [animation-delay:200ms] lg:grid-cols-3">
        <div className="lg:col-span-2" data-capture="sector-heatmap">
          {/* The heatmap always sees the full index, not the filtered rows. */}
          <SectorHeatmap stocks={stocks} onSelectSymbol={openSymbol} />
        </div>
        <PageInsight
          page="markets"
          data={{
            advancing: breadth.up,
            declining: breadth.down,
            indices: indices.map((i) => ({
              name: i.name,
              level: i.ltp,
              dayChangePct: i.dayChangePct,
            })),
            topMovers: topMovers(stocks),
          }}
        />
      </div>
    </PageShell>
  );
}
