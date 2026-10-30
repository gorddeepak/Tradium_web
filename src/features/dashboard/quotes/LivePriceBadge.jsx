import { useQuoteStatus } from "./QuoteContext";
import { cn } from "@/utils/utils";

/* Honest feed state, not a decoration.

   Live:        the upstream stream is connected and ticks are arriving.
   Reconnecting: enabled, but the upstream socket is down.
   Polling:     LIVE_QUOTES_ENABLED is off; prices come from the REST sync.
   Offline:     the browser's own socket is down and is retrying. */
function badgeState(status, connected) {
  if (!connected) {
    return {
      label: "Offline",
      dot: "bg-muted-foreground",
      text: "text-muted-foreground",
      title: "Quote stream disconnected; showing the last fetched prices",
    };
  }
  if (!status.enabled) {
    return {
      label: "Polling",
      dot: "bg-muted-foreground",
      text: "text-muted-foreground",
      title: "Live feed is off; prices refresh from the scheduled REST sync",
    };
  }
  if (status.streaming) {
    return {
      label: "Live",
      dot: "bg-positive",
      text: "text-positive",
      title: "Streaming live prices from the market feed",
    };
  }
  if (status.state === "connecting") {
    return {
      label: "Connecting",
      dot: "bg-muted-foreground",
      text: "text-muted-foreground",
      title: "Connecting to the live price feed",
    };
  }
  return {
    label: "Reconnecting",
    dot: "bg-amber-500",
    text: "text-amber-600",
    title: "Live feed is reconnecting; showing the last fetched prices",
  };
}

export function LivePriceBadge({ className }) {
  const { status, connected } = useQuoteStatus();
  const view = badgeState(status, connected);

  return (
    <span
      title={view.title}
      aria-label={view.title}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border border-border bg-surface px-2 py-1 text-[10px] font-semibold uppercase tracking-wider",
        view.text,
        className
      )}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", view.dot)} />
      <span className="hidden sm:inline">{view.label}</span>
    </span>
  );
}
