import { useEffect } from "react";
import {
  MarketingNav,
  Hero,
  TickerStrip,
  FeatureStrip,
  NovaSection,
  ScreenShowcase,
  FaqSection,
  ClosingCta,
  MarketingFooter,
} from "@/features/marketing";
import { useDocumentHead } from "@/hooks/useDocumentHead";

/* Section order is deliberate: product, proof, habits, Nova, screens, honest answers. */

export default function LandingPage() {
  useDocumentHead({
    title: "Tradium — practice trades with a sharper dashboard",
    description:
      "A mock NSE trading dashboard: holdings, positions, orders, watchlist, funds and single-stock execution, with an assistant that reads your portfolio. No real money involved.",
  });

  // The landing page only looks right in light mode — turn dark mode off even
  // if the user switched it on inside the dashboard.
  useEffect(() => {
    document.documentElement.classList.remove("dark");
  }, []);

  return (
    <div className="min-h-screen bg-background">
      <MarketingNav />
      <main>
        <Hero />
        <TickerStrip />
        <FeatureStrip />
        <NovaSection />
        <ScreenShowcase />
        <FaqSection />
        <ClosingCta />
      </main>
      <MarketingFooter />
    </div>
  );
}
