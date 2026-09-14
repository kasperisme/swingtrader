import type { CSSProperties } from "react";

import { signed, type Anchor } from "@/lib/news/article-verdict";

function toneOf(v: number): string {
  if (v > 0.03) return "bg-emerald-500";
  if (v < -0.03) return "bg-rose-500";
  return "bg-muted-foreground";
}

/**
 * A score on its −1…+1 scale: a track with the zero line marked, a fill from
 * zero to the value and a dot at the value. A bare "−0.40" carries no sense of
 * how far it is from nothing or from the edge; the rail does, at a glance.
 *
 * Animated with transforms only (globals.css `animate-rail-*`): the marker
 * layer spans the whole track and is translated by the value's offset from
 * centre — a percentage of its own width, which IS the track's width — and the
 * fill scales out from the zero line.
 */
export function ScoreRail({
  value,
  size = "sm",
  className = "",
}: {
  value: number;
  size?: "sm" | "lg";
  className?: string;
}) {
  const v = Math.max(-1, Math.min(1, value));
  const pos = ((v + 1) / 2) * 100;
  const tone = toneOf(v);
  const lg = size === "lg";
  return (
    <div role="img" aria-label={`${signed(v)} on a −1 to +1 scale`} className={className}>
      <div className={`relative rounded-full bg-muted ${lg ? "h-2" : "h-1.5"}`}>
        <span className="absolute inset-y-[-3px] left-1/2 w-px bg-foreground/30" />
        <span
          className={`animate-rail-fill absolute inset-y-0 rounded-full opacity-35 ${tone} ${
            v >= 0 ? "origin-left" : "origin-right"
          }`}
          style={{ left: `${Math.min(pos, 50)}%`, width: `${Math.abs(pos - 50)}%` }}
        />
        <span
          className="animate-rail-marker pointer-events-none absolute inset-0"
          style={{ "--rail-x": `${pos - 50}%` } as CSSProperties}
        >
          <span
            className={`absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-background ${tone} ${
              lg ? "h-3.5 w-3.5" : "h-2.5 w-2.5"
            }`}
          />
        </span>
      </div>
      {lg ? (
        <div className="mt-1.5 flex justify-between font-mono text-[9px] tabular-nums text-muted-foreground/80">
          <span>−1 bearish</span>
          <span>0</span>
          <span>bullish +1</span>
        </div>
      ) : null}
    </div>
  );
}

/** "More negative than 85% of claims this week" — the percentile under a rail. */
export function AnchorCaption({
  anchor,
  className = "",
}: {
  anchor: Anchor | null;
  className?: string;
}) {
  if (!anchor) return null;
  return (
    <p className={`text-[10px] leading-snug text-muted-foreground ${className}`}>{anchor.text}</p>
  );
}
