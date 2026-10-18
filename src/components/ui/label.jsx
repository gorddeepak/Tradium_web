import * as React from "react";

import { cn } from "@/utils/utils";

const Label = React.forwardRef(({ className, htmlFor, ...props }, ref) => (
  <label
    ref={ref}
    htmlFor={htmlFor}
    className={cn("block text-sm font-medium text-foreground", className)}
    {...props}
  />
));

Label.displayName = "Label";

export { Label };


