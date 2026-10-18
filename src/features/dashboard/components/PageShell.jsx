import { PageSkeleton } from "@/utils/tradiumUtils";

/* Shared page shell: PageSkeleton while loading, body in the centered container. */
export function PageShell({ loading, children }) {
  if (loading) return <PageSkeleton />;
  return <main className="mx-auto max-w-[1440px] px-6 py-8">{children}</main>;
}
