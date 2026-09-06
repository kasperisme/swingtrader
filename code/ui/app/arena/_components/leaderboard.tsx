"use client";

import { Fragment, useCallback, useState, useTransition } from "react";
import Link from "next/link";
import { ArrowUpRight, ChevronDown } from "lucide-react";
import {
  getAgentBook,
  type ArenaAgentBook,
  type ArenaStanding,
} from "@/app/actions/arena";
import { ARENA_COLOR_INDEX } from "@/lib/arena/colors";
import { PortfolioPanel } from "./portfolio-panel";

/**
 * The standings, where every row opens into that agent's book.
 *
 * The expanded panel is the SAME component the agent's own page uses, so the
 * two can never drift into disagreeing about a portfolio — and clicking a
 * point on its chart still rewinds the holdings table to that close.
 *
 * One row at a time. Nine open panels is nine charts competing for the same
 * question ("who is winning"), which the leaderboard above already answers;
 * the panel is for the follow-up ("what is it actually holding").
 *
 * The book is fetched on FIRST open and then kept, so re-opening a row is
 * instant and the initial page never ships nine seasons of holdings it may
 * never show.
 */

type Props = {
  rows: ArenaStanding[];
  championshipId: string;
};

function fmtMoney(v: number | null | undefined) {
  if (v == null) return "—";
  return `$${Math.round(v).toLocaleString("en-US")}`;
}

