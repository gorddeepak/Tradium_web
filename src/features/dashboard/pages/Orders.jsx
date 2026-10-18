import { useMemo, useState } from "react";
import { toast } from "sonner";
import { MetricReadout, PageHeader, SideBadge, StatusPill, InstrumentCell, TD, TD_R, TH, TH_ROW, fmtMoney, fmtDateTime, isToday } from "@/utils/tradiumUtils";
import { useOrders } from "@/features/dashboard/hooks/useOrders";
import { useFunds } from "@/features/dashboard/FundsContext";
import { usePagination } from "@/features/dashboard/hooks/usePagination";
import { TableShell } from "@/features/dashboard/components/TableShell";
import { PageShell } from "@/features/dashboard/components/PageShell";
import { cancelOrder } from "@/services/api";
import { cn } from "@/utils/utils";
import PageInsight from "@/features/assistant/components/PageInsight";

const tabs = ["ALL", "OPEN", "EXECUTED", "CANCELLED", "REJECTED"];

/* Column config: numeric:true right-aligns the column. */
const columns = [
  { key: "id", label: "Order ID" },
  { key: "instrument", label: "Instrument" },
  { key: "side", label: "Side" },
  { key: "type", label: "Type" },
  // MIS vs CNC matters, so show it
  { key: "product", label: "Product" },
  { key: "qty", label: "Qty", numeric: true },
  { key: "price", label: "Price", numeric: true },
  { key: "status", label: "Status" },
  { key: "time", label: "Time", numeric: true },
  { key: "action", label: "Action", numeric: true },
];

