// Lightweight, swingtrader-focused cron humanizer. Handles every cron string
// we use today (minute/hour + day-of-week patterns + interval syntax).
// Falls back to the raw cron string for anything it doesn't recognise.

const DOW_LONG_PLURAL = [
  "Sundays",
  "Mondays",
  "Tuesdays",
  "Wednesdays",
  "Thursdays",
  "Fridays",
  "Saturdays",
] as const;

const DOW_SHORT = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"] as const;

function formatTime(hour: number, minute: number): string {
  if (Number.isNaN(hour) || Number.isNaN(minute)) return "";
  const h12 = ((hour + 11) % 12) + 1;
  const ampm = hour < 12 ? "AM" : "PM";
  const mm = minute.toString().padStart(2, "0");
  return `${h12}:${mm} ${ampm}`;
}

function normaliseDow(n: number): number {
  // Cron allows 0 and 7 for Sunday. Normalise to 0–6.
  return ((n % 7) + 7) % 7;
}

function parseDowField(field: string): string | null {
  if (field === "*") return "Daily";
  if (field === "1-5") return "Weekdays";
  if (field === "6,0" || field === "0,6" || field === "6,7" || field === "0,6")
    return "Weekends";

  // Single day: 0–7 (0 and 7 both = Sunday).
  if (/^[0-7]$/.test(field)) {
    return DOW_LONG_PLURAL[normaliseDow(parseInt(field, 10))];
  }

  // Comma-separated list: "1,3,5" → "Mon, Wed, Fri".
  if (/^[0-7](,[0-7])+$/.test(field)) {
    const days = field
      .split(",")
      .map((d) => DOW_SHORT[normaliseDow(parseInt(d, 10))]);
    return days.join(", ");
  }

  // Range: "2-4" → "Tue–Thu".
  const range = field.match(/^([0-7])-([0-7])$/);
  if (range) {
    return `${DOW_SHORT[normaliseDow(parseInt(range[1], 10))]}–${
      DOW_SHORT[normaliseDow(parseInt(range[2], 10))]
    }`;
  }

  return null;
}

function withTz(base: string, timezone?: string | null): string {
  if (!timezone || timezone === "UTC") return base;
  return `${base} (${timezone})`;
}

export function humanizeCron(
  schedule: string,
  timezone?: string | null,
): string {
  const trimmed = (schedule ?? "").trim();
  const parts = trimmed.split(/\s+/);
  if (parts.length !== 5) return trimmed;

  const [minStr, hourStr, dom, month, dow] = parts;

  // ── Interval patterns ────────────────────────────────────────────────────
  if (hourStr === "*" && dom === "*" && month === "*" && dow === "*") {
    const m = minStr.match(/^\*\/(\d+)$/);
    if (m) {
      return withTz(
        `Every ${m[1]} minute${m[1] === "1" ? "" : "s"}`,
        timezone,
      );
    }
    if (minStr === "0") return withTz("Hourly", timezone);
  }

  if (minStr === "0" && dom === "*" && month === "*" && dow === "*") {
    const m = hourStr.match(/^\*\/(\d+)$/);
    if (m) {
      return withTz(`Every ${m[1]} hour${m[1] === "1" ? "" : "s"}`, timezone);
    }
  }

  // ── Specific time + day-of-week ──────────────────────────────────────────
  const minute = parseInt(minStr, 10);
  const hour = parseInt(hourStr, 10);
  const validClock =
    !Number.isNaN(minute) &&
    !Number.isNaN(hour) &&
    minute >= 0 &&
    minute < 60 &&
    hour >= 0 &&
    hour < 24;

  if (validClock && dom === "*" && month === "*") {
    const dowLabel = parseDowField(dow);
    if (dowLabel) {
      const time = formatTime(hour, minute);
      return withTz(`${dowLabel} at ${time}`, timezone);
    }
  }

  // Unknown pattern — keep the raw expression so a human can still parse it.
  return withTz(trimmed, timezone);
}
