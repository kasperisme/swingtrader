"use client";

import { useState } from "react";
import Link from "next/link";
import { Lock } from "lucide-react";

export type ClusterRow = {
  id: string;
  label: string;
  score: number;
  docSlug: string;
};

// How many cluster rows are visible before the gate. The rest are blurred +
// locked behind the early-access CTA.
const FREE_ROWS = 4;

function toneClass(score: number): string {
  if (score > 0.03) return "text-emerald-500";
  if (score < -0.03) return "text-rose-500";
  return "text-muted-foreground";
}

/**
 * Center-anchored bar. Maps the [-1, +1] score range onto [0%, 100%] width with
 * the neutral midpoint at 50%: positive scores fill rightward from center,
 * negative fill leftward. Thin (3px) per the design.
 */
function ClusterBar({ score }: { score: number }) {
  const clamped = Math.max(-1, Math.min(1, score));
  const pct = Math.abs(clamped) * 50; // up to 50% each side of the midpoint
  const isZero = Math.abs(score) <= 0.03;
  const isPos = clamped >= 0;
  const fill = isZero
    ? "bg-muted-foreground/40"
    : isPos
      ? "bg-emerald-500/80"
      : "bg-rose-500/80";
  return (
    <div className="relative h-[3px] w-full overflow-hidden rounded-sm bg-muted/40">
      <div className="absolute left-1/2 top-0 h-full w-px bg-border" />
      <div
        className={`absolute top-0 h-full ${fill}`}
        style={{
          left: isPos ? "50%" : `${50 - pct}%`,
          width: `${pct}%`,
        }}
      />
    </div>
  );
}

function ClusterLine({ row }: { row: ClusterRow }) {
  const sign = row.score >= 0 ? "+" : "";
  return (
    <li>
      <div className="mb-1 flex items-baseline justify-between gap-3">
        <Link
          href={row.docSlug}
          className="truncate text-sm text-foreground/90 hover:text-amber-400"
        >
          {row.label}
        </Link>
        <span className={`font-mono text-xs tabular-nums ${toneClass(row.score)}`}>
          {sign}
          {row.score.toFixed(3)}
        </span>
      </div>
      <ClusterBar score={row.score} />
    </li>
  );
}

export function ClusterScoreCard({ rows }: { rows: ClusterRow[] }) {
  const [showAll, setShowAll] = useState(false);

  const nonZero = rows.filter((r) => Math.abs(r.score) > 0.03);
  const hasZero = nonZero.length < rows.length;
  const visible = showAll ? rows : nonZero;

  const free = visible.slice(0, FREE_ROWS);
  const locked = visible.slice(FREE_ROWS);

  if (visible.length === 0) {
    return (
      <p className="text-sm text-muted-foreground/80">
        No cluster impact found for this article yet.
      </p>
    );
  }

  return (
    <div>
      <ul className="space-y-3.5">
        {free.map((c) => (
          <ClusterLine key={c.id} row={c} />
        ))}
      </ul>

      {locked.length > 0 && (
        <div className="relative mt-3.5">
          {/* Blurred preview of the gated rows. */}
          <ul
            aria-hidden
            className="space-y-3.5 select-none blur-[5px] [mask-image:linear-gradient(to_bottom,black,transparent)]"
          >
            {locked.map((c) => (
              <ClusterLine key={c.id} row={c} />
            ))}
          </ul>
          {/* Lock overlay → routes to the unlock CTA on the same page. */}
          <div className="absolute inset-0 flex items-center justify-center">
            <Link
              href="#early-access"
              className="inline-flex items-center gap-2 rounded-full border border-amber-500/30 bg-background/80 px-4 py-2 font-mono text-[11px] uppercase tracking-[0.18em] text-amber-400 backdrop-blur-sm transition-colors hover:border-amber-500/60 hover:text-amber-300"
            >
              <Lock size={12} />
              Unlock {locked.length} more cluster{locked.length === 1 ? "" : "s"}
            </Link>
          </div>
        </div>
      )}

      {hasZero && (
        <button
          type="button"
          onClick={() => setShowAll((v) => !v)}
          className="mt-4 font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground transition-colors hover:text-foreground"
        >
          {showAll ? "Show movers only" : "Show all"}
        </button>
      )}
    </div>
  );
}
