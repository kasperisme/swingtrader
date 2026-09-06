import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import type { ArenaStanding } from "@/app/actions/arena";
import { ARENA_COLOR_INDEX } from "@/lib/arena/colors";

/**
 * The top three, as a podium.
 *
 * Three deliberate choices:
 *
 *  - **Height carries rank, colour carries identity.** The plinths are 1st >
 *    2nd > 3rd and the columns are ordered 2 · 1 · 3 so the silhouette reads
 *    before any number does. The fill is still the AGENT's fixed hue, which is
 *    the same hue it has in the curve, the legend and the leaderboard — so the
 *    podium never invents a gold/silver/bronze scale that disagrees with the
 *    rest of the page.
 *
 *  - **Controls are allowed to win.** `jack-boggle` (buy SPY, hold) and
 *    `burton-malarkey` (random) can and do finish top three. Hiding them would
 *    make the podium a lie; they are drawn hollow, in neutral grey, with the
 *    control label kept, because a strategy losing to buy-and-hold is the most
 *    informative thing this page can say.
 *
 *  - **Return is the hero, NAV is the receipt.** One large number per place,
 *    signed and tinted; the dollar figure sits under it in the muted register.
 */

const PLACE_LABEL = ["Leader", "Second", "Third"] as const;

/** Plinth heights, in the podium's own visual order. */
const PLINTH = ["h-24 sm:h-28", "h-16 sm:h-20", "h-11 sm:h-14"] as const;

/** 2 · 1 · 3 on wide screens; rank order when stacked. */
const ORDER = ["sm:order-2", "sm:order-1", "sm:order-3"] as const;

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

function Place({ row, rank }: { row: ArenaStanding; rank: number }) {
  const i = rank - 1;
  const colorIndex = ARENA_COLOR_INDEX[row.slug] ?? null;
  const isControl = row.engine === "deterministic";
  const hue = isControl || colorIndex == null
    ? "var(--muted-foreground)"
    : `var(--arena-${colorIndex})`;

  return (
    <li
      className={`animate-screening-row-in flex flex-col justify-end ${ORDER[i]}`}
      style={{ animationDelay: `${i * 70}ms` }}
    >
      <Link
        href={`/agent/${row.slug}`}
        className="group flex flex-col justify-end rounded-t-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <div className="px-1 pb-3">
          <div className="flex items-center gap-2">
            <span
              aria-hidden
              className="h-2.5 w-2.5 shrink-0 rounded-full"
              style={{
                backgroundColor: isControl ? "transparent" : `hsl(${hue})`,
                boxShadow: isControl
                  ? `inset 0 0 0 1.5px hsl(${hue})`
                  : undefined,
              }}
            />
            <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
              {PLACE_LABEL[i]}
            </span>
          </div>

          <span className="mt-2 flex items-start gap-1 text-lg font-semibold leading-tight tracking-tight transition-colors group-hover:text-amber-600 dark:group-hover:text-amber-500">
            {row.name}
            <ArrowUpRight
              className="mt-1 h-3.5 w-3.5 shrink-0 opacity-0 transition-opacity group-hover:opacity-100"
              aria-hidden
            />
          </span>

          {row.tagline && (
            <p className="mt-1 line-clamp-2 text-xs leading-snug text-muted-foreground">
              {row.tagline}
            </p>
          )}

          <p
            className={`mt-3 font-mono text-2xl font-medium tabular-nums sm:text-3xl ${toneFor(row.total_return)}`}
          >
            {fmtPct(row.total_return)}
          </p>
          <p className="mt-1 font-mono text-xs tabular-nums text-muted-foreground">
            {fmtMoney(row.nav)}
            <span className="mx-1.5 opacity-40">·</span>
            {fmtPct(row.max_drawdown, 1)} DD
          </p>

          {isControl && (
            <span className="mt-2 inline-block rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
              control · no LLM
            </span>
          )}
        </div>

        {/* The plinth. Height is the rank; the fill is the agent.
            A control gets no hue — but it can WIN, and a plinth tinted in
            muted-foreground disappears into the page, which would make the
            leader read as an empty slot. So the controls are hatched instead:
            still colourless, still visibly a different kind of competitor,
            still solid enough to hold first place. */}
        <div
          aria-hidden
          className={`relative flex items-center justify-center overflow-hidden rounded-t-lg border-t-2 transition-[filter] group-hover:brightness-110 ${PLINTH[i]}`}
          style={{
            borderTopColor: `hsl(${hue})`,
            borderTopStyle: isControl ? "dashed" : "solid",
            backgroundImage: isControl
              ? `repeating-linear-gradient(-45deg, hsl(${hue} / 0.16) 0 6px, transparent 6px 12px),
                 linear-gradient(to bottom, hsl(${hue} / 0.14), hsl(${hue} / 0.03))`
              : `linear-gradient(to bottom, hsl(${hue} / 0.20), hsl(${hue} / 0.03))`,
          }}
        >
          <span className="font-mono text-2xl font-semibold tabular-nums text-foreground/50 sm:text-3xl">
            {rank}
          </span>
        </div>
      </Link>
    </li>
  );
}

export function Podium({ rows }: { rows: ArenaStanding[] }) {
  const top = rows.slice(0, 3);
  if (top.length === 0) return null;

  return (
    <ol
      className="grid items-end gap-x-4 gap-y-8 sm:grid-cols-3 sm:gap-y-0"
      aria-label="Top three agents"
    >
      {top.map((r, i) => (
        <Place key={r.slug} row={r} rank={i + 1} />
      ))}
    </ol>
  );
}
