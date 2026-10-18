import { useEffect, useState } from "react";
import { NavLink, Outlet, useMatch, useNavigate } from "react-router-dom";
import { Plus, X } from "lucide-react";
import { toast } from "sonner";
import { MetricReadout, PageHeader, fmtMoney, fmtPct, toneClass, topMovers } from "@/utils/tradiumUtils";
import { useWatchlist } from "@/features/dashboard/hooks/useWatchlist";
import { useSparkHistory } from "@/features/dashboard/hooks/useSparkHistory";
import { useInstrumentSearch } from "@/features/dashboard/hooks/useInstrumentSearch";
import { lookupInstrument } from "@/services/api";
import { ROUTES } from "@/pages/routes/routes";
import { cn } from "@/utils/utils";
import PageInsight from "@/features/assistant/components/PageInsight";
import { Sparkline } from "@/components/ui/Sparkline";

/* Watchlist rail + instrument detail via <Outlet />. PageInsight lives here
   (not in the pane) so its AI call fires once per visit, not per symbol click. */
export default function WatchlistPage() {
  const { watchlist, loading, add, remove, flashes } = useWatchlist();
  const [draft, setDraft] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const { results: suggestions, loading: searching } = useInstrumentSearch(draft);
  const sparkHistory = useSparkHistory(watchlist);

  /* The selected symbol lives in the child route, so match the nested pattern
     directly. */
  const match = useMatch(ROUTES.instrument(":symbol"));
  const selected = match?.params.symbol ?? null;
  const navigate = useNavigate();

  const advancing = watchlist.filter((w) => (w.dayChangePct ?? 0) >= 0).length;
  const declining = watchlist.length - advancing;
  const selectedTracked = watchlist.some((w) => w.symbol === selected);

  /* Shared add lookup for the form and the prompt; returns whether it added. */
  async function addSymbol(symbol) {
    if (watchlist.some((w) => w.symbol === symbol)) {
      toast.error(`${symbol} is already on your watchlist`);
      return false;
    }
    setSubmitting(true);
    try {
      const instrument = await lookupInstrument(symbol);
      await add({ symbol: instrument.symbol, name: instrument.name, exchange: instrument.exchange });
      toast.success(`${symbol} added to watchlist`);
      return true;
    } catch {
      toast.error(`No instrument found for "${symbol}"`);
      return false;
    } finally {
      setSubmitting(false);
    }
  }

  /* Picking an already-tracked suggestion opens it instead of erroring. */
  async function pickSuggestion(symbol) {
    if (watchlist.some((w) => w.symbol === symbol)) {
      navigate(ROUTES.instrument(symbol));
    } else {
      await addSymbol(symbol);
    }
    setDraft("");
  }

  async function handleAdd(e) {
    e.preventDefault();
    const symbol = draft.trim().toUpperCase();
    if (!symbol) return;
    if (await addSymbol(symbol)) {
      setDraft("");
    }
  }

  async function handleRemove(id, symbol) {
    await remove(id);
    toast(`${symbol} removed from watchlist`);
  }

  /* Auto-select the first symbol on a bare visit; the guard stops it firing
     before the list loads. */
  useEffect(() => {
    if (!loading && !selected && watchlist.length > 0) {
      navigate(ROUTES.instrument(watchlist[0].symbol), { replace: true });
    }
  }, [loading, selected, watchlist, navigate]);

  /* Block on the list fetch so the rail's counters don't flash zeroes. */
  if (loading) {
    return (
      <main className="p-8">
        <div className="skeleton-shimmer mb-6 h-4 w-32 rounded-md" />
        <div className="skeleton-shimmer h-[600px] w-full rounded-xl" />
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-[1440px] px-6 py-8">
      {/* 12-column grid: 324px rail, 1036px pane; they stack below lg. The
          header lives inside the left column. */}
      <div className="grid grid-cols-12 gap-8">
        <aside className="animate-entry col-span-12 space-y-6 [animation-delay:150ms] lg:col-span-3">
          <PageHeader
            eyebrow="Market monitor"
            title="Trade"
            description="Pick an instrument from your watchlist to chart it and place an order."
          />

          {/* This list's advancing/declining counts, above the rows they count. */}
          <div className="grid grid-cols-2 gap-6 rounded-xl border border-border bg-surface p-4 shadow-xs">
            <MetricReadout
              label="Advancing"
              value={String(advancing)}
              tone={1}
              sub={`of ${watchlist.length} tracked`}
              hint="Watchlist names up (or flat) since the previous close"
            />
            <MetricReadout
              label="Declining"
              value={String(declining)}
              tone={-1}
              hint="Watchlist names down since the previous close"
            />
          </div>

          <div className="overflow-hidden rounded-xl border border-border bg-surface shadow-xs">
            {/* Same card header style as HeatmapCard, so the rail and the chart
                card beside it read as one system. */}
            <div className="flex items-baseline justify-between gap-2 border-b border-border px-4 py-3">
              <h2 className="font-display text-sm font-bold tracking-tight">Watchlist</h2>
              <span className="num text-[11px] text-muted-foreground">{watchlist.length} symbols</span>
            </div>
            <div className="relative">
              <form onSubmit={handleAdd} className="flex items-center gap-2 border-b border-border px-3 py-2.5">
                <Plus className="size-3.5 shrink-0 text-muted-foreground" />
                {/* min-w-0 stops the input pushing the Add button out of the rail. */}
                <input
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  placeholder="Add symbol"
                  autoComplete="off"
                  className="num min-w-0 flex-1 bg-transparent text-[12px] uppercase outline-none placeholder:font-sans placeholder:normal-case placeholder:text-muted-foreground"
                />
                <button
                  type="submit"
                  disabled={submitting}
                  className="shrink-0 rounded bg-foreground px-2 py-1 text-[10px] font-semibold text-background disabled:opacity-50"
                >
                  {submitting ? "..." : "Add"}
                </button>
              </form>

              {/* Search suggestions, overlaying the list instead of pushing it down. */}
              {draft.trim() && (
                <div className="absolute inset-x-0 top-full z-10 max-h-64 overflow-y-auto rounded-b-xl border border-t-0 border-border bg-surface shadow-lg">
                  {searching && (
                    <p className="px-3 py-4 text-center text-[11px] text-muted-foreground">
                      Searching...
                    </p>
                  )}
                  {!searching && suggestions.length === 0 && (
                    <p className="px-3 py-4 text-center text-[11px] text-muted-foreground">
                      No matching stocks.
                    </p>
                  )}
                  {!searching &&
                    suggestions.map((s) => (
                      <button
                        key={s.symbol}
                        type="button"
                        onClick={() => pickSuggestion(s.symbol)}
                        className="flex w-full items-baseline gap-2 px-3 py-2 text-left hover:bg-surface-sunken/60"
                      >
                        <span className="num text-[12px] font-semibold">{s.symbol}</span>
                        <span className="min-w-0 flex-1 truncate text-[11px] text-muted-foreground">
                          {s.name}
                        </span>
                        <span className={cn("num text-[11px]", toneClass(s.changePct ?? 0))}>
                          {fmtPct(s.changePct ?? 0)}
                        </span>
                      </button>
                    ))}
                </div>
              )}
            </div>

            {/* Scroll, don't page — paging away from the selected symbol loses
                your place. 554px = ten rows. */}
            <div className="max-h-[554px] overflow-y-auto">
              {watchlist.map((w) => (
                /* NavLink and remove button are siblings — a <button> inside an <a>
                   is invalid. */
                <div key={w._id} className="group flex items-stretch border-b border-border last:border-b-0">
                  <NavLink
                    to={ROUTES.instrument(w.symbol)}
                    className={({ isActive }) =>
                      cn(
                        /* border-l-2 in both states so the text doesn't shift on click. */
                        "flex min-w-0 grow items-center justify-between gap-2 border-l-2 py-2.5 pl-3 pr-1 transition-colors",
                        isActive
                          ? "border-accent bg-surface-sunken"
                          : "border-transparent hover:bg-surface-sunken/60"
                      )
                    }
                  >
                    {/* grow absorbs spare width so prices line up on every row. */}
                    <span className="flex min-w-0 grow flex-col">
                      <span className="truncate text-[13px] font-semibold">{w.symbol}</span>
                      <span className="text-[10px] text-muted-foreground">{w.exchange}</span>
                    </span>
                    <Sparkline points={sparkHistory[w.symbol]} className="mx-1" />
                    {/* Fixed width so sparklines line up; the stamp key replays
                        the flash. */}
                    <span
                      key={flashes[w._id]?.stamp ?? "0"}
                      className={cn(
                        "flex w-[76px] shrink-0 flex-col items-end rounded",
                        flashes[w._id]?.dir === "up" && "price-flash-up",
                        flashes[w._id]?.dir === "down" && "price-flash-down"
                      )}
                    >
                      <span className="num text-[12px]">{fmtMoney(w.ltp ?? 0)}</span>
                      <span className={cn("num text-[10px]", toneClass(w.dayChangePct ?? 0))}>
                        {fmtPct(w.dayChangePct ?? 0)}
                      </span>
                    </span>
                  </NavLink>
                  <button
                    onClick={() => handleRemove(w._id, w.symbol)}
                    aria-label={`Remove ${w.symbol}`}
                    className="grid w-8 shrink-0 place-items-center text-muted-foreground opacity-0 transition-all hover:text-negative focus-visible:opacity-100 group-hover:opacity-100"
                  >
                    <X className="size-3" />
                  </button>
                </div>
              ))}
              {watchlist.length === 0 && (
                <p className="px-3 py-10 text-center text-[12px] text-muted-foreground">
                  Your watchlist is empty. Add a symbol above.
                </p>
              )}
            </div>
          </div>

          {/* Sits under the rail, next to the rows it describes. */}
          <div className="animate-entry [animation-delay:250ms]">
            <PageInsight
              page="watchlist"
              data={{
                tracked: watchlist.length,
                advancing,
                declining,
                topMovers: topMovers(watchlist),
              }}
            />
          </div>
        </aside>

        <div className="col-span-12 lg:col-span-9">
          {/* Shown when the URL selects a symbol not on this list. */}
          {selected && !selectedTracked && (
            <div className="animate-entry mb-4 flex w-fit flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border border-dashed border-border bg-surface px-3 py-2 text-[12px] [animation-delay:100ms]">
              <span className="text-muted-foreground">
                <span className="num font-semibold text-foreground">{selected}</span> isn&apos;t on your watchlist.
              </span>
              <button
                onClick={() => addSymbol(selected)}
                disabled={submitting}
                className="inline-flex items-center gap-1 rounded bg-foreground px-2 py-1 text-[10px] font-semibold text-background disabled:opacity-50"
              >
                <Plus className="size-3" /> Add to watchlist
              </button>
            </div>
          )}
          <Outlet />
        </div>
      </div>
    </main>
  );
}
