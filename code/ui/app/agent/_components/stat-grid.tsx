/**
 * A row of headline numbers — the stat line at the top of a record.
 *
 * Deliberately dumb: it takes formatted strings, because the caller is the only
 * thing that knows whether a number is money, a rate or a count, and a stat
 * grid that starts making those decisions ends up formatting one of them wrong.
 */
export type Stat = {
  label: string;
  value: string;
  /** Text colour for the value, when its sign carries meaning. */
  tone?: string | null;
  /** Small print under the value — units, a qualifier, a denominator. */
  note?: string | null;
};

export function StatGrid({
  stats,
  columns = 4,
}: {
  stats: Stat[];
  columns?: 3 | 4;
}) {
  if (stats.length === 0) return null;
  return (
    <dl
      className={`grid grid-cols-2 gap-x-6 gap-y-6 ${
        columns === 3 ? "sm:grid-cols-3" : "sm:grid-cols-4"
      }`}
    >
      {stats.map((s) => (
        <div key={s.label}>
          <dt className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
            {s.label}
          </dt>
          <dd
            className={`mt-1.5 font-mono text-2xl font-medium tabular-nums ${s.tone ?? ""}`}
          >
            {s.value}
          </dd>
          {s.note && (
            <p className="mt-0.5 font-mono text-[11px] text-muted-foreground/80">
              {s.note}
            </p>
          )}
        </div>
      ))}
    </dl>
  );
}
