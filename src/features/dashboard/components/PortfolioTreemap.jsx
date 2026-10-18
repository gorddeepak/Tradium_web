import { useMemo, useState } from "react";
import { fmtMoney, fmtPct, RangePills } from "@/utils/tradiumUtils";
import { UNCATEGORIZED } from "./heatmapScale";
import { HeatmapLegend } from "./HeatmapLegend";
import { Field, HeatmapCard } from "./HeatmapCard";

/* Colour cap for total P&L%, which runs much wider than a day's move. */
const CAP = 25;

/* Hovered-tile details as a fixed strip below the map. */
function DetailStrip({ row }) {
  if (!row) {
    return (
      <p className="text-[11px] text-muted-foreground">
        Hover a tile for details. Click one to find it in the table above.
      </p>
    );
  }

  return (
    <div className="flex flex-wrap items-baseline gap-x-5 gap-y-1">
      <span className="text-[13px] font-semibold">{row.symbol}</span>
      <span className="truncate text-[11px] text-muted-foreground">{row.name}</span>
      {/* A chip, not a Field — this is text, not a number. */}
      {row.sector && (
        <span className="rounded bg-secondary px-1.5 py-0.5 text-[10px] text-muted-foreground">
          {row.sector}
        </span>
      )}
      <Field label="Qty" value={String(row.qty)} />
      <Field label="Avg" value={fmtMoney(row.avgPrice)} />
      <Field label="LTP" value={fmtMoney(row.ltp)} />
      <Field label="Value" value={fmtMoney(row.value)} />
      <Field
        label="P&L"
        value={`${fmtMoney(row.pnl, { sign: true })} (${fmtPct(row.pnlPct)})`}
        tone={row.pnl}
      />
    </div>
  );
}

/* Tiles sized by market value, coloured by total P&L. */
export function PortfolioTreemap({ rows, onSelectSymbol }) {
  const [mode, setMode] = useState("stock");

  /* Memoised so the map doesn't relayout on every render. */
  const nodes = useMemo(() => {
    // keep only rows with a value, for the empty-state check
    const visible = rows.filter((r) => r.value > 0);
    const leaf = (r) => ({ symbol: r.symbol, value: r.value, change: r.pnlPct });

    if (mode === "stock") return visible.map(leaf);

    // a sector is just { name, children }
    const bySector = new Map();
    for (const r of visible) {
      const name = r.sector || UNCATEGORIZED;
      if (!bySector.has(name)) bySector.set(name, []);
      bySector.get(name).push(leaf(r));
    }
    // the layout sorts each level by value itself
    return [...bySector].map(([name, children]) => ({ name, children }));
  }, [rows, mode]);

  return (
    <HeatmapCard
      title="Allocation map"
      description={`Tile size is market value, colour is total P&L${mode === "sector" ? ", grouped by sector" : ""}.`}
      /* Outside the click wrapper, so these can't trigger a select. */
      action={
        <div className="flex shrink-0 items-center gap-3">
          <HeatmapLegend cap={CAP} />
          {/* Same pills as the Holdings filter. */}
          <RangePills values={["stock", "sector"]} active={mode} onChange={setMode} />
        </div>
      }
      rows={rows}
      data={nodes}
      /* Sets the map's height. */
      width={900}
      height={220}
      cap={CAP}
      /* Outline the hovered tile's sector. */
      getHighlightGroup={(row) => (mode === "sector" ? row.sector || UNCATEGORIZED : null)}
      renderStrip={(row) => <DetailStrip row={row} />}
      emptyMessage="No holdings to map."
      onSelectSymbol={onSelectSymbol}
    />
  );
}
