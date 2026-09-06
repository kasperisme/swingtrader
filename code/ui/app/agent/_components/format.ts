import type { ArenaOrder } from "@/app/actions/arena";

/** Formatting shared by the agent profile and its per-appearance pages. */

export function fmtMoney(v: number | null | undefined, digits = 0) {
  if (v == null) return "—";
  return `$${v.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`;
}

/** Signed dollars, using a real minus sign rather than a hyphen. */
export function fmtSignedMoney(v: number | null | undefined) {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : "−"}${fmtMoney(Math.abs(v))}`;
}

export function fmtPct(v: number | null | undefined, digits = 2) {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${(v * 100).toFixed(digits)}%`;
}

/** A rate, not a change — so no leading "+". */
export function fmtRate(v: number | null | undefined, digits = 0) {
  if (v == null) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

export function toneFor(v: number | null | undefined) {
  if (v == null) return "text-muted-foreground";
  if (v > 0) return "text-emerald-600 dark:text-emerald-500";
  if (v < 0) return "text-rose-600 dark:text-rose-500";
  return "text-muted-foreground";
}

export function fmtDate(iso: string | null | undefined) {
  if (!iso) return "—";
  return new Date(iso.length === 10 ? `${iso}T00:00:00Z` : iso).toLocaleDateString(
    "en-GB",
    { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" },
  );
}

export function fmtDay(iso: string | null | undefined) {
  if (!iso) return "—";
  return new Date(iso.length === 10 ? `${iso}T00:00:00Z` : iso).toLocaleDateString(
    "en-GB",
    { day: "numeric", month: "short", timeZone: "UTC" },
  );
}

/**
 * How a fill reads on the tape, once agents can short.
 *
 * Colouring by `side` inverted the meaning for both short cases: opening a
 * short is a new BEARISH position and was painted in the exit colour, while
 * covering one CLOSES a bearish bet and was painted like a fresh buy. So the
 * colour tracks the direction of the bet, not the direction of the cash:
 * emerald opens bullish, rose opens bearish, muted closes either.
 */
const EFFECT_LABEL: Record<
  NonNullable<ArenaOrder["position_effect"]>,
  { label: string; tone: string }
> = {
  open_long: { label: "BUY", tone: "text-emerald-600 dark:text-emerald-500" },
  close_long: { label: "SELL", tone: "text-muted-foreground" },
  open_short: { label: "SHORT", tone: "text-rose-600 dark:text-rose-500" },
  cover_short: { label: "COVER", tone: "text-muted-foreground" },
  flip_to_short: { label: "SELL → SHORT", tone: "text-rose-600 dark:text-rose-500" },
  flip_to_long: { label: "COVER → BUY", tone: "text-emerald-600 dark:text-emerald-500" },
};

/**
 * Rows written before position_effect existed, and any unfilled order, carry
 * NULL. Those fall back to the bare side — every agent but Jim Sigmons was
 * long-only then, so the old reading was right for them, and an invented label
 * would be worse than a plain one.
 */
export function orderVerb(o: ArenaOrder): { label: string; tone: string } {
  if (o.position_effect) return EFFECT_LABEL[o.position_effect];
  return {
    label: o.side.toUpperCase(),
    tone:
      o.side === "buy"
        ? "text-emerald-600 dark:text-emerald-500"
        : "text-rose-600 dark:text-rose-500",
  };
}

export const ORDER_TONE: Record<ArenaOrder["status"], string> = {
  filled: "text-foreground",
  pending: "text-amber-600 dark:text-amber-500",
  rejected: "text-rose-600 dark:text-rose-500",
  cancelled: "text-muted-foreground",
};
