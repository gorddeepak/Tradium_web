import { Link } from "react-router-dom";
import { useMemo, useState } from "react";
import {
  TD, TD_R, TH, TH_ROW,
  InstrumentCell, MetricReadout, PnlValue, RangePills, SectionHeading, Sunken,
  fmtMoney, fmtPct, isToday, StatusPill, toneClass, holdingMetrics, portfolioSummary, positionPnl,
} from "@/utils/tradiumUtils";
import { PerformanceChart } from "@/features/dashboard/components/PerformanceChart";
import { AllocationDonut } from "@/features/dashboard/components/AllocationDonut";
import { TableShell } from "@/features/dashboard/components/TableShell";
import { useHoldings } from "@/features/dashboard/hooks/useHoldings";
import { useOrders } from "@/features/dashboard/hooks/useOrders";
import { usePositions } from "@/features/dashboard/hooks/usePositions";
import { useWatchlist } from "@/features/dashboard/hooks/useWatchlist";
import { useSparkHistory } from "@/features/dashboard/hooks/useSparkHistory";
import { Sparkline } from "@/components/ui/Sparkline";
import { Button } from "@/components/ui/button";
import { useFunds } from "@/features/dashboard/FundsContext";
import { usePortfolioHistory } from "@/features/dashboard/hooks/usePortfolioHistory";
import { useAuth } from "@/features/auth/AuthContext";
import { ROUTES } from "@/pages/routes/routes";
import { cn } from "@/utils/utils";
import PageInsight from "@/features/assistant/components/PageInsight";

const ranges = ["1D", "1W", "1M", "1Y", "ALL"];

