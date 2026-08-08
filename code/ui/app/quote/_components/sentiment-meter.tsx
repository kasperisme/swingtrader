/**
 * Diverging sentiment readout for a directory row.
 *
 * Sentiment is signed (-1..+1), so a bar that grows from a fixed left edge would
 * misread it — this fills outward from a centre tick, left for negative and right
 * for positive. Scale is absolute (the track is the full -1..+1 range), not
 * normalised to whatever is on screen, so a row means the same thing on page 1
 * and page 60.
 *
 * The number is always rendered alongside: colour and direction carry the same
 * information twice, so the meter never depends on hue alone.
 */
export function SentimentMeter({ value }: { value: number | null }) {
  if (value == null) {
    return (
      <span className="font-mono text-xs tabular-nums text-muted-foreground">
        n/a
      </span>
    );
  }

  const clamped = Math.max(-1, Math.min(1, value));
  const pct = Math.abs(clamped) * 50; // half-track = 100% of one direction
  const positive = clamped > 0;
  const neutral = Math.abs(clamped) < 0.15;

  const tone = neutral
    ? "text-muted-foreground"
    : positive
      ? "text-emerald-600 dark:text-emerald-400"
      : "text-rose-600 dark:text-rose-400";

  const fill = neutral
    ? "bg-muted-foreground/40"
    : positive
      ? "bg-emerald-500/70"
      : "bg-rose-500/70";

  return (
    <span className="flex items-center justify-end gap-2.5">
      <span
        className="relative hidden h-1.5 w-16 overflow-hidden rounded-full bg-border/60 sm:block"
        role="img"
        aria-label={`Mean sentiment ${clamped.toFixed(2)} on a scale of -1 to 1`}
      >
        {/* Centre tick — without it a short bar is unreadable as signed. */}
        <span className="absolute left-1/2 top-0 h-full w-px -translate-x-1/2 bg-border" />
        <span
          className={`absolute top-0 h-full ${fill}`}
          style={
            positive
              ? { left: "50%", width: `${pct}%` }
              : { right: "50%", width: `${pct}%` }
          }
        />
      </span>
      <span className={`w-11 text-right font-mono text-xs tabular-nums ${tone}`}>
        {clamped > 0 ? "+" : ""}
        {clamped.toFixed(2)}
      </span>
    </span>
  );
}
