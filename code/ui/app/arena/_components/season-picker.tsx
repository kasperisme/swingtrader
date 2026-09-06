"use client";

import Link from "next/link";
import { Check, ChevronDown, Trophy } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { ArenaChampionship } from "@/app/actions/arena";
import { fmtDate, fmtMoney, fmtPct } from "@/lib/arena/format";

/**
 * The season identity line in the masthead, which is also the season selector.
 *
 * It started as a row of chips under the title, which put a navigation choice
 * in front of the result the page exists to show. Folding it into the line that
 * already NAMES the season removes the duplication — the reader was being told
 * which season this is, and separately offered a list of seasons, in adjacent
 * blocks.
 *
 * Radix rather than a hand-rolled disclosure: this is a menu, so it owes the
 * reader focus management, Escape, click-outside and arrow-key traversal, and
 * every one of those is a thing hand-rolled versions forget.
 *
 * The trigger renders as a plain line when there is only one season. A control
 * that opens to reveal a single choice is a control that lied about having one.
 */
export function SeasonPicker({
  current,
  seasons,
}: {
  current: ArenaChampionship;
  seasons: ArenaChampionship[];
}) {
  const identity = (
    <>
      <span className="text-foreground">{current.name}</span> ·{" "}
      {fmtDate(current.starts_on)} → {fmtDate(current.ends_on)}
      <br className="hidden sm:block" />
      <span className="sm:hidden"> · </span>
      {fmtMoney(current.starting_cash)} each · {current.entrants} entrants
      {current.is_backtest && " · replayed"}
    </>
  );

  if (seasons.length < 2) {
    return (
      <p className="font-mono text-xs leading-relaxed text-muted-foreground sm:text-right">
        {identity}
      </p>
    );
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger className="group flex items-start gap-1.5 rounded-sm text-left font-mono text-xs leading-relaxed text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:text-right">
        <span>{identity}</span>
        <ChevronDown
          aria-hidden
          className="mt-0.5 h-3.5 w-3.5 shrink-0 transition-transform group-data-[state=open]:rotate-180"
        />
        <span className="sr-only">Change season</span>
      </DropdownMenuTrigger>

      <DropdownMenuContent align="end" className="w-[19rem]">
        {seasons.map((s) => {
          const active = s.slug === current.slug;
          return (
            <DropdownMenuItem key={s.slug} asChild className="cursor-pointer">
              <Link
                href={active ? "/arena" : `/arena?championship=${s.slug}`}
                aria-current={active ? "page" : undefined}
                className="flex flex-col items-start gap-1 py-2"
              >
                <span className="flex w-full items-center gap-2">
                  {active ? (
                    <Check className="h-3.5 w-3.5 shrink-0 text-amber-600 dark:text-amber-500" aria-hidden />
                  ) : (
                    <span aria-hidden className="h-3.5 w-3.5 shrink-0" />
                  )}
                  <span className={active ? "font-medium" : ""}>{s.name}</span>
                  {s.status === "running" && (
                    <span className="ml-auto flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-widest text-emerald-700 dark:text-emerald-500">
                      <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                      live
                    </span>
                  )}
                  {s.status !== "running" && (
                    <span className="ml-auto font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
                      {s.status}
                    </span>
                  )}
                </span>
                <span className="pl-[1.375rem] font-mono text-[11px] tabular-nums text-muted-foreground">
                  {fmtDate(s.starts_on)} → {fmtDate(s.ends_on)}
                </span>
                {s.champion_name && (
                  <span className="flex items-center gap-1.5 pl-[1.375rem] text-[11px] text-muted-foreground">
                    <Trophy className="h-3 w-3 text-amber-600 dark:text-amber-500" aria-hidden />
                    {s.champion_name}
                    {s.champion_return != null && (
                      <span className="font-mono tabular-nums">
                        {fmtPct(s.champion_return)}
                      </span>
                    )}
                  </span>
                )}
              </Link>
            </DropdownMenuItem>
          );
        })}
        <p className="border-t px-2 pb-1 pt-2 text-[11px] leading-relaxed text-muted-foreground">
          Fixed three-month windows. Every agent is re-funded at the start of
          each, so a return is always measured within one season.
        </p>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
