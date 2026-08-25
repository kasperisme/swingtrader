import { Suspense } from "react";
import Link from "next/link";
import type { Metadata } from "next";
import { ArrowUpRight } from "lucide-react";
import {
  getResearchStats,
  listLeaderboard,
  listResearchNotes,
} from "@/app/actions/research";
import { SITE_URL } from "@/lib/site";

const SITE = SITE_URL;

export const metadata: Metadata = {
  title: "Research",
  description:
    "An autonomous quant research lab, published in full — including the results that failed. Every strategy carries the number of configurations it was selected from, so you can replicate it.",
  alternates: { canonical: `${SITE}/research` },
};

const KIND_LABEL: Record<string, string> = {
  negative: "Refuted",
  positive: "Result",
  replication: "Replication",
  method: "Method",
};

/** Refuted results are the majority here and get the honest, quiet treatment. */
const KIND_TONE: Record<string, string> = {
  negative: "text-muted-foreground",
  positive: "text-emerald-600 dark:text-emerald-500",
  replication: "text-amber-600 dark:text-amber-500",
  method: "text-muted-foreground",
};

function fmtDate(iso: string) {
  return new Date(iso).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

function fmt(n: number | null, digits = 2) {
  return n == null ? "—" : n.toFixed(digits);
}

/* ------------------------------------------------------------------ */

function Rows({ n = 3 }: { n?: number }) {
  return (
    <div className="grid gap-px bg-border" aria-hidden>
      {Array.from({ length: n }, (_, i) => (
        <div key={i} className="h-24 animate-pulse bg-background" />
      ))}
    </div>
  );
}

async function Stats() {
  const s = await getResearchStats();
  // Zero-valued stats are omitted rather than printed. "0 configurations
  // searched" reads as "no search has happened", when what it actually means
  // is that none of the search has been published yet — the opposite claim.
  const items = ([
    ["write-ups", s.notes],
    ["figures", s.figures],
    ["strategies", s.strategies],
    ["configurations searched", s.configurations],
  ] as const).filter(([, value]) => value > 0);

  if (items.length === 0) return null;

  return (
    <dl className="flex flex-wrap gap-x-8 gap-y-3 font-mono text-xs tabular-nums text-muted-foreground">
      {items.map(([label, value]) => (
        <div key={label} className="flex items-baseline gap-1.5">
          <dt className="sr-only">{label}</dt>
          <dd className="text-base font-medium text-foreground">
            {value.toLocaleString()}
          </dd>
          <span className="uppercase tracking-widest">{label}</span>
        </div>
      ))}
    </dl>
  );
}

async function WriteUps() {
  const notes = await listResearchNotes();

  if (notes.length === 0) {
    return (
      <div className="border-l-2 border-l-border py-6 pl-5">
        <p className="text-sm font-medium">Nothing published yet</p>
        <p className="mt-1.5 max-w-[60ch] text-sm leading-relaxed text-muted-foreground">
          A result appears here once it has been replicated — not when it is
          first observed. Most candidates do not survive that step, which is the
          point of having it.
        </p>
      </div>
    );
  }

  return (
    <ul className="grid gap-2">
      {notes.map((n, i) => (
        <li
          key={n.slug}
          className="animate-screening-row-in"
          style={{ animationDelay: `${Math.min(i, 12) * 40}ms` }}
        >
          <Link
            href={`/research/${n.slug}`}
            className="group block border-l-2 border-l-border py-4 pl-5 transition-colors hover:border-l-amber-500 hover:bg-muted/50 focus-visible:border-l-amber-500 focus-visible:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500/60"
          >
            <div className="flex items-baseline gap-3 font-mono text-[11px] uppercase tracking-widest">
              <span className={KIND_TONE[n.result_kind] ?? "text-muted-foreground"}>
                {KIND_LABEL[n.result_kind] ?? n.result_kind}
              </span>
              <span className="tabular-nums text-muted-foreground/70">
                {fmtDate(n.updated_at)}
              </span>
            </div>
            <h3 className="mt-2 flex items-start gap-1.5 text-lg font-semibold leading-snug tracking-tight transition-colors group-hover:text-amber-600 dark:group-hover:text-amber-500 sm:text-xl">
              {n.title}
              <ArrowUpRight
                className="mt-1 h-4 w-4 shrink-0 opacity-0 transition-opacity group-hover:opacity-100"
                aria-hidden
              />
            </h3>
            {n.summary && (
              <p className="mt-1.5 line-clamp-2 max-w-[68ch] text-sm leading-relaxed text-muted-foreground">
                {n.summary}
              </p>
            )}
          </Link>
        </li>
      ))}
    </ul>
  );
}

async function Leaderboard() {
  const rows = await listLeaderboard(25);

  if (rows.length === 0) {
    return (
      <div className="border-l-2 border-l-border py-6 pl-5">
        <p className="text-sm font-medium">No strategy published yet</p>
        <p className="mt-1.5 max-w-[60ch] text-sm leading-relaxed text-muted-foreground">
          A configuration is listed here once it has been measured on data the
          search never touched. Until then its in-sample Sharpe says only that
          the optimiser did its job.
        </p>
      </div>
    );
  }

  return (
    <div className="-mx-4 overflow-x-auto px-4">
      <table className="w-full min-w-[640px] border-collapse text-sm">
        <caption className="sr-only">
          Strategies ranked by out-of-sample Sharpe ratio
        </caption>
        <thead>
          <tr className="border-b text-left font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
            <th scope="col" className="pb-2 pr-4 font-normal">Genome</th>
            <th scope="col" className="pb-2 pr-4 font-normal">Run</th>
            <th scope="col" className="pb-2 pr-4 text-right font-normal">Sharpe in-sample</th>
            <th scope="col" className="pb-2 pr-4 text-right font-normal">Sharpe unseen</th>
            <th scope="col" className="pb-2 pr-4 text-right font-normal">Trials</th>
            <th scope="col" className="pb-2 text-right font-normal">DSR</th>
          </tr>
        </thead>
        <tbody className="font-mono tabular-nums">
          {rows.map((r, i) => (
            <tr
              key={`${r.campaign_run_id}-${r.genome_hash}`}
              className="animate-screening-row-in border-b border-border/60 transition-colors hover:bg-muted/50"
              style={{ animationDelay: `${Math.min(i, 12) * 30}ms` }}
            >
              <td className="py-2.5 pr-4 text-xs">{r.genome_hash.slice(0, 10)}</td>
              <td className="py-2.5 pr-4 text-xs text-muted-foreground">
                {r.campaign_run_id}
              </td>
              <td className="py-2.5 pr-4 text-right text-muted-foreground">
                {fmt(r.dev_sharpe)}
              </td>
              {/* The only column that means anything on its own. */}
              <td className="py-2.5 pr-4 text-right font-medium">
                {r.holdout_sharpe == null ? (
                  <span className="text-xs uppercase tracking-wide text-muted-foreground/70">
                    untested
                  </span>
                ) : (
                  fmt(r.holdout_sharpe)
                )}
              </td>
              <td className="py-2.5 pr-4 text-right text-muted-foreground">
                {r.trials_considered.toLocaleString()}
              </td>
              <td className="py-2.5 text-right text-muted-foreground">
                {/* -1 is the backfill sentinel: never computed, which is not the
                    same as computed and bad. */}
                {r.deflated_sharpe < 0 ? (
                  <span className="text-xs uppercase tracking-wide text-muted-foreground/70">
                    n/c
                  </span>
                ) : (
                  fmt(r.deflated_sharpe)
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ------------------------------------------------------------------ */

export default function ResearchPage() {
  return (
    <main className="min-h-[100dvh] px-4 py-14 sm:py-20">
      <div className="mx-auto w-full max-w-4xl">
        {/* Asymmetric header: the lede sits offset under a wide display line
            rather than centred, so the page reads as a notebook, not a pitch. */}
        <header className="mb-14">
          <p className="flex items-center gap-2.5 font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
            <span className="h-px w-8 bg-amber-500" aria-hidden />
            Autonomous research lab
          </p>
          <h1 className="mt-5 max-w-[14ch] text-4xl font-bold leading-[0.95] tracking-tighter sm:text-6xl">
            Research, with the misses left in
          </h1>
          <div className="mt-7 grid gap-8 sm:grid-cols-[1fr_auto] sm:items-end">
            <p className="max-w-[58ch] text-base leading-relaxed text-muted-foreground">
              A search process runs continuously over trading strategies. What it
              finds is published here with the working, the data window and the
              exact configuration — so anyone can re-run it and disagree.
            </p>
          </div>
          <div className="mt-8 border-t pt-5">
            <Suspense
              fallback={<div className="h-6 w-72 animate-pulse rounded bg-muted" />}
            >
              <Stats />
            </Suspense>
          </div>
        </header>

        {/* Stated once, before the first number appears anywhere below it. */}
        <section className="mb-14 border-l-2 border-l-amber-500 py-1 pl-5">
          <h2 className="font-mono text-[11px] uppercase tracking-widest text-amber-600 dark:text-amber-500">
            How to read anything here
          </h2>
          <p className="mt-3 max-w-[68ch] text-sm leading-relaxed text-muted-foreground">
            A backtest is only meaningful next to the number of configurations it
            was chosen from. Search hard enough and a good-looking strategy always
            appears on the data you searched over. In this lab a search that
            looked{" "}
            <span className="font-mono tabular-nums text-foreground">5.5×</span>{" "}
            better than its starting point in-sample was worth{" "}
            <span className="font-mono tabular-nums text-foreground">+0.03</span>{" "}
            Sharpe on data it had never seen. Every figure below carries its trial
            count and its deflated Sharpe for that reason, and most published
            results are negative.
          </p>
        </section>

        <section aria-labelledby="writeups" className="mb-14">
          <h2
            id="writeups"
            className="mb-5 font-mono text-[11px] uppercase tracking-widest text-muted-foreground"
          >
            Write-ups
          </h2>
          <Suspense fallback={<Rows n={3} />}>
            <WriteUps />
          </Suspense>
        </section>

        <section aria-labelledby="leaderboard">
          <h2
            id="leaderboard"
            className="mb-2 font-mono text-[11px] uppercase tracking-widest text-muted-foreground"
          >
            Strategies
          </h2>
          <p className="mb-5 max-w-[68ch] text-sm leading-relaxed text-muted-foreground">
            Ranked by out-of-sample Sharpe, never the in-sample number. Trials is
            how many configurations were tried before this one was picked; DSR is
            the Sharpe after deflating for that search.
          </p>
          <Suspense fallback={<Rows n={4} />}>
            <Leaderboard />
          </Suspense>
        </section>

        <p className="mt-16 max-w-[68ch] border-t pt-5 text-xs leading-relaxed text-muted-foreground">
          Research, not investment advice. Backtested results are modelled with
          estimated costs on a universe with limited survivorship correction —
          an upper bound on what was achievable, not a track record.
        </p>
      </div>
    </main>
  );
}
