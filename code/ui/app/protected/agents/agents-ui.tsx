"use client";

import { useState, useMemo, useCallback, useEffect, useId } from "react";
import { Bot, Pause, Play, Trash2, Plus, Clock, AlertCircle, Zap, Loader2, LayoutList, CalendarDays, ChevronLeft, ChevronRight, Pencil, X, Link2, Filter } from "lucide-react";
import {
  type ScheduledScreening,
  type ScreeningResult,
  type ScanRunSummary,
  type AgentScanRow,
  type TradingSession,
  createScheduledScreening,
  toggleScreening,
  deleteScheduledScreening,
  testRunScreening,
  pollTestResult,
  updateScheduledScreening,
  listScanRuns,
  listScanRowsForRuns,
} from "@/app/actions/screenings-agent";
import { TickerSearchCombobox } from "@/components/ticker-search-combobox";
import { relationshipsResolveTicker } from "@/app/actions/relationships";
import {
  type ScreeningsFilters,
  DEFAULT_SCREENINGS_FILTERS,
  countScreeningsFilterRules,
} from "@/app/protected/screenings/screenings-filters-model";
import { ScreeningsFilterBar, AddFilterWidget } from "@/app/protected/screenings/screenings-filter-bar";
import {
  collectAllRowDataKeys,
  orderedDataColumnKeys,
  inferBooleanFilterKeys,
  inferNumericFilterKeys,
  uniqueStringValuesForKey,
  MAX_CATEGORICAL_STRING_OPTIONS,
} from "@/app/protected/screenings/screenings-row-data";
import { applyRowDataFilters } from "@/app/protected/screenings/apply-row-data-filters";

type Props = {
  screenings: ScheduledScreening[];
  limits: {
    limit: number;
    used: number;
    plan: string;
    minSchedule: string;
  } | null;
  error: string | null;
  suggestionTickers: string[];
};

export function AgentsUI({ screenings, limits, error, suggestionTickers }: Props) {
  const [showForm, setShowForm] = useState(false);
  const [view, setView] = useState<"list" | "calendar">("list");
  const atLimit = limits ? limits.used >= limits.limit : true;

  return (
    <div className="flex min-w-0 w-full flex-col gap-6">
      {error && (
        <div className="flex min-w-0 items-start gap-3 rounded-xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
          <span className="min-w-0 break-words">{error}</span>
        </div>
      )}

      {/* Usage + controls */}
      <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0 flex-1">
          {limits && (
            <p className="text-sm text-muted-foreground break-words">
              <span className="font-semibold text-foreground">{limits.used}</span>
              <span className="text-muted-foreground/60"> / {limits.limit}</span>
              {" "}active agents
              <span className="ml-2 text-xs text-muted-foreground/60">({limits.plan} plan)</span>
            </p>
          )}
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {/* View toggle */}
          {screenings.length > 0 && (
            <div className="flex gap-0.5 rounded-lg border border-border p-0.5">
              <button
                type="button"
                onClick={() => setView("list")}
                className={`min-h-[40px] min-w-[40px] p-2 rounded-md transition-colors ${
                  view === "list" ? "bg-foreground text-background" : "text-muted-foreground hover:bg-muted"
                }`}
                title="List view"
              >
                <LayoutList className="w-3.5 h-3.5" />
              </button>
              <button
                type="button"
                onClick={() => setView("calendar")}
                className={`min-h-[40px] min-w-[40px] p-2 rounded-md transition-colors ${
                  view === "calendar" ? "bg-foreground text-background" : "text-muted-foreground hover:bg-muted"
                }`}
                title="Calendar view"
              >
                <CalendarDays className="w-3.5 h-3.5" />
              </button>
            </div>
          )}
          {!showForm && (
            <button
              type="button"
              onClick={() => setShowForm(true)}
              disabled={atLimit}
              className="inline-flex items-center gap-1.5 rounded-md bg-foreground px-3 py-2.5 text-sm font-medium text-background transition-opacity hover:opacity-90 disabled:opacity-40 disabled:pointer-events-none"
            >
              <Plus className="w-3.5 h-3.5" />
              New agent
            </button>
          )}
        </div>
      </div>

      {showForm && (
        <CreateForm
          onClose={() => setShowForm(false)}
          atLimit={atLimit}
          suggestionTickers={suggestionTickers}
        />
      )}

      {/* Calendar view */}
      {view === "calendar" && <WeekCalendar screenings={screenings} suggestionTickers={suggestionTickers} />}

      {/* Agent list */}
      {view === "list" && (
        <div className="flex flex-col gap-3">
          {screenings.length === 0 && !showForm && (
            <div className="rounded-2xl border border-dashed border-border px-6 py-14 text-center">
              <Bot className="mx-auto w-8 h-8 text-muted-foreground/30 mb-3" />
              <p className="text-sm font-medium text-foreground/70">No agents yet</p>
              <p className="mt-1 text-xs text-muted-foreground">
                Create one to get started — the agent runs on schedule and alerts you when conditions are met.
              </p>
            </div>
          )}
            {screenings.map((s) => (
            <AgentCard key={s.id} screening={s} suggestionTickers={suggestionTickers} />
          ))}
        </div>
      )}
    </div>
  );
}

// ── Recurrence builder ──────────────────────────────────────────────────────

type RecurrencePattern = "minutely" | "hourly" | "daily" | "weekly";

const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"] as const;
type DayIdx = 0 | 1 | 2 | 3 | 4 | 5 | 6;

// Mon → Sun order matching the image, with single-letter labels
const DAY_ORDER: { idx: DayIdx; label: string }[] = [
  { idx: 1, label: "M" }, { idx: 2, label: "T" }, { idx: 3, label: "W" },
  { idx: 4, label: "T" }, { idx: 5, label: "F" }, { idx: 6, label: "S" },
  { idx: 0, label: "S" },
];

function buildCron(
  pattern: RecurrencePattern,
  interval: number,
  days: DayIdx[],
  hour: number,
  minute: number,
): string {
  switch (pattern) {
    case "minutely":
      return interval === 1 ? `* * * * *` : `*/${interval} * * * *`;
    case "hourly":
      return `${minute} */${interval} * * *`;
    case "daily":
      return `${minute} ${hour} * * *`;
    case "weekly": {
      const dow = days.length === 7 ? "*" : days.length === 0 ? "1-5" : days.sort().join(",");
      return `${minute} ${hour} * * ${dow}`;
    }
  }
}

function describeCron(cron: string): string {
  const parts = cron.split(/\s+/);
  if (parts.length !== 5) return cron;
  const [m, h, , , dow] = parts;
  const time = formatTime(parseNum(h, 0), parseNum(m, 0));

  if (dow === "1-5" || dow === "1,2,3,4,5") return `Weekdays at ${time}`;
  if (dow === "*") {
    if (m.startsWith("*/")) return `Every ${m.slice(2)} min`;
    if (h.startsWith("*/")) return `Every ${h.slice(2)} h at :${String(parseNum(m, 0)).padStart(2, "0")}`;
    return `Daily at ${time}`;
  }
  const dayNames = dow.split(",").map((d) => DAYS[Number(d)]).join(", ");
  return `${dayNames} at ${time}`;
}

function parseNum(s: string, fallback: number): number {
  const n = parseInt(s.replace("*/", ""), 10);
  return isNaN(n) ? fallback : n;
}

function formatTime(h: number, m: number): string {
  const ampm = h >= 12 ? "PM" : "AM";
  const hh = h % 12 || 12;
  return `${hh}:${String(m).padStart(2, "0")} ${ampm}`;
}

