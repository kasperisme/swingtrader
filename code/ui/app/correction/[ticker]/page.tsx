import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ExposureChip } from "@/components/correction/narrative-card";
import {
  fmtDay,
  fmtPct,
  fmtPts,
  fmtUsd,
  getCorrectionDetail,
  GROUP_LABEL,
  GROUP_RULE,
  injectPriceText,
  type NarrativeDetail,
  type NarrativeGroup,
} from "@/lib/drawdown/narrative";
import { SITE_URL } from "@/lib/site";

/** Mirrors services/drawdown/narrative.py: FLUSH_CUT, and the bust cut max(BUST_CUT, g3 / 2). */
const FLUSH_CUT = 0.03;
const BUST_CUT = 0.1;

const TONE: Record<NarrativeGroup, string> = {
  on_top: "border-emerald-500/50 bg-emerald-500/10 text-emerald-500",
  holds: "border-foreground/30 bg-foreground/5 text-foreground",
  fragile: "border-amber-500/50 bg-amber-500/10 text-amber-500",
  drowns: "border-red-500/50 bg-red-500/10 text-red-500",
  not_cash_flow: "border-border text-muted-foreground",
  refused: "border-border text-muted-foreground",
};

function norm(raw: string) {
  return decodeURIComponent(raw || "").trim().toUpperCase().slice(0, 12);
}

export async function generateMetadata({ params }: { params: Promise<{ ticker: string }> }): Promise<Metadata> {
  const ticker = norm((await params).ticker);
  const d = await getCorrectionDetail(ticker);
  const name = d?.row.company ?? ticker;
  const title = d
    ? `${ticker} in the correction: ${GROUP_LABEL[d.row.group].toLowerCase()} — ${name}`
    : `${ticker} correction stress test`;
  const description = d?.row.thesis ?? `Whether ${name}'s priced-in narrative survives the correction.`;
  return {
    title,
    description: description.slice(0, 300),
    alternates: { canonical: `${SITE_URL}/correction/${ticker}` },
    robots: d ? { index: true, follow: true } : { index: false, follow: true },
  };
}

/**
 * How big a cut to analysts' 3-year growth the price can take, drawn against
 * the two cuts the test applies. The scale runs from the shortfall end to a
 * little past whichever is larger, the bust cut or the breakeven.
 */
function StressGauge({ row }: { row: NarrativeDetail }) {
  const be = row.breakevenCut;
  const g3 = row.consensus3y;
  if (be == null || g3 == null) return null;
  const bust = Math.max(BUST_CUT, g3 / 2);
  const lo = Math.min(-0.1, be - 0.05);
  const hi = Math.max(bust, be) + 0.08;
  const pos = (v: number) => `${(((Math.max(lo, Math.min(hi, v)) - lo) / (hi - lo)) * 100).toFixed(2)}%`;
  const ok = be >= 0;
  return (
    <figure className="mt-6" aria-label={`Can absorb a ${fmtPts(be)} cut to analyst growth; a correction-sized cut is 3 points and a bust-sized cut is ${fmtPts(bust)}`}>
      <div className="relative h-10">
        <div className="absolute inset-x-0 top-4 h-2 rounded-full bg-border" />
        <div
          className={`absolute top-4 h-2 rounded-full ${ok ? "bg-emerald-500/70" : "bg-red-500/70"}`}
          style={ok ? { left: pos(0), width: `calc(${pos(be)} - ${pos(0)})` } : { left: pos(be), width: `calc(${pos(0)} - ${pos(be)})` }}
        />
        {[
          { v: 0, label: "today's forecast" },
          { v: FLUSH_CUT, label: "correction cut" },
          { v: bust, label: "bust cut" },
        ].map((m) => (
          <div key={m.label} className="absolute top-2 h-6 w-px bg-foreground/50" style={{ left: pos(m.v) }} />
        ))}
        <div
          className={`absolute top-1.5 h-7 w-1.5 -translate-x-1/2 rounded-full ${ok ? "bg-emerald-500" : "bg-red-500"}`}
          style={{ left: pos(be) }}
        />
      </div>
      <div className="relative mt-1 h-10 text-[11px] leading-4 text-muted-foreground">
        <span className="absolute -translate-x-1/2 whitespace-nowrap" style={{ left: pos(0) }}>
          0pt
          <br />
          forecast today
        </span>
        <span className="absolute -translate-x-1/2 whitespace-nowrap" style={{ left: pos(bust) }}>
          {fmtPts(bust)}
          <br />
          bust cut
        </span>
      </div>
      <figcaption className="mt-2 text-xs text-muted-foreground">
        The marker is where the story breaks: {ok ? `analysts can cut 3-year growth by ${fmtPts(be)} before the price is no longer paid for` : `the price is already ${fmtPts(-be)} short of today's forecast`}. A correction-sized cut is 3 points; a bust-sized cut for this name is {fmtPts(bust)}.
      </figcaption>
    </figure>
  );
}

function Stat({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="bg-background p-4">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-1 text-xl font-semibold tabular-nums">{value}</dd>
      {note && <p className="mt-1 text-[11px] leading-4 text-muted-foreground">{note}</p>}
    </div>
  );
}

