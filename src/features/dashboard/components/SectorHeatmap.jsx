import { useMemo } from "react";
import { fmtLargeNumber as fmtCap, fmtMoney, fmtPct, fmtVolume } from "@/utils/tradiumUtils";
import { UNCATEGORIZED } from "./heatmapScale";
import { HeatmapLegend } from "./HeatmapLegend";
import { Field, HeatmapCard } from "./HeatmapCard";

/* Cap of 3 suits a single day's move. */
const CAP = 3;

/* Market fields only — market rows have no qty or P&L. */
function DetailStrip({ row }) {
  if (!row) {
    return (
      <p className="text-[11px] text-muted-foreground">
        Hover a tile for details. Click one to open its chart.
      </p>
    );
  }

  return (
    <div className="flex flex-wrap items-baseline gap-x-5 gap-y-1">
      <span className="text-[13px] font-semibold">{row.symbol}</span>
      <span className="truncate text-[11px] text-muted-foreground">{row.name}</span>
      {/* Not a Field — this is text, not a number. */}
      {row.sector && (
        <span className="rounded bg-secondary px-1.5 py-0.5 text-[10px] text-muted-foreground">
          {row.sector}
        </span>
      )}
      <Field label="LTP" value={fmtMoney(row.ltp)} />
      <Field
        label="Chg"
        value={`${fmtMoney(row.dayChange, { sign: true })} (${fmtPct(row.dayChangePct)})`}
        tone={row.dayChange}
      />
      <Field label="Vol" value={fmtVolume(row.volume)} />
      {/* Full market cap, not free-float. */}
      <Field label="Mkt cap" value={fmtCap(row.marketCap)} />
    </div>
  );
}

/* NIFTY 50 grouped into sectors, sized by market cap, coloured by today's move.
   No stock/sector toggle — grouping is the point of this card. */
export function SectorHeatmap({ stocks, onSelectSymbol }) {
  /* Memoised so the map doesn't relayout on every render. */
  const nodes = useMemo(() => {
    // drop zero/negative caps — they'd be invisible slivers
    const visible = stocks.filter((s) => s.marketCap > 0);

    const bySector = new Map();
    for (const s of visible) {
      const name = s.sector || UNCATEGORIZED;
      if (!bySector.has(name)) bySector.set(name, []);
      bySector.get(name).push({
        symbol: s.symbol,
        value: s.marketCap,
        change: s.dayChangePct,
      });
    }
    // the layout sorts each level by value itself
    return [...bySector].map(([name, children]) => ({ name, children }));
  }, [stocks]);

  return (
    <HeatmapCard
      title="Sector heatmap"
      description="Tile size is market cap, colour is today's move, grouped by sector."
      /* Outside the click wrapper, so it can't trigger a select. */
      action={<HeatmapLegend cap={CAP} />}
      rows={stocks}
      data={nodes}
      /* Taller — sector headers plus 50 tiles need room. */
      width={900}
      height={320}
      cap={CAP}
      /* Outline the hovered tile's whole sector. */
      getHighlightGroup={(row) => row.sector || UNCATEGORIZED}
      renderStrip={(row) => <DetailStrip row={row} />}
      emptyMessage="Awaiting first market sync."
      onSelectSymbol={onSelectSymbol}
    />
  );
}
