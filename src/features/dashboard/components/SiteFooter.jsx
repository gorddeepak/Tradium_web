import { isMarketOpen } from "@/services/marketStatus";
import { cn } from "@/utils/utils";

export function SiteFooter() {
  const open = isMarketOpen();

  return (
    <footer className="mx-auto mt-16 max-w-[1440px] border-t border-border px-6 py-10">
      <div className="flex flex-wrap items-center justify-between gap-4">
        {/* No company entity or Terms/Privacy links — Tradium can't back those claims. */}
        <div className="text-[11px] font-medium text-muted-foreground">
          Tradium — a portfolio project, not a brokerage. No real money.
        </div>
        {/* Colour follows the open state, so "closed" isn't green. */}
        <div
          className={cn(
            "flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider",
            open ? "text-positive" : "text-muted-foreground",
          )}
        >
          <span
            className={cn(
              "size-2 rounded-full",
              // Pulse only while markets are live — a static dot when closed
              // signals "off", matching the briefing's pulsing live dot.
              open ? "animate-pulse bg-positive" : "bg-muted-foreground",
            )}
          />
          {open ? "Markets open" : "Markets closed"}
        </div>
      </div>
    </footer>
  );
}

export default SiteFooter;




