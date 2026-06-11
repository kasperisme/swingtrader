import Link from "next/link";
import { ArrowRight, Mail } from "lucide-react";

/**
 * Top-of-page banner promoting the free personal news-briefing service.
 * The whole banner links to /briefings. Server component — no client JS.
 *
 * Placed as the first element on /articles and /articles/[slug] so the briefing
 * CTA is the first thing a visitor notices.
 */
export function BriefingBanner() {
  return (
    <Link
      href="/briefings"
      className="group flex flex-col gap-3 rounded-xl border border-amber-500/30 bg-gradient-to-r from-amber-500/[0.10] via-amber-500/[0.05] to-transparent p-4 transition-colors hover:border-amber-400/60 sm:flex-row sm:items-center sm:justify-between sm:gap-4 sm:p-5"
    >
      <div className="flex items-start gap-3 sm:items-center">
        <span className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-amber-500/30 bg-amber-500/10">
          <Mail className="h-5 w-5 text-amber-400" />
        </span>
        <div className="min-w-0">
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-amber-500">
            Free · No account
          </p>
          <p className="mt-0.5 text-base font-semibold leading-tight">
            Create your own personal news briefing
          </p>
          <p className="mt-0.5 text-sm leading-relaxed text-muted-foreground">
            A daily PDF of the news that moves your tickers — summaries and market
            impact, delivered an hour before the open.
          </p>
        </div>
      </div>
      <span className="inline-flex shrink-0 items-center justify-center gap-1.5 self-start rounded-lg bg-amber-500 px-4 py-2 text-sm font-semibold text-black transition-colors group-hover:bg-amber-400 sm:self-auto">
        Create my briefing
        <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
      </span>
    </Link>
  );
}
