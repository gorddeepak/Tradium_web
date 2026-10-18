import { cn } from "@/utils/utils";
import { fmtSparkline } from "@/utils/tradiumUtils";

/* A tiny line chart of recent daily closes for one watchlist row. */
export function Sparkline({ points, width = 32, height = 14, className = "" }) {
  if (!points || points.length < 2) return null;

  const min = Math.min(...points);
  const max = Math.max(...points);
  const span = max - min || 1; // flat series would divide by zero

  // Map each close to x (spread across the width) and y (inverted: higher
  // price = smaller y, because SVG y grows downward)
  const coords = points.map((close, i) => {
    const x = (i / (points.length - 1)) * width;
    const y = height - ((close - min) / span) * height;
    return fmtSparkline(x, y);
  }).join(" ");

  // Same path closed down to the bottom edge, for the soft fill under the line
  const area = `0,${height} ${coords} ${width},${height}`;

  const color = points[points.length - 1] >= points[0] ? "var(--positive)" : "var(--negative)";

  return (
    <div className={cn("shrink-0", className)} style={{ width, height }}>
      <svg width={width} height={height}>
        <polygon points={area} fill={color} fillOpacity={0.15} />
        <polyline points={coords} fill="none" stroke={color} strokeWidth={1.25} />
      </svg>
    </div>
  );
}
