import type { ResearchChart } from "@/app/actions/research";
import { InSampleBadge, railFor } from "./in-sample-badge";

/**
 * A figure carrying everything the picture cannot: which window it was drawn
 * on, how many configurations the plotted result was selected from, and what
 * the axes mean. The caption is stored beside the image rather than written
 * here, so it cannot drift from what was actually plotted.
 *
 * Rendered as a left rail rather than a boxed card — the rail's colour is the
 * data window, which makes the in-sample/out-of-sample split legible while
 * scrolling, before any label is read.
 */
export function ResearchFigure({ chart, index }: { chart: ResearchChart; index: number }) {
  return (
    <figure
      className={`animate-screening-row-in border-l-2 py-1 pl-5 ${railFor(chart.sample_window)}`}
      style={{ animationDelay: `${Math.min(index, 8) * 60}ms` }}
    >
      <figcaption className="mb-3 space-y-1.5">
        <h3 className="text-sm font-medium leading-snug">{chart.title}</h3>
        <InSampleBadge window={chart.sample_window} />
      </figcaption>

      {/* Plain <img>: next/image would need every host whitelisted and would
          re-encode plots whose pixel grid is the point.

          width/height are required, not optional. Without them a lazy image
          collapses to zero height, so it never enters the viewport, so it
          never loads — the figures rendered as a 0px region and the article
          measured 966px tall. They also reserve the box and kill layout
          shift. `h-auto` keeps the aspect ratio once CSS takes over. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={chart.public_url}
        alt={chart.caption}
        width={chart.width ?? undefined}
        height={chart.height ?? undefined}
        className="h-auto w-full rounded-sm bg-white ring-1 ring-border"
        loading="lazy"
      />

      <div className="mt-3 space-y-2">
        <p className="max-w-[68ch] text-sm leading-relaxed text-muted-foreground">
          {chart.caption}
        </p>
        <p className="flex flex-wrap gap-x-4 gap-y-1 font-mono text-[11px] tabular-nums text-muted-foreground/80">
          {chart.campaign_run_id && <span>run {chart.campaign_run_id}</span>}
          {chart.genome_hash && <span>genome {chart.genome_hash.slice(0, 12)}</span>}
          {/* The number that decides how to read any performance figure. */}
          {chart.trials_considered != null && (
            <span className="text-foreground">
              selected from {chart.trials_considered.toLocaleString()} configurations
            </span>
          )}
        </p>
      </div>
    </figure>
  );
}
