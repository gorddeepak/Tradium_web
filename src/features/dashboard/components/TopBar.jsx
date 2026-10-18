import { useState } from "react";
import { NavLink, Link } from "react-router-dom";
import { useFunds } from "@/features/dashboard/FundsContext";
import { fmtMoney } from "@/utils/tradiumUtils";
import { AccountMenu } from "./AccountMenu";
import { GlobalSearch } from "./GlobalSearch";
import { ROUTES } from "@/pages/routes/routes";
import { Menu, SearchIcon, Sparkles, X } from 'lucide-react';

const links = [
  { to: ROUTES.dashboard, label: "Dashboard" },
  // Markets is the only market-wide link; the rest are account-specific.
  { to: ROUTES.markets, label: "Markets" },
  { to: ROUTES.watchlist, label: "Trade" },
  { to: ROUTES.holdings, label: "Holdings" },
  { to: ROUTES.positions, label: "Positions" },
  { to: ROUTES.orders, label: "Orders" },
  { to: ROUTES.funds, label: "Funds" },
];

export function TopBar({ onOpenAssistant }) {
  const { funds } = useFunds();
  // mobile only: toggles the dropdown nav panel below md
  const [mobileOpen, setMobileOpen] = useState(false);
  // search palette state — on mobile it opens from the menu panel
  const [searchOpen, setSearchOpen] = useState(false);
  return (
    <nav className="sticky top-0 z-50 border-b border-border bg-background/80 backdrop-blur-md">
      {/* px-4 on phones keeps the bar from feeling crowded at 375px. */}
      <div className="mx-auto flex h-14 max-w-[1440px] items-center justify-between px-4 sm:px-6">
        <div className="flex items-center gap-10">
          <Link to={ROUTES.dashboard} className="font-display text-xl font-extrabold tracking-tighter">
            Tradium<span className="text-accent">.</span>
          </Link>
          {/* Full-height links so the underline sits on the border. */}
          <div className="hidden h-full items-center gap-6 text-sm font-medium md:flex">
            {links.map((l) => (
              <NavLink
                key={l.to}
                to={l.to}
                end={l.to === ROUTES.dashboard}
                className={({ isActive }) =>
                  `relative flex h-full items-center transition-colors ${
                    isActive ? "text-foreground" : "text-muted-foreground hover:text-foreground"
                  } after:absolute after:inset-x-1 after:bottom-0 after:h-[2px] after:rounded-t-full after:bg-accent after:transition-opacity after:content-[''] ${
                    isActive ? "after:opacity-100" : "after:opacity-0 hover:after:opacity-40"
                  }`
                }
              >
                {l.label}
              </NavLink>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-2 sm:gap-3">
          <GlobalSearch
            open={searchOpen}
            onOpenChange={setSearchOpen}
            triggerClassName="hidden md:flex"
          />
          {/* Solid dark — the navbar's one primary action. */}
          <button
            onClick={onOpenAssistant}
            className="hidden items-center gap-1.5 rounded-md bg-foreground px-3 py-1.5 text-[13px] font-semibold text-background shadow-sm transition-all hover:opacity-85 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-foreground md:flex"
          >
            <Sparkles size={14} className="text-accent" />
            {/* Accent period, like the Tradium logo. */}
            <span className="hidden sm:inline font-display font-extrabold tracking-tight">
              Ask Nova AI<span className="text-accent">.</span>
            </span>
          </button>
          <div className="flex items-center gap-3 rounded-md border border-border bg-surface px-3 py-1 shadow-xs">
            {/* Label hidden below sm — the number alone reads fine there. */}
            <div className="flex flex-col items-end">
              <span className="hidden text-[10px] font-semibold uppercase tracking-wider text-muted-foreground sm:block">
                Available balance
              </span>
              <span className="num text-sm">{fmtMoney(funds?.available ?? 0)}</span>
            </div>
            <div className="h-6 w-px bg-border" />
            <AccountMenu />
          </div>
          {/* Mobile menu button for the hidden nav links. */}
          <button
            onClick={() => setMobileOpen((o) => !o)}
            aria-expanded={mobileOpen}
            aria-label={mobileOpen ? "Close menu" : "Open menu"}
            className="rounded-md border border-border bg-surface p-2 text-muted-foreground shadow-xs transition-colors hover:text-foreground md:hidden"
          >
            {mobileOpen ? <X size={16} /> : <Menu size={16} />}
          </button>
        </div>
      </div>
      {mobileOpen && (
        <div className="border-t border-border bg-background px-4 py-4 sm:px-6 md:hidden">
          {/* Search and Nova live here on mobile; opening one closes the panel. */}
          <div className="mb-3 grid grid-cols-2 gap-2">
            <button
              onClick={() => {
                setMobileOpen(false);
                setSearchOpen(true);
              }}
              className="flex items-center justify-center gap-2 rounded-md border border-border bg-surface px-3 py-2 text-sm text-muted-foreground shadow-xs transition-colors hover:text-foreground"
            >
              <SearchIcon size={14} />
              Search
            </button>
            <button
              onClick={() => {
                setMobileOpen(false);
                onOpenAssistant();
              }}
              className="flex items-center justify-center gap-1.5 rounded-md bg-foreground px-3 py-2 text-sm font-semibold text-background shadow-sm transition-all hover:opacity-85"
            >
              <Sparkles size={14} className="text-accent" />
              Ask Nova AI<span className="text-accent">.</span>
            </button>
          </div>
          <div className="flex flex-col gap-1 text-sm font-medium">
            {links.map((l) => (
              <NavLink
                key={l.to}
                to={l.to}
                end={l.to === ROUTES.dashboard}
                onClick={() => setMobileOpen(false)}
                className={({ isActive }) =>
                  `rounded-md px-3 py-2 transition-colors ${
                    isActive
                      ? "bg-accent/10 text-foreground"
                      : "text-muted-foreground hover:bg-surface-sunken hover:text-foreground"
                  }`
                }
              >
                {l.label}
              </NavLink>
            ))}
          </div>
        </div>
      )}
    </nav>
  );
}

export default TopBar;




