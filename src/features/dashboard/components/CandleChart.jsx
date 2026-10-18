import { useEffect, useRef } from "react";
import { createChart, CandlestickSeries } from "lightweight-charts";

const COLORS = {
  mutedForeground: "#737373", // matches --muted-foreground visually
  border: "#e5e5e5",          // matches --border visually
  positive: "#16a34a",        // your green
  negative: "#dc2626",        // your red
};

/* fitKey identifies the dataset; a new one refits the view. */
export function CandleChart({ candles, height = 320, fitKey }) {
  const containerRef = useRef(null);
  // create the chart once; refs let data update without rebuilding
  const chartRef = useRef(null);
  const seriesRef = useRef(null);
  const candlesRef = useRef([]);
  const lastFitKeyRef = useRef(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
  height,
  layout: {
    background: { color: "transparent" },
    textColor: COLORS.mutedForeground,
    fontFamily: "JetBrains Mono, monospace",
    attributionLogo: false, // hides the "Charting by TradingView" badge
  },
  grid: {
    vertLines: { visible: false },
    horzLines: { color: COLORS.border },
  },
  timeScale: {
    borderColor: COLORS.border,
    timeVisible: true,
    secondsVisible: false,
  },
  rightPriceScale: { borderColor: COLORS.border },
});

    const series = chart.addSeries(CandlestickSeries, {
      upColor: COLORS.positive,
      downColor: COLORS.negative,
      borderVisible: false,
      wickUpColor: COLORS.positive,
      wickDownColor: COLORS.negative,
    });

    chartRef.current = chart;
    seriesRef.current = series;

    /* OHLC tooltip, our own div. */
    const container = containerRef.current;
    const tooltip = document.createElement("div");
    tooltip.style.cssText = [
      "position: absolute",
      "display: none",
      "pointer-events: none",
      "z-index: 10",
      "padding: 6px 8px",
      "border-radius: 8px",
      "border: 1px solid var(--border)",
      "background: var(--surface)",
      "box-shadow: 0 8px 24px -12px rgb(0 0 0 / 0.25)",
      "font-family: var(--font-mono)",
      "font-size: 10px",
      "line-height: 1.6",
      "white-space: nowrap",
    ].join("; ");
    container.appendChild(tooltip);

    // time -> index, to find the previous candle
    const indexByTime = new Map();

    chart.subscribeCrosshairMove((param) => {
      const data = param.seriesData?.get?.(series);
      if (!param.point || !data || data.open === undefined) {
        tooltip.style.display = "none";
        return;
      }
      const up = data.close >= data.open;
      const color = up ? COLORS.positive : COLORS.negative;
      const fmt = (v) => v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

      // % change vs the previous candle's close
      const idx = indexByTime.get(param.time);
      const prevClose = idx > 0 ? candlesRef.current[idx - 1].close : data.open;
      const pct = ((data.close - prevClose) / prevClose) * 100;
      const pctColor = pct >= 0 ? COLORS.positive : COLORS.negative;

      const row = (label, value, valueColor) =>
        `<span style="color: var(--muted-foreground)">${label}</span>` +
        `<b style="color: ${valueColor}; justify-self: end">${value}</b>`;
      tooltip.innerHTML =
        `<div style="display: grid; grid-template-columns: auto auto; column-gap: 14px; row-gap: 2px">` +
        row("Open", fmt(data.open), color) +
        row("High", fmt(data.high), color) +
        row("Low", fmt(data.low), color) +
        row("Close", fmt(data.close), color) +
        `</div>` +
        `<div style="margin-top: 4px; padding-top: 4px; border-top: 1px solid var(--border)">` +
        `<span style="color: var(--muted-foreground)">Change</span> ` +
        `<b style="color: ${pctColor}">${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%</b>` +
        `</div>`;

      // flip left near the right edge so it doesn't clip
      const tooltipWidth = tooltip.offsetWidth;
      const left = param.point.x + tooltipWidth + 20 > container.clientWidth
        ? param.point.x - tooltipWidth - 12
        : param.point.x + 12;
      tooltip.style.left = `${Math.max(4, left)}px`;
      tooltip.style.top = "8px";
      tooltip.style.display = "block";
    });

    const resize = () => chart.applyOptions({ width: container.clientWidth });
    window.addEventListener("resize", resize);
    resize();

    return () => {
      window.removeEventListener("resize", resize);
      tooltip.remove();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      lastFitKeyRef.current = null;
    };
  }, [height]);

  // Update data without resetting zoom; refit only when fitKey changes.
  useEffect(() => {
    if (!seriesRef.current || candles.length === 0) return;
    candlesRef.current = candles;
    seriesRef.current.setData(candles);
    if (lastFitKeyRef.current !== fitKey) {
      chartRef.current.timeScale().fitContent();
      lastFitKeyRef.current = fitKey;
    }
  }, [candles, fitKey]);

  return <div ref={containerRef} className="relative w-full" />;
}
