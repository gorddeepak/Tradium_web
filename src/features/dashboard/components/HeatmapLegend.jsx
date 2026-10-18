import { rampColor } from "./heatmapScale";

/* Five swatches from -cap to +cap; cap must match the map's own cap. */
export function HeatmapLegend({ cap }) {
  return (
    <div className="flex shrink-0 items-center gap-1.5">
      <span className="num text-[10px] text-muted-foreground">-{cap}%</span>
      {[-cap, -cap / 2, 0, cap / 2, cap].map((v) => (
        <span key={v} className="size-3 rounded-[2px]" style={{ background: rampColor(v, cap) }} />
      ))}
      <span className="num text-[10px] text-muted-foreground">+{cap}%</span>
    </div>
  );
}
