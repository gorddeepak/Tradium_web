import { Search, LayoutGrid, ArrowRightLeft, Wallet, Star, SunMoon, Sun, Moon } from "lucide-react";
import { useReveal } from "@/hooks/useReveal";
import { SectionHeader } from "@/features/marketing/components/SectionHeader";
import heatmapImg from "@/assets/screenshots/market_heatmap.png";
import watchlistImg from "@/assets/screenshots/feature-watchlist.png";
import searchImg from "@/assets/screenshots/feature-search.png";
import tradeImg from "@/assets/screenshots/feature-trade.png";
import depositImg from "@/assets/screenshots/feature-deposit-methods.png";

/* Five screenshot exhibits plus one live DOM demo (the theme pair). Nothing
   here is focusable, and every number is pinned to the seeded demo book. */

function WatchlistExhibit() {
  return (
    <div>
      {/* A real crop of the watchlist rail, not a stand-in. */}
      <img
        src={watchlistImg}
        alt="Tradium watchlist: NSE symbols with live prices, day's change and a sparkline per row, an Add-symbol field on top"
        width={574}
        height={641}
        loading="lazy"
        decoding="async"
        /* No CSS border: the screenshot already carries the app border baked
           in, and adding one draws a double line (unlike the heatmap crop). */
        className="block w-full"
      />
      <p className="mt-4 text-[11px] leading-relaxed text-muted-foreground">
        Add any NSE symbol. Click a row to chart it and trade.
      </p>
    </div>
  );
}

/* --- exhibit 1: global search ---------------------------------------- */

function SearchExhibit() {
  return (
    <div>
      {/* A real crop of the search dropdown for the query "ta", not a stand-in. */}
      <img
        src={searchImg}
        alt="Tradium global search showing results for the query 'ta': Tata Motors, Tata Steel and Titan, each with price and day's change"
        width={1210}
        height={566}
        loading="lazy"
        decoding="async"
        className="block w-full border border-border"
      />
    </div>
  );
}

/* --- exhibit 2: sector heatmap ---------------------------------------- */

function HeatmapExhibit() {
  return (
    <div>
      {/* A real crop of the Markets heatmap, not a stand-in. */}
      <img
        src={heatmapImg}
        alt="Tradium sector heatmap of NIFTY 50 stocks, tiles sized by market cap and coloured by day's move"
        width={892}
        height={318}
        loading="lazy"
        decoding="async"
        className="block w-full border border-border"
      />
      <p className="mt-4 text-[11px] leading-relaxed text-muted-foreground">
        Sized by market cap, coloured by the day&rsquo;s move. Redrawn every five minutes.
      </p>
    </div>
  );
}

/* --- exhibit 3: order ticket ------------------------------------------- */

function TicketExhibit() {
  return (
    <div>
      {/* A real crop of the order ticket in review state — BUY selected,
          Market, CNC — as the lead text promises. */}
      <img
        src={tradeImg}
        alt="Tradium order ticket for RELIANCE: buy side selected, market order, CNC product, quantity, stop-loss and target fields, and the estimated total shown before confirming"
        width={650}
        height={723}
        loading="lazy"
        decoding="async"
        /* No CSS border: the screenshot already carries the app border baked
           in, and adding one draws a double line (unlike the heatmap crop). */
        className="block w-full"
      />
    </div>
  );
}

/* --- exhibit 4: add funds ---------------------------------------------- */

function FundsExhibit() {
  return (
    <div>
      {/* The screenshot starts at the method list, so the step's heading is
         supplied here. */}
      <p className="mb-1 block font-sans text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        Deposit methods
      </p>
      {/* A real crop of the deposit-methods step, "Coming soon" greys included. */}
      <img
        src={depositImg}
        alt="Tradium confirm-deposit step for ₹25,000: UPI and net banking greyed out as coming soon, paper cash selected as the available method"
        width={786}
        height={395}
        loading="lazy"
        decoding="async"
        className="block w-full border border-border"
      />
    </div>
  );
}

/* --- exhibit 6: light / dark --------------------------------------------- */

/* The same mini table twice — the right half wrapped in `.dark`. Numbers
   pinned to the demo book. */
const themeRows = [
  { sym: "RELIANCE", pct: "+0.38%", up: true },
  { sym: "SBIN", pct: "+14.68%", up: true },
  { sym: "INFY", pct: "−8.76%", up: false },
];

