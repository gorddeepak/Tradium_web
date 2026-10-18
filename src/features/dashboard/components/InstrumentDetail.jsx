import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ExitPreview, RangePills, Sunken, FIELD_LABEL, estimateCharges, fmtMoney, fmtPct, fmtVolume, holdingMetrics, positionPnl, toneClass, validateExits, PnlValue } from "@/utils/tradiumUtils";
import { CandleChart } from "@/features/dashboard/components/CandleChart";
import { useInstrument } from "@/features/dashboard/hooks/useInstrument";
import { useFunds } from "@/features/dashboard/FundsContext";
import { useHoldings } from "@/features/dashboard/hooks/useHoldings";
import { usePositions } from "@/features/dashboard/hooks/usePositions";
import { placeOrder } from "@/services/api";
import { cn } from "@/utils/utils";

const ranges = ["1D", "5D", "1M", "6M", "1Y", "5Y", "ALL"];

/* The detail pane on the right of the watchlist: chart, stats, order ticket. */
export function InstrumentDetail() {
  const { symbol } = useParams();
  const [range, setRange] = useState("1M");
  const { instrument, candles, instrumentLoading, candlesLoading } = useInstrument(symbol, range);
  const { funds, refresh: refreshFunds } = useFunds();
  const { holdings, refresh: refreshHoldings } = useHoldings();
  // feeds the "Your position" strip
  const { positions } = usePositions();

  const [side, setSide] = useState("BUY");
  const [orderType, setOrderType] = useState("MARKET");
  const [product, setProduct] = useState("CNC");
  const [qty, setQty] = useState("10");
  const [limitPrice, setLimitPrice] = useState("");
  // optional bracket: server adds SL/target exits when the order fills
  const [slTrigger, setSlTrigger] = useState("");
  const [tpPrice, setTpPrice] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [confirming, setConfirming] = useState(false);

  /* A new symbol starts a clean ticket; the chart range survives. */
  useEffect(() => {
    setSide("BUY");
    setOrderType("MARKET");
    setProduct("CNC");
    setQty("10");
    setLimitPrice("");
    setSlTrigger("");
    setTpPrice("");
    setConfirming(false);
  }, [symbol]);

  // Rendered inside the pane, so the watchlist rail stays.
  if (instrumentLoading) {
    return (
      <div className="space-y-6">
        <div className="skeleton-shimmer h-24 w-full rounded-xl" />
        <div className="skeleton-shimmer h-[426px] w-full rounded-xl" />
      </div>
    );
  }
  if (!instrument) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center rounded-xl border border-border bg-surface text-sm text-muted-foreground shadow-xs">
        Instrument not found.
      </div>
    );
  }

  // A flat 52-week range would divide by zero; park the dot mid-range.
  const rangeSpan = instrument.week52High - instrument.week52Low;
  const rangePos = rangeSpan > 0 ? ((instrument.price - instrument.week52Low) / rangeSpan) * 100 : 50;
  // MARKET executes at the live price; LIMIT at the typed limit price.
  const estPrice = orderType === "MARKET" ? instrument.price : Number(limitPrice) || instrument.price;
  const total = estPrice * (Number(qty) || 0);
  // Price the server uses when placing the order.
  const execPrice = orderType === "MARKET" ? instrument.price : Number(limitPrice) || 0;
  const available = funds ? funds.available : 0;
  // MIS blocks cash either way; CNC only on buy.
  const blocksCash = side === "BUY" || product === "MIS";
  const insufficientFunds = blocksCash && total > available;
  // CNC sells can't exceed held qty; MIS shorts are allowed.
  const holding = holdings.find((h) => h.symbol === instrument.symbol && h.exchange === instrument.exchange);
  const heldQty = holding?.qty ?? 0;
  const avgPrice = holding?.avgPrice ?? 0;
  const insufficientHoldings = side === "SELL" && product !== "MIS" && (Number(qty) || 0) > heldQty;

  // The "Your position" strip, from both books.
  const holdingM = holding ? holdingMetrics(holding) : null;
  const position = positions.find((p) => p.symbol === instrument.symbol) ?? null;
  const positionM = position ? positionPnl(position) : null;

  const stats = [
    { label: "Open", value: fmtMoney(instrument.open) },
    { label: "High", value: fmtMoney(instrument.high) },
    { label: "Low", value: fmtMoney(instrument.low) },
    { label: "Prev close", value: fmtMoney(instrument.prevClose) },
    { label: "Volume", value: fmtVolume(instrument.volume) },
    { label: "Exchange", value: instrument.exchange },
  ];

  /* Submit only validates; the dialog places the order. */
  function reviewOrder(e) {
    e.preventDefault();
    const q = Number(qty);
    if (!q || q <= 0) return toast.error("Enter a quantity greater than zero");
    if (orderType === "LIMIT" && !Number(limitPrice)) return toast.error("Enter a limit price");
    // bracket exits share their validation with ExitRulesDialog
    const problem = validateExits({
      sl: Number(slTrigger) || 0,
      tp: Number(tpPrice) || 0,
      ltp: instrument.price,
      isLong: side === "BUY",
    });
    if (problem) return toast.error(problem);
    setConfirming(true);
  }

  async function confirmOrder() {
    const q = Number(qty);
    setSubmitting(true);
    try {
      await placeOrder({
        symbol: instrument.symbol,
        name: instrument.name,
        exchange: instrument.exchange,
        side,
        type: orderType,
        product,
        qty: q,
        price: execPrice,
        triggerPrice: 0,
        slTrigger: Number(slTrigger) || 0,
        tpPrice: Number(tpPrice) || 0,
      });
      setConfirming(false);
      // refresh so every readout updates right away
      refreshFunds().catch(() => {});
      refreshHoldings().catch(() => {});
      toast.success(`${side === "BUY" ? "Buy" : "Sell"} order placed for ${q} ${instrument.symbol}`, {
        description: `Estimated value ${fmtMoney(total)}`,
      });
    } catch (err) {
      toast.error(err.message || "Order failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-6">
      <header className="animate-entry flex flex-wrap items-end justify-between gap-4 border-b border-border pb-6">
        <div>
          <div className="mb-1.5 flex items-center gap-3">
            <h1 className="font-display text-2xl font-extrabold tracking-tight">{instrument.symbol}</h1>
            <span className="rounded border border-border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              {instrument.exchange}
            </span>
          </div>
          <p className="text-sm text-muted-foreground">{instrument.name}</p>
        </div>
        <div className="text-right">
          <p className="num text-2xl">{fmtMoney(instrument.price)}</p>
          <p className={cn("num mt-0.5 text-[13px]", toneClass(instrument.change))}>
            {fmtMoney(instrument.change, { sign: true })} ({fmtPct(instrument.changePct)}) today
          </p>
        </div>
      </header>

      {/* Your exposure to this symbol, one line per book. */}
      {(holdingM || positionM) && (
        <div className="animate-entry space-y-1.5 rounded-xl border border-border bg-surface p-4 text-[12px] shadow-xs">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Your position</p>
          {holdingM && (
            <div className="flex flex-wrap items-baseline justify-between gap-x-4">
              <p className="text-muted-foreground">
                CNC · <span className="num">{heldQty} qty</span> @{" "}
                <span className="num">{fmtMoney(avgPrice)}</span> avg · worth{" "}
                <span className="num">{fmtMoney(holdingM.value)}</span>
              </p>
              <PnlValue value={holdingM.pnl} pct={holdingM.pnlPct} className="font-medium" />
            </div>
          )}
          {positionM && (
            <div className="flex flex-wrap items-baseline justify-between gap-x-4">
              <p className="text-muted-foreground">
                MIS · {position.side} <span className="num">{position.qty}</span> @{" "}
                <span className="num">{fmtMoney(position.entry)}</span> entry
              </p>
              <PnlValue value={positionM.pnl} pct={positionM.pnlPct} className="font-medium" />
            </div>
          )}
        </div>
      )}

      <Sunken className="animate-entry [animation-delay:100ms]">
        <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
          <div>
            <h2 className="text-sm font-semibold">Price action</h2>
            <p className="num mt-1 text-[11px] text-muted-foreground">Candlestick · {range}</p>
          </div>
          <RangePills values={ranges} active={range} onChange={setRange} />
        </div>
        {/* Placeholder keeps the same height as the chart. */}
        {candlesLoading ? (
          <div className="flex h-[378px] items-center justify-center text-sm text-muted-foreground">
            Loading chart...
          </div>
        ) : (
          <CandleChart candles={candles} height={378} fitKey={`${symbol}-${range}`} />
        )}
      </Sunken>

      {/* Statistics and the ticket share a row at lg, stack below. */}
      <div className="grid gap-6 lg:grid-cols-2">
        <Sunken className="animate-entry [animation-delay:200ms]">
          <h2 className="mb-6 text-sm font-semibold">Key statistics</h2>
          {/* Three-up at sm, back to two-up at lg (half the pane). */}
          <div className="grid grid-cols-2 gap-x-8 gap-y-6 sm:grid-cols-3 lg:grid-cols-2">
            {stats.map((s) => (
              <div key={s.label} className="border-l border-border pl-4">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">{s.label}</p>
                <p className="num mt-1 text-base">{s.value}</p>
              </div>
            ))}
          </div>
          <div className="mt-8 border-t border-border pt-6">
            <div className="mb-2 flex items-center justify-between text-[11px] text-muted-foreground">
              <span className="num">{fmtMoney(instrument.week52Low)}</span>
              <span className="font-semibold uppercase tracking-wider">52-week range</span>
              <span className="num">{fmtMoney(instrument.week52High)}</span>
            </div>
            <div className="relative h-1.5 w-full rounded-full bg-secondary">
              <span
                className="absolute -top-1 size-3.5 -translate-x-1/2 rounded-full border-2 border-surface bg-foreground"
                style={{ left: `${Math.min(100, Math.max(0, rangePos))}%` }}
              />
            </div>
          </div>
        </Sunken>

        <Sunken className="animate-entry [animation-delay:300ms]">
          {/* Side is the decision the ticket hangs off, so it gets full width. */}
          <div className="mb-5 grid grid-cols-2 gap-2">
            {["BUY", "SELL"].map((s) => (
              <Button
                key={s}
                type="button"
                onClick={() => setSide(s)}
                className={cn(
                  "rounded-md py-2 text-[12px] font-semibold uppercase tracking-wide transition-all",
                  s === side
                    ? s === "BUY" ? "bg-accent text-accent-foreground" : "bg-foreground text-background"
                    : "bg-transparent border border-border text-muted-foreground hover:text-foreground"
                )}
              >
                {s}
              </Button>
            ))}
          </div>

          <form onSubmit={reviewOrder} className="space-y-4">
            {/* Order type gets its own row; qty and price pair below it. */}
            <div>
              <label className={FIELD_LABEL}>Order type</label>
              <div className="flex gap-1 rounded-lg bg-secondary p-1">
                {["MARKET", "LIMIT"].map((t) => (
                  <Button
                    key={t}
                    type="button"
                    onClick={() => setOrderType(t)}
                    className={cn(
                      "flex-1 rounded-md px-2 py-2 text-[11px] font-semibold transition-all",
                      t === orderType ? "bg-surface shadow-sm ring-1 ring-black/5 text-foreground" : "bg-transparent text-muted-foreground hover:text-foreground"
                    )}
                  >
                    {t}
                  </Button>
                ))}
              </div>
            </div>
            <div>
              <label className={FIELD_LABEL}>Product</label>
              <div className="flex gap-1 rounded-lg bg-secondary p-1">
                {["CNC", "MIS"].map((p) => (
                  <Button
                    key={p}
                    type="button"
                    onClick={() => setProduct(p)}
                    className={cn(
                      "flex-1 rounded-md px-2 py-2 text-[11px] font-semibold capitalize transition-all",
                      p === product ? "bg-surface shadow-sm ring-1 ring-black/5 text-foreground" : "bg-transparent text-muted-foreground hover:text-foreground"
                    )}
                  >
                    {p}
                  </Button>
                ))}
              </div>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label htmlFor="qty" className={FIELD_LABEL}>Quantity</label>
                <Input
                  id="qty"
                  inputMode="numeric"
                  value={qty}
                  onChange={(e) => setQty(e.target.value.replace(/[^0-9]/g, ""))}
                  className="num"
                />
              </div>
              <div>
                <label htmlFor="price" className={FIELD_LABEL}>Price</label>
                <Input
                  id="price"
                  inputMode="decimal"
                  disabled={orderType === "MARKET"}
                  value={orderType === "MARKET" ? "At market" : limitPrice}
                  onChange={(e) => setLimitPrice(e.target.value.replace(/[^0-9.]/g, ""))}
                  className="num"
                />
              </div>
            </div>

            {/* Optional SL/target exits; one firing cancels the other (OCO). */}
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label htmlFor="sl" className={FIELD_LABEL}>
                  Stop-loss trigger <span className="font-normal normal-case">(optional)</span>
                </label>
                <Input
                  id="sl"
                  inputMode="decimal"
                  placeholder="—"
                  value={slTrigger}
                  onChange={(e) => setSlTrigger(e.target.value.replace(/[^0-9.]/g, ""))}
                  className="num"
                />
              </div>
              <div>
                <label htmlFor="tp" className={FIELD_LABEL}>
                  Target price <span className="font-normal normal-case">(optional)</span>
                </label>
                <Input
                  id="tp"
                  inputMode="decimal"
                  placeholder="—"
                  value={tpPrice}
                  onChange={(e) => setTpPrice(e.target.value.replace(/[^0-9.]/g, ""))}
                  className="num"
                />
              </div>
            </div>

            {/* Exits compare against avgPrice if held, else the live/limit price. */}
            <ExitPreview
              sl={Number(slTrigger) || 0}
              tp={Number(tpPrice) || 0}
              isLong={side === "BUY"}
              refPrice={heldQty > 0
                ? avgPrice
                : orderType === "LIMIT" && Number(limitPrice)
                ? Number(limitPrice)
                : instrument.price}
              ltp={instrument.price}
              qty={Number(qty) || 0}
            />

            {/* Crossed exits are blocked at submit with a toast (see reviewOrder). */}

            <div className="flex flex-wrap items-center justify-between gap-4 border-t border-border pt-4">
              <div className="text-[12px]">
                <span className="text-muted-foreground">Estimated total </span>
                <span className="num font-medium">{fmtMoney(total)}</span>

                {/* One line for what the order costs the balance, one for what it becomes. */}
                {product === "MIS" ? (
                  insufficientFunds ? (
                    <p className="num mt-0.5 text-destructive">
                      Insufficient funds — only {fmtMoney(available)} available
                    </p>
                  ) : (
                    <p className="mt-0.5 text-muted-foreground">
                {/* Kite's label for the same number; this app's MIS has no leverage. */}
                      Margin required {fmtMoney(total)} · {side === "BUY"
                        ? "opens a long — profit if price rises"
                        : "opens a short — profit if price falls"} · released at square off
                    </p>
                  )
                ) : side === "BUY" ? (
                  <p className={cn("num mt-0.5", insufficientFunds ? "text-destructive" : "text-muted-foreground")}>
                    {insufficientFunds
                      ? `Insufficient funds — only ${fmtMoney(available)} available`
                      : `${fmtMoney(total)} blocked · ${fmtMoney(available)} available`}
                  </p>
                ) : (
                  <p className={cn("num mt-0.5", insufficientHoldings ? "text-destructive" : "text-muted-foreground")}>
                    {insufficientHoldings
                      ? `You only hold ${heldQty} ${instrument.symbol}`
                      : `${heldQty} ${instrument.symbol} in holdings — proceeds arrive on execution`}
                  </p>
                )}
              </div>
              <Button
                type="submit"
                disabled={submitting || insufficientFunds || insufficientHoldings}
                className={cn(
                  "rounded-lg px-6 py-3 text-[13px] font-semibold transition-transform active:scale-[0.99] disabled:opacity-50",
                  side === "BUY" ? "bg-accent text-accent-foreground" : "bg-foreground text-background"
                )}
              >
                {submitting ? "Placing order..." : side === "BUY" ? "Place buy order" : "Place sell order"}
              </Button>
            </div>
          </form>
        </Sunken>
      </div>

      {/* The order is restated in plain rows before it goes anywhere. */}
      <Dialog open={confirming} onOpenChange={(open) => !submitting && setConfirming(open)}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Confirm {side.toLowerCase()} order</DialogTitle>
            <DialogDescription>
              {instrument.symbol} · {instrument.exchange} · {product}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2.5 text-[13px]">
            {[
              {
                label: "Order type",
                value: orderType === "MARKET" ? "Market" : `Limit @ ${fmtMoney(execPrice)}`,
              },
              { label: "Quantity", value: String(Number(qty) || 0) },
              ...(Number(slTrigger) > 0
                ? [{ label: "Stop-loss", value: `triggers at ${fmtMoney(Number(slTrigger))}` }]
                : []),
              ...(Number(tpPrice) > 0
                ? [{ label: "Target", value: `sells at ${fmtMoney(Number(tpPrice))}` }]
                : []),
              { label: "Estimated total", value: fmtMoney(total) },
              ...(product === "MIS"
                ? [{ label: "Margin required", value: fmtMoney(total) }]
                : []),
              ...(side === "BUY"
                ? [{ label: "Available balance", value: fmtMoney(available) }]
                : []),
              ...(side === "SELL" && product !== "MIS"
                ? [{ label: "In holdings", value: `${heldQty} ${instrument.symbol}` }]
                : []),
              ...(side === "SELL" && product === "MIS"
                ? [{ label: "Result", value: "Opens a short position" }]
                : []),
            ].map((row) => (
              <div key={row.label} className="flex items-center justify-between border-b border-border pb-2.5 last:border-0 last:pb-0">
                <span className="text-muted-foreground">{row.label}</span>
                <span className="num font-medium">{row.value}</span>
              </div>
            ))}
            {/* Indicative charges only — nothing is debited. */}
            {(() => {
              const c = estimateCharges({ side, product, turnover: total });
              return (
                <div className="rounded-lg bg-surface-sunken p-3 text-[12px]">
                  <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                    Estimated charges
                  </div>
                  <div className="num space-y-1">
                    <div className="flex justify-between"><span className="text-muted-foreground">Brokerage</span><span>{fmtMoney(c.brokerage)}</span></div>
                    <div className="flex justify-between"><span className="text-muted-foreground">STT</span><span>{fmtMoney(c.stt)}</span></div>
                    <div className="flex justify-between"><span className="text-muted-foreground">Exchange txn</span><span>{fmtMoney(c.txnCharges)}</span></div>
                    <div className="flex justify-between"><span className="text-muted-foreground">SEBI charges</span><span>{fmtMoney(c.sebi)}</span></div>
                    <div className="flex justify-between"><span className="text-muted-foreground">GST</span><span>{fmtMoney(c.gst)}</span></div>
                    <div className="flex justify-between"><span className="text-muted-foreground">Stamp duty</span><span>{fmtMoney(c.stampDuty)}</span></div>
                    <div className="flex justify-between border-t border-border pt-1 font-medium"><span>Total charges</span><span>{fmtMoney(c.total)}</span></div>
                  </div>
                </div>
              );
            })()}
          </div>
          <DialogFooter className="gap-2">
            {side === "SELL" && insufficientHoldings && (
              <p className="num self-center text-[12px] text-destructive">
                You only hold {heldQty} {instrument.symbol} — reduce the quantity
              </p>
            )}
            <button
              type="button"
              onClick={() => setConfirming(false)}
              disabled={submitting}
              className="rounded-md border border-border px-4 py-2 text-[12px] font-semibold text-muted-foreground transition-colors hover:text-foreground disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={confirmOrder}
              disabled={submitting || insufficientHoldings}
              className={cn(
                "rounded-md px-4 py-2 text-[12px] font-semibold transition-transform active:scale-[0.99] disabled:opacity-50",
                side === "BUY" ? "bg-accent text-accent-foreground" : "bg-foreground text-background"
              )}
            >
              {submitting ? "Placing order..." : `Confirm ${side.toLowerCase()}`}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

// Placeholder pane before a symbol is picked — no auto-select, no fetches.
export function InstrumentEmpty() {
  return (
    <div className="animate-entry flex min-h-[60vh] flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border bg-surface p-8 text-center">
      <p className="text-sm font-semibold">Select an instrument</p>
      <p className="max-w-xs text-[13px] text-muted-foreground">
        Pick a symbol from the list to see its chart, key statistics and place an order.
      </p>
    </div>
  );
}
