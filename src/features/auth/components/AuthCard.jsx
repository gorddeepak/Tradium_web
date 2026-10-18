import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from "@/components/ui/card";

export default function AuthCard({ title, subtitle, footer, children }) {
  return (
    <div className="min-h-screen bg-background flex items-center justify-center px-4 py-12 sm:px-6 lg:px-8">
      <div className="w-full max-w-md">
        <Card className="overflow-hidden rounded-[2rem] border border-border bg-surface shadow-lg">
          <CardHeader className="space-y-3 border-b border-border px-8 py-8">
            <CardTitle className="text-3xl font-semibold tracking-tight text-foreground">{title}</CardTitle>
            <CardDescription className="text-sm leading-6 text-muted-foreground">{subtitle}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-6 px-8 py-8">{children}</CardContent>
          {/* gap-1 keeps "New here?" and the link from running together. */}
          {footer ? <CardFooter className="gap-1 border-t border-border px-8 py-6">{footer}</CardFooter> : null}
        </Card>
      </div>
    </div>
  );
}



