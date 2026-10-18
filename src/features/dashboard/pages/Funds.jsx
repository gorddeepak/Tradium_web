import { useState } from "react";
import { toast } from "sonner";
import { CheckIcon, SmartphoneIcon, LandmarkIcon, WalletIcon } from "lucide-react";
import { MetricReadout, PageHeader, SectionHeading, StatusPill, Sunken, TD, TD_R, TH, TH_ROW, FIELD_LABEL, fmtMoney, fmtDate, toneClass, portfolioSummary } from "@/utils/tradiumUtils";
import { useFunds } from "@/features/dashboard/FundsContext";
import { useHoldings } from "@/features/dashboard/hooks/useHoldings";
import { useTransactions } from "@/features/dashboard/hooks/useTransactions";
import { usePagination } from "@/features/dashboard/hooks/usePagination";
import { TableShell } from "@/features/dashboard/components/TableShell";
import { createTransaction } from "@/services/api";
import { cn } from "@/utils/utils";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";

/* Payment methods for looks — only paper cash actually works. */
const PAYMENT_METHODS = [
  { id: "UPI", label: "UPI", hint: "Instant · Free", icon: SmartphoneIcon, available: false },
  { id: "NETBANKING", label: "Net banking", hint: "Gateway fee applies", icon: LandmarkIcon, available: false },
  { id: "PAPER_CASH", label: "Paper cash", hint: "Instant · Simulated", icon: WalletIcon, available: true },
];

