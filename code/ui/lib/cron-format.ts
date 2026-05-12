const PRESETS: Record<string, string> = {
  "0 7 * * 1-5": "Weekdays at 7:00 AM",
  "0 7 * * *": "Daily at 7:00 AM",
  "0 9 * * 1-5": "Weekdays at 9:00 AM",
  "0 16 * * 1-5": "Weekdays at 4:00 PM",
  "0 */4 * * *": "Every 4 hours",
  "0 */2 * * *": "Every 2 hours",
  "0 * * * *": "Hourly",
  "*/30 * * * *": "Every 30 minutes",
  "*/15 * * * *": "Every 15 minutes",
};

export function humanizeCron(schedule: string, timezone?: string | null): string {
  const trimmed = (schedule ?? "").trim();
  const base = PRESETS[trimmed] ?? trimmed;
  if (!timezone || timezone === "UTC") return base;
  return `${base} (${timezone})`;
}
