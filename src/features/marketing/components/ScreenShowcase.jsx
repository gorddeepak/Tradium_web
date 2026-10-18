import { useState } from "react";
import { useReveal } from "@/hooks/useReveal";
import { SectionHeader } from "@/features/marketing/components/SectionHeader";
import tradeImg from "@/assets/screenshots/app-trade.png";
import holdingsImg from "@/assets/screenshots/app-holdings.png";
import positionsImg from "@/assets/screenshots/app-positions.png";
import ordersImg from "@/assets/screenshots/app-orders.png";
import fundsImg from "@/assets/screenshots/app-funds.png";
import marketsImg from "@/assets/screenshots/app-markets.png";

/* Real screenshots of the running app. No links here — every dashboard route
   is behind auth; the signup CTA is the way in. Each row reveals on its own
   useReveal. */

const screens = [
  {
    num: "01",
    label: "Trade",
    title: "Place the order",
    accent: "on the chart.",
    body: "Watchlist beside you, chart in front, ticket underneath — one page, nothing in a modal.",
    bullets: [
      "Candlestick chart, 1D to 5Y ranges.",
      "Key stats plus a 52-week range marker.",
      "Optional stop-loss and target, with a live exit preview.",
    ],
    img: tradeImg,
    alt: "Tradium trade page for Reliance with a candlestick chart, key statistics including a 52-week range marker, and a buy and sell order panel with optional stop-loss and target fields",
  },
  {
    num: "02",
    label: "Markets",
    title: "Live market",
    accent: "overview.",
    body: "Index levels, breadth, sortable table and sector heatmap refreshed every five minutes.",
    bullets: [
      "Index levels as points, not rupees.",
      "Sortable table with volume and market cap.",
      "Heatmap sized by market cap, coloured by the day's move.",
    ],
    img: marketsImg,
    alt: "Tradium markets page showing NIFTY 50 index levels, breadth stat, a sortable constituent table with volume and market cap, and a sector heatmap",
  },
  {
    num: "03",
    label: "Holdings",
    title: "Your holdings,",
    accent: "priced live.",
    body: "Your settled equity, priced live — the last-traded column is never yesterday’s.",
    bullets: [
      "Invested, current value, P&L and day's change up top.",
      "Sortable table — filter by symbol, gainers or losers.",
      "A portfolio treemap, sized by your stake.",
    ],
    img: holdingsImg,
    alt: "Tradium holdings table showing quantity, average price, last traded price, market value and profit and loss per stock, with a portfolio allocation treemap below",
  },
  {
    num: "04",
    label: "Positions",
    title: "Margin positions,",
    accent: "kept separate.",
    body: "Open legs only, never mixed into holdings. Different questions, different pages.",
    bullets: [
      "Net P&L, exposure and open-leg count at a glance.",
      "Long and short sides, badged per row.",
      "One-click square off, or SL/TP exit rules.",
    ],
    img: positionsImg,
    alt: "Tradium positions page showing long and short intraday legs with side badges, entry and last traded prices, and net profit and loss",
  },
  {
    num: "05",
    label: "Orders",
    title: "The whole",
    accent: "audit trail.",
    body: "Every order you’ve sent, kept — including the ones that went nowhere.",
    bullets: [
      "Turnover and working orders up top.",
      "Bracket exit legs carry an Exit badge.",
      "Partial fills show filled vs ordered.",
    ],
    img: ordersImg,
    alt: "Tradium orders page with status tabs and a full order history including partially filled orders and bracket exit legs",
  },
  {
    num: "06",
    label: "Funds",
    title: "Your money,",
    accent: "accounted for.",
    body: "What you can deploy, what’s already committed, and the ledger explaining the gap between them.",
    bullets: [
      "Available, used and total balance — plus realized P&L.",
      "Add or withdraw instantly with paper cash.",
      "Money out reads red.",
    ],
    img: fundsImg,
    alt: "Tradium funds page showing available balance, used margin, realized profit and loss, a margin utilisation bar and transaction history",
  },
];

