import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { CtaLink } from "@/features/marketing/components/CtaLink";
import { ROUTES } from "@/pages/routes/routes";

/* In-page anchors, so nothing in the nav sends a first-time visitor into a
   protected route (which would flash a spinner and bounce them to /login). */
const links = [
  { label: "What's built", href: "#whats-built" },
  { label: "Nova", href: "#nova" },
  { label: "Screens", href: "#screens" },
  { label: "FAQ", href: "#faq" },
];

/* Fixed (not sticky) so the hero's ground runs underneath. A background fades
   in after 16px of scroll; only the colours transition, border-b stays put.
   Hero's pt-32/pt-40 reserves this bar's height. */
export function MarketingNav() {
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 16);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <header
      className={
        "fixed inset-x-0 top-0 z-50 border-b transition-colors duration-300 " +
        (scrolled
          ? "border-border bg-background/85 backdrop-blur-md"
          : "border-transparent bg-transparent")
      }
    >
      <div className="mx-auto flex h-16 max-w-[1440px] items-center justify-between px-6 lg:px-24">
        <Link to={ROUTES.home} className="font-display text-xl font-extrabold tracking-tighter">
          Tradium<span className="text-accent">.</span>
        </Link>

        <nav className="hidden items-center gap-8 text-sm font-medium text-muted-foreground md:flex">
          {links.map((l) => (
            <a key={l.label} href={l.href} className="transition-colors hover:text-foreground">
              {l.label}
            </a>
          ))}
        </nav>

        <div className="flex items-center gap-3">
          <CtaLink to={ROUTES.login} variant="outline" size="sm" className="hidden sm:inline-flex">
            Log in
          </CtaLink>
          <CtaLink to={ROUTES.signup} size="sm">
            Open account
          </CtaLink>
        </div>
      </div>
    </header>
  );
}
