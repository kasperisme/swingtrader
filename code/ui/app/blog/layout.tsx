import Link from "next/link";
import { Suspense } from "react";

export default function BlogLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <Suspense
        fallback={
          <div className="mx-auto max-w-4xl px-6 py-14 text-sm text-muted-foreground animate-pulse">
            Loading blog...
          </div>
        }
      >
        {children}
      </Suspense>
    </div>
  );
}
