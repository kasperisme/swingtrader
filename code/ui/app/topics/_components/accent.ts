/**
 * Per-topic accent — the visual identity the `topics.accent` column was added for
 * and which the pages have never actually read.
 *
 * The point is one cohesive system, not one look per topic: every tracker gets
 * the same layout, type scale and components, and only the accent hue changes.
 * So this is a closed set rather than free-form colour — a topic can pick from
 * the palette, it cannot invent one, and an unknown token quietly falls back to
 * amber (the column's own default) rather than rendering an unstyled page.
 *
 * Classes are written out in full because Tailwind scans source statically —
 * `text-${accent}-500` would compile to nothing.
 */

export type AccentToken = "amber" | "steel" | "emerald" | "rose" | "violet";

export type AccentClasses = {
  /** The eyebrow's short rule. */
  rule: string;
  /** Eyebrow / label text. */
  label: string;
  /** Left rail on a claim or tracker row. */
  rail: string;
  /** Hover tint for a whole row. */
  hoverText: string;
  /** Underline decoration for inline links. */
  underline: string;
  /** Small solid marker. */
  dot: string;
};

const PALETTE: Record<AccentToken, AccentClasses> = {
  amber: {
    rule: "bg-amber-500/60",
    label: "text-amber-500/80",
    rail: "border-amber-500/50",
    hoverText: "group-hover:text-amber-600 dark:group-hover:text-amber-400",
    underline: "decoration-amber-500/50 hover:decoration-amber-500",
    dot: "bg-amber-500",
  },
  steel: {
    rule: "bg-sky-500/60",
    label: "text-sky-500/90",
    rail: "border-sky-500/50",
    hoverText: "group-hover:text-sky-600 dark:group-hover:text-sky-400",
    underline: "decoration-sky-500/50 hover:decoration-sky-500",
    dot: "bg-sky-500",
  },
  emerald: {
    rule: "bg-emerald-500/60",
    label: "text-emerald-500/90",
    rail: "border-emerald-500/50",
    hoverText: "group-hover:text-emerald-600 dark:group-hover:text-emerald-400",
    underline: "decoration-emerald-500/50 hover:decoration-emerald-500",
    dot: "bg-emerald-500",
  },
  rose: {
    rule: "bg-rose-500/60",
    label: "text-rose-500/90",
    rail: "border-rose-500/50",
    hoverText: "group-hover:text-rose-600 dark:group-hover:text-rose-400",
    underline: "decoration-rose-500/50 hover:decoration-rose-500",
    dot: "bg-rose-500",
  },
  violet: {
    rule: "bg-violet-500/60",
    label: "text-violet-500/90",
    rail: "border-violet-500/50",
    hoverText: "group-hover:text-violet-600 dark:group-hover:text-violet-400",
    underline: "decoration-violet-500/50 hover:decoration-violet-500",
    dot: "bg-violet-500",
  },
};

export function accentFor(token: string | null | undefined): AccentClasses {
  return PALETTE[(token ?? "") as AccentToken] ?? PALETTE.amber;
}
