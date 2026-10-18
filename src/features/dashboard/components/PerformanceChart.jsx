import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { fmtMoney } from "@/utils/tradiumUtils";

/* Two series on one ₹ axis: portfolio value (area) and invested (line on top). */
export function PerformanceChart({ data, up = true, height = 320 }) {
  const stroke = up ? "var(--positive)" : "var(--negative)";
  const investedStroke = "#3b82f6";

  // Domain must cover both series; invested is null on old snapshots
  const values = data.flatMap((d) => [d.value, d.invested]).filter((v) => v != null);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const pad = (max - min) * 0.15 || 1;

  return (
    <div>
      <div style={{ height }} className="w-full">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id="tradium-area" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={stroke} stopOpacity={0.16} />
                <stop offset="100%" stopColor={stroke} stopOpacity={0} />
              </linearGradient>
            </defs>
            <XAxis dataKey="label" tickLine={false} axisLine={false} minTickGap={48}
              tick={{ fontSize: 10, fill: "var(--muted-foreground)", fontFamily: "var(--font-mono)" }} />
            <YAxis domain={[min - pad, max + pad]} orientation="right" width={64} tickLine={false} axisLine={false}
              tickFormatter={(v) => fmtMoney(v, { decimals: 0 })}
              tick={{ fontSize: 10, fill: "var(--muted-foreground)", fontFamily: "var(--font-mono)" }} />
            <Tooltip
              cursor={{ stroke: "var(--border-strong)", strokeWidth: 1 }}
              contentStyle={{ borderRadius: 8, border: "1px solid var(--border)", background: "var(--surface)", fontSize: 12, fontFamily: "var(--font-mono)", boxShadow: "0 8px 24px -12px rgb(0 0 0 / 0.25)" }}
              labelStyle={{ color: "var(--muted-foreground)", fontSize: 10 }}
              formatter={(v, name) => [
                v == null ? "—" : fmtMoney(v),
                name === "value" ? "Portfolio value" : "Invested value",
              ]}
            />
            <Area type="monotone" dataKey="value" stroke={stroke} strokeWidth={2} fill="url(#tradium-area)" dot={false} activeDot={{ r: 3, strokeWidth: 0, fill: stroke }} />
            <Area type="monotone" dataKey="invested" stroke={investedStroke} strokeWidth={1.5} fill="none" dot={false} activeDot={{ r: 3, strokeWidth: 0, fill: investedStroke }} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-2 flex items-center gap-5 px-1 text-xs font-medium text-muted-foreground">
        <span className="flex items-center gap-2">
          <span className="h-[2px] w-5 rounded-full" style={{ background: stroke }} />
          Portfolio value
        </span>
        <span className="flex items-center gap-2">
          <span className="h-[2px] w-5 rounded-full" style={{ background: investedStroke }} />
          Invested value
        </span>
      </div>
    </div>
  );
}