export default function OrdersPage() {
  const { orders, loading, refresh: refreshOrders } = useOrders();
  // funds feeds the blocked-margin sub and refreshes on cancel (refund)
  const { funds, refresh: refreshFunds } = useFunds();
  const [tab, setTab] = useState("ALL");
  // A Set of ids that are cancelling right now.
  const [cancellingIds, setCancellingIds] = useState(() => new Set());

  async function onCancel(order) {
    setCancellingIds((prev) => new Set(prev).add(order._id));
    try {
      await cancelOrder(order._id);
      toast.success(`Cancelled ${order.side.toLowerCase()} order for ${order.qty} ${order.symbol}`);
      await Promise.all([refreshOrders(), refreshFunds()]);
    } catch (err) {
      toast.error(err.message || "Failed to cancel order");
    } finally {
      setCancellingIds((prev) => {
        const next = new Set(prev);
        next.delete(order._id);
        return next;
      });
    }
  }

  const rows = useMemo(
    () => orders.filter((o) => tab === "ALL" || o.status === tab),
    [orders, tab]
  );

  const counts = useMemo(() => {
    const c = { ALL: orders.length };
    for (const o of orders) c[o.status] = (c[o.status] ?? 0) + 1;
    return c;
  }, [orders]);

  const turnover = rows.reduce((s, o) => s + o.filled * o.price, 0);

  /* Filled value bought and sold today, executed orders only. */
  const { boughtToday, soldToday } = orders.reduce(
    (acc, o) => {
      if (o.status === "EXECUTED" && isToday(o.createdAt)) {
        if (o.side === "BUY") acc.boughtToday += o.filled * o.price;
        else acc.soldToday += o.filled * o.price;
      }
      return acc;
    },
    { boughtToday: 0, soldToday: 0 }
  );

  // Turnover uses all matching rows, not just this page.
  const { page, setPage, totalPages, pageRows } = usePagination(rows);

  return (
    <PageShell loading={loading}>
      <PageHeader
        eyebrow="Order book"
        title="Orders"
        description="Every instruction sent to the exchange today and yesterday."
      >
        <div className="grid grid-cols-2 gap-x-6 gap-y-8 border-border pl-0 md:grid-cols-3 md:gap-x-8 md:border-l md:pl-10">
          {/* Today's filled buy/sell values. */}
          <MetricReadout
            label="Bought today"
            value={fmtMoney(boughtToday)}
            sub={`Sold ${fmtMoney(soldToday)}`}
            hint="Filled value of today's executed orders, buys and sells. Open and partial orders excluded"
          />
          <MetricReadout
            label="Executed turnover"
            value={fmtMoney(turnover)}
            hint={`Filled qty × price across every order in the ${tab.toLowerCase()} tab`}
          />
          <MetricReadout
            label="Working orders"
            value={String(counts["OPEN"] ?? 0)}
            sub={funds?.blockedInOrders ? `${fmtMoney(funds.blockedInOrders, { decimals: 0 })} blocked` : undefined}
            hint="Open orders. A buy's estimated total is blocked from available funds until it fills or is cancelled"
          />
        </div>
      </PageHeader>

      <div className="animate-entry mb-4 flex w-fit gap-1 rounded-lg bg-secondary p-1 [animation-delay:100ms]">
        {tabs.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={cn(
              "flex items-center gap-2 rounded-md px-3 py-1 text-[11px] font-semibold capitalize transition-all",
              t === tab ? "bg-surface shadow-sm ring-1 ring-black/5" : "text-muted-foreground hover:text-foreground"
            )}
          >
            {t.toLowerCase()}
            <span className="num text-[10px] opacity-60">{counts[t] ?? 0}</span>
          </button>
        ))}
      </div>

      {/* Orders aren't sortable, so the header is a plain row instead of SortableHead. */}
      <TableShell
        header={
          <tr className={TH_ROW}>
            {columns.map((c) => (
              <th
                key={c.key}
                className={cn(
                  TH,
                  c.numeric && "text-right"
                )}
              >
                {c.label}
              </th>
            ))}
          </tr>
        }
        rows={rows}
        colSpan={10}
        empty="No orders with this status."
        page={page}
        totalPages={totalPages}
        onPageChange={setPage}
      >
        {pageRows.map((o) => (
          <tr key={o._id} className="transition-colors hover:bg-surface-sunken">
            <td className={cn(TD, "text-[11px] text-muted-foreground")}>{o._id.slice(-8).toUpperCase()}</td>
            <td className={TD}>
              <InstrumentCell symbol={o.symbol} name={o.name} />
            </td>
            <td className={TD}>
              <SideBadge value={o.side} accent={o.side === "BUY"} />
            </td>
            <td className={cn(TD, "font-sans text-[11px] uppercase tracking-wide text-muted-foreground")}>
              {o.type.toLowerCase()}
              {/* Show the trigger price for stop orders. */}
              {(o.type === "SL" || o.type === "SL-M") && o.triggerPrice > 0 && (
                <span className="num ml-1 normal-case text-muted-foreground/70">
                  · trig {fmtMoney(o.triggerPrice)}
                </span>
              )}
              {/* Badge for bracket exit legs. */}
              {o.isExit && (
                <span className="ml-1.5 rounded border border-border px-1 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-muted-foreground">
                  Exit
                </span>
              )}
            </td>
            <td className={cn(TD, "font-sans text-[11px] uppercase tracking-wide text-muted-foreground")}>
              {o.product.toLowerCase()}
            </td>
            <td className={TD_R}>
              {o.filled}
              <span className="text-muted-foreground"> / {o.qty}</span>
            </td>
            <td className={TD_R}>
              {fmtMoney(o.price)}
              {/* SL has a limit price; MARKET types have none. */}
              {o.type === "SL" && <div className="font-sans text-[10px] text-muted-foreground">limit</div>}
              {(o.type === "MARKET" || o.type === "SL-M") && (
                <div className="font-sans text-[10px] text-muted-foreground">at market</div>
              )}
            </td>
            <td className={TD}>
              <StatusPill status={o.status} />
            </td>
            <td className={cn(TD_R, "text-[11px] text-muted-foreground")}>
              {fmtDateTime(o.createdAt)}
            </td>
            {/* Cancel button only for open orders. */}
            <td className={TD_R}>
              {o.status === "OPEN" ? (
                <button
                  onClick={() => onCancel(o)}
                  disabled={cancellingIds.has(o._id)}
                  className="rounded-md border border-border px-2.5 py-1 font-sans text-[11px] font-semibold text-muted-foreground transition-colors hover:border-destructive/40 hover:bg-destructive/5 hover:text-destructive disabled:opacity-50"
                >
                  {cancellingIds.has(o._id) ? "Cancelling..." : "Cancel"}
                </button>
              ) : (
                <span className="text-muted-foreground/40">—</span>
              )}
            </td>
          </tr>
        ))}
      </TableShell>
      <div className="animate-entry mt-6 [animation-delay:200ms]">
        <PageInsight
          page="orders"
          data={{
            totalOrders: orders.length,
            openOrders: counts.OPEN ?? 0,
            executedOrders: counts.EXECUTED ?? 0,
            cancelledOrders: counts.CANCELLED ?? 0,
            rejectedOrders: counts.REJECTED ?? 0,
            turnover,
          }}
        />
      </div>
    </PageShell>
  );
}
