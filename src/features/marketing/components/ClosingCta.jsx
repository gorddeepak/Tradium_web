import { Link } from "react-router-dom";
import { CtaLink } from "@/features/marketing/components/CtaLink";
import { ROUTES } from "@/pages/routes/routes";
import { useReveal } from "@/hooks/useReveal";

/* Honest subline and fine print; the button lands a beat after the sentence. */

export function ClosingCta() {
  const [revealRef, shown] = useReveal();

  return (
    <section className="border-t border-border bg-surface">
      <div
        ref={revealRef}
        className="mx-auto max-w-[1440px] px-6 py-20 text-center lg:px-24 lg:py-24"
      >
        <div className={shown ? "animate-rise" : "opacity-0"}>
          <h2 className="font-display text-[clamp(2rem,4.5vw,3rem)] font-bold leading-[1.05] tracking-[-0.03em]">
            Place a trade in the
            <br className="hidden sm:block" />{" "}
            <span className="text-accent">next two minutes</span>
          </h2>
          <p className="mx-auto mt-5 max-w-lg text-[15px] leading-relaxed text-muted-foreground">
            A name, an email, a password — and the whole dashboard is yours.
          </p>
        </div>

        {/* Margin sits on the wrapper, not the inline-flex Link. */}
        <div
          className={
            "mt-9 " + (shown ? "animate-rise [animation-delay:140ms]" : "opacity-0")
          }
        >
          <CtaLink to={ROUTES.signup} size="lg" arrow>
            Create an account
          </CtaLink>
        </div>

        <p
          className={
            "mt-5 text-[12px] text-muted-foreground " +
            (shown ? "animate-rise [animation-delay:240ms]" : "opacity-0")
          }
        >
          No payment step, no bank details, no real money.{" "}
          <Link to={ROUTES.login} className="story-link font-semibold text-foreground">
            Already have an account?
          </Link>
        </p>
      </div>
    </section>
  );
}
