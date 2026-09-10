/**
 * Route-level loading shapes.
 *
 * These exist for `loading.tsx`, and `loading.tsx` exists for two reasons that
 * are easy to conflate:
 *
 *   1. **Feedback.** Without a boundary the App Router has nothing to render
 *      until the destination's server components resolve, so a click leaves the
 *      reader on the OLD page — measured at 0.7–2.8s warm and up to 15s cold on
 *      these routes. The navigation looks broken rather than slow.
 *   2. **Prefetching.** For a DYNAMIC route, `<Link>` prefetches "the partial
 *      route down to the nearest segment with a loading.js boundary". Every page
 *      here reads Supabase per request, so with no boundary anywhere there was
 *      nothing for a prefetch to fetch — which is why hovering a link bought
 *      nothing at all.
 *
 * They deliberately do NOT try to be pixel-accurate previews of the page. A
 * skeleton that mimics the final layout too closely reads as a broken render
 * when the real content lands in a different shape; these are coarse, calm, and
 * obviously provisional. Match the page's ROUGH rhythm — masthead, then rows —
 * and no more.
 *
 * `aria-hidden` throughout: a screen reader should hear the real content when it
 * arrives, not a description of grey boxes. Next announces the route change.
 */

function Bar({ className = "" }: { className?: string }) {
  return <div className={`rounded bg-muted ${className}`} />;
}

/** Masthead: an eyebrow, a title, a standfirst. The top of nearly every page. */
export function SkeletonMasthead({ wide = false }: { wide?: boolean }) {
  return (
    <div className="space-y-4" aria-hidden>
      <Bar className="h-3 w-32" />
      <Bar className={`h-10 ${wide ? "w-3/4" : "w-2/3"} max-w-[24ch]`} />
      <Bar className="h-4 w-full max-w-[52ch]" />
    </div>
  );
}

/** A stack of equal rows — tables, leaderboards, feeds. */
export function SkeletonRows({ n = 6, h = "h-14" }: { n?: number; h?: string }) {
  return (
    <div className="grid gap-px bg-border" aria-hidden>
      {Array.from({ length: n }, (_, i) => (
        <div key={i} className={`${h} bg-background`} />
      ))}
    </div>
  );
}

/** A card grid — galleries, directories, indexes. */
export function SkeletonCards({
  n = 6,
  h = "h-44",
  cols = "sm:grid-cols-2 lg:grid-cols-3",
}: {
  n?: number;
  h?: string;
  cols?: string;
}) {
  return (
    <div className={`grid grid-cols-1 gap-4 ${cols}`} aria-hidden>
      {Array.from({ length: n }, (_, i) => (
        <div key={i} className={`${h} rounded-xl border border-border/70 bg-muted/40`} />
      ))}
    </div>
  );
}

/** Body copy — articles, docs, research write-ups. */
export function SkeletonProse({ n = 8 }: { n?: number }) {
  const widths = ["w-full", "w-11/12", "w-full", "w-10/12", "w-full", "w-9/12"];
  return (
    <div className="space-y-3" aria-hidden>
      {Array.from({ length: n }, (_, i) => (
        <Bar key={i} className={`h-4 ${widths[i % widths.length]} max-w-[62ch]`} />
      ))}
    </div>
  );
}

/**
 * The wrapper every `loading.tsx` uses.
 *
 * One `animate-pulse` on the container rather than one per element: separate
 * animations drift out of phase within a second or two and the page starts to
 * shimmer, which reads as activity rather than as waiting.
 */
export function PageSkeleton({
  children,
  className = "mx-auto max-w-5xl px-4 py-10 sm:py-14",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <main className={`animate-pulse ${className}`} aria-busy="true" aria-hidden>
      {children}
    </main>
  );
}
