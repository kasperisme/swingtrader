/**
 * US trading-session markers for the news-impact heatmap.
 *
 * Picks out the hourly buckets that contain the 9:30 NY open and the 16:00 NY
 * close, plus the buckets that fall fully inside an open session. Handles DST
 * transitions and observed market holidays.
 */

import type { HeatmapGranularity } from "./aggregate";

type DateParts = {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
};

function getTimeZoneParts(date: Date, timeZone: string): DateParts {
  const dtf = new Intl.DateTimeFormat("en-US", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  const parts = dtf.formatToParts(date);
  const map = Object.fromEntries(parts.map((p) => [p.type, p.value]));
  return {
    year: Number.parseInt(map.year ?? "0", 10),
    month: Number.parseInt(map.month ?? "0", 10),
    day: Number.parseInt(map.day ?? "0", 10),
    hour: Number.parseInt(map.hour ?? "0", 10),
    minute: Number.parseInt(map.minute ?? "0", 10),
  };
}

function compareDateOnly(
  a: { year: number; month: number; day: number },
  b: { year: number; month: number; day: number },
): number {
  if (a.year !== b.year) return a.year - b.year;
  if (a.month !== b.month) return a.month - b.month;
  return a.day - b.day;
}

function addDaysDateOnly(
  d: { year: number; month: number; day: number },
  deltaDays: number,
): { year: number; month: number; day: number } {
  const tmp = new Date(Date.UTC(d.year, d.month - 1, d.day));
  tmp.setUTCDate(tmp.getUTCDate() + deltaDays);
  return {
    year: tmp.getUTCFullYear(),
    month: tmp.getUTCMonth() + 1,
    day: tmp.getUTCDate(),
  };
}

function nthWeekdayOfMonth(
  year: number,
  month1to12: number,
  weekday: number,
  n: number,
): { year: number; month: number; day: number } {
  const first = new Date(Date.UTC(year, month1to12 - 1, 1));
  const firstWeekday = first.getUTCDay();
  const delta = (weekday - firstWeekday + 7) % 7;
  const day = 1 + delta + (n - 1) * 7;
  return { year, month: month1to12, day };
}

function lastWeekdayOfMonth(
  year: number,
  month1to12: number,
  weekday: number,
): { year: number; month: number; day: number } {
  const last = new Date(Date.UTC(year, month1to12, 0));
  const lastDay = last.getUTCDate();
  const lastWeekday = last.getUTCDay();
  const delta = (lastWeekday - weekday + 7) % 7;
  return { year, month: month1to12, day: lastDay - delta };
}

function easterSundayUtc(year: number): {
  year: number;
  month: number;
  day: number;
} {
  // Anonymous Gregorian algorithm.
  const a = year % 19;
  const b = Math.floor(year / 100);
  const c = year % 100;
  const d = Math.floor(b / 4);
  const e = b % 4;
  const f = Math.floor((b + 8) / 25);
  const g = Math.floor((b - f + 1) / 3);
  const h = (19 * a + b - d - g + 15) % 30;
  const i = Math.floor(c / 4);
  const k = c % 4;
  const l = (32 + 2 * e + 2 * i - h - k) % 7;
  const m = Math.floor((a + 11 * h + 22 * l) / 451);
  const month = Math.floor((h + l - 7 * m + 114) / 31);
  const day = ((h + l - 7 * m + 114) % 31) + 1;
  return { year, month, day };
}

function observedFixedHoliday(
  year: number,
  month: number,
  day: number,
): { year: number; month: number; day: number } {
  const d = new Date(Date.UTC(year, month - 1, day));
  const dow = d.getUTCDay();
  if (dow === 6) return addDaysDateOnly({ year, month, day }, -1);
  if (dow === 0) return addDaysDateOnly({ year, month, day }, 1);
  return { year, month, day };
}

function isUsMarketHolidayNyDate(
  year: number,
  month: number,
  day: number,
): boolean {
  const target = { year, month, day };
  const same = (x: { year: number; month: number; day: number }) =>
    compareDateOnly(x, target) === 0;

  return (
    same(observedFixedHoliday(year, 1, 1)) ||
    same(nthWeekdayOfMonth(year, 1, 1, 3)) ||
    same(nthWeekdayOfMonth(year, 2, 1, 3)) ||
    same(addDaysDateOnly(easterSundayUtc(year), -2)) ||
    same(lastWeekdayOfMonth(year, 5, 1)) ||
    same(observedFixedHoliday(year, 6, 19)) ||
    same(observedFixedHoliday(year, 7, 4)) ||
    same(nthWeekdayOfMonth(year, 9, 1, 1)) ||
    same(nthWeekdayOfMonth(year, 11, 4, 4)) ||
    same(observedFixedHoliday(year, 12, 25))
  );
}

function isUsMarketTradingDayNyDate(
  year: number,
  month: number,
  day: number,
): boolean {
  const dow = new Date(Date.UTC(year, month - 1, day)).getUTCDay();
  if (dow === 0 || dow === 6) return false;
  return !isUsMarketHolidayNyDate(year, month, day);
}

function nyTimeToUtcMs(
  year: number,
  month: number,
  day: number,
  hour: number,
  minute: number,
): number {
  // Resolve NY wall-clock to UTC with iterative timezone-part correction.
  let guessUtcMs = Date.UTC(year, month - 1, day, hour, minute, 0, 0);
  const desiredMs = Date.UTC(year, month - 1, day, hour, minute, 0, 0);
  for (let i = 0; i < 5; i += 1) {
    const current = getTimeZoneParts(new Date(guessUtcMs), "America/New_York");
    const currentMs = Date.UTC(
      current.year,
      current.month - 1,
      current.day,
      current.hour,
      current.minute,
      0,
      0,
    );
    const diffMs = desiredMs - currentMs;
    if (diffMs === 0) break;
    guessUtcMs += diffMs;
  }
  return guessUtcMs;
}

export type SessionMarkers = {
  /** Buckets that contain the 9:30 NY open. */
  openBucketIdxs: Set<number>;
  /** Buckets that contain the 16:00 NY close. */
  closeBucketIdxs: Set<number>;
  /** Buckets fully inside a regular session (open..close inclusive). */
  sessionBucketIdxs: Set<number>;
};

const EMPTY_MARKERS: SessionMarkers = {
  openBucketIdxs: new Set(),
  closeBucketIdxs: new Set(),
  sessionBucketIdxs: new Set(),
};

export function computeSessionMarkers(
  bucketStartsIso: string[],
  granularity: HeatmapGranularity,
): SessionMarkers {
  if (granularity !== "1h" && granularity !== "4h") return EMPTY_MARKERS;
  if (bucketStartsIso.length === 0) return EMPTY_MARKERS;

  const bucketMs = bucketStartsIso.map((iso) => Date.parse(iso));
  const stepMs = granularity === "1h" ? 3_600_000 : 4 * 3_600_000;

  // Walk every NY trading day that overlaps the window.
  const firstMs = bucketMs[0];
  const lastMs = bucketMs[bucketMs.length - 1] + stepMs;

  // Find NY date of firstMs and lastMs, then iterate.
  const startParts = getTimeZoneParts(new Date(firstMs), "America/New_York");
  const endParts = getTimeZoneParts(new Date(lastMs), "America/New_York");

  const tradingDays: Array<{ year: number; month: number; day: number }> = [];
  let cursor = { year: startParts.year, month: startParts.month, day: startParts.day };
  const limit = { year: endParts.year, month: endParts.month, day: endParts.day };
  let safety = 200; // generous upper bound (90d max range)
  while (compareDateOnly(cursor, limit) <= 0 && safety-- > 0) {
    if (isUsMarketTradingDayNyDate(cursor.year, cursor.month, cursor.day)) {
      tradingDays.push({ ...cursor });
    }
    cursor = addDaysDateOnly(cursor, 1);
  }

  const open = new Set<number>();
  const close = new Set<number>();
  const inSession = new Set<number>();

  function bucketIdxFor(utcMs: number): number {
    // Floor to bucket start
    const idx = Math.floor((utcMs - firstMs) / stepMs);
    if (idx < 0 || idx >= bucketStartsIso.length) return -1;
    return idx;
  }

  for (const day of tradingDays) {
    const openMs = nyTimeToUtcMs(day.year, day.month, day.day, 9, 30);
    const closeMs = nyTimeToUtcMs(day.year, day.month, day.day, 16, 0);
    const openIdx = bucketIdxFor(openMs);
    const closeIdx = bucketIdxFor(closeMs);
    if (openIdx >= 0) open.add(openIdx);
    if (closeIdx >= 0) close.add(closeIdx);
    if (openIdx >= 0 && closeIdx >= 0) {
      for (let i = openIdx; i <= closeIdx; i += 1) inSession.add(i);
    } else if (openIdx >= 0) {
      for (let i = openIdx; i < bucketStartsIso.length; i += 1) inSession.add(i);
    } else if (closeIdx >= 0) {
      for (let i = 0; i <= closeIdx; i += 1) inSession.add(i);
    }
  }

  return {
    openBucketIdxs: open,
    closeBucketIdxs: close,
    sessionBucketIdxs: inSession,
  };
}
