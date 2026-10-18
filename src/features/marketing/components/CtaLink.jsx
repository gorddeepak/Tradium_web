import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import { cn } from "@/utils/utils";

/* The landing page's button-looking link. `to` renders a router Link,
   `href` a plain anchor (in-page sections like #whats-built).
   Sizes: sm = nav, md = hero, lg = closing CTA. `arrow` adds the
   chevron that slides right on hover. */
const sizes = {
  sm: "px-4 py-2 text-[13px]",
  md: "px-7 py-3.5 text-sm",
  lg: "px-8 py-3.5 text-sm",
};

export function CtaLink({ to, href, variant = "solid", size = "md", arrow = false, className, children }) {
  const classes = cn(
    "group inline-flex items-center gap-2 rounded-lg font-semibold",
    sizes[size],
    variant === "solid"
      ? "bg-primary text-primary-foreground transition-opacity hover:opacity-90"
      : variant === "accent"
        // The Nova CTA on the dark band — accent instead of primary.
        ? "bg-accent text-accent-foreground transition-opacity hover:opacity-90"
        : "border border-border transition-colors hover:bg-secondary",
    className
  );

  return to ? (
    <Link to={to} className={classes}>
      {children}
      {arrow && (
        <ArrowRight className="size-4 transition-transform duration-300 group-hover:translate-x-1" aria-hidden="true" />
      )}
    </Link>
  ) : (
    <a href={href} className={classes}>
      {children}
      {arrow && (
        <ArrowRight className="size-4 transition-transform duration-300 group-hover:translate-x-1" aria-hidden="true" />
      )}
    </a>
  );
}
