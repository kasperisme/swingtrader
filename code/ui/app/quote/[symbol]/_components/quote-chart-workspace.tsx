"use client";

import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";

import { PageTour } from "@/app/protected/_components/page-tour";

function WorkspaceSkeleton() {
  return (
    <div className="flex h-full flex-col gap-3 p-2" aria-hidden>
      <div className="h-8 w-64 animate-pulse rounded-md bg-muted/60" />
      <div className="flex-1 animate-pulse rounded-xl bg-card" />
      <span className="sr-only">Loading chart workspace…</span>
    </div>
  );
}

/**
 * The candlestick workspace is the heaviest thing on the site — the SVG chart,
 * the AI chat and the date picker are several thousand lines between them, and
 * none of it belongs in a public quote page's first paint. Own chunk, no SSR,
 * and only mounted once the reader scrolls to it.
 */
const QuoteChartWorkspaceInner = dynamic(
  () =>
    import("./quote-chart-workspace-inner").then(
      (m) => m.QuoteChartWorkspaceInner,
    ),
  { ssr: false, loading: () => <WorkspaceSkeleton /> },
);

export function QuoteChartWorkspace({ symbol }: { symbol: string }) {
  const hostRef = useRef<HTMLDivElement>(null);
  const [shouldMount, setShouldMount] = useState(false);

  useEffect(() => {
    const el = hostRef.current;
    if (!el || shouldMount) return;
    if (typeof IntersectionObserver === "undefined") {
      setShouldMount(true);
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setShouldMount(true);
          io.disconnect();
        }
      },
      { rootMargin: "400px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [shouldMount]);

  return (
    <>
      {/* The charts tour came here with the workspace. Never auto-starts: this
          is a public page, so it only runs when the help chat fires it. */}
      <PageTour tourKey="charts" autoStart={false} />
      <div ref={hostRef} className="min-h-[520px]">
        {shouldMount ? (
          <QuoteChartWorkspaceInner symbol={symbol} />
        ) : (
          <div className="h-[520px]">
            <WorkspaceSkeleton />
          </div>
        )}
      </div>
    </>
  );
}
