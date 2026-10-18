import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { SearchIcon } from "lucide-react";

import {
  Command,
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Spinner } from "@/components/ui/spinner";
import { fmtMoney, fmtPct, toneClass } from "@/utils/tradiumUtils";
import { useInstrumentSearch } from "@/features/dashboard/hooks/useInstrumentSearch";
import { ROUTES } from "@/pages/routes/routes";

/* Global Ctrl+K stock search dialog — plain debounced API, no AI. */
export function GlobalSearch({ open, onOpenChange, triggerClassName = "" }) {
  const [query, setQuery] = useState("");
  const { results, loading } = useInstrumentSearch(query, open);
  const navigate = useNavigate();

  // Toggle the search palette with Ctrl+K.
  useEffect(() => {
    const onKeyDown = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        onOpenChange?.(!open);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onOpenChange]);

  const goToSymbol = (symbol) => {
    onOpenChange?.(false);
    setQuery("");
    navigate(ROUTES.instrument(symbol));
  };

  return (
    <>
      <button
        onClick={() => onOpenChange?.(true)}
        aria-label="Search stocks"
        className={`flex items-center gap-2 rounded-md border border-border bg-surface px-3 py-1.5 text-[13px] text-muted-foreground shadow-xs transition-colors hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-foreground ${triggerClassName}`}
      >
        <SearchIcon size={14} />
        <span className="hidden md:inline">Search</span>
        <kbd className="hidden rounded border border-border bg-background px-1 font-sans text-[10px] font-semibold md:inline">
          Ctrl K
        </kbd>
      </button>

      <CommandDialog open={open} onOpenChange={onOpenChange} title="Search stocks" description="Search NIFTY 50 stocks and indices">
        <Command shouldFilter={false}>
          <CommandInput
            placeholder="Search by symbol or name..."
            value={query}
            onValueChange={setQuery}
          />
          <CommandList>
            {loading && query.trim() && (
              <div className="flex items-center justify-center gap-2 py-6 text-sm text-muted-foreground">
                <Spinner className="size-4" />
                Searching...
              </div>
            )}
            {!loading && query.trim() && results.length === 0 && (
              <CommandEmpty>No matching stocks or indices.</CommandEmpty>
            )}
            {!query.trim() && !results.length && (
              <div className="py-6 text-center text-sm text-muted-foreground">
                Start typing to search stocks and indices.
              </div>
            )}
            {results.length > 0 && query.trim() && (
              <CommandGroup heading="Stocks & Indices">
                {results.map((r) => (
                  <CommandItem
                    key={r.symbol}
                    value={r.symbol}
                    onSelect={() => goToSymbol(r.symbol)}
                  >
                    <SearchIcon className="opacity-50" />
                    <span className="font-medium">{r.symbol}</span>
                    <span className="truncate text-muted-foreground">{r.name}</span>
                    <span className="ml-auto num text-xs text-muted-foreground">
                      {fmtMoney(r.price)}
                    </span>
                    <span
                      className={`num text-xs ${toneClass(r.changePct ?? 0)}`}
                    >
                      {fmtPct(r.changePct ?? 0)}
                    </span>
                  </CommandItem>
                ))}
              </CommandGroup>
            )}
          </CommandList>
        </Command>
      </CommandDialog>
    </>
  );
}

export default GlobalSearch;