export default async function CorrectionTickerPage({ params }: { params: Promise<{ ticker: string }> }) {
  const ticker = norm((await params).ticker);
  const d = await getCorrectionDetail(ticker);
  if (!d) notFound();
  const { run, row } = d;
  const short = (row.breakevenCut ?? 0) < 0;
  const breaks = (row.breaksIf ?? "").replace(/^already short; it holds only if /, "");
  const valued = row.requiredCagr != null;

  return (
    <main className="mx-auto max-w-4xl px-4 py-10 sm:px-6 md:py-14">
      <nav className="text-xs text-muted-foreground" aria-label="Breadcrumb">
        <Link href="/correction" className="hover:text-foreground">
          Correction stress test
        </Link>{" "}
        / <span className="text-foreground">{ticker}</span>
      </nav>

      <header className="mt-4 flex flex-wrap items-end gap-x-4 gap-y-2">
        <h1 className="font-mono text-4xl font-bold tracking-tight">{ticker}</h1>
        <p className="pb-1 text-sm text-muted-foreground">{[row.company, row.sector].filter(Boolean).join(" · ")}</p>
      </header>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <span className={`rounded-full border px-3 py-1 text-sm font-semibold ${TONE[row.group]}`}>{GROUP_LABEL[row.group]}</span>
        <ExposureChip exposure={row.exposure} />
        <span className="text-xs text-muted-foreground">
          {fmtUsd(row.price)} at the {fmtDay(row.closeDate)} close · scored {fmtDay(run.asOf)}
        </span>
      </div>
      <p className="mt-3 max-w-2xl text-sm text-muted-foreground">{GROUP_RULE[row.group]}</p>

      {valued ? (
        <section className="mt-8 rounded-3xl border border-border bg-card/40 p-6" aria-labelledby="thesis-heading">
          <h2 id="thesis-heading" className="text-xs font-semibold uppercase tracking-widest text-amber-500">
            {short ? "Why it drowns" : "Why it holds"}
          </h2>
          <p className="mt-3 text-lg leading-8">{row.thesis}</p>
          {breaks && (
            <p className="mt-4 text-sm">
              <span className={`font-semibold ${short ? "text-red-500" : "text-amber-500"}`}>
                {short ? "Would recover if: " : "Breaks if: "}
              </span>
              {breaks}. We re-check this against analyst estimates every evening.
            </p>
          )}
          <StressGauge row={row} />
        </section>
      ) : (
        <p className="mt-8 rounded-2xl border border-border p-6 text-sm text-muted-foreground">{row.reason}</p>
      )}

      {valued && (
        <dl className="mt-8 grid grid-cols-2 gap-px overflow-hidden rounded-2xl border border-border bg-border sm:grid-cols-3">
          <Stat label="Growth the price needs" value={`${fmtPct(row.requiredCagr)}/yr`} note={`10 years, at a ${fmtPct(row.marginUsed, 0).replace("+", "")} margin analysts expect`} />
          <Stat label="Analyst forecast, next 3 years" value={`${fmtPct(row.consensus3y)}/yr`} note={`${fmtPct(row.supportedCagr)}/yr over 10 years once faded to terminal growth`} />
          <Stat label={short ? "Shortfall" : "Cut it can absorb"} value={fmtPts(row.breakevenCut)} note="points off 3-year analyst growth" />
          <Stat label="From recent peak" value={fmtPct(row.drawdownFromPeak)} />
          <Stat
            label="To median analyst target"
            value={fmtPct(row.upsideToMedian, 0)}
            note={row.nTargets ? `${row.nTargets} published targets${row.targetsPredateDrop ? ", set before the drop" : ""}` : undefined}
          />
          <Stat label="Beta" value={row.beta == null ? "—" : row.beta.toFixed(2)} note={row.epicenter ? "Part of the AI epicenter" : row.linkedWith.length ? `Linked to ${row.linkedWith.join(", ")}` : undefined} />
        </dl>
      )}

      {row.flags.length > 0 && (
        <section className="mt-8" aria-labelledby="flags-heading">
          <h2 id="flags-heading" className="text-sm font-semibold">Read with care</h2>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-muted-foreground">
            {row.flags.map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
        </section>
      )}

      {(row.position || row.paysFor.length > 0 || row.crux) && (
        <section className="mt-10 border-t border-border pt-8" aria-labelledby="story-heading">
          <h2 id="story-heading" className="text-lg font-semibold">The narrative the price carries</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            From the priced-in reconstruction of {fmtDay(row.modelAsOf)}. Its figures use that day&apos;s price and
            free-cash-flow margin, so they can differ from the stress test above.
          </p>
          {row.position && <p className="mt-4 leading-7">{injectPriceText(row.position, null)}</p>}
          {row.paysFor.length > 0 && (
            <>
              <h3 className="mt-6 text-sm font-semibold">What the price pays for</h3>
              <ul className="mt-2 list-disc space-y-2 pl-5 text-sm leading-6 text-foreground/90">
                {row.paysFor.map((p) => (
                  <li key={p}>{injectPriceText(p, null)}</li>
                ))}
              </ul>
            </>
          )}
          {row.crux && (
            <>
              <h3 className="mt-6 text-sm font-semibold">The question that settles it</h3>
              <p className="mt-2 text-sm leading-6 text-foreground/90">{injectPriceText(row.crux, null)}</p>
            </>
          )}
          <Link href={`/quote/${ticker}`} className="mt-6 inline-flex text-sm font-medium text-amber-500 hover:underline">
            What the price refuses to pay for, and the full reconstruction, on the {ticker} quote page →
          </Link>
        </section>
      )}

      <p className="mt-12 border-t border-border pt-6 text-xs leading-5 text-muted-foreground">
        A stress test of whether this narrative is still paid for by analyst forecasts, not a forecast that the stock
        will rise. The price-implied growth on its own has not predicted returns in our testing, and this list
        (sealed {fmtDay(run.asOf)}) has not been graded yet. Cut sizes are assumptions. Not investment advice.{" "}
        <Link href="/correction" className="text-amber-500 hover:underline">
          Back to all names
        </Link>
      </p>
    </main>
  );
}
