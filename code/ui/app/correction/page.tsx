import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { fmtDay, getCorrectionBoard, GROUP_LABEL, GROUP_RULE, type NarrativeGroup } from "@/lib/drawdown/narrative";
import { SITE_URL } from "@/lib/site";
import { CorrectionBoard } from "./_components/correction-board";

export const metadata: Metadata = {
  title: "Correction Stress Test — whose priced-in story survives the drop",
  description:
    "For every stock with a priced-in reconstruction: the growth its share price now requires, what analysts forecast, and how big a cut to that forecast it can absorb before the story is no longer paid for.",
  alternates: { canonical: `${SITE_URL}/correction` },
};

const SUMMARY: NarrativeGroup[] = ["on_top", "holds", "fragile", "drowns", "not_cash_flow"];
const TONE: Partial<Record<NarrativeGroup, string>> = {
  on_top: "text-emerald-500",
  fragile: "text-amber-500",
  drowns: "text-red-500",
};

async function Board() {
  const board = await getCorrectionBoard();
  if (!board) {
    return (
      <p className="mt-10 text-sm text-muted-foreground">
        The stress test has not completed a run yet. It updates after each evening&apos;s estimate snapshot.
      </p>
    );
  }
  const { run, rows } = board;
  return (
    <>
      <p className="mt-2 text-xs text-muted-foreground">
        Prices as of {fmtDay(rows.find((r) => r.closeDate)?.closeDate ?? run.asOf)} · analyst consensus snapshot{" "}
        {fmtDay(run.estimateSnapshot)} · {run.universe.toLocaleString("en-US")} names with a priced-in reconstruction
      </p>
      <dl className="mt-8 grid grid-cols-2 gap-px overflow-hidden rounded-2xl border border-border bg-border sm:grid-cols-5">
        {SUMMARY.map((g) => (
          <div key={g} className="bg-background p-4">
            <dt className="text-xs text-muted-foreground">{GROUP_LABEL[g]}</dt>
            <dd className={`mt-1 text-2xl font-semibold tabular-nums ${TONE[g] ?? ""}`}>
              {(run.groups[g] ?? 0).toLocaleString("en-US")}
            </dd>
          </div>
        ))}
      </dl>
      <div className="mt-10">
        <CorrectionBoard rows={rows.filter((r) => r.group !== "not_cash_flow" && r.group !== "refused")} />
      </div>
      <p className="mt-10 font-mono text-[11px] text-muted-foreground">
        Sealed {fmtDay(run.asOf)} · sha256 {run.sealSha256.slice(0, 16)}…
      </p>
    </>
  );
}

export default function CorrectionPage() {
  return (
    <main className="mx-auto max-w-6xl px-4 py-12 sm:px-6 md:py-16 lg:px-8">
      <p className="text-xs font-semibold uppercase tracking-widest text-amber-500">Correction stress test</p>
      <h1 className="mt-3 max-w-3xl text-balance text-3xl font-bold tracking-tight sm:text-4xl">
        Whose priced-in story survives the correction?
      </h1>
      <p className="mt-4 max-w-3xl text-base leading-7 text-muted-foreground">
        Every share price is a bet on growth. For each stock we take the growth its price now requires — a ten-year
        reverse DCF at the latest close — and set it against what analysts forecast for the next three years. Then we
        ask how far those forecasts can be cut before the price is paying for growth nobody expects. A correction is
        exactly when forecasts get cut.
      </p>

      <Suspense fallback={<div className="mt-10 h-96 animate-pulse rounded-2xl bg-card/40" />}>
        <Board />
      </Suspense>

      <section className="mt-16 max-w-3xl border-t border-border pt-10" aria-labelledby="method-heading">
        <h2 id="method-heading" className="text-lg font-semibold">How to read it — and what it is not</h2>
        <ul className="mt-4 space-y-3 text-sm leading-6 text-muted-foreground">
          {(["on_top", "holds", "fragile", "drowns"] as NarrativeGroup[]).map((g) => (
            <li key={g}>
              <b className={`font-semibold ${TONE[g] ?? "text-foreground"}`}>{GROUP_LABEL[g]}.</b> {GROUP_RULE[g]}
            </li>
          ))}
          <li>
            <b className="font-semibold text-foreground">Exposure</b> is a separate axis: a stock that is part of the AI
            epicenter, or linked to it as a supplier, customer or partner and volatile, will fall with it while the
            correction runs, even if its story holds.
          </li>
          <li>
            <b className="font-semibold text-foreground">This is not a forecast that a stock will rise.</b> Our own test
            of the price-implied growth on its own found it does not predict returns. The groups describe whether a
            narrative is still paid for by analyst forecasts. Each day&apos;s list is sealed with a hash so it can be
            graded against what happens next; it has not been graded yet.
          </li>
          <li>
            The cut sizes are stated assumptions, not values fitted to history. Analyst targets set before the drop make
            &ldquo;distance to median target&rdquo; look larger than analysts would say today.
          </li>
          <li>
            The reconstructions themselves are on each company&apos;s{" "}
            <Link href="/quote/NVDA" className="text-amber-500 hover:underline">
              quote page
            </Link>
            . Not investment advice.
          </li>
        </ul>
      </section>
    </main>
  );
}
