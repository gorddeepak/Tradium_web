import { Link } from "react-router-dom";
import { isMarketOpen } from "@/services/marketStatus";
import { ROUTES } from "@/pages/routes/routes";

/* The status pill comes from isMarketOpen(), not hardcoded. */

const links = [
  { label: "What's built", href: "#whats-built" },
  { label: "Nova", href: "#nova" },
  { label: "Screens", href: "#screens" },
  { label: "FAQ", href: "#faq" },
];

export function MarketingFooter() {
  const open = isMarketOpen();

  return (
    <footer className="border-t border-border">
      <div className="mx-auto max-w-[1440px] px-6 py-12 lg:px-24">
        <div className="flex flex-wrap items-start justify-between gap-10">
          <div className="max-w-sm">
            <span className="font-display text-lg font-extrabold tracking-tighter">
              Tradium<span className="text-accent">.</span>
            </span>
            <p className="mt-3 text-[12px] leading-relaxed text-muted-foreground">
              Where the market, trading and intelligence meet.
            </p>
          </div>

          <nav className="flex flex-wrap gap-x-8 gap-y-3 text-[13px] font-medium text-muted-foreground">
            {links.map((l) => (
              <a key={l.label} href={l.href} className="transition-colors hover:text-foreground">
                {l.label}
              </a>
            ))}
            <Link to={ROUTES.login} className="transition-colors hover:text-foreground">
              Log in
            </Link>
            <Link to={ROUTES.signup} className="transition-colors hover:text-foreground">
              Open account
            </Link>
          </nav>
        </div>

        <div className="mt-10 flex flex-wrap items-center justify-between gap-4 border-t border-border pt-6">
          <span className="text-[11px] text-muted-foreground">
            &copy; 2026 Tradium.
          </span>

          <span
            className={
              "flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.1em] " +
              (open ? "text-positive" : "text-muted-foreground")
            }
          >
            <span
              className={
                "size-1.5 rounded-full " + (open ? "bg-positive" : "bg-muted-foreground")
              }
              aria-hidden="true"
            />
            {open ? "NSE open" : "NSE closed"}
          </span>
        </div>
      </div>
    </footer>
  );
}