function fmtPct(v: number | null | undefined, digits = 2) {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${(v * 100).toFixed(digits)}%`;
}

function toneFor(v: number | null | undefined) {
  if (v == null) return "text-muted-foreground";
  if (v > 0) return "text-emerald-600 dark:text-emerald-500";
  if (v < 0) return "text-rose-600 dark:text-rose-500";
  return "text-muted-foreground";
}

export function Leaderboard({ rows, championshipId }: Props) {
  const [open, setOpen] = useState<string | null>(null);
  const [books, setBooks] = useState<Record<string, ArenaAgentBook>>({});
  const [pending, startTransition] = useTransition();

  const toggle = useCallback(
    (slug: string) => {
      if (open === slug) {
        setOpen(null);
        return;
      }
      setOpen(slug);
      if (books[slug]) return;
      startTransition(async () => {
        const book = await getAgentBook(slug, championshipId);
        setBooks((prev) => ({ ...prev, [slug]: book }));
      });
    },
    [open, books, championshipId],
  );

  return (
    <div className="-mx-4 overflow-x-auto px-4">
      <table className="w-full min-w-[760px] border-collapse text-sm">
        <caption className="sr-only">
          Agents ranked by total return since the championship opened, with
          maximum drawdown, Sharpe ratio, open positions and orders filled. Each
          row opens that agent&rsquo;s portfolio and its value over time.
        </caption>
        <thead>
          <tr className="border-b text-left font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
            <th scope="col" className="pb-2 pr-3 text-right font-normal">#</th>
            <th scope="col" className="pb-2 pr-4 font-normal">Agent</th>
            <th scope="col" className="pb-2 pr-4 text-right font-normal">NAV</th>
            <th scope="col" className="pb-2 pr-4 text-right font-normal">Return</th>
            <th scope="col" className="pb-2 pr-4 text-right font-normal">Max DD</th>
            <th scope="col" className="pb-2 pr-4 text-right font-normal">Sharpe</th>
            <th scope="col" className="pb-2 pr-4 text-right font-normal">Pos</th>
            <th scope="col" className="pb-2 pr-4 text-right font-normal">Fills</th>
            <th scope="col" className="pb-2 w-8">
              <span className="sr-only">Portfolio</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => {
            const rank = i + 1;
            const colorIndex = ARENA_COLOR_INDEX[row.slug] ?? null;
            const isControl = row.engine === "deterministic";
            const isOpen = open === row.slug;
            const book = books[row.slug];
            const panelId = `arena-book-${row.slug}`;

            return (
              <Fragment key={row.slug}>
              <tr
                onClick={(e) => {
                  // The name's link and the disclosure button own their own
                  // clicks; everywhere else on the row is a second, larger hit
                  // target for the same toggle.
                  if ((e.target as HTMLElement).closest("a,button")) return;
                  toggle(row.slug);
                }}
                className={`animate-screening-row-in cursor-pointer border-b transition-colors hover:bg-muted/50 ${
                  isOpen ? "border-transparent bg-muted/40" : "border-border/60"
                }`}
                style={{ animationDelay: `${Math.min(i, 12) * 30}ms` }}
              >
                <td className="py-3 pr-3 text-right font-mono text-xs text-muted-foreground">
                  {rank}
                </td>
                <td className="py-3 pr-4">
                  <div className="flex items-start gap-2.5">
                    <span
                      aria-hidden
                      className="mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full"
                      // A hollow ring for the controls, matching their dashed
                      // line in the chart legend. A DASHED ring at this size
                      // renders as three specks and reads as a loading spinner,
                      // so the distinction is hollow-vs-filled instead.
                      style={{
                        backgroundColor: isControl
                          ? "transparent"
                          : `hsl(var(--arena-${colorIndex}))`,
                        boxShadow: isControl
                          ? "inset 0 0 0 1.5px hsl(var(--muted-foreground))"
                          : undefined,
                      }}
                    />
                    <span className="min-w-0">
                      <Link
                        href={`/agent/${row.slug}`}
                        className="group flex items-center gap-1 font-medium leading-tight transition-colors hover:text-amber-600 dark:hover:text-amber-500"
                      >
                        {row.name}
                        <ArrowUpRight
                          className="h-3.5 w-3.5 shrink-0 opacity-0 transition-opacity group-hover:opacity-100"
                          aria-hidden
                        />
                      </Link>
                      {row.tagline && (
                        <span className="mt-0.5 block max-w-[46ch] text-xs leading-snug text-muted-foreground">
                          {row.tagline}
                        </span>
                      )}
                      {isControl && (
                        <span className="mt-1 inline-block rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
                          control · no LLM
                        </span>
                      )}
                    </span>
                  </div>
                </td>
                <td className="py-3 pr-4 text-right font-mono tabular-nums">
                  {fmtMoney(row.nav)}
                </td>
                <td
                  className={`py-3 pr-4 text-right font-mono font-medium tabular-nums ${toneFor(row.total_return)}`}
                >
                  {fmtPct(row.total_return)}
                </td>
                <td className="py-3 pr-4 text-right font-mono tabular-nums text-muted-foreground">
                  {fmtPct(row.max_drawdown, 1)}
                </td>
                <td className="py-3 pr-4 text-right font-mono tabular-nums text-muted-foreground">
                  {/* Sharpe is NULL until there is enough curve for it to mean
                      anything; printing a number off five sessions is theatre. */}
                  {row.sharpe == null ? (
                    <span className="text-[11px] uppercase tracking-wide text-muted-foreground/60">
                      {(row.nav_days ?? 0) < 20 ? "too early" : "—"}
                    </span>
                  ) : (
                    row.sharpe.toFixed(2)
                  )}
                </td>
                <td className="py-3 pr-4 text-right font-mono tabular-nums text-muted-foreground">
                  {row.n_positions ?? 0}
                </td>
                <td className="py-3 pr-4 text-right font-mono tabular-nums text-muted-foreground">
                  {row.filled_orders ?? 0}
                </td>
                <td className="py-3 text-right">
                  <button
                    type="button"
                    onClick={() => toggle(row.slug)}
                    aria-expanded={isOpen}
                    aria-controls={panelId}
                    className="inline-flex h-7 w-7 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-background hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <span className="sr-only">
                      {isOpen ? "Hide" : "Show"} {row.name}&rsquo;s portfolio
                    </span>
                    <ChevronDown
                      className={`h-4 w-4 transition-transform duration-200 ${isOpen ? "rotate-180" : ""}`}
                      aria-hidden
                    />
                  </button>
                </td>
              </tr>

              {isOpen && (
                <tr className="border-b border-border/60">
                  <td colSpan={9} className="p-0">
                    <div
                      id={panelId}
                      className="animate-screening-row-in border-l-2 bg-muted/20 px-4 py-6 sm:px-6"
                      style={{
                        borderLeftColor: isControl
                          ? "hsl(var(--muted-foreground))"
                          : `hsl(var(--arena-${colorIndex}))`,
                      }}
                    >
                      {book ? (
                        <>
                          <PortfolioPanel
                            points={book.points}
                            livePositions={book.positions}
                            startingCash={book.startingCash}
                            colorIndex={isControl ? null : colorIndex}
                            nav={book.nav}
                            cash={book.cash}
                          />
                          <div className="mt-6">
                            <Link
                              href={`/agent/${row.slug}`}
                              className="inline-flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-widest text-muted-foreground transition-colors hover:text-amber-600 dark:hover:text-amber-500"
                            >
                              {row.name}&rsquo;s orders, reasoning and sources
                              <ArrowUpRight className="h-3.5 w-3.5" aria-hidden />
                            </Link>
                          </div>
                        </>
                      ) : (
                        <div aria-live="polite">
                          <span className="sr-only">
                            {pending ? "Loading portfolio" : "Portfolio unavailable"}
                          </span>
                          <div className="h-[260px] animate-pulse rounded-lg bg-muted" />
                          <div className="mt-6 grid gap-px">
                            {Array.from({ length: 4 }, (_, n) => (
                              <div
                                key={n}
                                className="h-9 animate-pulse bg-muted"
                                aria-hidden
                              />
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  </td>
                </tr>
              )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
