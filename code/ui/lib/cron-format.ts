// Human-readable cron descriptions, powered by `cronstrue`.
//
// cronstrue handles the full cron grammar (intervals, lists, ranges, step
// values, day/month names…), so we no longer maintain a bespoke parser that
// only covered the handful of patterns we ship today. The public signature is
// unchanged — every call site (schedule badges, detail pages, meta
// descriptions) keeps working. We still append a non-UTC timezone and fall back
// to the raw expression for anything cronstrue can't parse.

import cronstrue from "cronstrue";

function withTz(base: string, timezone?: string | null): string {
  if (!timezone || timezone === "UTC") return base;
  return `${base} (${timezone})`;
}

export function humanizeCron(
  schedule: string,
  timezone?: string | null,
): string {
  const trimmed = (schedule ?? "").trim();
  if (!trimmed) return "";

  try {
    const text = cronstrue.toString(trimmed, {
      throwExceptionOnParseError: true,
      verbose: false,
      use24HourTimeFormat: false,
    });
    return withTz(text, timezone);
  } catch {
    // Unknown / invalid expression — keep the raw cron so a human can still
    // read it rather than showing an error string.
    return withTz(trimmed, timezone);
  }
}
