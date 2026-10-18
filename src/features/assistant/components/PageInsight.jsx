import { useCompletion } from '@ai-sdk/react';
import { useEffect } from 'react';
import { useAssistant } from '@/features/assistant/AssistantContext';
import { BASE_URL } from '@/services/api';

export default function PageInsight({ page, data }) {
  const isDashboard = page === 'dashboard';
  const { completion, complete, isLoading, error } = useCompletion({
    api: isDashboard
      ? `${BASE_URL}/assistant/briefing`
      : `${BASE_URL}/assistant/insight`,
    credentials: 'include',
    streamProtocol: 'text',
  });
  const { openWithContext } = useAssistant();

  useEffect(() => {
    if (data) complete('', { body: { page, data } });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, JSON.stringify(data)]);

  if (!data) return null;

  // Work out the one line of text to show. Kept as plain if/else instead of
  // nested ternaries so it stays readable.
  let insightText = completion;
  if (error) {
    insightText = 'Insight unavailable right now.';
  } else if (isLoading && !completion) {
    insightText = isDashboard ? 'Reading your portfolio...' : 'Analyzing...';
  }

  return (
    <div className="relative overflow-hidden rounded-xl bg-foreground p-6 text-background">
      <div className="relative z-10">
        <div className="mb-2 flex items-center gap-2">
          <span className="size-2 animate-pulse rounded-full bg-accent" />
          <h2 className="text-xs font-semibold uppercase tracking-widest opacity-80">
            Nova insights
          </h2>
        </div>
        {/* One size on every page — the card is already the loud one. */}
        <p className="font-display mb-2 text-lg font-bold leading-snug">
          {insightText}
        </p>
        {/* Sends the insight text above (not the raw data) so the chat bubble stays readable */}
        <button
          onClick={() => openWithContext({ page, insight: completion })}
          disabled={!completion}
          className="mt-2 inline-flex items-center gap-1 rounded-md border border-background/20 bg-background/5 px-3 py-1.5 text-xs font-semibold text-background/90 transition-colors hover:bg-background/10 hover:text-background disabled:opacity-40"
        >
          Ask about this
        </button>
      </div>
      <div className="absolute right-0 top-0 size-32 -translate-y-10 translate-x-10 rounded-full bg-accent/20 blur-3xl" />
    </div>
  );
}