/* Wraps a screenshot in a browser frame. width/height are load-bearing — they
   reserve the shimmer's box. */
function BrowserFrame({ img, alt }) {
  const [loaded, setLoaded] = useState(false);

  return (
    <figure className="overflow-hidden rounded-xl border border-border bg-surface shadow-[0_20px_60px_-22px_rgba(0,0,0,0.22)] transition duration-500 group-hover:-translate-y-1.5 group-hover:shadow-2xl">
      <div className="flex items-center gap-1.5 border-b border-border bg-surface-sunken px-4 py-3">
        <span className="size-2.5 rounded-full bg-muted-foreground/25" />
        <span className="size-2.5 rounded-full bg-muted-foreground/25" />
        <span className="size-2.5 rounded-full bg-muted-foreground/25" />
      </div>
      <div className={"overflow-hidden " + (loaded ? "" : "skeleton-shimmer")}>
        <img
          src={img}
          alt={alt}
          width={1440}
          height={900}
          loading="lazy"
          decoding="async"
          onLoad={() => setLoaded(true)}
          onError={() => setLoaded(true)}
          className={"block w-full " + (loaded ? "animate-media-in" : "opacity-0")}
        />
      </div>
    </figure>
  );
}

/* One row: copy first, screenshot a beat behind. */
function ScreenRow({ screen, flipped }) {
  const [rowRef, shown] = useReveal();

  return (
    <div
      ref={rowRef}
      className="group grid items-center gap-10 lg:grid-cols-2 lg:gap-16"
    >
      <div className={"max-w-lg " + (shown ? "animate-rise" : "opacity-0")}>
        <p className="num mb-4 flex items-center gap-2 text-[11px] font-bold uppercase tracking-[0.15em]">
          <span className="text-accent">{screen.num}</span>
          <span className="text-border-strong">/</span>
          <span className="text-muted-foreground">{screen.label}</span>
        </p>

        <h3 className="font-display text-[clamp(1.5rem,2.5vw,2.125rem)] font-bold leading-[1.15] tracking-[-0.03em]">
          {screen.title} <span className="text-accent">{screen.accent}</span>
        </h3>

        <p className="mt-4 text-[15px] leading-relaxed text-muted-foreground">
          {screen.body}
        </p>

        <ul className="mt-7 space-y-3.5 border-l-2 border-accent/25 pl-6 transition-colors duration-500 group-hover:border-accent">
          {screen.bullets.map((b) => (
            <li key={b} className="flex gap-3 text-sm leading-relaxed">
              <span className="mt-[7px] size-1.5 shrink-0 rounded-full bg-accent" />
              <span>{b}</span>
            </li>
          ))}
        </ul>
      </div>

      <div
        className={
          (flipped ? "lg:order-first " : "") +
          (shown ? "animate-rise [animation-delay:180ms]" : "opacity-0")
        }
      >
        <BrowserFrame img={screen.img} alt={screen.alt} />
      </div>
    </div>
  );
}

export function ScreenShowcase() {
  const [headerRef, headerShown] = useReveal();

  return (
    <section
      id="screens"
      className="mx-auto max-w-[1440px] scroll-mt-16 px-6 py-20 lg:px-24 lg:py-28"
    >
      <div
        ref={headerRef}
        className={
          "mb-16 max-w-2xl lg:mb-24 " + (headerShown ? "animate-rise" : "opacity-0")
        }
      >
        <SectionHeader eyebrow="Screens">
          Eight screens.
          <br />
          <span className="text-accent">Nothing to relearn.</span>
        </SectionHeader>
        <p className="mt-5 text-[15px] leading-relaxed text-muted-foreground">
          Trade, holdings, positions, orders, funds, markets &mdash; every
          screenshot below is the real app.
        </p>
      </div>

      <div className="flex flex-col gap-20 lg:gap-28">
        {screens.map((s, i) => (
          <ScreenRow key={s.num} screen={s} flipped={i % 2 === 1} />
        ))}
      </div>
    </section>
  );
}