export default function FundsPage() {
  const { funds, loading: fundsLoading, refresh: refreshFunds } = useFunds();
  const { transactions, setTransactions, loading: txnLoading } = useTransactions();
  // holdings only feed the net-worth footer
  const { holdings } = useHoldings();
  const [mode, setMode] = useState("DEPOSIT");
  const [amount, setAmount] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [paymentMethod, setPaymentMethod] = useState("PAPER_CASH");
  // "review" -> user checks amount + method, "success" -> payment done, shows tick
  const [dialogPhase, setDialogPhase] = useState("review");
  // the amount actually transacted, kept for the success screen after the input clears
  const [completedAmount, setCompletedAmount] = useState(0);

  /* Must run before the early return below — hooks run every render. */
  const { page, setPage, totalPages, pageRows } = usePagination(transactions);

  if (fundsLoading || txnLoading) {
    return (
      <main className="p-8">
        <div className="skeleton-shimmer mb-6 h-4 w-24 rounded-md" />
        <div className="skeleton-shimmer h-48 w-full rounded-xl" />
      </main>
    );
  }

  const available = funds?.available ?? 0;
  const usedMargin = funds?.usedMargin ?? 0;
  const total = available + usedMargin;
  const utilisation = total ? (usedMargin / total) * 100 : 0;
  // Cash (this page) + stocks (Holdings) = net worth.
  const portfolio = portfolioSummary(holdings);
  const netWorth = portfolio.value + total;
  // the balance the pending form amount would leave
  const availableAfter =
    mode === "DEPOSIT" ? available + (Number(amount) || 0) : available - (Number(amount) || 0);

  // Validate the amount, then open the dialog.
  function submit(e) {
    e.preventDefault();
    const value = Number(amount);
    if (!value || value <= 0) {
      toast.error("Enter an amount greater than zero");
      return;
    }
    if (mode === "WITHDRAWAL" && value > available) {
      toast.error("Amount exceeds available balance");
      return;
    }
    setDialogPhase("review");
    setConfirmOpen(true);
  }

  async function confirmTransaction() {
    const value = Number(amount);
    setSubmitting(true);
    try {
      // Send the method so the transaction records it.
      const result = await createTransaction({
        kind: mode,
        amount: value,
        method: PAYMENT_METHODS.find((m) => m.id === paymentMethod)?.label,
      });
      setTransactions((t) => [result.transaction, ...t]);
      // refresh so every balance readout updates
      await refreshFunds();
      setCompletedAmount(value);
      setAmount("");
      setDialogPhase("success");
      toast.success(`${mode === "DEPOSIT" ? "Deposit" : "Withdrawal"} of ${fmtMoney(value)} completed`);
      // let the user see the tick, then close
      setTimeout(() => {
        setConfirmOpen(false);
        setSubmitting(false);
      }, 1600);
    } catch (err) {
      toast.error(err.message || "Transaction failed");
      setSubmitting(false);
    }
  }

  return (
    <main className="mx-auto max-w-[1440px] px-6 py-8">
      <PageHeader
        eyebrow="Treasury"
        title="Funds"
        description="Cash available to trade, margin currently committed, and every movement in between."
      >
        <div className="grid grid-cols-2 gap-x-6 gap-y-8 border-border pl-0 md:grid-cols-4 md:gap-x-8 md:border-l md:pl-10">
          <MetricReadout
            label="Available balance"
            value={fmtMoney(available)}
            hint="Cash free to trade right now — total balance minus margin blocked by open positions and orders"
          />
          <MetricReadout
            label="Used margin"
            value={fmtMoney(usedMargin)}
            hint="Cash blocked by open MIS positions. Released when they are squared off"
          />
          <MetricReadout
            label="Total balance"
            value={fmtMoney(total)}
            hint="All money in the funds account: available + blocked"
          />
          {/* Realized P&L is all-time, not today's number. */}
          <MetricReadout
            label="Realized P&L"
            value={`${(funds?.realizedPnl ?? 0) >= 0 ? "+" : ""}${fmtMoney(funds?.realizedPnl ?? 0)}`}
            tone={funds?.realizedPnl ?? 0}
            sub="all-time, settled trades"
            hint="Sum of every closed trade's settlement — sells and square-offs. Unrealized holdings P&L is on the Holdings page"
          />
        </div>
      </PageHeader>

      <div className="grid grid-cols-12 gap-8">
        <div className="col-span-12 space-y-8 lg:col-span-8">
          <Sunken className="animate-entry [animation-delay:100ms]">
            <SectionHeading
              title="Margin utilisation"
              action={<span className="num text-[11px] text-muted-foreground">{utilisation.toFixed(1)}% deployed</span>}
            />
            <div className="h-2 w-full overflow-hidden rounded-full bg-secondary">
              <div className="h-full bg-accent" style={{ width: `${utilisation}%` }} />
            </div>
            <div className="mt-6 grid grid-cols-3 gap-6 border-t border-border pt-6">
              <div>
                <p className="text-[11px] uppercase tracking-wider text-muted-foreground">Blocked in open orders</p>
                <p className="num mt-1 text-lg">{fmtMoney(funds?.blockedInOrders ?? 0)}</p>
              </div>
              <div>
                <p className="text-[11px] uppercase tracking-wider text-muted-foreground">MIS margin at risk</p>
                <p className="num mt-1 text-lg">{fmtMoney(funds?.misMargin ?? 0)}</p>
              </div>
              <div>
                <p className="text-[11px] uppercase tracking-wider text-muted-foreground">Settlement cycle</p>
                <p className="num mt-1 text-lg">T+1</p>
              </div>
            </div>
            {/* Net worth = cash + stocks, shown in plain sight. */}
            <p className="num mt-6 border-t border-border pt-4 text-[11px] text-muted-foreground">
              Net worth {fmtMoney(netWorth)} = holdings {fmtMoney(portfolio.value)} + funds {fmtMoney(total)}
            </p>
          </Sunken>

          <section className="animate-entry [animation-delay:200ms]">
            <h2 className="font-display mb-4 text-xl font-extrabold tracking-tight">Transaction history</h2>
            {/* Not sortable, so the header is a plain row instead of SortableHead. */}
            <TableShell
              header={
                <tr className={TH_ROW}>
                  {["Type", "Method", "Date", "Amount", "Status"].map((h, i) => (
                    <th key={h} className={cn(TH, i === 3 && "text-right")}>
                      {h}
                    </th>
                  ))}
                </tr>
              }
              rows={transactions}
              colSpan={5}
              empty="No transactions yet."
              page={page}
              totalPages={totalPages}
              onPageChange={setPage}
            >
              {pageRows.map((t) => (
                <tr key={t._id} className="transition-colors hover:bg-surface-sunken">
                  <td className={cn(TD, "font-sans text-[11px] uppercase tracking-wide")}>{t.kind.toLowerCase()}</td>
                  <td className={cn(TD, "font-sans text-[13px] text-muted-foreground")}>{t.method}</td>
                  <td className={cn(TD, "text-[12px] text-muted-foreground")}>
                    {fmtDate(t.createdAt)}
                  </td>
                  <td className={cn(TD_R, toneClass(t.amount))}>{fmtMoney(t.amount, { sign: true })}</td>
                  <td className={TD}><StatusPill status={t.status} /></td>
                </tr>
              ))}
            </TableShell>
          </section>
        </div>

        <div className="col-span-12 lg:col-span-4">
          <Sunken className="animate-entry sticky top-20 [animation-delay:300ms]">
            <div className="mb-5 flex gap-1 rounded-lg bg-secondary p-1">
              {["DEPOSIT", "WITHDRAWAL"].map((m) => (
                <button
                  key={m}
                  onClick={() => setMode(m)}
                  className={cn(
                    "flex-1 rounded-md px-3 py-1.5 text-[12px] font-semibold capitalize transition-all",
                    m === mode ? "bg-surface shadow-sm ring-1 ring-black/5" : "text-muted-foreground hover:text-foreground"
                  )}
                >
                  {m === "DEPOSIT" ? "Add funds" : "Withdraw"}
                </button>
              ))}
            </div>

            <form onSubmit={submit} className="space-y-4">
              <div>
                <label htmlFor="amount" className={FIELD_LABEL}>
                  Amount
                </label>
                <div className="flex items-center rounded-md border border-input bg-surface-sunken px-3">
                  <span className="num text-sm text-muted-foreground">₹</span>
                  <input
                    id="amount"
                    inputMode="decimal"
                    value={amount}
                    onChange={(e) => setAmount(e.target.value.replace(/[^0-9.]/g, ""))}
                    placeholder="0.00"
                    className="num w-full bg-transparent px-2 py-2.5 text-sm outline-none"
                  />
                </div>
              </div>

              <div className="flex gap-2">
                {[5000, 25000, 50000].map((v) => (
                  <button key={v} type="button" onClick={() => setAmount(String(v))} className="num flex-1 rounded border border-border py-1.5 text-[11px] text-muted-foreground transition-colors hover:border-accent/40 hover:text-accent">
                    {fmtMoney(v, { decimals: 0 })}
                  </button>
                ))}
              </div>

              <div className="space-y-2 border-t border-border pt-4 text-[12px]">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Available after</span>
                  <span className="num">{fmtMoney(availableAfter)}</span>
                </div>
              </div>

              <button
                type="submit"
                className="w-full rounded-lg bg-accent py-3 text-[13px] font-semibold text-accent-foreground transition-transform active:scale-[0.99]"
              >
                {mode === "DEPOSIT" ? "Add funds" : "Request withdrawal"}
              </button>
            </form>
          </Sunken>

          <Dialog open={confirmOpen} onOpenChange={(open) => !submitting && setConfirmOpen(open)}>
            <DialogContent
              showCloseButton={!submitting}
              onInteractOutside={(e) => submitting && e.preventDefault()}
            >
              {dialogPhase === "success" ? (
                <div className="flex flex-col items-center gap-3 py-6 text-center">
                  <div className="bg-emerald-500/10 text-emerald-600 flex size-12 items-center justify-center rounded-full">
                    <CheckIcon className="size-6" />
                  </div>
                  <DialogHeader className="items-center">
                    <DialogTitle>
                      {mode === "DEPOSIT" ? "Deposit successful" : "Withdrawal successful"}
                    </DialogTitle>
                    <DialogDescription>
                      {fmtMoney(mode === "DEPOSIT" ? completedAmount : -completedAmount, { sign: true })} via{" "}
                      {PAYMENT_METHODS.find((m) => m.id === paymentMethod)?.label}
                    </DialogDescription>
                  </DialogHeader>
                </div>
              ) : (
                <>
                  <DialogHeader>
                    <DialogTitle>
                      {mode === "DEPOSIT" ? "Confirm deposit" : "Confirm withdrawal"}
                    </DialogTitle>
                    <DialogDescription>
                      {mode === "DEPOSIT"
                        ? "Choose a payment method and review the amount."
                        : "Funds will be debited from your available balance."}
                    </DialogDescription>
                  </DialogHeader>

                  {mode === "DEPOSIT" && (
                    <div className="space-y-2">
                      {PAYMENT_METHODS.map((m) => {
                        const Icon = m.icon;
                        return (
                          <button
                            key={m.id}
                            type="button"
                            disabled={!m.available}
                            onClick={() => setPaymentMethod(m.id)}
                            className={cn(
                              "flex w-full items-center gap-3 rounded-lg border p-3 text-left transition-colors",
                              m.available
                                ? paymentMethod === m.id
                                  ? "border-accent bg-accent/5"
                                  : "border-border hover:border-accent/40"
                                : "cursor-not-allowed border-border opacity-50"
                            )}
                          >
                            <Icon className="size-5 text-muted-foreground" />
                            <span className="flex-1">
                              <span className="block text-[13px] font-medium">{m.label}</span>
                              <span className="block text-[11px] text-muted-foreground">{m.hint}</span>
                            </span>
                            {!m.available && (
                              <span className="rounded-full bg-secondary px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
                                Coming soon
                              </span>
                            )}
                            {m.available && paymentMethod === m.id && (
                              <span className="bg-accent size-2.5 rounded-full" />
                            )}
                          </button>
                        );
                      })}
                    </div>
                  )}

                  <div className="num space-y-2 rounded-lg bg-surface-sunken p-4 text-[13px]">
                    <div className="flex justify-between">
                      <span className="font-sans text-muted-foreground">Amount</span>
                      <span className={toneClass(mode === "DEPOSIT" ? 1 : -1)}>
                        {fmtMoney(Number(amount) || 0, { sign: true })}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="font-sans text-muted-foreground">Current balance</span>
                      <span>{fmtMoney(available)}</span>
                    </div>
                    <div className="flex justify-between border-t border-border pt-2 font-semibold">
                      <span className="font-sans">Balance after</span>
                      <span>{fmtMoney(availableAfter)}</span>
                    </div>
                  </div>

                  <DialogFooter>
                    <Button variant="outline" disabled={submitting} onClick={() => setConfirmOpen(false)}>
                      Cancel
                    </Button>
                    <Button onClick={confirmTransaction} disabled={submitting}>
                      {submitting && <Spinner className="size-4" />}
                      {submitting ? "Processing..." : "Confirm"}
                    </Button>
                  </DialogFooter>
                </>
              )}
            </DialogContent>
          </Dialog>
        </div>
      </div>
    </main>
  );
}
