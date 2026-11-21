import Link from "next/link";
import { NarrativeCard } from "@/components/correction/narrative-card";
import { fmtDay, getCorrectionBoard, topAndDrowning } from "@/lib/drawdown/narrative";

/**
 * The correction stress test, leading the landing page while a drawdown is on.
 *
 * Three names that come out on top and three that drown, each with its thesis
 * and the level that breaks it; everything else is on /correction. Renders
 * nothing if no complete run exists, so the page never carries an empty board.
 *
 * Framed as a test throughout: the groups say whether a price's narrative is
 * still funded by analyst forecasts, not which stocks will go up, and they have
 * not been graded.
 */
export async function CorrectionStressTestSection() {
  const board = await getCorrectionBoard();
  if (!board) return null;
  const { run, rows } = board;
  const { top, drowning } = topAndDrowning(rows, 3);
  if (!top.length && !drowning.length) return null;
  const g = run.groups;
  const valued = (g.on_top ?? 0) + (g.holds ?? 0) + (g.fragile ?? 0) + (g.drowns ?? 0);

  return (
    <section
      id="correction"
      aria-labelledby="correction-heading"
      className="relative border-b border-border bg-gradient-to-b from-amber-500/[0.04] to-transparent py-10 md:py-14"
    >
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        <div className="flex flex-wrap items-center gap-3">
          <p className="text-xs font-semibold uppercase tracking-widest text-amber-500">Correction stress test</p>
          <span className="inline-flex items-center rounded-full border border-border px-2.5 py-0.5 font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
            Updated {fmtDay(run.asOf)}
          </span>
        </div>

        <h2 id="correction-heading" className="mt-3 max-w-3xl text-balance text-2xl font-bold tracking-tight sm:text-3xl">
          The market just dropped. Whose story is still paid for?
        </h2>
        <p className="mt-3 max-w-3xl text-sm leading-6 text-muted-foreground">
          For {valued.toLocaleString("en-US")} stocks we compared the growth each share price now requires with what
          analysts forecast, then cut those forecasts the way a correction does.{" "}
          <b className="font-semibold text-emerald-500">{g.on_top ?? 0}</b> come out on top: the story survives even a
          bust-sized cut. <b className="font-semibold text-red-500">{g.drowns ?? 0}</b> drown: the price already needs
          more growth than analysts expect.
        </p>

        <div className="mt-8 grid gap-8 lg:grid-cols-2">
          <div>
            <h3 className="mb-3 text-sm font-semibold text-emerald-500">Comes out on top</h3>
            <div className="grid gap-3">
              {top.map((r) => (
                <NarrativeCard key={r.ticker} row={r} compact />
              ))}
            </div>
          </div>
          <div>
            <h3 className="mb-3 text-sm font-semibold text-red-500">Drowns</h3>
            <div className="grid gap-3">
              {drowning.map((r) => (
                <NarrativeCard key={r.ticker} row={r} compact />
              ))}
            </div>
          </div>
        </div>

        <div className="mt-8 flex flex-wrap items-center gap-x-6 gap-y-3">
          <Link
            href="/correction"
            className="inline-flex items-center gap-1.5 text-sm font-medium text-amber-400 hover:underline"
          >
            See all {valued.toLocaleString("en-US")} names, filter by exposure →
          </Link>
          <p className="max-w-xl text-xs text-muted-foreground">
            A stress test of whether each narrative is funded — not a forecast that a stock will rise. The list was
            sealed on {fmtDay(run.asOf)} and has not been graded yet. Not investment advice.
          </p>
        </div>
      </div>
    </section>
  );
}