function RecurrenceScheduler({
  value,
  onChange,
  tradingSession,
  onTradingSessionChange,
}: {
  value: string;
  onChange: (cron: string) => void;
  tradingSession?: string | null;
  onTradingSessionChange?: (v: string | null) => void;
}) {
  const uid = useId();
  const parsed = useMemo(() => {
    const [m, h, , , dow] = value.split(/\s+/);
    const minute = parseNum(m, 0);
    const hour = parseNum(h, 7);
    let pattern: RecurrencePattern = "weekly";
    let interval = 1;
    let days: DayIdx[] = [1, 2, 3, 4, 5];

    if (m.startsWith("*/")) {
      pattern = "minutely";
      interval = parseNum(m, 15);
    } else if (h.startsWith("*/")) {
      pattern = "hourly";
      interval = parseNum(h, 1);
    } else if (dow === "*") {
      pattern = "daily";
    } else if (dow !== undefined) {
      pattern = "weekly";
      days = dow.split(",").map((d) => parseInt(d, 10) as DayIdx).filter((d) => d >= 0 && d <= 6);
      if (days.length === 0) days = [1, 2, 3, 4, 5];
    }

    return { pattern, interval, days, hour, minute };
  }, [value]);

  const [endsType, setEndsType] = useState<"never" | "after" | "on">("never");
  const [endsAfter, setEndsAfter] = useState(10);
  const [endsOn, setEndsOn] = useState("");

  function patch(p: Partial<typeof parsed>) {
    const next = { ...parsed, ...p };
    onChange(buildCron(next.pattern, next.interval, next.days, next.hour, next.minute));
  }

  function toggleDay(d: DayIdx) {
    const has = parsed.days.includes(d);
    const next = has ? parsed.days.filter((x) => x !== d) : [...parsed.days, d];
    if (next.length === 0) return;
    patch({ days: next });
  }

  const patterns: { value: RecurrencePattern; label: string }[] = [
    { value: "minutely", label: "Minutes" },
    { value: "hourly", label: "Hourly" },
    { value: "daily", label: "Daily" },
    { value: "weekly", label: "Weekly" },
  ];

  const MINUTE_OPTIONS = [1, 5, 10, 15, 20, 30, 45, 60];
  const HOUR_OPTIONS = [1, 2, 3, 4, 6, 8, 12, 24];
  const unitLabel = { minutely: "minutes", hourly: "hours", daily: "days", weekly: "weeks" }[parsed.pattern];
  const today = new Date().toLocaleDateString("en-US", { month: "numeric", day: "numeric", year: "numeric" });

  const sel =
    "max-w-full min-w-0 rounded-md border border-input bg-background px-2 py-1.5 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring sm:max-w-none";
  const row =
    "flex min-w-0 flex-col gap-1.5 px-3 py-2.5 sm:flex-row sm:items-start sm:gap-4 sm:px-4";
  const lbl = "shrink-0 text-sm text-muted-foreground pt-0.5 sm:w-28";

  return (
    <div className="w-full min-w-0 divide-y divide-border rounded-xl border border-border text-sm">

      {/* Repeats */}
      <div className={row}>
        <span className={lbl}>Repeats:</span>
        <div className="min-w-0 w-full sm:w-auto">
        <select
          value={parsed.pattern}
          onChange={(e) => {
            const p = e.target.value as RecurrencePattern;
            const patch2: Partial<typeof parsed> = { pattern: p };
            if (p === "minutely" && parsed.interval < 1) patch2.interval = 15;
            if (p === "hourly" && parsed.interval > 24) patch2.interval = 1;
            patch(patch2);
          }}
          className={sel}
        >
          {patterns.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
        </select>
        </div>
      </div>

      {/* Repeat every */}
      <div className={row}>
        <span className={lbl}>Repeat every:</span>
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          {parsed.pattern === "minutely" ? (
            <select value={parsed.interval} onChange={(e) => patch({ interval: parseInt(e.target.value) })} className={sel}>
              {MINUTE_OPTIONS.map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          ) : parsed.pattern === "hourly" ? (
            <select value={parsed.interval} onChange={(e) => patch({ interval: parseInt(e.target.value) })} className={sel}>
              {HOUR_OPTIONS.map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          ) : (
            <span className={`${sel} pointer-events-none opacity-60 select-none`}>1</span>
          )}
          <span className="text-muted-foreground">{unitLabel}</span>
        </div>
      </div>

      {/* At — daily / weekly */}
      {(parsed.pattern === "daily" || parsed.pattern === "weekly") && (
        <div className={row}>
          <span className={lbl}>At:</span>
          <div className="flex min-w-0 flex-wrap items-center gap-1.5">
            <select value={parsed.hour} onChange={(e) => patch({ hour: parseInt(e.target.value) })} className={sel}>
              {Array.from({ length: 24 }, (_, i) => {
                const ap = i >= 12 ? "PM" : "AM";
                const hh = i % 12 || 12;
                return <option key={i} value={i}>{hh}:00 {ap}</option>;
              })}
            </select>
            <span className="text-muted-foreground">:</span>
            <select value={parsed.minute} onChange={(e) => patch({ minute: parseInt(e.target.value) })} className={sel}>
              {[0, 15, 30, 45].map((m) => (
                <option key={m} value={m}>{String(m).padStart(2, "0")}</option>
              ))}
            </select>
          </div>
        </div>
      )}

      {/* Repeat on — weekly */}
      {parsed.pattern === "weekly" && (
        <div className={row}>
          <span className={lbl}>Repeat on:</span>
          <div className="flex flex-wrap gap-1">
            {DAY_ORDER.map(({ idx, label }) => {
              const active = parsed.days.includes(idx);
              return (
                <button
                  key={idx}
                  type="button"
                  onClick={() => toggleDay(idx)}
                  className={`w-8 h-8 rounded-sm text-xs font-semibold border transition-colors ${
                    active
                      ? "bg-foreground text-background border-foreground"
                      : "border-border text-muted-foreground hover:bg-muted"
                  }`}
                >
                  {label}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Starts on */}
      <div className={row}>
        <span className={lbl}>Starts on:</span>
        <span className="text-muted-foreground bg-muted/50 px-2 py-1 rounded-md">{today}</span>
      </div>

      {/* Ends */}
      <div className={row}>
        <span className={lbl}>Ends:</span>
        <div className="flex flex-col gap-2 pt-0.5">
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="radio" name={`${uid}-ends`} checked={endsType === "never"} onChange={() => setEndsType("never")} className="accent-foreground" />
            Never
          </label>
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="radio" name={`${uid}-ends`} checked={endsType === "after"} onChange={() => setEndsType("after")} className="accent-foreground" />
            After
            <input
              type="number" min={1} max={999} value={endsAfter}
              onChange={(e) => { setEndsAfter(Math.max(1, parseInt(e.target.value) || 1)); setEndsType("after"); }}
              className="w-16 rounded-md border border-input bg-background px-2 py-0.5 text-center focus:outline-none focus:ring-2 focus:ring-ring"
            />
            occurrences
          </label>
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="radio" name={`${uid}-ends`} checked={endsType === "on"} onChange={() => setEndsType("on")} className="accent-foreground" />
            On
            <input
              type="date" value={endsOn}
              onChange={(e) => { setEndsOn(e.target.value); setEndsType("on"); }}
              className="rounded-md border border-input bg-background px-2 py-0.5 focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </label>
        </div>
      </div>

      {/* Trading session gate */}
      {onTradingSessionChange && (
        <div className={row}>
          <span className={lbl}>Trading hours:</span>
          <div className="flex flex-col gap-1.5">
            <select
              value={tradingSession ?? "none"}
              onChange={(e) => onTradingSessionChange(e.target.value === "none" ? null : e.target.value)}
              className={sel}
            >
              <option value="none">Any time</option>
              <option value="nyse">NYSE session (9:30 AM – 4:00 PM ET)</option>
            </select>
            {tradingSession && tradingSession !== "none" && (
              <p className="text-xs text-muted-foreground">
                Agent only runs when the market is open. Scheduled runs outside trading hours are skipped.
              </p>
            )}
          </div>
        </div>
      )}

      {/* Summary */}
      <div className={`${row} bg-muted/30 rounded-b-xl`}>
        <span className={lbl}>Summary:</span>
        <span className="min-w-0 break-words font-semibold text-foreground">
          {describeCron(value)}
          {tradingSession && tradingSession !== "none" && (
            <span className="ml-2 font-normal text-muted-foreground">· market hours only</span>
          )}
        </span>
      </div>
    </div>
  );
}

// ── Timezone select ─────────────────────────────────────────────────────────

const _TZ_COMMON = [
  "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles",
  "America/Anchorage", "Pacific/Honolulu", "UTC",
  "Europe/London", "Europe/Paris", "Europe/Berlin", "Europe/Moscow",
  "Asia/Dubai", "Asia/Kolkata", "Asia/Shanghai", "Asia/Singapore", "Asia/Tokyo",
  "Australia/Sydney", "Pacific/Auckland",
];

const _TZ_GROUPED: { group: string; zones: string[] }[] = (() => {
  let all: string[];
  try {
    all = (Intl as unknown as { supportedValuesOf(k: string): string[] }).supportedValuesOf("timeZone");
  } catch {
    all = _TZ_COMMON;
  }
  const map = new Map<string, string[]>();
  for (const tz of all) {
    const region = tz.includes("/") ? tz.split("/")[0] : "Other";
    if (!map.has(region)) map.set(region, []);
    map.get(region)!.push(tz);
  }
  return [
    { group: "Common", zones: _TZ_COMMON.filter((z) => all.includes(z)) },
    ...[...map.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([g, z]) => ({ group: g, zones: z })),
  ];
})();

function TimezoneSelect({ value, onChange, className }: { value: string; onChange: (tz: string) => void; className?: string }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} className={className}>
      {_TZ_GROUPED.map(({ group, zones }) => (
        <optgroup key={group} label={group}>
          {zones.map((tz) => (
            <option key={tz} value={tz}>{tz.replace(/_/g, " ")}</option>
          ))}
        </optgroup>
      ))}
    </select>
  );
}

// ── Cron next-run calculator ────────────────────────────────────────────────

function expandField(field: string, min: number, max: number): number[] {
  if (field === "*") return Array.from({ length: max - min + 1 }, (_, i) => min + i);
  const vals: number[] = [];
  for (const part of field.split(",")) {
    if (part.includes("/")) {
      const [range, stepStr] = part.split("/");
      const step = parseInt(stepStr, 10);
      const [lo, hi] = range === "*" ? [min, max] : range.split("-").map(Number);
      for (let i = lo; i <= hi; i += step) vals.push(i);
    } else if (part.includes("-")) {
      const [lo, hi] = part.split("-").map(Number);
      for (let i = lo; i <= hi; i++) vals.push(i);
    } else {
      vals.push(parseInt(part, 10));
    }
  }
  return [...new Set(vals)].sort((a, b) => a - b).filter((v) => v >= min && v <= max);
}

function nextRuns(cron: string, count: number, from?: Date): Date[] {
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) return [];
  const [mField, hField, , , dowField] = parts;
  const minutes = expandField(mField, 0, 59);
  const hours = expandField(hField, 0, 23);
  const dows = expandField(dowField === "*" ? "0-6" : dowField, 0, 6);

  const cursor = new Date(from ?? Date.now());
  cursor.setSeconds(0, 0);
  cursor.setMinutes(cursor.getMinutes() + 1);

  const results: Date[] = [];
  const limit = new Date(cursor);
  limit.setDate(limit.getDate() + 8);

  while (results.length < count && cursor < limit) {
    if (!dows.includes(cursor.getDay())) {
      cursor.setDate(cursor.getDate() + 1);
      cursor.setHours(0, 0, 0, 0);
      continue;
    }
    if (!hours.includes(cursor.getHours())) {
      cursor.setHours(cursor.getHours() + 1, 0, 0, 0);
      continue;
    }
    if (!minutes.includes(cursor.getMinutes())) {
      const next = minutes.find((m) => m > cursor.getMinutes());
      if (next !== undefined) {
        cursor.setMinutes(next);
      } else {
        cursor.setHours(cursor.getHours() + 1, 0, 0, 0);
      }
      continue;
    }
    results.push(new Date(cursor));
    cursor.setMinutes(cursor.getMinutes() + 1);
  }
  return results;
}

// ── Agent color palette ─────────────────────────────────────────────────────

const AGENT_COLORS = [
  "bg-blue-500",
  "bg-emerald-500",
  "bg-violet-500",
  "bg-amber-500",
  "bg-rose-500",
  "bg-cyan-500",
  "bg-orange-500",
  "bg-pink-500",
  "bg-teal-500",
  "bg-indigo-500",
  "bg-lime-500",
  "bg-fuchsia-500",
  "bg-sky-500",
  "bg-red-500",
  "bg-green-500",
  "bg-purple-500",
  "bg-yellow-500",
  "bg-blue-400",
  "bg-emerald-400",
  "bg-violet-400",
  "bg-amber-400",
  "bg-rose-400",
  "bg-cyan-400",
  "bg-orange-400",
  "bg-pink-400",
];

const AGENT_BORDER = [
  "border-blue-400",
  "border-emerald-400",
  "border-violet-400",
  "border-amber-400",
  "border-rose-400",
  "border-cyan-400",
  "border-orange-400",
  "border-pink-400",
  "border-teal-400",
  "border-indigo-400",
  "border-lime-400",
  "border-fuchsia-400",
  "border-sky-400",
  "border-red-400",
  "border-green-400",
  "border-purple-400",
  "border-yellow-400",
  "border-blue-300",
  "border-emerald-300",
  "border-violet-300",
  "border-amber-300",
  "border-rose-300",
  "border-cyan-300",
  "border-orange-300",
  "border-pink-300",
];

const AGENT_TEXT = [
  "text-blue-600 dark:text-blue-400",
  "text-emerald-600 dark:text-emerald-400",
  "text-violet-600 dark:text-violet-400",
  "text-amber-600 dark:text-amber-400",
  "text-rose-600 dark:text-rose-400",
  "text-cyan-600 dark:text-cyan-400",
  "text-orange-600 dark:text-orange-400",
  "text-pink-600 dark:text-pink-400",
  "text-teal-600 dark:text-teal-400",
  "text-indigo-600 dark:text-indigo-400",
  "text-lime-600 dark:text-lime-400",
  "text-fuchsia-600 dark:text-fuchsia-400",
  "text-sky-600 dark:text-sky-400",
  "text-red-600 dark:text-red-400",
  "text-green-600 dark:text-green-400",
  "text-purple-600 dark:text-purple-400",
  "text-yellow-600 dark:text-yellow-400",
  "text-blue-500 dark:text-blue-300",
  "text-emerald-500 dark:text-emerald-300",
  "text-violet-500 dark:text-violet-300",
  "text-amber-500 dark:text-amber-300",
  "text-rose-500 dark:text-rose-300",
  "text-cyan-500 dark:text-cyan-300",
  "text-orange-500 dark:text-orange-300",
  "text-pink-500 dark:text-pink-300",
];

// ── Ticker picker (search + pill list) ──────────────────────────────────────

function TickerPicker({
  tickers,
  onChange,
  suggestionTickers,
}: {
  tickers: string[];
  onChange: (tickers: string[]) => void;
  suggestionTickers: string[];
}) {
  const [searchInput, setSearchInput] = useState("");

  const comboboxOptions = useMemo(() => {
    const base = new Set<string>();
    for (const t of suggestionTickers) base.add(t);
    for (const t of tickers) base.add(t);
    const q = searchInput.trim().toUpperCase();
    if (q) base.add(q);
    return Array.from(base).filter(Boolean).sort();
  }, [searchInput, suggestionTickers, tickers]);

  async function addTicker() {
    const q = searchInput.trim().toUpperCase();
    if (!q) return;
    try {
      const resolved = await relationshipsResolveTicker(searchInput.trim());
      const canonical = resolved.ok ? resolved.data.canonicalTicker : q;
      if (!tickers.includes(canonical)) {
        onChange([...tickers, canonical]);
      }
    } catch {
      if (!tickers.includes(q)) {
        onChange([...tickers, q]);
      }
    }
    setSearchInput("");
  }

  function removeTicker(t: string) {
    onChange(tickers.filter((x) => x !== t));
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <TickerSearchCombobox
          className="flex-1"
          value={searchInput}
          onChange={setSearchInput}
          onSubmit={() => void addTicker()}
          options={comboboxOptions}
          placeholder="Search ticker…"
        />
        <button
          type="button"
          onClick={() => void addTicker()}
          disabled={!searchInput.trim()}
          className="h-9 rounded-md border border-border bg-background px-3 text-xs font-medium text-foreground transition-colors hover:bg-muted disabled:opacity-40"
        >
          Add
        </button>
      </div>
      {tickers.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {tickers.map((t) => (
            <span
              key={t}
              className="inline-flex items-center gap-1 rounded-md bg-muted px-2 py-0.5 text-xs font-mono font-medium text-foreground"
            >
              {t}
              <button
                type="button"
                onClick={() => removeTicker(t)}
                className="text-muted-foreground hover:text-foreground transition-colors"
              >
                <X className="w-3 h-3" />
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Scan run picker (multi-select checkboxes) ──────────────────────────────────

function ScanRunPicker({
  linkedIds,
  onChange,
  scanRuns,
}: {
  linkedIds: number[];
  onChange: (ids: number[]) => void;
  scanRuns: ScanRunSummary[];
}) {
  if (scanRuns.length === 0) {
    return <p className="text-xs text-muted-foreground">No scan runs yet. Create one on the Screenings page.</p>;
  }

  function toggle(id: number) {
    if (linkedIds.includes(id)) {
      onChange(linkedIds.filter((x) => x !== id));
    } else {
      onChange([...linkedIds, id]);
    }
  }

  function runLabel(r: ScanRunSummary): string {
    const date = r.scan_date.slice(0, 10);
    return r.source ? `${date} · ${r.source}` : date;
  }

  return (
    <div className="flex flex-col gap-1.5 max-h-40 overflow-y-auto">
      {scanRuns.map((r) => {
        const checked = linkedIds.includes(r.id);
        return (
          <label
            key={r.id}
            className="flex items-center gap-2 text-xs cursor-pointer hover:bg-muted/50 rounded px-1.5 py-1 transition-colors"
          >
            <input
              type="checkbox"
              checked={checked}
              onChange={() => toggle(r.id)}
              className="rounded border-border"
            />
            <span className="truncate text-foreground">{runLabel(r)}</span>
          </label>
        );
      })}
    </div>
  );
}

const HOURS_SHOW = [6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20];
const DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const ROW_H = 28;

function getWeekStart(offset: number): Date {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  const dow = d.getDay();
  const diff = dow === 0 ? 6 : dow - 1;
  d.setDate(d.getDate() - diff + offset * 7);
  return d;
}

function WeekCalendar({ screenings, suggestionTickers }: { screenings: ScheduledScreening[]; suggestionTickers: string[] }) {
  const [weekOffset, setWeekOffset] = useState(0);
  const [openPill, setOpenPill] = useState<string | null>(null);
  const weekStart = useMemo(() => getWeekStart(weekOffset), [weekOffset]);

  const days = useMemo(
    () => Array.from({ length: 7 }, (_, i) => {
      const d = new Date(weekStart);
      d.setDate(d.getDate() + i);
      return d;
    }),
    [weekStart],
  );

  const isCurrentWeek = weekOffset === 0;

  const isToday = useCallback((d: Date) => {
    if (!isCurrentWeek) return false;
    const now = new Date();
    return d.getFullYear() === now.getFullYear()
      && d.getMonth() === now.getMonth()
      && d.getDate() === now.getDate();
  }, [isCurrentWeek]);

  const activeScreenings = useMemo(
    () => screenings.filter((s) => s.is_active),
    [screenings],
  );

  const runsByDay = useMemo(() => {
    const map: Record<string, { screening: ScheduledScreening; time: Date; idx: number; key: string }[]> = {};
    const from = new Date(weekStart);
    for (let i = 0; i < activeScreenings.length; i++) {
      const s = activeScreenings[i];
      const runs = nextRuns(s.schedule, 50, from);
      for (const run of runs) {
        const key = run.toDateString();
        const runKey = `${s.id}-${run.getTime()}`;
        (map[key] ??= []).push({ screening: s, time: run, idx: i, key: runKey });
      }
    }
    for (const k of Object.keys(map)) {
      map[k].sort((a, b) => a.time.getTime() - b.time.getTime());
    }
    return map;
  }, [activeScreenings, weekStart]);

  const nowLine = useMemo(() => {
    if (!isCurrentWeek) return null;
    const n = new Date();
    const h = n.getHours();
    const m = n.getMinutes();
    if (h < HOURS_SHOW[0] || h > HOURS_SHOW[HOURS_SHOW.length - 1]) return null;
    const y = (h - HOURS_SHOW[0]) * ROW_H + (m / 60) * ROW_H;
    return y;
  }, [isCurrentWeek]);

  const fmtTime = (d: Date) => {
    const hh = d.getHours() % 12 || 12;
    const mm = String(d.getMinutes()).padStart(2, "0");
    const ap = d.getHours() >= 12 ? "PM" : "AM";
    return `${hh}:${mm} ${ap}`;
  };

  const navBtn = "p-1 rounded-md border border-border text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-30 disabled:pointer-events-none";

  if (activeScreenings.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-border px-6 py-14 text-center">
        <CalendarDays className="mx-auto w-8 h-8 text-muted-foreground/30 mb-3" />
        <p className="text-sm font-medium text-foreground/70">No scheduled runs</p>
        <p className="mt-1 text-xs text-muted-foreground">
          Create and activate an agent to see its execution schedule on the calendar.
        </p>
      </div>
    );
  }

  return (
    <div className="min-w-0 overflow-hidden rounded-2xl border border-border bg-card">
      {/* Header with nav */}
      <div className="flex flex-col gap-2 border-b border-border px-3 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-5">
        <p className="min-w-0 shrink-0 text-xs font-semibold uppercase tracking-widest text-foreground/60">
          Execution calendar
        </p>
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setWeekOffset((w) => w - 1)}
            className={navBtn}
            title="Previous week"
          >
            <ChevronLeft className="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            onClick={() => setWeekOffset(0)}
            disabled={isCurrentWeek}
            className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${
              isCurrentWeek
                ? "text-muted-foreground/40 cursor-default"
                : "border border-border text-muted-foreground hover:bg-muted hover:text-foreground"
            }`}
          >
            Today
          </button>
          <button
            type="button"
            onClick={() => setWeekOffset((w) => w + 1)}
            className={navBtn}
            title="Next week"
          >
            <ChevronRight className="w-3.5 h-3.5" />
          </button>
          <span className="text-xs text-muted-foreground/60 sm:ml-1 break-words">
            {weekStart.toLocaleDateString(undefined, { month: "short", day: "numeric" })}
            {" – "}
            {days[6].toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}
          </span>
        </div>
      </div>

      <div className="min-w-0 overflow-x-auto">
        <div className="w-full min-w-0">
          {/* Day headers — fluid columns so the grid fits the viewport */}
          <div className="grid grid-cols-[3.5rem_repeat(7,minmax(0,1fr))] border-b border-border">
            <div className="shrink-0" aria-hidden />
            {days.map((d, i) => (
              <div
                key={i}
                className={`min-w-0 px-0.5 py-2 text-center text-[10px] font-medium leading-tight sm:text-xs ${
                  isToday(d) ? "text-foreground bg-foreground/[0.03]" : "text-muted-foreground"
                }`}
              >
                <span className="block max-w-full truncate">{DAY_LABELS[i]}</span>
                <span
                  className={`mt-0.5 inline-flex min-h-[1.25rem] min-w-[1.25rem] items-center justify-center rounded-full text-[9px] sm:text-[10px] ${
                    isToday(d) ? "bg-foreground text-background" : ""
                  }`}
                >
                  {d.getDate()}
                </span>
              </div>
            ))}
          </div>

          {/* Time grid */}
          <div className="relative min-w-0">
            {HOURS_SHOW.map((hour) => (
              <div
                key={hour}
                className="grid grid-cols-[3.5rem_repeat(7,minmax(0,1fr))] border-b border-border/50 last:border-b-0"
              >
                <div className="shrink-0 pr-2 text-right text-[10px] leading-none text-muted-foreground/50" style={{ height: ROW_H, paddingTop: 2 }}>
                  {hour % 12 || 12}{hour >= 12 ? "p" : "a"}
                </div>
                {days.map((d, colIdx) => {
                  const dayRuns = runsByDay[d.toDateString()] ?? [];
                  const inHour = dayRuns.filter((r) => r.time.getHours() === hour);
                  const byMinute = new Map<number, typeof inHour>();
                  for (const r of inHour) {
                    const m = r.time.getMinutes();
                    const list = byMinute.get(m);
                    if (list) list.push(r);
                    else byMinute.set(m, [r]);
                  }
                  const minuteGroups = Array.from(byMinute.entries()).sort(([a], [b]) => a - b);

                  return (
                    <div
                      key={colIdx}
                      className={`relative min-w-0 ${isToday(d) ? "bg-foreground/[0.02]" : ""}`}
                      style={{ height: ROW_H }}
                    >
                      {minuteGroups.map(([minute, runsInMinute]) => {
                        const sorted = [...runsInMinute].sort((a, b) =>
                          a.screening.id.localeCompare(b.screening.id),
                        );
                        return (
                          <div
                            key={minute}
                            className="absolute left-0.5 right-0.5 z-10 flex min-w-0 gap-px"
                            style={{ top: (minute / 60) * ROW_H }}
                          >
                            {sorted.map((run) => {
                              const isOpen = openPill === run.key;
                              return (
                                <div key={run.key} className="min-w-0 flex-1 basis-0">
                                  <div
                                    onDoubleClick={() => setOpenPill(isOpen ? null : run.key)}
                                    className={`cursor-pointer select-none overflow-hidden rounded border ${AGENT_BORDER[run.idx % AGENT_BORDER.length]} ${AGENT_COLORS[run.idx % AGENT_COLORS.length]}/20 transition-all hover:brightness-110`}
                                    style={{ height: 20 }}
                                  >
                                    <span className={`block truncate px-1 text-[10px] font-semibold leading-[20px] sm:px-1.5 sm:text-[11px] ${AGENT_TEXT[run.idx % AGENT_TEXT.length]}`}>
                                      {fmtTime(run.time)}
                                      <span className="ml-0.5 font-normal opacity-70 sm:ml-1">{run.screening.name}</span>
                                    </span>
                                  </div>

                                  {isOpen && (
                                    <PillPopover
                                      screening={run.screening}
                                      colorIdx={run.idx}
                                      onClose={() => setOpenPill(null)}
                                      suggestionTickers={suggestionTickers}
                                    />
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        );
                      })}
                    </div>
                  );
                })}
              </div>
            ))}

            {/* Now line */}
            {nowLine !== null && (() => {
              const n = new Date();
              const todayIdx = n.getDay() === 0 ? 6 : n.getDay() - 1;
              return (
                <div
                  className="absolute pointer-events-none"
                  style={{
                    left: `calc(${todayIdx} * (100% - 3.5rem) / 7 + 3.5rem)`,
                    width: `calc((100% - 3.5rem) / 7)`,
                    top: nowLine,
                    height: 2,
                  }}
                >
                  <div className="w-full h-full bg-rose-500 rounded-full" />
                  <div className="absolute -left-1 -top-[3px] w-2 h-2 rounded-full bg-rose-500" />
                </div>
              );
            })()}
          </div>
        </div>
      </div>

      {/* Legend */}
      <div className="flex flex-wrap items-center gap-3 border-t border-border px-3 py-3 sm:px-5">
        {activeScreenings.map((s, i) => (
          <div key={s.id} className="flex items-center gap-1.5">
            <div className={`w-2.5 h-2.5 rounded-sm ${AGENT_COLORS[i % AGENT_COLORS.length]}`} />
            <span className="text-xs text-muted-foreground truncate max-w-[140px]">{s.name}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Pill popover (double-click actions) ─────────────────────────────────────

function PillPopover({
  screening,
  colorIdx,
  onClose,
  suggestionTickers,
}: {
  screening: ScheduledScreening;
  colorIdx: number;
  onClose: () => void;
  suggestionTickers: string[];
}) {
  const [mode, setMode] = useState<"menu" | "edit">("menu");
  const [toggling, setToggling] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<ScreeningResult | null>(null);
  const [testError, setTestError] = useState<string | null>(null);

  const [editName, setEditName] = useState(screening.name);
  const [editPrompt, setEditPrompt] = useState(screening.prompt);
  const [editSchedule, setEditSchedule] = useState(screening.schedule);
  const [editTimezone, setEditTimezone] = useState(screening.timezone);
  const [editTradingSession, setEditTradingSession] = useState<string | null>(screening.trading_session ?? null);
  const [editTickers, setEditTickers] = useState<string[]>(screening.tickers ?? []);
  const [editLinkedScanRunIds, setEditLinkedScanRunIds] = useState<number[]>(screening.linked_scan_run_ids ?? []);
  const [editScanFilters, setEditScanFilters] = useState<ScreeningsFilters>((screening.scan_filters as ScreeningsFilters | null) ?? DEFAULT_SCREENINGS_FILTERS);
  const [editConditionEnabled, setEditConditionEnabled] = useState<boolean>(screening.condition_enabled ?? false);
  const [editTriggerCondition, setEditTriggerCondition] = useState<string>(screening.trigger_condition ?? "");
  const [scanRuns, setScanRuns] = useState<ScanRunSummary[]>([]);
  const [saving, setSaving] = useState(false);
  const [saveErr, setSaveErr] = useState<string | null>(null);

  useEffect(() => {
    void listScanRuns().then((res) => {
      if (res.ok) setScanRuns(res.data);
    });
  }, []);

  async function handleToggle() {
    setToggling(true);
    await toggleScreening(screening.id, !screening.is_active);
    onClose();
    window.location.reload();
  }

  async function handleDelete() {
    if (!confirm(`Delete "${screening.name}"?`)) return;
    setDeleting(true);
    await deleteScheduledScreening(screening.id);
    onClose();
    window.location.reload();
  }

  async function handleTestRun() {
    setTesting(true);
    setTestResult(null);
    setTestError(null);
    const req = await testRunScreening(screening.id);
    if (!req.ok) {
      setTestError(req.error);
      setTesting(false);
      return;
    }
    const deadline = Date.now() + 3 * 60 * 1000;
    while (Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 3000));
      const poll = await pollTestResult(screening.id);
      if (!poll.ok) continue;
      if (poll.data) {
        const runAt = new Date(poll.data.run_at).getTime();
        if (runAt > Date.now() - 3 * 60 * 1000) {
          setTestResult(poll.data);
          setTesting(false);
          return;
        }
      }
    }
    setTestError("Timed out — agent may not be running.");
    setTesting(false);
  }

  async function handleSave() {
    if (!editPrompt.trim()) return;
    if (editConditionEnabled && !editTriggerCondition.trim()) {
      setSaveErr("Trigger condition is required when 'Only send when condition is met' is enabled.");
      return;
    }
    setSaving(true);
    setSaveErr(null);
    const res = await updateScheduledScreening(screening.id, {
      name: editName.trim() || "Untitled Agent",
      prompt: editPrompt.trim(),
      schedule: editSchedule,
      timezone: editTimezone,
      tickers: editTickers,
      linked_scan_run_ids: editLinkedScanRunIds,
      scan_filters: countScreeningsFilterRules(editScanFilters) > 0 ? editScanFilters : null,
      trading_session: (editTradingSession as TradingSession) ?? "none",
      condition_enabled: editConditionEnabled,
      trigger_condition: editConditionEnabled ? editTriggerCondition.trim() : null,
    });
    if (res.ok) {
      onClose();
      window.location.reload();
    } else {
      setSaveErr(res.error);
      setSaving(false);
    }
  }

  const actionBtn = "flex items-center gap-1.5 w-full px-2.5 py-1.5 text-xs rounded-md transition-colors";
  const inputClass = "w-full rounded-md border border-input bg-background px-2.5 py-1.5 text-xs placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-50";

  if (mode === "edit") {
    return (
      <div className="absolute left-0 top-[22px] z-50 w-[min(18rem,calc(100vw-2rem))] max-w-[calc(100vw-2rem)] rounded-xl border border-border bg-card shadow-lg shadow-black/10 overflow-hidden">
        <div className="px-3 pt-3 pb-2 border-b border-border flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className={`w-2 h-2 rounded-full ${AGENT_COLORS[colorIdx % AGENT_COLORS.length]}`} />
            <span className="text-xs font-semibold text-foreground">Edit agent</span>
          </div>
          <button type="button" onClick={() => setMode("menu")} className="text-xs text-muted-foreground/50 hover:text-muted-foreground transition-colors">Back</button>
        </div>
        <div className="px-3 py-3 flex flex-col gap-3">
          {saveErr && <p className="text-[11px] text-destructive">{saveErr}</p>}
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Name</label>
            <input type="text" value={editName} onChange={(e) => setEditName(e.target.value)} className={inputClass} />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Prompt</label>
            <textarea value={editPrompt} onChange={(e) => setEditPrompt(e.target.value)} rows={4} className={inputClass} />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Recurrence</label>
            <RecurrenceScheduler value={editSchedule} onChange={setEditSchedule} tradingSession={editTradingSession} onTradingSessionChange={setEditTradingSession} />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Timezone</label>
            <TimezoneSelect value={editTimezone} onChange={setEditTimezone} className={inputClass} />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Tickers</label>
            <TickerPicker
              tickers={editTickers}
              onChange={setEditTickers}
              suggestionTickers={suggestionTickers}
            />
          </div>
          {scanRuns.length > 0 && (
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Linked screenings</label>
              <ScanRunPicker
                linkedIds={editLinkedScanRunIds}
                onChange={setEditLinkedScanRunIds}
                scanRuns={scanRuns}
              />
            </div>
          )}
          {editLinkedScanRunIds.length > 0 && (
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide flex items-center gap-1">
                <Filter className="w-3 h-3" /> Filter tickers
              </label>
              <AgentFilterSection
                linkedScanRunIds={editLinkedScanRunIds}
                filters={editScanFilters}
                setFilters={setEditScanFilters}
              />
            </div>
          )}
          <div className="flex flex-col gap-1.5">
            <label className="inline-flex items-start gap-2 text-[11px] font-medium text-foreground">
              <input
                type="checkbox"
                checked={editConditionEnabled}
                onChange={(e) => setEditConditionEnabled(e.target.checked)}
                className="mt-0.5 h-3 w-3 rounded border-input"
              />
              <span>
                Only send when condition is met
                <span className="ml-1 normal-case font-normal text-muted-foreground/60">
                  agent only triggers if your condition is satisfied
                </span>
              </span>
            </label>
            {editConditionEnabled && (
              <textarea
                value={editTriggerCondition}
                onChange={(e) => setEditTriggerCondition(e.target.value)}
                rows={3}
                placeholder="e.g. At least one holding has news with sentiment_score below -0.4 today."
                className={inputClass}
              />
            )}
          </div>
          <div className="flex items-center gap-2 pt-1 border-t border-border">
            <button
              type="button"
              onClick={() => void handleSave()}
              disabled={saving || !editPrompt.trim() || (editConditionEnabled && !editTriggerCondition.trim())}
              className="inline-flex items-center gap-1.5 rounded-md bg-foreground px-3 py-1.5 text-xs font-medium text-background transition-opacity hover:opacity-90 disabled:opacity-40 disabled:pointer-events-none"
            >
              {saving ? "Saving…" : "Save"}
            </button>
            <button type="button" onClick={onClose} className="rounded-md border border-border px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-muted">
              Cancel
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="absolute left-0 top-[22px] z-50 w-[min(14rem,calc(100vw-2rem))] max-w-[calc(100vw-2rem)] rounded-xl border border-border bg-card shadow-lg shadow-black/10 overflow-hidden">
      {/* Agent header */}
      <div className="px-3 pt-3 pb-2 border-b border-border">
        <div className="flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full ${AGENT_COLORS[colorIdx % AGENT_COLORS.length]}`} />
          <span className="text-xs font-semibold text-foreground truncate">{screening.name}</span>
        </div>
        <p className="mt-1 break-words text-[11px] text-muted-foreground">
          {describeCron(screening.schedule)} &middot; {screening.timezone}
          {screening.trading_session && screening.trading_session !== "none" && screening.trading_session !== null && (
            <span className="ml-1.5 inline-flex items-center rounded bg-foreground/10 px-1 py-px font-medium text-foreground/70">market hours</span>
          )}
        </p>
      </div>

      {/* Actions */}
      <div className="p-1.5 flex flex-col gap-0.5">
        <button
          type="button"
          onClick={() => void handleTestRun()}
          disabled={testing}
          className={`${actionBtn} ${testing ? "text-muted-foreground" : "text-amber-600 dark:text-amber-400 hover:bg-amber-500/10"}`}
        >
          {testing ? <Loader2 className="w-3 h-3 animate-spin" /> : <Zap className="w-3 h-3" />}
          {testing ? "Running..." : "Test run now"}
        </button>
        <button
          type="button"
          onClick={() => setMode("edit")}
          className={`${actionBtn} text-muted-foreground hover:bg-muted hover:text-foreground`}
        >
          <Pencil className="w-3 h-3" />
          Edit agent
        </button>
        <button
          type="button"
          onClick={() => void handleToggle()}
          disabled={toggling}
          className={`${actionBtn} text-muted-foreground hover:bg-muted hover:text-foreground`}
        >
          {toggling ? <Loader2 className="w-3 h-3 animate-spin" /> : screening.is_active ? <Pause className="w-3 h-3" /> : <Play className="w-3 h-3" />}
          {screening.is_active ? "Pause agent" : "Resume agent"}
        </button>
        <button
          type="button"
          onClick={() => void handleDelete()}
          disabled={deleting}
          className={`${actionBtn} text-destructive/80 hover:bg-destructive/10 hover:text-destructive`}
        >
          {deleting ? <Loader2 className="w-3 h-3 animate-spin" /> : <Trash2 className="w-3 h-3" />}
          Delete agent
        </button>
      </div>

      {/* Test result */}
      {(testResult || testError) && (
        <div className="border-t border-border px-3 py-2">
          {testError && <p className="text-[11px] text-destructive">{testError}</p>}
          {testResult && (
            <div>
              <span className={`text-[11px] font-medium ${testResult.triggered ? "text-amber-600 dark:text-amber-400" : "text-muted-foreground"}`}>
                {testResult.triggered ? "Triggered" : "Not triggered"}
              </span>
              {testResult.summary && (
                <p className="mt-0.5 text-[11px] text-foreground/70 leading-relaxed line-clamp-3">{testResult.summary}</p>
              )}
            </div>
          )}
        </div>
      )}

      {/* Dismiss */}
      <div className="border-t border-border px-3 py-2">
        <button
          type="button"
          onClick={onClose}
          className="text-xs text-muted-foreground/50 hover:text-muted-foreground transition-colors"
        >
          Close
        </button>
      </div>
    </div>
  );
}

// ── Agent filter section ─────────────────────────────────────────────────────

type SetFilters = (f: ScreeningsFilters | ((prev: ScreeningsFilters) => ScreeningsFilters)) => void;

function AgentFilterSection({
  linkedScanRunIds,
  filters,
  setFilters,
}: {
  linkedScanRunIds: number[];
  filters: ScreeningsFilters;
  setFilters: SetFilters;
}) {
  const [rows, setRows] = useState<AgentScanRow[]>([]);
  const [loadingRows, setLoadingRows] = useState(false);
  const [filterOpen, setFilterOpen] = useState(false);

  const runIdsKey = linkedScanRunIds.join(",");
  useEffect(() => {
    if (linkedScanRunIds.length === 0) { setRows([]); return; }
    setLoadingRows(true);
    void listScanRowsForRuns(linkedScanRunIds).then((res) => {
      setLoadingRows(false);
      if (res.ok) setRows(res.data);
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runIdsKey]);

  const allKeys = useMemo(() => collectAllRowDataKeys(rows), [rows]);
  const orderedKeys = useMemo(() => orderedDataColumnKeys(allKeys), [allKeys]);
  const boolKeys = useMemo(() => inferBooleanFilterKeys(rows, orderedKeys), [rows, orderedKeys]);
  const numKeys = useMemo(() => inferNumericFilterKeys(rows, orderedKeys), [rows, orderedKeys]);
  const categoricalStringCols = useMemo(() => {
    return orderedKeys
      .filter((k) => !boolKeys.includes(k) && !numKeys.includes(k))
      .map((k) => ({ key: k, options: uniqueStringValuesForKey(rows, k) }))
      .filter((c) => c.options.length > 0 && c.options.length <= MAX_CATEGORICAL_STRING_OPTIONS);
  }, [rows, orderedKeys, boolKeys, numKeys]);
  const freeStringKeys = useMemo(() => {
    const catKeys = new Set(categoricalStringCols.map((c) => c.key));
    return orderedKeys.filter((k) => !boolKeys.includes(k) && !numKeys.includes(k) && !catKeys.has(k));
  }, [orderedKeys, boolKeys, numKeys, categoricalStringCols]);

  const filteredSymbols = useMemo(() => {
    const filtered = applyRowDataFilters(rows, filters);
    const seen = new Set<string>();
    const out: string[] = [];
    for (const r of filtered) {
      if (r.symbol && !seen.has(r.symbol)) { seen.add(r.symbol); out.push(r.symbol); }
    }
    return out;
  }, [rows, filters]);

  const totalSymbols = useMemo(() => {
    const seen = new Set(rows.map((r) => r.symbol).filter(Boolean));
    return seen.size;
  }, [rows]);

  if (linkedScanRunIds.length === 0) return null;

  return (
    <div className="flex flex-col gap-2">
      {loadingRows ? (
        <p className="text-xs text-muted-foreground flex items-center gap-1.5">
          <Loader2 className="w-3 h-3 animate-spin" /> Loading screening rows…
        </p>
      ) : (
        <>
          <AddFilterWidget
            open={filterOpen}
            onOpen={() => setFilterOpen(true)}
            onClose={() => setFilterOpen(false)}
            filters={filters}
            setFilters={setFilters}
            noteStageOptions={[]}
            noteTagOptions={[]}
            boolKeys={boolKeys}
            numKeys={numKeys}
            categoricalStringCols={categoricalStringCols}
            freeStringKeys={freeStringKeys}
          />
          <ScreeningsFilterBar filters={filters} setFilters={setFilters} />
          <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
            <span className="font-semibold text-foreground tabular-nums">{filteredSymbols.length}</span>
            <span>of {totalSymbols} tickers match</span>
            {filteredSymbols.length > 0 && (
              <>
                <span className="text-border mx-0.5">·</span>
                {filteredSymbols.slice(0, 10).map((s) => (
                  <span key={s} className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px] text-foreground/80">{s}</span>
                ))}
                {filteredSymbols.length > 10 && (
                  <span>+{filteredSymbols.length - 10} more</span>
                )}
              </>
            )}
          </div>
        </>
      )}
    </div>
  );
}

// ── Create form ─────────────────────────────────────────────────────────────

function CreateForm({ onClose, atLimit, suggestionTickers }: { onClose: () => void; atLimit: boolean; suggestionTickers: string[] }) {
  const [name, setName] = useState("");
  const [prompt, setPrompt] = useState("");
  const [schedule, setSchedule] = useState("0 7 * * 1-5");
  const [timezone, setTimezone] = useState("America/New_York");
  const [tradingSession, setTradingSession] = useState<string | null>(null);
  const [tickers, setTickers] = useState<string[]>([]);
  const [linkedScanRunIds, setLinkedScanRunIds] = useState<number[]>([]);
  const [scanFilters, setScanFilters] = useState<ScreeningsFilters>(DEFAULT_SCREENINGS_FILTERS);
  const [conditionEnabled, setConditionEnabled] = useState(false);
  const [triggerCondition, setTriggerCondition] = useState("");
  const [scanRuns, setScanRuns] = useState<ScanRunSummary[]>([]);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    void listScanRuns().then((res) => {
      if (res.ok) setScanRuns(res.data);
    });
  }, []);

  async function handleSave() {
    if (!prompt.trim()) return;
    setSaving(true);
    setErr(null);
    if (conditionEnabled && !triggerCondition.trim()) {
      setErr("Trigger condition is required when 'Only send when condition is met' is enabled.");
      setSaving(false);
      return;
    }
    const res = await createScheduledScreening({
      name: name.trim() || "Untitled Agent",
      prompt: prompt.trim(),
      schedule,
      timezone,
      tickers,
      linked_scan_run_ids: linkedScanRunIds,
      scan_filters: countScreeningsFilterRules(scanFilters) > 0 ? scanFilters : null,
      trading_session: (tradingSession as TradingSession) ?? "none",
      condition_enabled: conditionEnabled,
      trigger_condition: conditionEnabled ? triggerCondition.trim() : null,
    });
    if (res.ok) {
      onClose();
      window.location.reload();
    } else {
      setErr(res.error);
      setSaving(false);
    }
  }

  const inputClass =
    "w-full rounded-md border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-50";

  return (
    <div className="min-w-0 overflow-hidden rounded-2xl border border-border bg-card">
      <div className="border-b border-border px-4 py-3 sm:px-5">
        <p className="text-xs font-semibold uppercase tracking-widest text-amber-500">New agent</p>
      </div>
      <div className="flex min-w-0 flex-col gap-4 px-4 py-5 sm:px-5">
        {err && (
          <p className="text-sm text-destructive">{err}</p>
        )}
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Name</label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Airline Macro Watch"
            className={inputClass}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
            Prompt
            <span className="ml-2 normal-case font-normal text-muted-foreground/60">
              describe what to watch for in plain English
            </span>
          </label>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            rows={5}
            placeholder={`e.g. Check MACRO_SENSITIVITY cluster trend for airline stocks (AAL, DAL, UAL). Alert me when the cluster score drops below -0.3. Include which dimensions are driving it and any headlines from the last 14 hours.`}
            className={inputClass}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
            Recurrence
          </label>
          <RecurrenceScheduler value={schedule} onChange={setSchedule} tradingSession={tradingSession} onTradingSessionChange={setTradingSession} />
        </div>
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Timezone</label>
          <TimezoneSelect value={timezone} onChange={setTimezone} className={inputClass} />
        </div>
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
            Tickers
            <span className="ml-2 normal-case font-normal text-muted-foreground/60">
              focus the agent on specific symbols
            </span>
          </label>
          <TickerPicker
            tickers={tickers}
            onChange={setTickers}
            suggestionTickers={suggestionTickers}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
            Linked screenings
            <span className="ml-2 normal-case font-normal text-muted-foreground/60">
              include context from your scan runs
            </span>
          </label>
          <ScanRunPicker
            linkedIds={linkedScanRunIds}
            onChange={setLinkedScanRunIds}
            scanRuns={scanRuns}
          />
        </div>
        {linkedScanRunIds.length > 0 && (
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide flex items-center gap-1.5">
              <Filter className="w-3 h-3" />
              Filter tickers
              <span className="normal-case font-normal text-muted-foreground/60">narrow which tickers the agent focuses on</span>
            </label>
            <AgentFilterSection
              linkedScanRunIds={linkedScanRunIds}
              filters={scanFilters}
              setFilters={setScanFilters}
            />
          </div>
        )}
        <div className="flex flex-col gap-1.5">
          <label className="inline-flex items-center gap-2 text-xs font-medium text-foreground">
            <input
              type="checkbox"
              checked={conditionEnabled}
              onChange={(e) => setConditionEnabled(e.target.checked)}
              className="h-3.5 w-3.5 rounded border-input"
            />
            Only send when a condition is met
            <span className="normal-case font-normal text-muted-foreground/60">
              the agent only triggers a Telegram alert if the condition you write is satisfied
            </span>
          </label>
          {conditionEnabled && (
            <textarea
              value={triggerCondition}
              onChange={(e) => setTriggerCondition(e.target.value)}
              rows={3}
              placeholder="e.g. At least one of my holdings has a same-day news article with sentiment_score below -0.4. OR: Relative volume on AAPL or NVDA is above 2x their 20-day average."
              className={inputClass}
            />
          )}
        </div>
        <div className="flex min-w-0 flex-col gap-3 border-t border-border pt-3 sm:flex-row sm:flex-wrap sm:items-center sm:gap-3 sm:pt-1">
          <div className="flex min-w-0 flex-wrap items-center gap-2 sm:gap-3">
            <button
              type="button"
              onClick={() => void handleSave()}
              disabled={saving || atLimit || !prompt.trim() || (conditionEnabled && !triggerCondition.trim())}
              className="inline-flex items-center gap-1.5 rounded-md bg-foreground px-4 py-2 text-sm font-medium text-background transition-opacity hover:opacity-90 disabled:opacity-40 disabled:pointer-events-none"
            >
              {saving ? "Saving…" : "Save & activate"}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="rounded-md border border-border px-4 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted"
            >
              Cancel
            </button>
          </div>
          <p className="min-w-0 text-xs text-muted-foreground/60 sm:ml-auto">
            Alerts delivered to Telegram (if connected) and shown here
          </p>
        </div>
      </div>
    </div>
  );
}

function AgentCard({ screening, suggestionTickers }: { screening: ScheduledScreening; suggestionTickers: string[] }) {
  const [editing, setEditing] = useState(false);
  const [toggling, setToggling] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<ScreeningResult | null>(null);
  const [testError, setTestError] = useState<string | null>(null);

  const [editName, setEditName] = useState(screening.name);
  const [editPrompt, setEditPrompt] = useState(screening.prompt);
  const [editSchedule, setEditSchedule] = useState(screening.schedule);
  const [editTimezone, setEditTimezone] = useState(screening.timezone);
  const [editTradingSession, setEditTradingSession] = useState<string | null>(screening.trading_session ?? null);
  const [editTickers, setEditTickers] = useState<string[]>(screening.tickers ?? []);
  const [editLinkedScanRunIds, setEditLinkedScanRunIds] = useState<number[]>(screening.linked_scan_run_ids ?? []);
  const [editScanFilters, setEditScanFilters] = useState<ScreeningsFilters>((screening.scan_filters as ScreeningsFilters | null) ?? DEFAULT_SCREENINGS_FILTERS);
  const [editConditionEnabled, setEditConditionEnabled] = useState<boolean>(screening.condition_enabled ?? false);
  const [editTriggerCondition, setEditTriggerCondition] = useState<string>(screening.trigger_condition ?? "");
  const [scanRuns, setScanRuns] = useState<ScanRunSummary[]>([]);
  const [saving, setSaving] = useState(false);
  const [saveErr, setSaveErr] = useState<string | null>(null);

  useEffect(() => {
    void listScanRuns().then((res) => {
      if (res.ok) setScanRuns(res.data);
    });
  }, []);

  async function handleToggle() {
    setToggling(true);
    await toggleScreening(screening.id, !screening.is_active);
    window.location.reload();
  }

  async function handleDelete() {
    if (!confirm(`Delete "${screening.name}"?`)) return;
    setDeleting(true);
    await deleteScheduledScreening(screening.id);
    window.location.reload();
  }

  async function handleSave() {
    if (!editPrompt.trim()) return;
    if (editConditionEnabled && !editTriggerCondition.trim()) {
      setSaveErr("Trigger condition is required when 'Only send when condition is met' is enabled.");
      return;
    }
    setSaving(true);
    setSaveErr(null);
    const res = await updateScheduledScreening(screening.id, {
      name: editName.trim() || "Untitled Agent",
      prompt: editPrompt.trim(),
      schedule: editSchedule,
      timezone: editTimezone,
      tickers: editTickers,
      linked_scan_run_ids: editLinkedScanRunIds,
      scan_filters: countScreeningsFilterRules(editScanFilters) > 0 ? editScanFilters : null,
      trading_session: (editTradingSession as TradingSession) ?? "none",
      condition_enabled: editConditionEnabled,
      trigger_condition: editConditionEnabled ? editTriggerCondition.trim() : null,
    });
    if (res.ok) {
      setEditing(false);
      window.location.reload();
    } else {
      setSaveErr(res.error);
      setSaving(false);
    }
  }

  async function handleTestRun() {
    setTesting(true);
    setTestResult(null);
    setTestError(null);

    const req = await testRunScreening(screening.id);
    if (!req.ok) {
      setTestError(req.error);
      setTesting(false);
      return;
    }

    const deadline = Date.now() + 3 * 60 * 1000;
    while (Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 3000));
      const poll = await pollTestResult(screening.id);
      if (!poll.ok) continue;
      if (poll.data) {
        const runAt = new Date(poll.data.run_at).getTime();
        if (runAt > Date.now() - 3 * 60 * 1000) {
          setTestResult(poll.data);
          setTesting(false);
          return;
        }
      }
    }

    setTestError("Timed out waiting for result — the Mac Mini agent may not be running.");
    setTesting(false);
  }

  const scheduleLabel = describeCron(screening.schedule);
  const inputClass = "w-full rounded-md border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-50";

  if (editing) {
    return (
      <div className="min-w-0 overflow-hidden rounded-2xl border border-border bg-card">
        <div className="flex items-center justify-between border-b border-border px-4 py-3 sm:px-5">
          <div className="flex items-center gap-2">
            <div className={`w-2 h-2 rounded-full ${screening.is_active ? "bg-emerald-500" : "bg-muted-foreground/30"}`} />
            <span className="text-xs font-semibold uppercase tracking-widest text-amber-500">Edit agent</span>
          </div>
          <button type="button" onClick={() => setEditing(false)} className="text-xs text-muted-foreground hover:text-foreground transition-colors">Cancel</button>
        </div>
        <div className="flex min-w-0 flex-col gap-4 px-4 py-5 sm:px-5">
          {saveErr && <p className="text-sm text-destructive">{saveErr}</p>}
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Name</label>
            <input type="text" value={editName} onChange={(e) => setEditName(e.target.value)} className={inputClass} />
          </div>
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Prompt</label>
            <textarea value={editPrompt} onChange={(e) => setEditPrompt(e.target.value)} rows={4} className={inputClass} />
          </div>
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Recurrence</label>
            <RecurrenceScheduler value={editSchedule} onChange={setEditSchedule} tradingSession={editTradingSession} onTradingSessionChange={setEditTradingSession} />
            </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Timezone</label>
            <TimezoneSelect value={editTimezone} onChange={setEditTimezone} className={inputClass} />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
              Tickers
              <span className="ml-2 normal-case font-normal text-muted-foreground/60">focus the agent on specific symbols</span>
            </label>
            <TickerPicker tickers={editTickers} onChange={setEditTickers} suggestionTickers={suggestionTickers} />
          </div>
          {scanRuns.length > 0 && (
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Linked screenings
                <span className="ml-2 normal-case font-normal text-muted-foreground/60">pull context from a scan run</span>
              </label>
              <ScanRunPicker linkedIds={editLinkedScanRunIds} onChange={setEditLinkedScanRunIds} scanRuns={scanRuns} />
            </div>
          )}
          {editLinkedScanRunIds.length > 0 && (
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide flex items-center gap-1.5">
                <Filter className="w-3 h-3" />
                Filter tickers
                <span className="normal-case font-normal text-muted-foreground/60">narrow which tickers the agent focuses on</span>
              </label>
              <AgentFilterSection
                linkedScanRunIds={editLinkedScanRunIds}
                filters={editScanFilters}
                setFilters={setEditScanFilters}
              />
            </div>
          )}
          <div className="flex flex-col gap-1.5">
            <label className="inline-flex items-center gap-2 text-xs font-medium text-foreground">
              <input
                type="checkbox"
                checked={editConditionEnabled}
                onChange={(e) => setEditConditionEnabled(e.target.checked)}
                className="h-3.5 w-3.5 rounded border-input"
              />
              Only send when a condition is met
              <span className="normal-case font-normal text-muted-foreground/60">
                the agent only triggers a Telegram alert if the condition you write is satisfied
              </span>
            </label>
            {editConditionEnabled && (
              <textarea
                value={editTriggerCondition}
                onChange={(e) => setEditTriggerCondition(e.target.value)}
                rows={3}
                placeholder="e.g. At least one of my holdings has a same-day news article with sentiment_score below -0.4."
                className={inputClass}
              />
            )}
          </div>
          <div className="flex min-w-0 flex-wrap items-center gap-2 border-t border-border pt-3 sm:gap-3 sm:pt-1">
            <button
              type="button"
              onClick={() => void handleSave()}
              disabled={saving || !editPrompt.trim() || (editConditionEnabled && !editTriggerCondition.trim())}
              className="inline-flex items-center gap-1.5 rounded-md bg-foreground px-4 py-2 text-sm font-medium text-background transition-opacity hover:opacity-90 disabled:opacity-40 disabled:pointer-events-none"
            >
              {saving ? "Saving…" : "Save changes"}
            </button>
            <button type="button" onClick={() => setEditing(false)} className="rounded-md border border-border px-4 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted">
              Cancel
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={`rounded-2xl border bg-card transition-opacity ${deleting ? "opacity-50 pointer-events-none" : "border-border"}`}>
      <div className="flex min-w-0 flex-col gap-3 px-4 py-4 sm:flex-row sm:items-start sm:gap-3 sm:px-5">
        <div className="flex min-w-0 flex-1 items-start gap-3">
          <div className={`mt-1 h-2 w-2 shrink-0 rounded-full ${screening.is_active ? "bg-emerald-500" : "bg-muted-foreground/30"}`} />

          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-sm text-foreground truncate">{screening.name}</span>
            <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${
              screening.is_active
                ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                : "bg-muted text-muted-foreground"
            }`}>
              {screening.is_active ? "Active" : "Paused"}
            </span>
            {screening.last_triggered && (
              <span className="inline-flex items-center rounded-full bg-amber-500/10 px-2 py-0.5 text-[11px] font-medium text-amber-600 dark:text-amber-400">
                Triggered
              </span>
            )}
            </div>

            <p className="mt-1 text-sm text-muted-foreground line-clamp-2">{screening.prompt}</p>

            {((screening.tickers?.length ?? 0) > 0 || (screening.linked_scan_run_ids?.length ?? 0) > 0) && (
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              {(screening.tickers ?? []).map((t) => (
                <span key={t} className="inline-flex items-center rounded bg-muted px-1.5 py-0.5 text-[11px] font-mono font-medium text-foreground/80">
                  {t}
                </span>
              ))}
              {(screening.linked_scan_run_ids ?? []).length > 0 && (
                <span className="inline-flex items-center gap-1 rounded bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">
                  <Link2 className="w-3 h-3" />
                  {screening.linked_scan_run_ids.length} linked
                </span>
              )}
              {screening.scan_filters &&
                countScreeningsFilterRules(screening.scan_filters) > 0 && (
                <span className="inline-flex items-center gap-1 rounded bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">
                  <Filter className="w-3 h-3" />
                  {countScreeningsFilterRules(screening.scan_filters)} filter
                  {countScreeningsFilterRules(screening.scan_filters) !== 1
                    ? "s"
                    : ""}
                </span>
              )}
            </div>
            )}

            <div className="mt-2 flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground/60">
            <span className="inline-flex min-w-0 items-center gap-1 break-words">
              <Clock className="h-3 w-3 shrink-0" />
              <span className="min-w-0">{scheduleLabel}</span>
            </span>
            {screening.trading_session && screening.trading_session !== "none" && screening.trading_session !== null && (
              <span className="inline-flex items-center gap-1 rounded bg-foreground/10 px-1.5 py-0.5 font-medium text-foreground/70">
                Market hours
              </span>
            )}
            {screening.condition_enabled && (
              <span
                className="inline-flex items-center gap-1 rounded bg-amber-500/10 px-1.5 py-0.5 font-medium text-amber-600 dark:text-amber-400"
                title={screening.trigger_condition ?? undefined}
              >
                Conditional
              </span>
            )}
            <span className="min-w-0 break-all">{screening.timezone}</span>
            {screening.last_run_at && (
              <span className="min-w-0 break-words">
                Last run {new Date(screening.last_run_at).toISOString().replace("T", " ").slice(0, 16)} UTC
              </span>
            )}
            </div>

            {testing && (
            <div className="mt-3 flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
              Queued — waiting for Mac Mini to pick up…
            </div>
            )}
            {testError && (
            <div className="mt-3 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
              {testError}
            </div>
            )}
            {testResult && (
            <div className={`mt-3 rounded-lg border px-3 py-2.5 text-xs ${
              testResult.triggered
                ? "border-amber-500/30 bg-amber-500/5"
                : "border-border bg-muted/50"
            }`}>
              <div className="flex items-center gap-1.5 mb-1">
                <span className={`font-medium ${testResult.triggered ? "text-amber-600 dark:text-amber-400" : "text-muted-foreground"}`}>
                  {testResult.triggered ? "Triggered" : "Not triggered"}
                </span>
              </div>
              {testResult.summary && (
                <p className="text-foreground/80 leading-relaxed">{testResult.summary}</p>
              )}
            </div>
            )}
          </div>
        </div>

        <div className="flex shrink-0 items-center justify-end gap-2 sm:pt-1">
          <button
            type="button"
            onClick={() => { setEditing(true); setEditName(screening.name); setEditPrompt(screening.prompt); setEditSchedule(screening.schedule); setEditTimezone(screening.timezone); setEditTradingSession(screening.trading_session ?? null); setEditTickers(screening.tickers ?? []); setEditLinkedScanRunIds(screening.linked_scan_run_ids ?? []); setEditConditionEnabled(screening.condition_enabled ?? false); setEditTriggerCondition(screening.trigger_condition ?? ""); setSaveErr(null); }}
            title="Edit agent"
            className="flex h-8 w-8 items-center justify-center rounded-md border border-border text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <Pencil className="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            onClick={() => void handleTestRun()}
            disabled={testing}
            title="Test run now"
            className="flex h-8 w-8 items-center justify-center rounded-md border border-border text-muted-foreground transition-colors hover:border-amber-500/30 hover:bg-amber-500/10 hover:text-amber-600 disabled:opacity-40"
          >
            {testing
              ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
              : <Zap className="w-3.5 h-3.5" />}
          </button>
          <button
            type="button"
            onClick={() => void handleToggle()}
            disabled={toggling}
            title={screening.is_active ? "Pause agent" : "Resume agent"}
            className="flex h-8 w-8 items-center justify-center rounded-md border border-border text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-40"
          >
            {screening.is_active
              ? <Pause className="w-3.5 h-3.5" />
              : <Play className="w-3.5 h-3.5" />}
          </button>
          <button
            type="button"
            onClick={() => void handleDelete()}
            disabled={deleting}
            title="Delete agent"
            className="flex h-8 w-8 items-center justify-center rounded-md border border-border text-muted-foreground transition-colors hover:border-destructive/30 hover:bg-destructive/10 hover:text-destructive disabled:opacity-40"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
}
