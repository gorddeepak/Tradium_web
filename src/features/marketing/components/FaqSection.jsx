import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { SectionHeader } from "@/features/marketing/components/SectionHeader";

/* Full disclosure in plain language, so nothing else has to overclaim. */

const faqs = [
  {
    q: "Is this a real brokerage?",
    a: "No. Tradium is a portfolio project showcasing full-stack work — React, Express, MongoDB. It isn't a registered broker, holds no client funds, and can't place an order on any exchange.",
  },
  {
    q: "Where do the prices come from?",
    a: "Real ones, inside the app. A scheduled job pulls quotes for your NSE symbols from Yahoo Finance every few minutes, so holdings and watchlist rows show genuine last-traded prices and day changes. The tape at the top of this page is the only exception — sample data, not a live feed.",
  },
  {
    q: "How does the money work?",
    a: "It's paper cash. Deposit or withdraw any amount and your available margin moves instantly — no payment step, nothing real. UPI and net banking appear in the app but are marked coming soon, so there is no bank connection anywhere.",
  },
  {
    q: "What can Nova AI do?",
    a: "It answers questions about your own account in plain language — holdings, positions, orders, watchlist, funds — and sums up every page in a one-line insight. It's read-only: it can look up any number, and place an order in none. It only ever sees your rows, never another user's.",
  },
  {
    q: "Which model powers Nova AI?",
    a: "Gemini, by Google — called from the backend, so the API key never reaches your browser. Replies stream in as they're written, and every figure comes from a tool call against your live data. Nova AI doesn't guess.",
  },
  {
    q: "How is my account secured?",
    a: "Passwords are hashed with bcrypt and never stored in plain text. Sessions use a signed JWT in an httpOnly cookie — invisible to JavaScript — expiring after seven days. Every API route, Nova AI's tools included, sits behind the same auth guard.",
  },
  {
    q: "Can I lose money?",
    a: "No. No payment step, no deposit, no bank connection. Orders fill against the last known price so the workflow feels real, but no cash ever moves and there's nothing to lose.",
  },
  {
    q: "Is the code available?",
    a: "Yes — it's a portfolio project, so reading it is the point. The frontend lives in src/ organised by feature, and the Express API in server/ with one router and controller per resource.",
  },
];

export function FaqSection() {
  return (
    <section id="faq" className="border-t border-border scroll-mt-16">
      <div className="mx-auto grid max-w-[1440px] gap-12 px-6 py-20 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)] lg:gap-20 lg:px-24 lg:py-28">
        <div>
          <SectionHeader eyebrow="Straight answers">
            What this is,
            <br />
            <span className="text-accent">and what it isn&rsquo;t</span>
          </SectionHeader>
          <p className="mt-5 text-[15px] leading-relaxed text-muted-foreground">
            No fine print. If something here would matter to you, it&rsquo;s on this
            list.
          </p>
        </div>

        <Accordion type="single" collapsible className="w-full">
          {faqs.map((f) => (
            <AccordionItem key={f.q} value={f.q}>
              <AccordionTrigger className="text-left text-[15px] font-semibold">
                {f.q}
              </AccordionTrigger>
              <AccordionContent className="text-[14px] leading-relaxed text-muted-foreground">
                {f.a}
              </AccordionContent>
            </AccordionItem>
          ))}
        </Accordion>
      </div>
    </section>
  );
}
