"use client";

import { useState, useMemo, useCallback } from "react";
import { Bot, Pause, Play, Trash2, Plus, Clock, AlertCircle, Zap, Loader2, CalendarClock, LayoutList, CalendarDays, ChevronLeft, ChevronRight, Pencil } from "lucide-react";
import {
  type ScheduledScreening,
  type ScreeningResult,
  createScheduledScreening,
  toggleScreening,
  deleteScheduledScreening,
  testRunScreening,
  pollTestResult,
  updateScheduledScreening,
} from "@/app/actions/screenings-agent";

type Props = {
  screenings: ScheduledScreening[];
  limits: {
    limit: number;
    used: number;
    plan: string;
    minSchedule: string;
  } | null;
  error: string | null;
};

export function AgentsUI({ screenings, limits, error }: Props) {
  const [showForm, setShowForm] = useState(false);
  const [view, setView] = useState<"list" | "calendar">("list");
  const atLimit = limits ? limits.used >= limits.limit : true;

  return (
    <div className="flex flex-col gap-6 w-full">
      {error && (
        <div className="flex items-start gap-3 rounded-xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
          {error}
        </div>
      )}

      {/* Usage + controls */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          {limits && (
            <p className="text-sm text-muted-foreground">
              <span className="font-semibold text-foreground">{limits.used}</span>
              <span className="text-muted-foreground/60"> / {limits.limit}</span>
              {" "}active agents
              <span className="ml-2 text-xs text-muted-foreground/60">({limits.plan} plan)</span>
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          {/* View toggle */}
          {screenings.length > 0 && (
            <div className="flex gap-0.5 rounded-lg border border-border p-0.5">
              <button
                type="button"
                onClick={() => setView("list")}
                className={`p-1.5 rounded-md transition-colors ${
                  view === "list" ? "bg-foreground text-background" : "text-muted-foreground hover:bg-muted"
                }`}
                title="List view"
              >
                <LayoutList className="w-3.5 h-3.5" />
              </button>
              <button
                type="button"
                onClick={() => setView("calendar")}
                className={`p-1.5 rounded-md transition-colors ${
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
              className="inline-flex items-center gap-1.5 rounded-md bg-foreground px-3 py-1.5 text-sm font-medium text-background transition-opacity hover:opacity-90 disabled:opacity-40 disabled:pointer-events-none"
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
        />
      )}

      {/* Calendar view */}
      {view === "calendar" && <WeekCalendar screenings={screenings} />}

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
            <AgentCard key={s.id} screening={s} />
          ))}
        </div>
      )}
    </div>
  );
}

// ── Outlook-style recurrence builder ────────────────────────────────────────

type RecurrencePattern = "minutely" | "hourly" | "daily" | "weekly";

const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"] as const;
type DayIdx = 0 | 1 | 2 | 3 | 4 | 5 | 6;

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
      return interval === 1 ? `${minute} * * * *` : `${minute} */${interval} * * *`;
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
}: {
  value: string;
  onChange: (cron: string) => void;
}) {
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

  function patch(patch: Partial<typeof parsed>) {
    const next = { ...parsed, ...patch };
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

  const pill = "px-3 py-1.5 text-xs font-medium rounded-md transition-colors cursor-pointer";
  const pillOn = "bg-foreground text-background";
  const pillOff = "text-muted-foreground hover:bg-muted";

  return (
    <div className="flex flex-col gap-3">
      {/* Pattern selector */}
      <div className="flex gap-1 rounded-lg border border-border p-1">
        {patterns.map((p) => (
          <button
            key={p.value}
            type="button"
            onClick={() => {
              const patchVal: Partial<typeof parsed> = { pattern: p.value };
              if (p.value === "minutely" && parsed.interval < 15) patchVal.interval = 15;
              if (p.value === "hourly" && parsed.interval > 24) patchVal.interval = 1;
              patch(patchVal);
            }}
            className={`${pill} ${parsed.pattern === p.value ? pillOn : pillOff}`}
          >
            {p.label}
          </button>
        ))}
      </div>

      {/* Interval row — only for minutely/hourly */}
      {(parsed.pattern === "minutely" || parsed.pattern === "hourly") && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <span>Every</span>
          <input
            type="number"
            min={parsed.pattern === "minutely" ? 1 : 1}
            max={parsed.pattern === "minutely" ? 60 : 24}
            value={parsed.interval}
            onChange={(e) => patch({ interval: Math.max(1, parseInt(e.target.value) || 1) })}
            className="w-16 rounded-md border border-input bg-background px-2 py-1 text-center text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
          />
          <span>{parsed.pattern === "minutely" ? "min" : "hour(s)"}</span>
        </div>
      )}

      {/* Time picker — daily/weekly */}
      {(parsed.pattern === "daily" || parsed.pattern === "weekly") && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <span>At</span>
          <select
            value={parsed.hour}
            onChange={(e) => patch({ hour: parseInt(e.target.value) })}
            className="rounded-md border border-input bg-background px-2 py-1 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
          >
            {Array.from({ length: 24 }, (_, i) => {
              const ampm = i >= 12 ? "PM" : "AM";
              const hh = i % 12 || 12;
              return <option key={i} value={i}>{hh}:00 {ampm}</option>;
            })}
          </select>
          <span>:</span>
          <select
            value={parsed.minute}
            onChange={(e) => patch({ minute: parseInt(e.target.value) })}
            className="rounded-md border border-input bg-background px-2 py-1 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
          >
            {[0, 15, 30, 45].map((m) => (
              <option key={m} value={m}>{String(m).padStart(2, "0")}</option>
            ))}
          </select>
        </div>
      )}

      {/* Day picker — weekly only */}
      {parsed.pattern === "weekly" && (
        <div className="flex items-center gap-1">
          {DAYS.map((label, idx) => {
            const active = parsed.days.includes(idx as DayIdx);
            return (
              <button
                key={idx}
                type="button"
                onClick={() => toggleDay(idx as DayIdx)}
                className={`w-9 h-9 rounded-md text-xs font-medium transition-colors ${
                  active
                    ? "bg-foreground text-background"
                    : "border border-border text-muted-foreground hover:bg-muted"
                }`}
              >
                {label}
              </button>
            );
          })}
        </div>
      )}

      {/* Human-readable summary */}
      <div className="flex items-center gap-2 text-xs text-muted-foreground/70 pt-1 border-t border-border">
        <CalendarClock className="w-3.5 h-3.5" />
        <span>{describeCron(value)}</span>
      </div>
    </div>
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

// ── Week calendar ───────────────────────────────────────────────────────────

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

function WeekCalendar({ screenings }: { screenings: ScheduledScreening[] }) {
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
    <div className="rounded-2xl border border-border bg-card overflow-hidden">
      {/* Header with nav */}
      <div className="border-b border-border px-5 py-3 flex items-center justify-between">
        <p className="text-xs font-semibold uppercase tracking-widest text-foreground/60">
          Execution calendar
        </p>
        <div className="flex items-center gap-2">
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
          <span className="text-xs text-muted-foreground/60 ml-1">
            {weekStart.toLocaleDateString(undefined, { month: "short", day: "numeric" })}
            {" – "}
            {days[6].toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}
          </span>
        </div>
      </div>

      <div className="overflow-x-auto">
        <div className="min-w-[700px]">
          {/* Day headers */}
          <div className="flex border-b border-border">
            <div className="w-14 shrink-0" />
            {days.map((d, i) => (
              <div
                key={i}
                className={`flex-1 text-center py-2 text-xs font-medium ${
                  isToday(d) ? "text-foreground bg-foreground/[0.03]" : "text-muted-foreground"
                }`}
              >
                <span>{DAY_LABELS[i]}</span>
                <span className={`ml-1 inline-flex items-center justify-center w-5 h-5 rounded-full text-[10px] ${
                  isToday(d) ? "bg-foreground text-background" : ""
                }`}>
                  {d.getDate()}
                </span>
              </div>
            ))}
          </div>

          {/* Time grid */}
          <div className="relative">
            {HOURS_SHOW.map((hour) => (
              <div key={hour} className="flex border-b border-border/50 last:border-b-0">
                <div className="w-14 shrink-0 text-right pr-2 text-[10px] text-muted-foreground/50 leading-none" style={{ height: ROW_H, paddingTop: 2 }}>
                  {hour % 12 || 12}{hour >= 12 ? "p" : "a"}
                </div>
                {days.map((d, colIdx) => {
                  const dayRuns = runsByDay[d.toDateString()] ?? [];
                  const inSlot = dayRuns.filter(
                    (r) => r.time.getHours() === hour,
                  );
                  return (
                    <div
                      key={colIdx}
                      className={`flex-1 relative ${isToday(d) ? "bg-foreground/[0.02]" : ""}`}
                      style={{ height: ROW_H }}
                    >
                      {inSlot.map((run) => {
                        const isOpen = openPill === run.key;
                        return (
                          <div key={run.key} className="absolute z-10" style={{ left: 1, right: 1, top: (run.time.getMinutes() / 60) * ROW_H }}>
                            <div
                              onDoubleClick={() => setOpenPill(isOpen ? null : run.key)}
                              className={`rounded cursor-pointer border overflow-hidden select-none ${AGENT_BORDER[run.idx % AGENT_BORDER.length]} ${AGENT_COLORS[run.idx % AGENT_COLORS.length]}/20 hover:brightness-110 transition-all`}
                              style={{ height: 20 }}
                            >
                              <span className={`block px-1.5 truncate text-[11px] font-semibold leading-[20px] ${AGENT_TEXT[run.idx % AGENT_TEXT.length]}`}>
                                {fmtTime(run.time)}
                                <span className="font-normal opacity-70 ml-1">{run.screening.name}</span>
                              </span>
                            </div>

                            {isOpen && (
                              <PillPopover
                                screening={run.screening}
                                colorIdx={run.idx}
                                onClose={() => setOpenPill(null)}
                              />
                            )}
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
                    left: `calc(${todayIdx} * (100% - 56px) / 7 + 56px)`,
                    width: `calc((100% - 56px) / 7)`,
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
      <div className="border-t border-border px-5 py-3 flex flex-wrap items-center gap-3">
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
}: {
  screening: ScheduledScreening;
  colorIdx: number;
  onClose: () => void;
}) {
  const [mode, setMode] = useState<"menu" | "edit">("menu");
  const [toggling, setToggling] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<ScreeningResult | null>(null);
  const [testError, setTestError] = useState<string | null>(null);

  // Edit form state
  const [editName, setEditName] = useState(screening.name);
  const [editPrompt, setEditPrompt] = useState(screening.prompt);
  const [editSchedule, setEditSchedule] = useState(screening.schedule);
  const [editTimezone, setEditTimezone] = useState(screening.timezone);
  const [saving, setSaving] = useState(false);
  const [saveErr, setSaveErr] = useState<string | null>(null);

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
    setSaving(true);
    setSaveErr(null);
    const res = await updateScheduledScreening(screening.id, {
      name: editName.trim() || "Untitled Agent",
      prompt: editPrompt.trim(),
      schedule: editSchedule,
      timezone: editTimezone,
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
      <div className="absolute left-0 top-[22px] z-50 w-72 rounded-xl border border-border bg-card shadow-lg shadow-black/10 overflow-hidden">
        <div className="px-3 pt-3 pb-2 border-b border-border flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className={`w-2 h-2 rounded-full ${AGENT_COLORS[colorIdx % AGENT_COLORS.length]}`} />
            <span className="text-xs font-semibold text-foreground">Edit agent</span>
          </div>
          <button type="button" onClick={() => setMode("menu")} className="text-[10px] text-muted-foreground/50 hover:text-muted-foreground transition-colors">Back</button>
        </div>
        <div className="px-3 py-3 flex flex-col gap-3">
          {saveErr && <p className="text-[11px] text-destructive">{saveErr}</p>}
          <div className="flex flex-col gap-1">
            <label className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide">Name</label>
            <input type="text" value={editName} onChange={(e) => setEditName(e.target.value)} className={inputClass} />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide">Prompt</label>
            <textarea value={editPrompt} onChange={(e) => setEditPrompt(e.target.value)} rows={4} className={inputClass} />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide">Recurrence</label>
            <RecurrenceScheduler value={editSchedule} onChange={setEditSchedule} />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide">Timezone</label>
            <select value={editTimezone} onChange={(e) => setEditTimezone(e.target.value)} className={inputClass}>
              <option value="America/New_York">Eastern (ET)</option>
              <option value="America/Chicago">Central (CT)</option>
              <option value="America/Denver">Mountain (MT)</option>
              <option value="America/Los_Angeles">Pacific (PT)</option>
              <option value="UTC">UTC</option>
            </select>
          </div>
          <div className="flex items-center gap-2 pt-1 border-t border-border">
            <button
              type="button"
              onClick={() => void handleSave()}
              disabled={saving || !editPrompt.trim()}
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
    <div className="absolute left-0 top-[22px] z-50 w-56 rounded-xl border border-border bg-card shadow-lg shadow-black/10 overflow-hidden">
      {/* Agent header */}
      <div className="px-3 pt-3 pb-2 border-b border-border">
        <div className="flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full ${AGENT_COLORS[colorIdx % AGENT_COLORS.length]}`} />
          <span className="text-xs font-semibold text-foreground truncate">{screening.name}</span>
        </div>
        <p className="mt-1 text-[11px] text-muted-foreground">{describeCron(screening.schedule)} &middot; {screening.timezone}</p>
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
      <div className="border-t border-border px-3 py-1.5">
        <button
          type="button"
          onClick={onClose}
          className="text-[10px] text-muted-foreground/50 hover:text-muted-foreground transition-colors"
        >
          Close
        </button>
      </div>
    </div>
  );
}

// ── Create form ─────────────────────────────────────────────────────────────

function CreateForm({ onClose, atLimit }: { onClose: () => void; atLimit: boolean }) {
  const [name, setName] = useState("");
  const [prompt, setPrompt] = useState("");
  const [schedule, setSchedule] = useState("0 7 * * 1-5");
  const [timezone, setTimezone] = useState("America/New_York");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function handleSave() {
    if (!prompt.trim()) return;
    setSaving(true);
    setErr(null);
    const res = await createScheduledScreening({
      name: name.trim() || "Untitled Agent",
      prompt: prompt.trim(),
      schedule,
      timezone,
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
    <div className="rounded-2xl border border-border bg-card overflow-hidden">
      <div className="border-b border-border px-5 py-3">
        <p className="text-xs font-semibold uppercase tracking-widest text-amber-500">New agent</p>
      </div>
      <div className="px-5 py-5 flex flex-col gap-4">
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
          <RecurrenceScheduler value={schedule} onChange={setSchedule} />
        </div>
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Timezone</label>
          <select
            value={timezone}
            onChange={(e) => setTimezone(e.target.value)}
            className={inputClass}
          >
            <option value="America/New_York">Eastern (ET)</option>
            <option value="America/Chicago">Central (CT)</option>
            <option value="America/Denver">Mountain (MT)</option>
            <option value="America/Los_Angeles">Pacific (PT)</option>
            <option value="UTC">UTC</option>
          </select>
        </div>
        <div className="flex items-center gap-3 pt-1 border-t border-border">
          <button
            type="button"
            onClick={() => void handleSave()}
            disabled={saving || atLimit || !prompt.trim()}
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
          <p className="ml-auto text-xs text-muted-foreground/60 hidden sm:block">
            Alerts delivered to Telegram (if connected) and shown here
          </p>
        </div>
      </div>
    </div>
  );
}

function AgentCard({ screening }: { screening: ScheduledScreening }) {
  const [toggling, setToggling] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<ScreeningResult | null>(null);
  const [testError, setTestError] = useState<string | null>(null);

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
        const requestedAt = screening.run_requested_at
          ? new Date(screening.run_requested_at).getTime()
          : 0;
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

  return (
    <div className={`rounded-2xl border bg-card transition-opacity ${deleting ? "opacity-50 pointer-events-none" : "border-border"}`}>
      <div className="flex items-start gap-3 px-5 py-4">
        <div className={`mt-1 w-2 h-2 rounded-full shrink-0 ${screening.is_active ? "bg-emerald-500" : "bg-muted-foreground/30"}`} />

        <div className="flex-1 min-w-0">
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

          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground/60">
            <span className="inline-flex items-center gap-1">
              <Clock className="w-3 h-3" />
              {scheduleLabel}
            </span>
            <span>{screening.timezone}</span>
            {screening.last_run_at && (
              <span>Last run {new Date(screening.last_run_at).toISOString().replace("T", " ").slice(0, 16)} UTC</span>
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

        <div className="flex items-center gap-2 shrink-0">
          <button
            type="button"
            onClick={() => void handleTestRun()}
            disabled={testing}
            title="Test run now"
            className="flex items-center justify-center w-8 h-8 rounded-md border border-border text-muted-foreground transition-colors hover:bg-amber-500/10 hover:text-amber-600 hover:border-amber-500/30 disabled:opacity-40"
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
            className="flex items-center justify-center w-8 h-8 rounded-md border border-border text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-40"
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
            className="flex items-center justify-center w-8 h-8 rounded-md border border-border text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive hover:border-destructive/30 disabled:opacity-40"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
}
