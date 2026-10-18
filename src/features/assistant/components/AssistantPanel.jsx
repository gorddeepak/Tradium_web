import {
    Conversation,
    ConversationContent,
    ConversationScrollButton,
} from '@/features/assistant/ai-elements/conversation';
import { Button } from '@/components/ui/button';
import { MessageResponse } from '@/features/assistant/ai-elements/message';
import {
    PromptInput,
    PromptInputTextarea,
    PromptInputSubmit,
} from '@/features/assistant/ai-elements/prompt-input';
import { Tool, ToolHeader, ToolContent, ToolOutput } from '@/features/assistant/ai-elements/tool';
import { Suggestion } from '@/features/assistant/ai-elements/suggestion';
import { Spinner } from '@/components/ui/spinner';
import { useState, useEffect, useRef } from 'react';
import { Sparkles, X, User } from 'lucide-react';
import { useAssistant } from '@/features/assistant/AssistantContext';
import { useAuth } from '@/features/auth/AuthContext';

const suggestions = [
    "How's my portfolio doing?",
    'Any big movers today?',
    'Summarize my open positions',
    "What's my buying power?",
];

// Small round icon for Nova (the assistant)
function NovaAvatar() {
    return (
        <div className="flex size-7 shrink-0 items-center justify-center rounded-full bg-foreground text-background">
            <Sparkles className="size-3.5" />
        </div>
    );
}

// Small round icon for the user (shows their initials)
function UserAvatar({ initials }) {
    return (
        <div className="flex size-7 shrink-0 items-center justify-center rounded-full border border-border bg-surface text-[11px] font-semibold text-muted-foreground">
            {initials || <User className="size-3.5" />}
        </div>
    );
}

export default function AssistantPanel() {
    const [input, setInput] = useState('');
    const seedContextSentRef = useRef(false);
    const inputRef = useRef(null);
    const { seedContext, setSeedContext, chat, setIsOpen } = useAssistant();
    const { user } = useAuth();
    const { messages, sendMessage, status } = chat;
    const isLoading = status === 'streaming' || status === 'submitted';
    const initials = user?.username ? user.username.slice(0, 2).toUpperCase() : '';

    // focus the input as soon as the panel opens, so "Ask about this" and
    // the open button lead straight into typing
    useEffect(() => {
        inputRef.current?.focus();
    }, []);

    // and again each time Nova finishes a reply, so the next question is
    // ready without clicking the box
    const wasLoadingRef = useRef(false);
    useEffect(() => {
        if (isLoading) {
            wasLoadingRef.current = true;
            return;
        }
        if (wasLoadingRef.current) {
            wasLoadingRef.current = false;
            inputRef.current?.focus();
        }
    }, [isLoading]);

    useEffect(() => {
        if (seedContext && !seedContextSentRef.current) {
            sendMessage({
                text: `About my ${seedContext.page} page, you told me: "${seedContext.insight}" Can you explain this in more detail?`,
            });
            seedContextSentRef.current = true;
            setSeedContext(null);
        }
        if (!seedContext) {
            seedContextSentRef.current = false;
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [seedContext]);

    return (
        <div className="flex h-full flex-col bg-background">
            {/* Header */}
            <div className="flex items-center justify-between border-b border-border px-4 py-3">
                <div className="flex items-center gap-2.5">
                    <NovaAvatar />
                    <div>
                        {/* The Nova wordmark, styled like the Tradium logo. */}
                        <p className="font-display text-sm font-extrabold tracking-tight">
                            Nova AI<span className="text-accent">.</span>
                        </p>
                        <p className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                            <span className="size-1.5 rounded-full bg-positive" />
                            Portfolio assistant
                        </p>
                    </div>
                </div>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  asChild
                  onClick={() => setIsOpen(false)}
                  aria-label="Close"
                >
                  <X className="size-3.5" />
                </Button>
            </div>

            {/* Messages */}
            {messages.length === 0 ? (
                // Welcome screen (shown before any message)
                <div className="flex flex-1 flex-col items-center justify-center px-6 text-center">
                    <div className="flex size-12 items-center justify-center rounded-2xl bg-foreground text-background">
                        <Sparkles className="size-6" />
                    </div>
                    <h3 className="mt-4 font-display text-base font-semibold">
                        Ask Nova AI anything<span className="text-accent">.</span>
                    </h3>
                    <p className="mt-1.5 max-w-[17rem] text-sm text-muted-foreground">
                        I can pull your real portfolio, positions, orders, watchlist, and funds.
                    </p>
                    <div className="mt-5 flex flex-wrap justify-center gap-2">
                        {suggestions.map((text) => (
                            <Suggestion key={text} suggestion={text} onClick={() => sendMessage({ text })} />
                        ))}
                    </div>
                </div>
            ) : (
                <Conversation>
                    <ConversationContent className="gap-6">
                        {messages.map((message) => {
                            const isUser = message.role === 'user';
                            return (
                                <div
                                    key={message.id}
                                    className={`animate-entry flex items-start gap-2.5 ${isUser ? 'flex-row-reverse' : ''}`}
                                >
                                    {isUser ? <UserAvatar initials={initials} /> : <NovaAvatar />}
                                    <div className={`flex min-w-0 flex-1 flex-col gap-2 break-words ${isUser ? 'items-end' : 'items-start'}`}>
                                        {message.parts.map((part, i) => {
                                            if (part.type === 'text') {
                                                if (isUser) {
                                                    return (
                                                        <div key={i} className="rounded-2xl rounded-tr-sm bg-accent px-3.5 py-2.5 text-sm text-accent-foreground">
                                                            {part.text}
                                                        </div>
                                                    );
                                                }
                                                return (
                                                    <div key={i} className="text-sm leading-relaxed">
                                                        <MessageResponse>{part.text}</MessageResponse>
                                                    </div>
                                                );
                                            }
                                            // Tool parts are named after the tool, e.g. "tool-getHoldings"
                                            if (part.type.startsWith('tool-')) {
                                                return (
                                                    <Tool key={i} className="w-full">
                                                        <ToolHeader type={part.type} state={part.state} />
                                                        <ToolContent>
                                                            <ToolOutput output={part.output} errorText={part.errorText} />
                                                        </ToolContent>
                                                    </Tool>
                                                );
                                            }
                                            return null;
                                        })}
                                    </div>
                                </div>
                            );
                        })}

                        {/* Show a "thinking" line while waiting for Nova's reply */}
                        {status === 'submitted' && (
                            <div className="flex items-center gap-2.5">
                                <NovaAvatar />
                                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                                    <Spinner />
                                    Nova AI is thinking...
                                </div>
                            </div>
                        )}
                    </ConversationContent>
                    <ConversationScrollButton />
                </Conversation>
            )}

            {/* Input box */}
            <div className="border-t border-border p-3">
                <PromptInput
                    onSubmit={(message, event) => {
                        event.preventDefault();
                        if (message.text) {
                            sendMessage({ text: message.text });
                            setInput('');
                        }
                    }}
                >
                    <PromptInputTextarea
                        ref={inputRef}
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        placeholder="Ask about your portfolio..."
                        disabled={isLoading}
                    />
                    {/* mr-1: InputGroupButton is p-0 and would otherwise sit
                        flush against the input group's right border */}
                    <PromptInputSubmit className="mr-1" disabled={isLoading} />
                </PromptInput>
                <p className="mt-2 text-center text-[11px] text-muted-foreground">
                    Nova can make mistakes and doesn’t give investment advice.
                </p>
            </div>
        </div>
    );
}




