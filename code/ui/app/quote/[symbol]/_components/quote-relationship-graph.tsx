"use client";

import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";

import { PageTour } from "@/app/protected/_components/page-tour";

function GraphSkeleton() {
  return (
    <div className="flex h-full flex-col gap-2 p-2" aria-hidden>
      <div className="h-6 w-2/3 animate-pulse rounded bg-muted/40" />
      <div className="flex-1 animate-pulse rounded-xl bg-card" />
      <span className="sr-only">Loading relationship graph…</span>
    </div>
  );
}

/**
 * The explorer pulls in d3 and the full details drawer — far too much to ship
 * in the quote page's first paint, which is a public SEO surface. Split it into
 * its own chunk and keep it out of SSR entirely; the graph is interactive-only
 * and contributes nothing to the crawled HTML.
 */
const RelationshipNetworkExplorer = dynamic(
  () =>
    import(
      "@/components/relationship-network/relationship-network-explorer"
    ).then((m) => m.RelationshipNetworkExplorer),
  { ssr: false, loading: () => <GraphSkeleton /> },
);

/**
 * The relationship graph, seeded and locked on the quote's own ticker.
 *
 * This replaces /protected/relations. There the graph opened on AAPL and you
 * searched your way to a company; here the company is already the subject of
 * the page, so the seed controls are hidden and the graph is simply *about*
 * this ticker — which is how it was nearly always used anyway.
 *
 * Mounted on first scroll into view rather than on page load: the chunk is
 * large and the neighbourhood query is a round-trip, and neither should be
 * spent on visitors who never reach this far down.
 */
export function QuoteRelationshipGraph({ symbol }: { symbol: string }) {
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
      // Start loading a little before it is actually on screen, so the graph is
      // usually ready by the time the user gets to it.
      { rootMargin: "400px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [shouldMount]);

  return (
    <>
      {/* The relations tour moved here with the graph. Never auto-starts: this
          is a public page, so it only runs when the help chat fires it. */}
      <PageTour tourKey="relations" autoStart={false} />
      <div
        ref={hostRef}
        className="h-[560px] overflow-hidden rounded-xl border border-border bg-card"
      >
        {shouldMount ? (
          <RelationshipNetworkExplorer
            key={symbol}
            vectors={[]}
            initialSeedTicker={symbol}
            hideSeedControls
            fillViewport
          />
        ) : (
          <GraphSkeleton />
        )}
      </div>
    </>
  );
}