function ThemeSample() {
  return (
    /* text-foreground re-resolves against whichever theme scope this sits in. */
    <div className="overflow-hidden rounded-lg border border-border bg-surface text-foreground shadow-xs">
      {/* Header band — shows the sunken surface and an accent touch in both halves. */}
      <div className="border-b border-border bg-surface-sunken px-3 py-2.5">
        <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          Holdings
        </p>
      </div>
      <div className="divide-y divide-border">
        {themeRows.map((r) => (
          <div key={r.sym} className="flex items-center gap-2 px-3 py-3">
            <span className="text-[12px] font-semibold">{r.sym}</span>
            <span className={"num ml-auto text-[11px] font-semibold " + (r.up ? "text-positive" : "text-negative")}>
              {r.pct}
            </span>
          </div>
        ))}
      </div>
      {/* Footer readout — accent bar plus the signed daily P&L, the number that
          changes most between halves. */}
      <div className="flex items-center justify-between border-t border-border px-3 py-3">
        <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
          <span className="size-1.5 rounded-full bg-accent" aria-hidden="true" />
          Day&rsquo;s P&L
        </span>
        <span className="num text-[12px] font-semibold text-positive">+₹1,680</span>
      </div>
    </div>
  );
}

function ThemeExhibit() {
  return (
    <div>
      <div className="grid grid-cols-2 gap-2">
        {/* Labels outside the scopes so they keep the page's own theme.
            mt-2 nudges them down so they sit closer to their cards. */}
        <div>
          <div className="mb-3 mt-4 flex items-center justify-center gap-1.5 text-[11px] font-medium text-muted-foreground">
            <Sun className="size-3.5" aria-hidden="true" />
            Light mode
          </div>
          <div className="light">
            <ThemeSample />
          </div>
        </div>
        <div>
          <div className="mb-3 mt-4 flex items-center justify-center gap-1.5 text-[11px] font-medium text-muted-foreground">
            <Moon className="size-3.5" aria-hidden="true" />
            Dark mode
          </div>
          <div className="dark">
            <ThemeSample />
          </div>
        </div>
      </div>
      <p className="mt-4 text-[11px] leading-relaxed text-muted-foreground">
        One toggle, remembered on reload. Every screen, every table, both ways.
      </p>
    </div>
  );
}

/* --- the section -------------------------------------------------------- */

const exhibits = [
  {
    icon: Search,
    title: "Find any symbol",
    lead: "Search or Ctrl+K from anywhere in the dashboard.",
    render: SearchExhibit,
  },
  {
    icon: LayoutGrid,
    title: "The market at a glance",
    lead: "NIFTY 50 grouped into sectors, sized by market cap.",
    render: HeatmapExhibit,
  },
  {
    icon: Wallet,
    title: "Paper cash, one click",
    lead: "Deposit and withdraw instantly.",
    render: FundsExhibit,
  },
  {
    icon: ArrowRightLeft,
    title: "One honest ticket",
    lead: "The estimated total is shown before you confirm.",
    render: TicketExhibit,
  },
  {
    icon: Star,
    title: "Watchlist built in",
    lead: "Add any NSE symbol — click a row to chart it.",
    render: WatchlistExhibit,
  },
  {
    icon: SunMoon,
    title: "Light and dark",
    lead: "One toggle, remembered on reload.",
    render: ThemeExhibit,
  },
];

export function FeatureStrip() {
  const [revealRef, shown] = useReveal();

  return (
    <section id="whats-built" className="border-t border-border scroll-mt-16">
      <div
        ref={revealRef}
        className="mx-auto max-w-[1440px] px-6 py-20 lg:px-24 lg:py-28"
      >
        <div className={shown ? "animate-rise mb-14 max-w-2xl" : "mb-14 max-w-2xl opacity-0"}>
          <SectionHeader eyebrow="Features">
            Everyday tools, <span className="text-accent">built in</span>
          </SectionHeader>
          <p className="mt-5 text-lg leading-relaxed text-muted-foreground">
            Six tools, all live in the app today.
          </p>
        </div>

        {/* gap-px over bg-border draws the hairlines; cells sit on bg-background. */}
        <div
          className={
            "grid gap-px overflow-hidden rounded-xl border border-border bg-border sm:grid-cols-2 lg:grid-cols-3 " +
            (shown ? "animate-rise [animation-delay:140ms]" : "opacity-0")
          }
        >
          {exhibits.map((e) => {
            const Icon = e.icon;
            const Exhibit = e.render;
            return (
              <article key={e.title} className="bg-background p-7 lg:p-8">
                <Icon className="mb-5 size-5 text-accent" aria-hidden="true" />
                <h3 className="font-display text-[19px] font-semibold tracking-[-0.01em]">
                  {e.title}
                </h3>
                <p className="mb-5 mt-2.5 text-sm font-medium leading-relaxed">{e.lead}</p>
                <Exhibit />
              </article>
            );
          })}
        </div>
      </div>
    </section>
  );
}
