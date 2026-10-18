/* Slimmed from the vendored Vercel AI Elements prompt-input (1,176 lines).
   Tradium's AssistantPanel uses only PromptInput, PromptInputTextarea and
   PromptInputSubmit — the provider/attachments/screenshot/menu machinery was
   never wired up, so it's gone. Behavior kept: Enter submits (Shift+Enter
   newline, IME-composition safe), the submit button's disabled state is
   respected, and onSubmit receives ({ text }, event). */
import {
  InputGroup,
  InputGroupButton,
  InputGroupTextarea,
} from "@/components/ui/input-group";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/utils/utils";
import { CornerDownLeftIcon, SquareIcon, XIcon } from "lucide-react";
import { useCallback, useState } from "react";

export const PromptInput = ({ className, onSubmit, children, ...props }) => {
  const handleSubmit = useCallback(
    (event) => {
      event.preventDefault();
      const text = new FormData(event.currentTarget).get("message") || "";
      event.currentTarget.reset();
      onSubmit?.({ text }, event);
    },
    [onSubmit],
  );

  return (
    <form className={cn("w-full", className)} onSubmit={handleSubmit} {...props}>
      <InputGroup className="overflow-hidden">{children}</InputGroup>
    </form>
  );
};

export const PromptInputTextarea = ({
  className,
  placeholder = "What would you like to know?",
  ...props
}) => {
  const [isComposing, setIsComposing] = useState(false);

  const handleKeyDown = useCallback((e) => {
    if (e.key !== "Enter" || e.shiftKey || isComposing || e.nativeEvent.isComposing) {
      return;
    }
    e.preventDefault();
    // respect a disabled submit button instead of submitting anyway
    const submitButton = e.currentTarget.form?.querySelector('button[type="submit"]');
    if (submitButton?.disabled) return;
    e.currentTarget.form?.requestSubmit();
  }, [isComposing]);

  return (
    <InputGroupTextarea
      className={cn("field-sizing-content max-h-48 min-h-16", className)}
      name="message"
      onCompositionEnd={() => setIsComposing(false)}
      onCompositionStart={() => setIsComposing(true)}
      onKeyDown={handleKeyDown}
      placeholder={placeholder}
      {...props}
    />
  );
};

export const PromptInputSubmit = ({
  className,
  variant = "default",
  size = "icon-sm",
  status,
  children,
  ...props
}) => {
  const isGenerating = status === "submitted" || status === "streaming";

  let Icon = <CornerDownLeftIcon className="size-4" />;
  if (status === "submitted") {
    Icon = <Spinner />;
  } else if (status === "streaming") {
    Icon = <SquareIcon className="size-4" />;
  } else if (status === "error") {
    Icon = <XIcon className="size-4" />;
  }

  return (
    <InputGroupButton
      aria-label={isGenerating ? "Stop" : "Submit"}
      className={cn(className)}
      size={size}
      type="submit"
      variant={variant}
      {...props}
    >
      {children ?? Icon}
    </InputGroupButton>
  );
};