export default function DashboardHome() {
  const [range, setRange] = useState("1M");
  const { holdings, loading: holdingsLoading } = useHoldings();
  const { orders, loading: ordersLoading } = useOrders();
  const { positions } = usePositions();
  const { watchlist, loading: watchlistLoading } = useWatchlist();
  const sparkHistory = useSparkHistory(watchlist);
  const { funds } = useFunds();
  const { series, loading: seriesLoading } = usePortfolioHistory(range);

  const portfolio = useMemo(() => portfolioSummary(holdings), [holdings]);

  /* Headline row: misPnl covers open MIS legs, cash covers the funds account,
     netWorth covers everything. */
  const misPnl = positions.reduce((sum, p) => sum + positionPnl(p).pnl, 0);
  const misInvested = positions.reduce((sum, p) => sum + p.qty * p.entry, 0);
  const cash = (funds?.available ?? 0) + (funds?.usedMargin ?? 0);
  const netWorth = portfolio.value + cash + misPnl;

  /* Whole-account P&L against the combined cost base. */
  const overallPnl = portfolio.pnl + misPnl;
  const totalInvested = portfolio.invested + misInvested;
  const overallPct = totalInvested ? (overallPnl / totalInvested) * 100 : 0;

  // Today's P&L covers both books: holdings since yesterday's close plus open MIS legs.
  const todayPnl = portfolio.dayPnl + misPnl;
  /* Yesterday's whole-account value: holdings at close, MIS legs at entry. */
  const prevWholeValue = portfolio.value - portfolio.dayPnl + misInvested;
  const todayPnlPct = prevWholeValue ? (todayPnl / prevWholeValue) * 100 : 0;

  const topHoldings = useMemo(
    () => [...holdings].sort((a, b) => b.qty * b.ltp - a.qty * a.ltp).slice(0, 4),
    [holdings]
  );
  const { user } = useAuth();

  /* Mirrors the loaded layout so nothing jumps when the data lands. */
  if (holdingsLoading) return (
    <main className="mx-auto max-w-[1440px] px-6 py-8">
      <div className="mb-10 flex flex-wrap items-end justify-between gap-8">
        <div className="space-y-2">
          <div className="skeleton-shimmer h-3.5 w-28 rounded-md" />
          <div className="skeleton-shimmer h-9 w-56 rounded-md" />
        </div>
        <div className="grid grid-cols-2 gap-x-6 gap-y-8 lg:grid-cols-4 lg:gap-x-8">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="space-y-2">
              <div className="skeleton-shimmer h-2.5 w-20 rounded-md" />
              <div className="skeleton-shimmer h-5 w-24 rounded-md" />
            </div>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-12 gap-8">
        <div className="col-span-12 space-y-8 lg:col-span-8">
          <div className="skeleton-shimmer h-[400px] w-full rounded-xl" />
          <div className="skeleton-shimmer h-64 w-full rounded-xl" />
        </div>
        <div className="col-span-12 space-y-8 lg:col-span-4">
          <div className="skeleton-shimmer h-[240px] w-full rounded-xl" />
          <div className="skeleton-shimmer h-[240px] w-full rounded-xl" />
          <div className="skeleton-shimmer h-[200px] w-full rounded-xl" />
        </div>
      </div>
    </main>
  );

  return (
    <main className="mx-auto max-w-[1440px] px-6 py-8">
      <header className="animate-entry mb-10 flex flex-wrap items-end justify-between gap-8">
        <div>
          <p className="mb-1 text-sm font-medium text-muted-foreground">
            {new Date().toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long" })}
          </p>
          <h1 className="font-display text-4xl font-extrabold tracking-tight">
            Welcome{user?.username ? `, ${user.username}` : ""}.
          </h1>
        </div>
        {/* 4 columns from md up so the row fits beside the heading at almost
            every desktop width (see the matching grid in the loaded header). */}
        <div className="grid grid-cols-2 gap-x-6 gap-y-8 border-border pl-0 md:grid-cols-4 md:gap-x-8 md:border-l md:pl-10">
          {/* The only card that spans all three books, so its sub doubles as a
              legend: the three components add up to the headline number. */}
          <MetricReadout
            label="Net worth"
            value={fmtMoney(netWorth)}
            sub={`${fmtMoney(cash, { decimals: 0 })} in funds`}
            hint="Holdings at market price + money in funds (available + blocked margin) + open intraday P&L"
          />
          <MetricReadout
            label="Today's P&L"
            value={fmtMoney(todayPnl, { sign: true })}
            tone={todayPnl}
            /* Single whole-account % — no split sub-line, so the units match
               the Overall card. */
            sub={fmtPct(todayPnlPct)}
            hint="Holdings' move since the previous close, plus mark-to-market P&L of open MIS positions, as a % of yesterday's whole-account value"
          />
          {/* Whole-account P&L: holdings + open MIS, % against the combined
              cost base. */}
          <MetricReadout
            label="Overall P&L"
            value={fmtMoney(overallPnl, { sign: true })}
            tone={overallPnl}
            sub={`${fmtPct(overallPct)} on ${fmtMoney(totalInvested, { decimals: 0 })} invested`}
            hint="Unrealized P&L on holdings plus mark-to-market P&L of open MIS positions, as a % of the combined cost base"
          />
          <MetricReadout
            label="Available margin"
            value={fmtMoney(funds?.available ?? 0)}
            sub={`${fmtMoney(funds?.usedMargin ?? 0, { decimals: 0 })} blocked`}
            hint="Cash free to trade right now. Blocked margin and collateral excluded"
          />
        </div>
      </header>

      <div className="grid grid-cols-12 gap-8">
        <div className="col-span-12 space-y-8 lg:col-span-8">
          <Sunken className="animate-entry [animation-delay:100ms]">
            <div className="mb-8 flex flex-wrap items-center justify-between gap-4">
              <div>
                <h2 className="text-sm font-semibold">Performance over time</h2>
                <p className="mt-1 text-[11px] text-muted-foreground">
                  Holdings + open positions at market vs cost basis — cash excluded, {range === "ALL" ? "since inception" : `last ${range}`}
                </p>
              </div>
              <RangePills values={ranges} active={range} onChange={setRange} />
            </div>
            {seriesLoading ? (
              <div className="skeleton-shimmer h-[320px] w-full rounded-lg" />
            ) : series.length < 2 ? (
              /* Same whole-account numbers as the card: MIS legs contribute
                 qty × entry to invested and their P&L to value. */
              (() => {
                const v = series[0]?.value ?? 0;
                const inv = portfolio.invested + misInvested;
                return (
                  <PerformanceChart
                    data={[{ label: "", value: v, invested: inv }, { label: "", value: v, invested: inv }]}
                    up={true}
                  />
                );
              })()
            ) : (
              <PerformanceChart data={series} up={overallPnl >= 0} />
            )}
          </Sunken>

          <section className="animate-entry [animation-delay:200ms]">
            <div className="mb-4 flex items-center justify-between border-b border-border pb-3">
              <h2 className="font-display text-xl font-extrabold tracking-tight">Top holdings</h2>
              <Link to="/dashboard/holdings" className="text-sm font-semibold text-accent hover:underline">
                View all holdings
              </Link>
            </div>
            {/* Not sortable and always has rows (top 4), so no header sort and no empty state. */}
            <TableShell
              header={
                <tr className={TH_ROW}>
                  <th className={TH}>Instrument</th>
                  <th className={cn(TH, "text-right")}>Qty</th>
                  <th className={cn(TH, "text-right")}>Avg price</th>
                  <th className={cn(TH, "text-right")}>LTP</th>
                  <th className={cn(TH, "text-right")}>P&L</th>
                  <th className="px-4 py-3" />
                </tr>
              }
              rows={topHoldings}
              colSpan={6}
            >
              {topHoldings.map((h) => {
                const m = holdingMetrics(h);
                return (
                  <tr key={h._id} className="group transition-colors hover:bg-surface-sunken">
                    <td className={TD}>
                      <InstrumentCell symbol={h.symbol} name={h.name} />
                    </td>
                    <td className={TD_R}>{h.qty}</td>
                    <td className={TD_R}>{fmtMoney(h.avgPrice)}</td>
                    <td className={TD_R}>{fmtMoney(h.ltp)}</td>
                    <td className={TD_R}><PnlValue value={m.pnl} pct={m.pnlPct} /></td>
                    <td className={TD_R}>
                      <Button
                        asChild
                        size="xs"
                        variant="contrast"
                      >
                        <Link to={ROUTES.instrument(h.symbol)}>Trade</Link>
                      </Button>
                    </td>
                  </tr>
                );
              })}
            </TableShell>
          </section>

          <PageInsight
            page="dashboard"
            data={{
              username: user?.username,
              portfolioValue: portfolio.value,
              dayPnl: portfolio.dayPnl,
              dayPnlPct: portfolio.dayPnlPct,
              overallPnl: portfolio.pnl,
              misPnl: misPnl,
              misInvested: misInvested,
              totalInvested: totalInvested,
              netWorth: netWorth,
              cash: cash,
              topMovers: topHoldings
                .slice()
                .sort((a, b) => Math.abs(b.dayChangePct ?? 0) - Math.abs(a.dayChangePct ?? 0))
                .slice(0, 3)
                .map(h => ({ symbol: h.symbol, dayChangePct: h.dayChangePct })),
              ordersToday: orders.filter(o => isToday(o.createdAt)).length,
              watchlistTopMover: watchlist.length
                ? watchlist.slice().sort((a, b) => Math.abs(b.dayChangePct) - Math.abs(a.dayChangePct))[0]
                : null,
              availableMargin: funds?.available ?? 0,
            }}
          />
        </div>

        <div className="col-span-12 space-y-8 lg:col-span-4">
          <Sunken className="animate-entry [animation-delay:300ms] p-5">
            <SectionHeading
              title="Watchlist"
              action={<Link to="/dashboard/watchlist" className="text-[11px] font-semibold text-accent hover:underline">Manage</Link>}
            />
            <div className="space-y-1">
              {watchlistLoading ? (
                /* Row-shaped: one bar for the symbol and a small block for the
                   price, matching the real rows so nothing reflows on load. */
                [0, 1, 2, 3, 4].map((i) => (
                  <div key={i} className="flex items-center justify-between p-2">
                    <div className="skeleton-shimmer h-8 w-24 rounded-md" />
                    <div className="skeleton-shimmer h-8 w-16 rounded-md" />
                  </div>
                ))
              ) : watchlist.length === 0 ? (
                <p className="text-xs text-muted-foreground">No instruments added yet.</p>
              ) : (
                watchlist.slice(0, 5).map((w) => (
                  <Link
                    key={w._id}
                    to={ROUTES.instrument(w.symbol)}
                    className="flex items-center justify-between rounded-lg p-2 transition-colors hover:bg-surface-sunken"
                  >
                    {/* Mirrors the watchlist rail's row: symbol on the left,
                        price and day change stacked right, sparkline between. */}
                    <div className="flex min-w-0 grow flex-col">
                      <span className="truncate text-sm font-semibold">{w.symbol}</span>
                      <span className="text-[10px] text-muted-foreground">{w.exchange}</span>
                    </div>
                    <Sparkline points={sparkHistory[w.symbol]} className="mx-2" />
                    <div className="flex w-[76px] shrink-0 flex-col items-end">
                      <span className="num text-[12px]">{fmtMoney(w.ltp)}</span>
                      <span className={cn("num text-[10px]", toneClass(w.dayChangePct))}>
                        {fmtPct(w.dayChangePct)}
                      </span>
                    </div>
                  </Link>
                ))
              )}
            </div>
          </Sunken>

          <Sunken className="animate-entry [animation-delay:400ms] p-5">
            <SectionHeading title="Holdings allocation" />
            <AllocationDonut holdings={holdings} />
          </Sunken>

          <Sunken className="animate-entry [animation-delay:500ms] p-5">
            <SectionHeading
              title="Recent orders"
              action={<Link to="/dashboard/orders" className="text-[11px] font-semibold text-accent hover:underline">All orders</Link>}
            />
            <div className="space-y-4">
              {ordersLoading ? (
                /* Same idea as the watchlist rows: label + status pill shapes. */
                [0, 1, 2].map((i) => (
                  <div key={i} className="flex items-start justify-between">
                    <div className="space-y-1.5">
                      <div className="skeleton-shimmer h-3.5 w-32 rounded-md" />
                      <div className="skeleton-shimmer h-2.5 w-24 rounded-md" />
                    </div>
                    <div className="skeleton-shimmer h-5 w-16 rounded-full" />
                  </div>
                ))
              ) : orders.length === 0 ? (
                <p className="text-xs text-muted-foreground">No orders yet.</p>
              ) : (
                orders.slice(0, 4).map((o) => (
                  <div key={o._id} className="flex items-start justify-between">
                    <div className="flex flex-col">
                      <span className="text-[12px] font-semibold">{o.side === "BUY" ? "Buy" : "Sell"} {o.symbol}</span>
                      <span className="num text-[10px] text-muted-foreground">
                        {o.qty} × {fmtMoney(o.price)} · {new Date(o.createdAt).toLocaleTimeString()}
                      </span>
                    </div>
                    <StatusPill status={o.status} />
                  </div>
                ))
              )}
            </div>
          </Sunken>
        </div>
      </div>
    </main>
  );
}
