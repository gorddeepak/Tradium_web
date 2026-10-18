import { useState } from "react";
import { CtaLink } from "@/features/marketing/components/CtaLink";
import { ROUTES } from "@/pages/routes/routes";
import dashboardImg from "@/assets/screenshots/app-dashboard.png";

/* Stacked hero: left-aligned type on a warm-grey ground, then the dashboard
 * screenshot in a black bezel. */

export function Hero() {
  // Turns off the shimmer behind the screenshot once either image has loaded.
  const [shotLoaded, setShotLoaded] = useState(false);

  return (
    /* Full-bleed; pt-32/lg:pt-40 covers the fixed header's height. */
    <section className="relative overflow-hidden bg-surface-sunken pt-32 pb-20 lg:pt-40">
      {/* Ruled background anchored to the top, faded out at the edges by the
          mask so it has no hard cutoff. */}
      <div
        className="pointer-events-none absolute inset-x-0 top-0 h-[44rem]"
        style={{
          backgroundImage:
            "linear-gradient(to right, hsl(0 0% 0% / 0.05) 1px, transparent 1px), linear-gradient(to bottom, hsl(0 0% 0% / 0.05) 1px, transparent 1px)",
          backgroundSize: "76px 76px, 76px 76px",
          maskImage: "radial-gradient(ellipse 92% 92% at 30% 0%, #000 32%, transparent 80%)",
        }}
        aria-hidden="true"
      />

      <div className="relative z-10 mx-auto max-w-[1440px] px-6 lg:px-24">
        <div className="max-w-4xl">
          {/* A quiet pill — the headline should be read first. */}
          <span className="animate-rise mb-7 inline-flex items-center gap-2 rounded-full border border-border bg-surface py-1.5 pl-2.5 pr-3.5">
            <span className="size-2 animate-pulse rounded-full bg-positive" aria-hidden="true" />
            <span className="font-display text-[13px] font-medium tracking-tight text-muted-foreground">
              Powered by{" "}
              <span className="font-extrabold text-foreground">
                Nova AI<span className="text-accent">.</span>
              </span>
            </span>
          </span>

          {/* One span per line so each animates in turn; keep delay utilities
              longhand. */}
          <h1
            className="font-display text-[clamp(1.875rem,7.4vw,5.5rem)] font-bold tracking-[-0.05em]"
            style={{ lineHeight: 1 }}
          >
            {/* Arrives blurred and resolves — the motion is the act of focusing. */}
            <span className="animate-focus-in [animation-delay:120ms] block text-foreground/70">
              Focus on what matters.
            </span>
            <span className="animate-rise [animation-delay:300ms] block">
              Beyond numbers.
            </span>
            <span className="animate-rise [animation-delay:480ms] block text-accent">
              See the big picture.
            </span>
          </h1>

          {/* Subhead and buttons animate as one unit. */}
          <div className="animate-rise [animation-delay:700ms]">
            <p className="mt-7 max-w-lg text-lg leading-relaxed text-muted-foreground">
              Where the market, trading and intelligence meet.
            </p>

            <div className="mt-9 flex flex-wrap gap-3">
              <CtaLink to={ROUTES.signup} size="md" arrow>
                Open the dashboard
              </CtaLink>
              <CtaLink href="#whats-built" variant="outline" size="md">
                See what&rsquo;s built
              </CtaLink>
            </div>
          </div>
        </div>

        {/* Black bezel frame; the cap keeps the shot reading as a framed object. */}
        <div className="animate-rise [animation-delay:880ms] mt-16">
          <div className="mx-auto max-w-sm rounded-[1.75rem] bg-ink p-2.5 shadow-2xl lg:max-w-[1040px] lg:p-3">
            <div
              className={
                "overflow-hidden rounded-[1.25rem] " +
                (shotLoaded ? "" : "skeleton-shimmer")
              }
            >
              {/* Intrinsic sizes reserve space; no lazy load — this is the LCP element. */}
              <img
                src={dashboardImg}
                width={2880}
                height={2180}
                fetchPriority="high"
                onLoad={() => setShotLoaded(true)}
                alt="The Tradium dashboard: portfolio value ₹2,77,990.30, the day's profit and loss, a performance chart, a top-holdings table with per-stock profit and loss, and a watchlist, recent orders and AI briefing card down the right side."
                className="block w-full"
              />
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
