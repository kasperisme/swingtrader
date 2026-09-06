/**
 * Formatters shared by the arena's server and client components.
 *
 * They live here rather than in the page because the season picker is a Client
 * Component: functions cannot be passed across that boundary as props, and two
 * private copies is how the dates on the trigger start disagreeing with the
 * dates in the table. One definition, imported by both sides.
 */

export function fmtMoney(v: number | null | undefined): string {
  if (v == null) return "—";
  return `$${Math.round(v).toLocaleString("en-US")}`;
}

export function fmtPct(v: number | null | undefined, digits = 2): string {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${(v * 100).toFixed(digits)}%`;
}

/** UTC-pinned: a championship window is a calendar fact, not a local one. */
export function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}
