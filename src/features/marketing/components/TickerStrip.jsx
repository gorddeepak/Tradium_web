import { instruments } from "@/data/market";
import { fmtMoney, fmtPct, toneClass } from "@/utils/tradiumUtils";

/* Sample tape. The marquee pauses on hover, and landing.css stops the
   animation entirely under prefers-reduced-motion. */

export function TickerStrip() {
  const row = (
    <div className="flex shrink-0 items-center gap-14 pr-14" aria-hidden="true">
      {instruments.map((i) => (
        <div key={i.symbol} className="num flex items-center gap-3 text-[13px]">
          <span className="font-semibold text-foreground">{i.symbol}</span>
          <span className="text-muted-foreground">{fmtMoney(i.price)}</span>
          <span className={toneClass(i.changePct)}>{fmtPct(i.changePct)}</span>
        </div>
      ))}
    </div>
  );

  return (
    <div className="group relative overflow-hidden border-y border-border bg-surface py-4">
      <div className="marquee flex w-max group-hover:[animation-play-state:paused]">
        {row}
        {row}
      </div>

      {/* Edge fades so symbols dissolve instead of being chopped off. */}
      <div
        className="pointer-events-none absolute inset-y-0 left-0 w-16 bg-gradient-to-r from-surface to-transparent"
        aria-hidden="true"
      />
      <div
        className="pointer-events-none absolute inset-y-0 right-0 w-16 bg-gradient-to-l from-surface to-transparent"
        aria-hidden="true"
      />

      {/* One accessible, non-animated summary in place of the scrolling copy. */}
      <p className="sr-only">
        Sample NSE price tape showing ten instruments. Illustrative data, not a live feed.
      </p>
    </div>
  );
}
