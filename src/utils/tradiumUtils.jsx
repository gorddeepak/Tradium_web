import { ArrowDown, ArrowUp } from "lucide-react";
import { cn } from "./utils";

export function fmtMoney(v, opts = {}) {
  const decimals = opts.decimals ?? 2;
  const s = Math.abs(v).toLocaleString("en-IN", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
  const sign = v < 0 ? "-" : opts.sign ? "+" : "";
  return `${sign}₹${s}`;
}

export function fmtPct(v) {
  return `${v >= 0 ? "+" : "-"}${Math.abs(v).toFixed(2)}%`;
}

export function fmtVolume(v) {
  if (v >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return String(v);
}

// Indian market caps read best in crore / lakh crore.
export function fmtLargeNumber(v) {
  if (v >= 1e12) return `₹${(v / 1e12).toFixed(2)}L Cr`;
  if (v >= 1e7) return `₹${(v / 1e7).toFixed(0)} Cr`;
  return fmtMoney(v, { decimals: 0 });
}

// SVG polyline coordinate pair for the watchlist sparkline.
export function fmtSparkline(x, y) {
  return `${x.toFixed(1)},${y.toFixed(1)}`;
}

/* Rough estimate of Zerodha's charges — display only, the server never debits these. */
export function estimateCharges({ side, product, turnover }) {
  const brokerage = product === "MIS" ? Math.min(20, turnover * 0.0003) : 0;
  const stt = product === "MIS"
    ? (side === "SELL" ? turnover * 0.00025 : 0)
    : turnover * 0.001;
  const txnCharges = turnover * 0.0000297;
  const sebi = turnover * (10 / 1e7);
  const gst = (brokerage + txnCharges + sebi) * 0.18;
  const stampDuty = side === "BUY" ? turnover * 0.00015 : 0;
  return { brokerage, stt, txnCharges, sebi, gst, stampDuty, total: brokerage + stt + txnCharges + sebi + gst + stampDuty };
}

export function toneClass(v) {
  return v > 0 ? "text-positive" : v < 0 ? "text-negative" : "text-muted-foreground";
}

/* Order/transaction timestamps: compact "04 Sep, 14:32" style. */
export function fmtDateTime(v) {
  return new Date(v).toLocaleString("en-IN", {
    hour: "2-digit",
    minute: "2-digit",
    day: "numeric",
    month: "short",
  });
}

/* Transaction table's date-only column: "04 Sep 2026". */
export function fmtDate(v) {
  return new Date(v).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

// True when the date falls on today's calendar date.
export function isToday(v) {
  return new Date(v).toDateString() === new Date().toDateString();
}

export function PnlValue({ value, pct, className, size = "sm" }) {
  return (
    <span className={cn("num inline-flex items-baseline gap-2", toneClass(value), className)}>
      <span className={size === "lg" ? "text-2xl" : ""}>{fmtMoney(value, { sign: true })}</span>
      {pct !== undefined && (
        <span className={size === "lg" ? "text-sm" : "text-[11px] opacity-70"}>{fmtPct(pct)}</span>
      )}
    </span>
  );
}

/* `hint` shows as a hover tooltip. */
export function MetricReadout({ label, value, sub, tone, hint }) {
  return (
    <div className="flex flex-col" title={hint}>
      <span className="mb-1 text-[11px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
        {label}
      </span>
      {/* text-xl on small screens so the number fits the 4-column grid. */}
      <span className={cn("num text-xl lg:text-2xl", tone !== undefined && toneClass(tone))}>{value}</span>
      {sub && <span className="mt-1 text-[11px] text-muted-foreground">{sub}</span>}
    </div>
  );
}

export function Sunken({ className, children }) {
  return (
    <section className={cn("rounded-xl border border-border bg-surface p-6 shadow-xs", className)}>
      {children}
    </section>
  );
}

export function SectionHeading({ title, action, className }) {
  return (
    <div className={cn("mb-4 flex items-center justify-between border-b border-border pb-3", className)}>
      <h2 className="text-sm font-semibold">{title}</h2>
      {action}
    </div>
  );
}

export function PageHeader({ eyebrow, title, description, children }) {
  return (
    <header className="animate-entry mb-10 flex flex-wrap items-end justify-between gap-6">
      <div>
        {eyebrow && (
          <p className="mb-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
            {eyebrow}
          </p>
        )}
        <h1 className="font-display text-4xl font-extrabold tracking-tight">{title}</h1>
        {/* max-w-md keeps the description from pushing the metrics down. */}
        {description && <p className="mt-2 max-w-md text-sm text-muted-foreground">{description}</p>}
      </div>
      {children}
    </header>
  );
}

export function StatusPill({ status }) {
  const map = {
    EXECUTED: "bg-positive/10 text-positive",
    FILLED: "bg-positive/10 text-positive",
    COMPLETED: "bg-positive/10 text-positive",
    OPEN: "bg-accent/10 text-accent",
    PROCESSING: "bg-accent/10 text-accent",
    CANCELLED: "bg-secondary text-muted-foreground",
    REJECTED: "bg-negative/10 text-negative",
  };
  return (
    <span
      className={cn(
        "inline-block rounded px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
        map[status] ?? "bg-secondary text-muted-foreground",
      )}
    >
      {status.toLowerCase()}
    </span>
  );
}

export function SideBadge({ value, accent }) {
  return (
    <span
      className={cn(
        "rounded px-2 py-0.5 font-sans text-[10px] font-semibold uppercase tracking-wide",
        accent ? "bg-accent/10 text-accent" : "bg-secondary text-foreground"
      )}
    >
      {value}
    </span>
  );
}

export function RangePills({ values, active, onChange, capitalize }) {
  return (
    <div className="flex gap-1 rounded-lg bg-secondary p-1">
      {values.map((v) => (
        <button
          key={v}
          type="button"
          onClick={() => onChange(v)}
          className={cn(
            "rounded-md px-3 py-1 text-[11px] font-semibold transition-all",
            capitalize && "capitalize",
            v === active
              ? "bg-surface shadow-sm ring-1 ring-black/5"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {v}
        </button>
      ))}
    </div>
  );
}

/* ---------- shared table-page pieces ---------- */

/* Loading state shared by every table page. */
export function PageSkeleton() {
  return (
    <main className="p-8">
      <div className="skeleton-shimmer mb-6 h-4 w-24 rounded-md" />
      <div className="skeleton-shimmer h-64 w-full rounded-xl" />
    </main>
  );
}

/* The stacked symbol-over-name cell that leads the table on every page. */
export function InstrumentCell({ symbol, name }) {
  return (
    <div className="flex flex-col">
      <span className="font-sans text-sm font-semibold">{symbol}</span>
      <span className="font-sans text-[11px] text-muted-foreground">{name}</span>
    </div>
  );
}

/* Repeated table/form class strings — one place so every page stays in sync. */
export const TD = "px-4 py-4";
export const TD_R = "px-4 py-4 text-right";
export const TH = "px-4 py-3 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground";
export const TH_ROW = "border-b border-border bg-surface-sunken/60";
export const FIELD_LABEL = "mb-1 block text-[10px] font-semibold uppercase tracking-wider text-muted-foreground";

/* Sortable table header row, built from a columns config. */
export function SortableHead({ columns, sort, dir, onSort }) {
  return (
    <tr className={TH_ROW}>
      {columns.map((c) => (
        <th
          key={c.key}
          className={cn(
            TH,
            c.numeric && "text-right",
          )}
        >
          <button
            onClick={() => onSort(c.key)}
            className={cn(
              "inline-flex items-center gap-1 transition-colors hover:text-foreground",
              sort === c.key && "text-foreground",
            )}
          >
            {c.label}
            {sort === c.key && (dir === "asc" ? <ArrowUp className="size-3" /> : <ArrowDown className="size-3" />)}
          </button>
        </th>
      ))}
      <th className="px-4 py-3" />
    </tr>
  );
}

/* The biggest absolute day movers, for a page's insight card. */
export function topMovers(rows, n = 3) {
  return rows
    .slice()
    .sort((a, b) => Math.abs(b.dayChangePct) - Math.abs(a.dayChangePct))
    .slice(0, n)
    .map((r) => ({ symbol: r.symbol, dayChangePct: r.dayChangePct }));
}

/* Build the row shape ExitRulesDialog expects. */
export function rowFromHolding(h) {
  return {
    symbol: h.symbol,
    name: h.name,
    exchange: h.exchange,
    product: "CNC",
    side: "LONG",
    qty: h.qty,
    entry: h.avgPrice,
    ltp: h.ltp,
  };
}

export function rowFromPosition(p) {
  return {
    symbol: p.symbol,
    name: p.name,
    exchange: p.exchange,
    product: "MIS",
    side: p.side,
    qty: p.qty,
    entry: p.entry,
    ltp: p.ltp,
  };
}

/* ---------- shared SL/TP (bracket) exit logic ---------- */

/* Check SL/target inputs; returns an error message or null. */
export function validateExits({ sl, tp, ltp, isLong }) {
  if (sl > 0 && tp > 0) {
    // stop on the losing side, target on the winning side
    const ordered = isLong ? sl < tp : sl > tp;
    if (!ordered) return isLong
      ? "Stop-loss trigger must be below the target price"
      : "Stop-loss trigger must be above the target price";
  }
  if (sl > 0) {
    const crossed = isLong ? sl >= ltp : sl <= ltp;
    if (crossed) return isLong
      ? "Stop-loss trigger must be below the live price"
      : "Stop-loss trigger must be above the live price";
  }
  if (tp > 0) {
    const crossed = isLong ? tp <= ltp : tp >= ltp;
    if (crossed) return isLong
      ? "Target price must be above the live price"
      : "Target price must be below the live price";
  }
  return null;
}

/* Preview of gain/loss under the SL/TP inputs. */
export function ExitPreview({ sl, tp, isLong, refPrice, ltp, qty }) {
  if (sl <= 0 && tp <= 0) return null;
  // positive diff = gain, negative = loss (direction depends on long/short)
  const signed = (diff) => (diff < 0 ? "−" : "+") + fmtMoney(Math.abs(diff));
  const slDiff = isLong ? sl - refPrice : refPrice - sl;
  const tpDiff = isLong ? tp - refPrice : refPrice - tp;
  const slValid = sl > 0 && (isLong ? sl < ltp : sl > ltp);
  const tpValid = tp > 0 && (isLong ? tp > ltp : tp < ltp);
  return (
    <div className="num space-y-1 text-[11px]">
      {slValid && (
        <p className="text-destructive">
          If stop hits ₹{sl.toFixed(2)}: {signed(slDiff)} ({(slDiff / refPrice * 100).toFixed(2)}%) per share
          {qty > 0 && <> · {signed(slDiff * qty)} total</>}
        </p>
      )}
      {sl > 0 && !slValid && (
        <p className="text-destructive">
          {isLong ? "Stop-loss trigger must be below the live price" : "Stop-loss trigger must be above the live price"}
        </p>
      )}
      {tpValid && (
        <p className="text-emerald-600 dark:text-emerald-400">
          If target hits ₹{tp.toFixed(2)}: {signed(tpDiff)} ({(tpDiff / refPrice * 100).toFixed(2)}%) per share
          {qty > 0 && <> · {signed(tpDiff * qty)} total</>}
        </p>
      )}
      {tp > 0 && !tpValid && (
        <p className="text-destructive">
          {isLong ? "Target price must be above the live price" : "Target price must be below the live price"}
        </p>
      )}
    </div>
  );
}

/* ---------- portfolio math ---------- */

export function holdingMetrics(h) {
  const invested = h.qty * h.avgPrice;
  const value = h.qty * h.ltp;
  const pnl = value - invested;
  const pnlPct = invested ? (pnl / invested) * 100 : 0;
  return { invested, value, pnl, pnlPct };
}

// Convert a day % change into rupees per share.
function dayChangeRupees(h) {
  const denom = 100 + h.dayChangePct;
  if (!denom) return 0; // a -100% change would divide by zero
  return h.qty * h.ltp * (h.dayChangePct / denom);
}

// Kept in sync with calculatePortfolioSummary in server/utils/portfolioMath.js.
export function portfolioSummary(holdings) {
  const invested = holdings.reduce((s, h) => s + h.qty * h.avgPrice, 0);
  const value = holdings.reduce((s, h) => s + h.qty * h.ltp, 0);
  const dayPnl = holdings.reduce((s, h) => s + dayChangeRupees(h), 0);

  // what these same holdings were worth at yesterday's close
  const prevValue = value - dayPnl;

  return {
    invested,
    value,
    pnl: value - invested,
    pnlPct: invested ? ((value - invested) / invested) * 100 : 0,
    dayPnl,
    dayPnlPct: prevValue !== 0 ? (dayPnl / prevValue) * 100 : 0,
  };
}

export function positionPnl(p) {
  const dir = p.side === "LONG" ? 1 : -1;
  const pnl = (p.ltp - p.entry) * p.qty * dir;
  const pnlPct = ((p.ltp - p.entry) / p.entry) * 100 * dir;
  return { pnl, pnlPct };
}

/* ---------- chart colours ---------- */

/* One fixed colour per symbol, so charts always agree. */
export function holdingColors(holdings) {
  const symbols = holdings.map((h) => h.symbol).sort();
  const colors = {};
  symbols.forEach((symbol, i) => {
    // 10 palette tokens = the donut's MAX_SLICES, so named slices never wrap.
    colors[symbol] = `var(--chart-${(i % 10) + 1})`;
  });
  return colors;
}

