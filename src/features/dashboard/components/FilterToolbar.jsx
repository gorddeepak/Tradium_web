import { Search } from "lucide-react";
import { RangePills } from "@/utils/tradiumUtils";

// The search box + all/gainers/losers pills shared by the table pages.
export function FilterToolbar({ query, onQueryChange, filter, onFilterChange }) {
  return (
    <div className="animate-entry mb-4 flex flex-wrap items-center justify-between gap-3 [animation-delay:100ms]">
      <div className="flex items-center gap-2 rounded-md border border-border bg-surface px-3 py-2 shadow-xs">
        <Search className="size-3.5 text-muted-foreground" />
        <input
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
          placeholder="Filter by symbol or name"
          className="w-56 bg-transparent text-[13px] outline-none placeholder:text-muted-foreground"
        />
      </div>
      <RangePills values={["all", "gainers", "losers"]} active={filter} onChange={onFilterChange} capitalize />
    </div>
  );
}
