import { useState } from "react";
import { MarketHeatmap } from "openalgo-heatmap";
import { cn } from "@/utils/utils";
import { toneClass } from "@/utils/tradiumUtils";
import { rampColor, HIGHLIGHT } from "./heatmapScale";

/* Label + value pair used by both heatmap detail strips. */
export function Field({ label, value, tone }) {
  return (
    <span className="flex items-baseline gap-1.5">
      <span className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</span>
      <span className={cn("num text-[12px]", tone !== undefined && toneClass(tone))}>{value}</span>
    </span>
  );
}

/* Shared card chrome for the two heatmap cards; the caller passes rows, the
   highlight group, the strip content, and any controls outside the click. */
export function HeatmapCard({
  title,
  description,
  action,
  rows,
  data,
  width,
  height,
  cap,
  getHighlightGroup,
  renderStrip,
  emptyMessage,
  onSelectSymbol,
}) {
  const [hoveredSymbol, setHoveredSymbol] = useState(null);
  const hovered = hoveredSymbol ? rows.find((r) => r.symbol === hoveredSymbol) : null;

  if (data.length === 0) {
    return (
      <div className="flex h-full items-center justify-center rounded-xl border border-border bg-surface p-6 shadow-xs">
        <p className="text-xs text-muted-foreground">{emptyMessage}</p>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col rounded-xl border border-border bg-surface shadow-xs">
      <div className="flex items-start justify-between gap-4 border-b border-border px-4 py-3">
        <div>
          <h2 className="font-display text-sm font-bold tracking-tight">{title}</h2>
          <p className="text-[11px] text-muted-foreground">{description}</p>
        </div>
        {action}
      </div>

      {/* The click lives on the wrapper — the tiles are plain SVG rects. */}
      <div
        className="allocation-map grow p-3"
        onClick={() => {
          if (hoveredSymbol) onSelectSymbol(hoveredSymbol);
        }}
      >
        <MarketHeatmap
          /* viewBox units set the aspect ratio; legend and tooltip are our own. */
          data={data}
          width={width}
          height={height}
          cap={cap}
          headerHeight={14}
          background="transparent"
          fontFamily="var(--font-sans)"
          colorScale={rampColor}
          showLegend={false}
          showTooltip={false}
          onHover={(leaf) => setHoveredSymbol(leaf?.symbol ?? null)}
          highlightGroup={hovered ? getHighlightGroup(hovered) : null}
          highlightColor={HIGHLIGHT}
          style={{ cursor: hoveredSymbol ? "pointer" : "default" }}
        />
      </div>

      {/* Reserved height, so the card does not jump as the strip fills in. */}
      <div className="min-h-[38px] border-t border-border px-4 py-2">{renderStrip(hovered)}</div>
    </div>
  );
}
