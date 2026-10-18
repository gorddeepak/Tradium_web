"use client";;
import { Badge } from "@/components/ui/badge";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/utils/utils";
import {
  CheckCircleIcon,
  ChevronDownIcon,
  CircleIcon,
  ClockIcon,
  WrenchIcon,
  XCircleIcon,
} from "lucide-react";
import { isValidElement } from "react";

/* Plain <pre> replaces the vendored Shiki CodeBlock: syntax colors on tool
   JSON weren't worth a ~770KB highlighter download. */
const CodeBlock = ({ code }) => (
  <pre className="overflow-x-auto rounded-md bg-muted/50 p-4 text-xs leading-relaxed text-foreground">
    {code}
  </pre>
);

export const Tool = ({
  className,
  ...props
}) => (
  <Collapsible
    className={cn("group not-prose w-full rounded-md border", className)}
    {...props} />
);

const statusLabels = {
  "approval-requested": "Awaiting Approval",
  "approval-responded": "Responded",
  "input-available": "Running",
  "input-streaming": "Pending",
  "output-available": "Completed",
  "output-denied": "Denied",
  "output-error": "Error",
};

const statusIcons = {
  "approval-requested": <ClockIcon className="size-4 text-yellow-600" />,
  "approval-responded": <CheckCircleIcon className="size-4 text-blue-600" />,
  "input-available": <ClockIcon className="size-4 animate-pulse" />,
  "input-streaming": <CircleIcon className="size-4" />,
  "output-available": <CheckCircleIcon className="size-4 text-green-600" />,
  "output-denied": <XCircleIcon className="size-4 text-orange-600" />,
  "output-error": <XCircleIcon className="size-4 text-red-600" />,
};

export const getStatusBadge = (status) => (
  <Badge className="gap-1.5 rounded-full text-xs" variant="secondary">
    {statusIcons[status]}
    {statusLabels[status]}
  </Badge>
);

export const ToolHeader = ({
  className,
  title,
  type,
  state,
  toolName,
  ...props
}) => {
  const derivedName =
    type === "dynamic-tool" ? toolName : type.split("-").slice(1).join("-");

  return (
    <CollapsibleTrigger
      className={cn("flex w-full items-center justify-between gap-4 p-3", className)}
      {...props}>
      <div className="flex items-center gap-2">
        <WrenchIcon className="size-4 text-muted-foreground" />
        <span className="font-medium text-sm">{title ?? derivedName}</span>
        {getStatusBadge(state)}
      </div>
      <ChevronDownIcon
        className="size-4 text-muted-foreground transition-transform group-data-[state=open]:rotate-180" />
    </CollapsibleTrigger>
  );
};

export const ToolContent = ({
  className,
  ...props
}) => (
  <CollapsibleContent
    className={cn(
      "data-[state=closed]:fade-out-0 data-[state=closed]:slide-out-to-top-2 data-[state=open]:slide-in-from-top-2 space-y-4 p-4 text-popover-foreground outline-none data-[state=closed]:animate-out data-[state=open]:animate-in",
      className
    )}
    {...props} />
);

export const ToolInput = ({
  className,
  input,
  ...props
}) => (
  <div className={cn("space-y-2 overflow-hidden", className)} {...props}>
    <h4
      className="font-medium text-muted-foreground text-xs uppercase tracking-wide">
      Parameters
    </h4>
    <div className="rounded-md bg-muted/50">
      <CodeBlock code={JSON.stringify(input, null, 2)} language="json" />
    </div>
  </div>
);

export const ToolOutput = ({
  className,
  output,
  errorText,
  ...props
}) => {
  if (!(output || errorText)) {
    return null;
  }

  // If tool outputs a structured object with a `summary` string, show that first
  const summaryText = output && typeof output === 'object' && typeof output.summary === 'string' ? output.summary : null;
  const displayObject = output && typeof output === 'object' && Object.prototype.hasOwnProperty.call(output, 'data') ? output.data : output;

  let Output = <div>{String(displayObject)}</div>;

  if (typeof displayObject === "object" && !isValidElement(displayObject)) {
    Output = (
      <CodeBlock code={JSON.stringify(displayObject, null, 2)} language="json" />
    );
  } else if (typeof displayObject === "string") {
    Output = <CodeBlock code={displayObject} language="json" />;
  }

  return (
    <div className={cn("space-y-2", className)} {...props}>
      {errorText && (
        <div className="rounded-md bg-destructive/10 p-2 text-xs text-destructive">
          {errorText}
        </div>
      )}
      {summaryText && <p className="text-sm text-foreground">{summaryText}</p>}
      {!errorText && (
        <Collapsible>
          <CollapsibleTrigger
            className="text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline">
            Raw data
          </CollapsibleTrigger>
          <CollapsibleContent
            className="mt-2 overflow-x-auto rounded-md bg-muted/50 text-xs text-foreground [&_table]:w-full">
            {Output}
          </CollapsibleContent>
        </Collapsible>
      )}
    </div>
  );
};


