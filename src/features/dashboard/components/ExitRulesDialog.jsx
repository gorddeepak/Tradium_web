import { useState } from "react";
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
import { cn } from "@/utils/utils";
import { ExitPreview, FIELD_LABEL, fmtMoney, validateExits } from "@/utils/tradiumUtils";
import { placeExitRules } from "@/services/api";

/* Set or replace the stop-loss/target pair (OCO) for a holding or open position.
   Pages keep ONE dialog mounted and pass it the clicked row. */
export function ExitRulesDialog({ open, onOpenChange, row, onDone }) {
  const [slTrigger, setSlTrigger] = useState("");
  const [tpPrice, setTpPrice] = useState("");
  const [submitting, setSubmitting] = useState(false);

  // Inputs reset whenever the dialog closes, so the next row starts clean
  function handleClose(open) {
    if (!open) {
      setSlTrigger("");
      setTpPrice("");
    }
    onOpenChange(open);
  }

  if (!row) return null;

  const isLong = row.side === "LONG";
  const entry = row.entry;
  const ltp = row.ltp;

  const sl = Number(slTrigger) || 0;
  const tp = Number(tpPrice) || 0;

  async function save() {
    if (sl <= 0 && tp <= 0) return toast.error("Set at least a stop-loss trigger or a target price");
    // crossed exits are rejected here (see validateExits)
    const problem = validateExits({ sl, tp, ltp, isLong });
    if (problem) return toast.error(problem);
    setSubmitting(true);
    try {
      await placeExitRules({
        symbol: row.symbol,
        exchange: row.exchange,
        product: row.product,
        slTrigger: sl,
        tpPrice: tp,
      });
      toast.success(`Exit rules set for ${row.symbol}`);
      onOpenChange(false);
      onDone?.();
    } catch (err) {
      toast.error(err.message || "Failed to set exit rules");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !submitting && handleClose(o)}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>Set exit rules</DialogTitle>
          <DialogDescription>
            {row.symbol} · {row.name} · {row.product} {row.side.toLowerCase()}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 text-[13px]">
          <div className="grid grid-cols-2 gap-6 rounded-lg bg-surface-sunken p-3">
            <div>
              <p className="font-sans text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Entry</p>
              <p className="num mt-1 font-medium">{fmtMoney(entry)}</p>
            </div>
            <div>
              <p className="font-sans text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Live price</p>
              <p className="num mt-1 font-medium">{fmtMoney(ltp)}</p>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label htmlFor="exit-sl" className={cn(FIELD_LABEL, "font-sans")}>
                Stop-loss trigger
              </label>
              <Input
                id="exit-sl"
                inputMode="decimal"
                placeholder="—"
                value={slTrigger}
                onChange={(e) => setSlTrigger(e.target.value.replace(/[^0-9.]/g, ""))}
                className="num"
              />
            </div>
            <div>
              <label htmlFor="exit-tp" className={cn(FIELD_LABEL, "font-sans")}>
                Target price
              </label>
              <Input
                id="exit-tp"
                inputMode="decimal"
                placeholder="—"
                value={tpPrice}
                onChange={(e) => setTpPrice(e.target.value.replace(/[^0-9.]/g, ""))}
                className="num"
              />
            </div>
          </div>

          {/* Same preview style as the order ticket: the numbers the rules
              exist for, measured from the entry price shown above. */}
          <ExitPreview sl={sl} tp={tp} isLong={isLong} refPrice={entry} ltp={ltp} qty={row.qty} />

          <p className="font-sans text-[11px] text-muted-foreground">
            Applies to all {row.qty} {row.symbol}. Saving replaces any existing stop-loss/target — when one fires, the other is cancelled.
          </p>
        </div>

        <DialogFooter className="gap-2">
          <Button
            variant="outline"
            size="default"
            onClick={() => handleClose(false)}
            disabled={submitting}
            className="text-[12px] font-semibold text-muted-foreground transition-colors hover:text-foreground disabled:opacity-50"
          >
            Cancel
          </Button>
          <Button
            onClick={save}
            disabled={submitting}
            className="text-[12px] font-semibold text-background transition-transform active:scale-[0.99] disabled:opacity-50"
          >
            {submitting ? "Saving..." : "Save rules"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
