import {
  Sparkles,
  CornerDownLeft,
  MessageCircle,
  Activity,
  Layers,
  ShieldCheck,
  ScanLine,
  TrendingUp,
} from "lucide-react";
import { CtaLink } from "@/features/marketing/components/CtaLink";
import { ROUTES } from "@/pages/routes/routes";
import { useReveal } from "@/hooks/useReveal";
import { SectionHeader } from "@/features/marketing/components/SectionHeader";
import novaPanelImg from "@/assets/screenshots/nova-assistant.png";
import novaInsightsImg from "@/assets/screenshots/nova-insights.png";

/* The dark band showing Nova. Everything here is a fixed example — the numbers
   match the seeded demo data. One useReveal per row so each animates in. */

const chatPoints = [
  {
    icon: MessageCircle,
    text: "Ask in plain language. Get a plain answer.",
  },
  {
    icon: Activity,
    text: "Answers come from your live account. Nothing invented.",
  },
  {
    icon: Layers,
    text: "One question can span screens — holdings, positions, funds.",
  },
  {
    icon: ShieldCheck,
    text: "Read-only, always. It never places an order.",
  },
];

const insightPoints = [
  {
    icon: ScanLine,
    text: "Every page opens already summed up — one line, at a glance.",
  },
  {
    icon: TrendingUp,
    text: "It names the stock moving your day, not “markets were mixed”.",
  },
  {
    icon: CornerDownLeft,
    text: "“Ask about this” starts the chat with that line.",
  },
];

/* Pages that really show a PageInsight card. */
const insightPages = ["Overview", "Holdings", "Positions", "Orders", "Trade", "Markets"];

export function NovaSection() {
  const [chatRowRef, chatShown] = useReveal();
  const [insightRowRef, insightShown] = useReveal();

  return (
    <section id="nova" className="scroll-mt-16 bg-ink text-ink-foreground">
      <div className="mx-auto max-w-[1440px] px-6 py-20 lg:px-24 lg:py-28">
        {/* Row one — what Nova is, beside a rendered chat exchange */}
        <div
          ref={chatRowRef}
          className="grid items-center gap-14 lg:grid-cols-2 lg:gap-20"
        >
          {/* Copy */}
          <div className={chatShown ? "animate-rise" : "opacity-0"}>
            {/* Nova wordmark, styled like the Tradium logo. */}
            <p className="mb-4 inline-flex items-center gap-2">
              <Sparkles className="size-3.5 text-accent" aria-hidden="true" />
              <span className="font-display text-[15px] font-extrabold tracking-tight">
                Nova AI<span className="text-accent">.</span>
              </span>
            </p>
            <SectionHeader>
              Understand your portfolio,
              <br />
              <span className="text-accent">just by asking</span>
            </SectionHeader>
            <p className="mt-6 text-lg leading-relaxed text-ink-foreground/70">
              Nova AI is your portfolio assistant. Ask anything &mdash; it
              answers from your own account.
            </p>
            <ul className="mt-8 space-y-4 text-[15px] text-ink-foreground/80">
              {chatPoints.map((p) => {
                const Icon = p.icon;
                return (
                  <li key={p.text} className="flex gap-3.5">
                    <Icon
                      className="mt-0.5 size-[18px] shrink-0 text-accent"
                      aria-hidden="true"
                    />
                    <span className="leading-relaxed">{p.text}</span>
                  </li>
                );
              })}
            </ul>
            <CtaLink to={ROUTES.signup} variant="accent" size="md" arrow className="mt-9 px-6">
              Try Nova AI on your own portfolio
            </CtaLink>
          </div>

          {/* A real screenshot of the panel — the live assistant writes each
             reply from your own rows. */}
          <div className={chatShown ? "animate-rise [animation-delay:160ms]" : "opacity-0"}>
            {/* max-w-sm ≈ the screenshot's native width — stops the browser
                upscaling it to fill the ~600px column.
                rounded-xl matches the panel’s inner radius. */}
            <div className="mx-auto w-full max-w-sm rounded-xl overflow-hidden">
              <img
                src={novaPanelImg}
                alt="The Nova AI chat panel: a user asking 'How is my portfolio doing today?', a completed getHoldings tool call, and Nova's answer that the day's loss is driven mostly by BHARTIARTL"
                width={381}
                height={521}
                loading="lazy"
                decoding="async"
                className="block w-full"
              />
            </div>
          </div>
        </div>

        {/* Row two — the insight card, under the chat panel. */}
        <div
          ref={insightRowRef}
          className="mt-20 grid items-center gap-14 border-t border-ink-border pt-20 lg:mt-28 lg:grid-cols-2 lg:gap-20 lg:pt-28"
        >
          {/* A real screenshot of the insight card — the live card writes its
             own line from your rows. */}
          <div className={`order-2 lg:order-none ${insightShown ? "animate-rise" : "opacity-0"}`}>
            {/* Full column width plus a slight bleed into the grid gap —
                the screenshot is a wide, short banner (750×158), so a little
                extra width makes it read clearly.
                border-2 gives the edge-free screenshot a visible edge. */}
            <div className="-mx-4 w-[calc(100%+2rem)] overflow-hidden rounded-xl border-2 border-ink-border lg:-mx-10 lg:w-[calc(100%+5rem)]">
              <img
                src={novaInsightsImg}
                alt="The Nova AI insight card, with its one-line summary of the page and an 'Ask about this' button"
                width={750}
                height={158}
                loading="lazy"
                decoding="async"
                className="block w-full"
              />
            </div>

            {/* The screens that show this card. */}
            <p className="mt-7 text-[11px] font-bold uppercase tracking-[0.15em] text-ink-foreground/40">
              Appears on
            </p>
            <ul className="mt-3 flex flex-wrap gap-2">
              {insightPages.map((p) => (
                <li
                  key={p}
                  className="rounded-md border border-ink-border px-2.5 py-1.5 text-xs font-medium text-ink-foreground/70"
                >
                  {p}
                </li>
              ))}
            </ul>
          </div>

          {/* Copy */}
          <div className={insightShown ? "animate-rise [animation-delay:160ms]" : "opacity-0"}>
            <p className="mb-4 text-[11px] font-bold uppercase tracking-[0.15em] text-accent">
              Page insights
            </p>
            <h2 className="font-display text-[clamp(1.75rem,3vw,2.25rem)] font-bold leading-[1.08] tracking-[-0.03em]">
              It sums up the page
              <br />
              <span className="text-accent">before you ask</span>
            </h2>
            <p className="mt-6 text-[15px] leading-relaxed text-ink-foreground/70">
              The half of Nova AI you never have to type into.
            </p>
            <ul className="mt-7 space-y-4 text-[15px] text-ink-foreground/80">
              {insightPoints.map((p) => {
                const Icon = p.icon;
                return (
                  <li key={p.text} className="flex gap-3.5">
                    <Icon
                      className="mt-0.5 size-[18px] shrink-0 text-accent"
                      aria-hidden="true"
                    />
                    <span className="leading-relaxed">{p.text}</span>
                  </li>
                );
              })}
            </ul>
          </div>
        </div>
      </div>
    </section>
  );
}
