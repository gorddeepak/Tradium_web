import { useMemo, useState } from "react";
import { PieChart } from "@/components/charts/pie-chart";
import { PieSlice } from "@/components/charts/pie-slice";
import { PieCenter } from "@/components/charts/pie-center";
import { fmtMoney, holdingColors } from "@/utils/tradiumUtils";

/* Cap the donut at ten slices: nine holdings plus a pooled "Others". */
const MAX_SLICES = 10;

/* padAngle is in RADIANS here, not degrees. */
const PAD_ANGLE = (2 * Math.PI) / 180;

/* How far a hovered slice slides out; the chart reserves the same padding. */
const HOVER_OFFSET = 10;
const INNER_RADIUS = 45;
const SIZE = (72 + HOVER_OFFSET) * 2;

export function AllocationDonut({ holdings }) {
  /* Controlled hover so the legend can follow the hovered slice. */
  const [hoveredIndex, setHoveredIndex] = useState(null);
  /* Memoised so the entrance animation doesn't restart on every render. */
  const slices = useMemo(() => {
    const colors = holdingColors(holdings);

    /* `label` rather than `name`, because that is the key PieCenter reads to
       caption the value it shows while a slice is hovered. */
    const rows = holdings
      .map((h) => ({
        symbol: h.symbol,
        label: h.name,
        value: h.qty * h.ltp,
        color: colors[h.symbol],
      }))
      .filter((r) => r.value > 0)
      .sort((a, b) => b.value - a.value);

    /* Sorting only picks which holdings get named — colours are fixed by symbol. */
    if (rows.length <= MAX_SLICES) return rows;

    const named = rows.slice(0, MAX_SLICES - 1);
    const rest = rows.slice(MAX_SLICES - 1);
    return [
      ...named,
      {
        symbol: "__OTHERS__",
        label: `Others (${rest.length})`,
        value: rest.reduce((s, r) => s + r.value, 0),
        color: "var(--chart-other)",
      },
    ];
  }, [holdings]);

  const total = slices.reduce((s, r) => s + r.value, 0);

  if (!total) {
    return <p className="text-xs text-muted-foreground">No holdings to allocate yet.</p>;
  }

  return (
    <div>
      <PieChart
        className="mx-auto"
        size={SIZE}
        
        data={slices}
        innerRadius={INNER_RADIUS}
        padAngle={PAD_ANGLE}
        hoverOffset={HOVER_OFFSET}
        hoveredIndex={hoveredIndex}
        onHoverChange={setHoveredIndex}
      >
        {/* One PieSlice per datum; geometry and colour come from chart context. */}
        {slices.map((s, i) => (
          <PieSlice key={s.symbol} index={i} showGlow={false} />
        ))}

        {/* The centre shows the hovered slice's value, or the portfolio total. */}
        <PieCenter
          defaultLabel="Total"
          formatOptions={{
            style: "currency",
            currency: "INR",
            maximumFractionDigits: 0,
          }}
          valueClassName="num text-base font-semibold"
          labelClassName="text-[10px] leading-tight uppercase tracking-wider text-muted-foreground"
        />
      </PieChart>

      {/* Keep this legend — colour never carries identity on its own. */}
      <ul className="mt-4 space-y-2">
        {slices.map((s, i) => {
          /* The matching legend row brightens while a slice is hovered. */
          const isHovered = hoveredIndex === i;
          const isFaded = hoveredIndex !== null && !isHovered;
          return (
            <li
              key={s.symbol}
              className={`flex items-center gap-2 text-xs transition-opacity duration-150 ${
                isFaded ? "opacity-50" : ""
              }`}
              onMouseEnter={() => setHoveredIndex(i)}
              onMouseLeave={() => setHoveredIndex(null)}
            >
              <span
                className="h-2.5 w-2.5 shrink-0 rounded-[2px]"
                style={{ background: s.color }}
              />
              <span
                className={`flex-1 truncate ${
                  isHovered ? "text-foreground font-medium" : "text-muted-foreground"
                }`}
              >
                {s.label}
             </span>
              <span className="num shrink-0 font-medium" title={fmtMoney(s.value)}>
                {((s.value / total) * 100).toFixed(1)}%
             </span>
           </li>
          );
        })}
      </ul>
    </div>
  );
}
