"use client";

import { useState, useMemo, useCallback, useEffect, useId, type ReactNode } from "react";
import {
  Dialog,
  DialogContent,
  DialogTitle,
} from "@/components/ui/dialog";
import { track } from "@/lib/analytics/events";
import { Bot, Pause, Play, Trash2, Plus, Clock, AlertCircle, Zap, Loader2, LayoutList, CalendarDays, ChevronLeft, ChevronRight, Pencil, X, Link2, Filter, Send, History, CheckCircle2, Bell, AlertTriangle, MinusCircle, MoreHorizontal, ChevronDown } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { TelegramConnect } from "@/components/telegram-connect";
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
  getScreeningResults,
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
  telegramConnected: boolean;
};

export function AgentsUI({ screenings, limits, error, suggestionTickers, telegramConnected }: Props) {
  const [showForm, setShowForm] = useState(false);
  const [view, setView] = useState<"list" | "calendar">("list");
  const atLimit = limits ? limits.used >= limits.limit : true;
  const createBlocked = !telegramConnected || atLimit;

  async function handleCreate(v: AgentFormValues): Promise<AgentSubmitResult> {
    const res = await createScheduledScreening(toScreeningPayload(v));
    if (res.ok) {
      track("agent_created", { agent_id: res.data?.id ?? "", kind: "scheduled_screening" });
      window.location.reload();
      return { ok: true };
    }
    if (/active screenings/i.test(res.error)) {
      track("paywall_hit", { surface: "screenings_create", user_plan: "unknown", reason: "screenings_active_limit" });
    }
    return { ok: false, error: res.error };
  }

  function openCreate() {
    if (createBlocked) return;
    setShowForm(true);
  }

  const newAgentTitle = !telegramConnected
    ? "Connect Telegram first to create agents"
    : atLimit
      ? "You've reached your active-agent limit"
      : undefined;

  return (
    <div className="flex min-w-0 w-full flex-col gap-5">
      {error && (
        <div className="flex min-w-0 items-start gap-3 rounded-xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
          <span className="min-w-0 break-words">{error}</span>
        </div>
      )}

      {!telegramConnected && (
        <div className="flex min-w-0 flex-col gap-3">
          <div className="flex min-w-0 items-start gap-3 rounded-xl border border-amber-500/40 bg-amber-500/5 px-4 py-3 text-sm">
            <Send className="w-4 h-4 shrink-0 mt-0.5 text-amber-500" />
            <div className="min-w-0">
              <p className="font-medium text-foreground">Connect Telegram to create agents</p>
              <p className="mt-0.5 text-xs text-muted-foreground">
                Agents deliver alerts via Telegram. Pair your account below — once
                connected, you&apos;ll be able to create and run scheduled agents.
              </p>
            </div>
          </div>
          <TelegramConnect />
        </div>
      )}

      {/* Command bar — capacity readout · view toggle · new agent */}
      <div className="flex min-w-0 flex-col gap-3 rounded-xl border border-border bg-card/40 px-3.5 py-3 sm:flex-row sm:items-center sm:justify-between">
        {limits ? (
          <CapacityReadout used={limits.used} limit={limits.limit} plan={limits.plan} />
        ) : (
          <span className="font-mono text-[11px] text-muted-foreground/50">loading…</span>
        )}
        <div className="flex shrink-0 items-center gap-2">
          {screenings.length > 0 && (
            <div className="flex gap-0.5 rounded-lg border border-border p-0.5">
              <button
                type="button"
                onClick={() => setView("list")}
                aria-pressed={view === "list"}
                className={`flex h-9 w-9 items-center justify-center rounded-md transition-colors ${view === "list" ? "bg-foreground text-background" : "text-muted-foreground hover:bg-muted"}`}
                title="List view"
              >
                <LayoutList className="w-3.5 h-3.5" />
              </button>
              <button
                type="button"
                onClick={() => setView("calendar")}
                aria-pressed={view === "calendar"}
                className={`flex h-9 w-9 items-center justify-center rounded-md transition-colors ${view === "calendar" ? "bg-foreground text-background" : "text-muted-foreground hover:bg-muted"}`}
                title="Calendar view"
              >
                <CalendarDays className="w-3.5 h-3.5" />
              </button>
            </div>
          )}
          <button
            type="button"
            onClick={openCreate}
            disabled={createBlocked}
            data-tour="agent-create"
            title={newAgentTitle}
            className="inline-flex h-9 items-center gap-1.5 rounded-md bg-foreground px-3.5 text-sm font-medium text-background shadow-sm transition-all hover:opacity-90 active:scale-[0.98] disabled:pointer-events-none disabled:opacity-40 disabled:active:scale-100"
          >
            <Plus className="w-3.5 h-3.5" />
            New agent
          </button>
        </div>
      </div>

      {telegramConnected && (
        <AgentFormDialog
          open={showForm}
          onOpenChange={setShowForm}
          mode="create"
          suggestionTickers={suggestionTickers}
          onSubmit={handleCreate}
          disabled={atLimit}
        />
      )}

      {/* Calendar view */}
      {view === "calendar" && <WeekCalendar screenings={screenings} suggestionTickers={suggestionTickers} />}

      {/* Agent list */}
      {view === "list" && (
        <div data-tour="agent-list" className="flex flex-col gap-2.5">
          {screenings.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-border/70 px-6 py-16 text-center">
              <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl border border-border bg-muted/40">
                <Bot className="h-6 w-6 text-muted-foreground/50" />
              </div>
              <p className="text-base font-semibold tracking-tight text-foreground">No agents yet</p>
              <p className="mx-auto mt-1.5 max-w-[44ch] text-sm leading-relaxed text-muted-foreground">
                Spin up your first agent — it watches the market on your schedule
                and pings you the moment your conditions hit.
              </p>
              <button
                type="button"
                onClick={openCreate}
                disabled={createBlocked}
                title={newAgentTitle}
                className="mt-5 inline-flex items-center gap-1.5 rounded-md bg-foreground px-4 py-2.5 text-sm font-medium text-background shadow-sm transition-all hover:opacity-90 active:scale-[0.98] disabled:opacity-40 disabled:pointer-events-none disabled:active:scale-100"
              >
                <Plus className="h-3.5 w-3.5" />
                Create your first agent
              </button>
            </div>
          ) : (
            screenings.map((s) => (
              <AgentCard key={s.id} screening={s} suggestionTickers={suggestionTickers} />
            ))
          )}
        </div>
      )}
    </div>
  );
}

/** Mono capacity readout — `●●●○○ 3 / 5 · PRO`. Dots for small plans, bar for large. */
function CapacityReadout({ used, limit, plan }: { used: number; limit: number; plan: string }) {
  const nearLimit = used >= limit;
  const fillClass = nearLimit ? "bg-rose-500" : "bg-emerald-500";
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1">
      {limit <= 10 ? (
        <div className="flex items-center gap-1" aria-hidden>
          {Array.from({ length: limit }, (_, i) => (
            <span key={i} className={`h-2 w-2 rounded-full ${i < used ? fillClass : "bg-muted-foreground/20"}`} />
          ))}
        </div>
      ) : (
        <div className="h-1.5 w-24 overflow-hidden rounded-full bg-muted">
          <div className={`h-full rounded-full ${fillClass}`} style={{ width: `${Math.min(100, (used / Math.max(1, limit)) * 100)}%` }} />
        </div>
      )}
      <span className="font-mono text-sm tabular-nums text-foreground">
        {used}
        <span className="text-muted-foreground/50"> / {limit}</span>
      </span>
      <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground/60">active agents</span>
      <span className="rounded border border-border px-1.5 py-0.5 font-mono text-[9px] font-semibold uppercase tracking-[0.1em] text-muted-foreground/70">
        {plan}
      </span>
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

      {/* Repeats — segmented chips */}
      <div className={row}>
        <span className={lbl}>Repeats:</span>
        <div className="flex min-w-0 flex-wrap gap-1">
          {patterns.map((p) => {
            const activeP = parsed.pattern === p.value;
            return (
              <button
                key={p.value}
                type="button"
                onClick={() => {
                  const patch2: Partial<typeof parsed> = { pattern: p.value };
                  if (p.value === "minutely" && parsed.interval < 1) patch2.interval = 15;
                  if (p.value === "hourly" && parsed.interval > 24) patch2.interval = 1;
                  patch(patch2);
                }}
                className={`rounded-md border px-2.5 py-1 font-mono text-[11px] tracking-[0.04em] transition-colors ${
                  activeP
                    ? "border-foreground bg-foreground text-background"
                    : "border-border text-muted-foreground hover:bg-muted"
                }`}
              >
                {p.label}
              </button>
            );
          })}
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
        <span className="min-w-0 break-words font-mono text-[13px] font-semibold tracking-[0.02em] text-amber-600 dark:text-amber-400">
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

/** Compact "in 2h 14m" / "in 45m" / "now" relative label for the next run. */
function fmtCountdown(when: Date | undefined): string {
  if (!when) return "—";
  const ms = when.getTime() - Date.now();
  if (ms <= 0) return "now";
  const mins = Math.round(ms / 60000);
  if (mins < 1) return "now";
  if (mins < 60) return `in ${mins}m`;
  const hrs = Math.floor(mins / 60);
  const rem = mins % 60;
  if (hrs < 24) return rem ? `in ${hrs}h ${rem}m` : `in ${hrs}h`;
  const days = Math.floor(hrs / 24);
  const remH = hrs % 24;
  return remH ? `in ${days}d ${remH}h` : `in ${days}d`;
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

// ── Linked-screening helpers ────────────────────────────────────────────────

/** Pretty label for a scan-run `source`. `market_screening:foo-bar` → "Foo Bar". */
function formatSourceLabel(source: string): string {
  const slug = source.startsWith("market_screening:")
    ? source.slice("market_screening:".length)
    : source;
  if (source.startsWith("market_screening:")) {
    return slug
      .replace(/[-_]+/g, " ")
      .replace(/\b\w/g, (c) => c.toUpperCase())
      .trim();
  }
  return source;
}

/** Newest run id for a source. `scanRuns` is ordered scan_date desc, so the
 * first match is the latest. Returns null if the source has no runs. */
function latestRunIdForSource(source: string, scanRuns: ScanRunSummary[]): number | null {
  for (const r of scanRuns) if (r.source === source) return r.id;
  return null;
}

/** Effective linked run ids = pinned ids ∪ {latest run per followed source}.
 * Mirrors the engine's resolution so the filter preview matches what runs. */
function effectiveLinkedRunIds(
  pinnedIds: number[],
  followedSources: string[],
  scanRuns: ScanRunSummary[],
): number[] {
  const seen = new Set<number>();
  const out: number[] = [];
  for (const id of pinnedIds) {
    if (!seen.has(id)) { seen.add(id); out.push(id); }
  }
  for (const s of followedSources) {
    const id = latestRunIdForSource(s, scanRuns);
    if (id != null && !seen.has(id)) { seen.add(id); out.push(id); }
  }
  return out;
}

// ── Scan run picker (source-grouped, latest-vs-pin per source) ─────────────────

type SourceGroup = { source: string; runs: ScanRunSummary[] };

function ScanRunPicker({
  pinnedIds,
  followedSources,
  onChangePinned,
  onChangeFollowed,
  scanRuns,
}: {
  pinnedIds: number[];
  followedSources: string[];
  onChangePinned: (ids: number[]) => void;
  onChangeFollowed: (sources: string[]) => void;
  scanRuns: ScanRunSummary[];
}) {
  if (scanRuns.length === 0) {
    return <p className="text-xs text-muted-foreground">No scan runs yet. Create one on the Screenings page.</p>;
  }

  // Group runs by source (preserving scan_date-desc order); null-source runs are pin-only.
  const groups: SourceGroup[] = [];
  const groupBySource = new Map<string, SourceGroup>();
  const ungrouped: ScanRunSummary[] = [];
  for (const r of scanRuns) {
    if (!r.source) { ungrouped.push(r); continue; }
    let g = groupBySource.get(r.source);
    if (!g) { g = { source: r.source, runs: [] }; groupBySource.set(r.source, g); groups.push(g); }
    g.runs.push(r);
  }

  function pinnedIdInGroup(g: SourceGroup): number | null {
    for (const r of g.runs) if (pinnedIds.includes(r.id)) return r.id;
    return null;
  }

  function followLatest(g: SourceGroup) {
    // remove any pinned id from this group, add source to followed
    const groupIds = new Set(g.runs.map((r) => r.id));
    onChangePinned(pinnedIds.filter((id) => !groupIds.has(id)));
    if (!followedSources.includes(g.source)) onChangeFollowed([...followedSources, g.source]);
  }

  function pinRun(g: SourceGroup, id: number) {
    // exactly one pinned id per group; clear followed for this source
    const groupIds = new Set(g.runs.map((r) => r.id));
    onChangePinned([...pinnedIds.filter((x) => !groupIds.has(x)), id]);
    if (followedSources.includes(g.source)) onChangeFollowed(followedSources.filter((s) => s !== g.source));
  }

  function clearGroup(g: SourceGroup) {
    const groupIds = new Set(g.runs.map((r) => r.id));
    onChangePinned(pinnedIds.filter((id) => !groupIds.has(id)));
    if (followedSources.includes(g.source)) onChangeFollowed(followedSources.filter((s) => s !== g.source));
  }

  function toggleUngrouped(id: number) {
    if (pinnedIds.includes(id)) onChangePinned(pinnedIds.filter((x) => x !== id));
    else onChangePinned([...pinnedIds, id]);
  }

  const segBtn = "px-2 py-0.5 text-[11px] font-medium rounded transition-colors";

  return (
    <div className="flex flex-col gap-1.5 max-h-56 overflow-y-auto">
      {groups.map((g) => {
        const followed = followedSources.includes(g.source);
        const pinnedId = pinnedIdInGroup(g);
        const included = followed || pinnedId != null;
        const latestDate = g.runs[0]?.scan_date.slice(0, 10) ?? "";
        return (
          <div key={g.source} className="rounded-md border border-border/60 px-2 py-1.5">
            <label className="flex items-center gap-2 text-xs cursor-pointer">
              <input
                type="checkbox"
                checked={included}
                onChange={() => (included ? clearGroup(g) : followLatest(g))}
                className="rounded border-border"
              />
              <span className="truncate text-foreground font-medium">{formatSourceLabel(g.source)}</span>
              <span className="ml-auto shrink-0 text-[10px] text-muted-foreground/60 tabular-nums">
                {g.runs.length} run{g.runs.length !== 1 ? "s" : ""}
              </span>
            </label>
            {included && (
              <div className="mt-1.5 flex flex-wrap items-center gap-1.5 pl-6">
                <div className="inline-flex rounded-md border border-border bg-background p-0.5">
                  <button
                    type="button"
                    onClick={() => followLatest(g)}
                    className={`${segBtn} ${followed ? "bg-foreground text-background" : "text-muted-foreground hover:text-foreground"}`}
                  >
                    Latest run
                  </button>
                  <button
                    type="button"
                    onClick={() => pinRun(g, pinnedId ?? g.runs[0].id)}
                    className={`${segBtn} ${!followed ? "bg-foreground text-background" : "text-muted-foreground hover:text-foreground"}`}
                  >
                    Pin a run
                  </button>
                </div>
                {followed ? (
                  <span className="text-[11px] text-muted-foreground/70">follows newest · now {latestDate}</span>
                ) : (
                  <select
                    value={pinnedId ?? g.runs[0].id}
                    onChange={(e) => pinRun(g, Number(e.target.value))}
                    className="rounded-md border border-input bg-background px-1.5 py-0.5 text-[11px] text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                  >
                    {g.runs.map((r) => (
                      <option key={r.id} value={r.id}>{r.scan_date.slice(0, 10)}</option>
                    ))}
                  </select>
                )}
              </div>
            )}
          </div>
        );
      })}
      {ungrouped.length > 0 && (
        <div className="flex flex-col gap-1 pt-0.5">
          {groups.length > 0 && (
            <span className="text-[10px] uppercase tracking-wide text-muted-foreground/50 px-1.5">Unlabeled runs</span>
          )}
          {ungrouped.map((r) => (
            <label
              key={r.id}
              className="flex items-center gap-2 text-xs cursor-pointer hover:bg-muted/50 rounded px-1.5 py-1 transition-colors"
            >
              <input
                type="checkbox"
                checked={pinnedIds.includes(r.id)}
                onChange={() => toggleUngrouped(r.id)}
                className="rounded border-border"
              />
              <span className="truncate text-foreground">{r.scan_date.slice(0, 10)}</span>
            </label>
          ))}
        </div>
      )}
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
  const [editing, setEditing] = useState(false);
  const [toggling, setToggling] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<ScreeningResult | null>(null);
  const [testError, setTestError] = useState<string | null>(null);

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
    track("agent_run", { agent_id: screening.id, manual: true });
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

  async function handleEditSubmit(v: AgentFormValues): Promise<AgentSubmitResult> {
    const res = await updateScheduledScreening(screening.id, toScreeningPayload(v));
    if (res.ok) {
      onClose();
      window.location.reload();
      return { ok: true };
    }
    return { ok: false, error: res.error };
  }

  const actionBtn = "flex items-center gap-1.5 w-full px-2.5 py-1.5 text-xs rounded-md transition-colors";

  return (
    <>
      <div className="absolute left-0 top-[22px] z-50 w-[min(14rem,calc(100vw-2rem))] max-w-[calc(100vw-2rem)] rounded-xl border border-border bg-card shadow-lg shadow-black/10 overflow-hidden">
        {/* Agent header */}
        <div className="px-3 pt-3 pb-2 border-b border-border">
          <div className="flex items-center gap-2">
            <div className={`w-2 h-2 rounded-full ${AGENT_COLORS[colorIdx % AGENT_COLORS.length]}`} />
            <span className="text-xs font-semibold text-foreground truncate">{screening.name}</span>
          </div>
          <p className="mt-1 break-words font-mono text-[10px] text-muted-foreground">
            {describeCron(screening.schedule)} &middot; {screening.timezone}
            {screening.trading_session && screening.trading_session !== "none" && screening.trading_session !== null && (
              <span className="ml-1.5 inline-flex items-center rounded bg-foreground/10 px-1 py-px font-medium text-foreground/70">mkt hrs</span>
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
            onClick={() => setEditing(true)}
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
                <span className={`font-mono text-[10px] uppercase tracking-[0.1em] ${testResult.triggered ? "text-amber-600 dark:text-amber-400" : "text-muted-foreground"}`}>
                  {testResult.triggered ? "triggered" : "not triggered"}
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

      <AgentFormDialog
        open={editing}
        onOpenChange={setEditing}
        mode="edit"
        initial={screeningToFormInitial(screening)}
        suggestionTickers={suggestionTickers}
        onSubmit={handleEditSubmit}
      />
    </>
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

// ── Shared agent form (create + edit) ────────────────────────────────────────

export type AgentFormValues = {
  name: string;
  prompt: string;
  schedule: string;
  timezone: string;
  tradingSession: string | null;
  tickers: string[];
  linkedScanRunIds: number[];
  linkedScanSources: string[];
  scanFilters: ScreeningsFilters;
  conditionEnabled: boolean;
  triggerCondition: string;
};

type AgentSubmitResult = { ok: true } | { ok: false; error: string };

const PROMPT_IDEAS = ["Airline macro selloff", "NVDA earnings gap", "Biotech FDA catalysts"];

function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground/50">
      {children}
    </p>
  );
}

/** One form, three call-sites (create + card edit + calendar edit). Owns its
 * own field state + save/error; the caller supplies `onSubmit` (which performs
 * the server action) and reloads on success. */
function AgentForm({
  initial,
  suggestionTickers,
  submitLabel,
  onSubmit,
  onCancel,
  disabled,
}: {
  initial?: Partial<AgentFormValues>;
  suggestionTickers: string[];
  submitLabel: string;
  onSubmit: (v: AgentFormValues) => Promise<AgentSubmitResult>;
  onCancel: () => void;
  disabled?: boolean;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [prompt, setPrompt] = useState(initial?.prompt ?? "");
  const [schedule, setSchedule] = useState(initial?.schedule ?? "0 7 * * 1-5");
  const [timezone, setTimezone] = useState(initial?.timezone ?? "America/New_York");
  const [tradingSession, setTradingSession] = useState<string | null>(initial?.tradingSession ?? null);
  const [tickers, setTickers] = useState<string[]>(initial?.tickers ?? []);
  const [linkedScanRunIds, setLinkedScanRunIds] = useState<number[]>(initial?.linkedScanRunIds ?? []);
  const [linkedScanSources, setLinkedScanSources] = useState<string[]>(initial?.linkedScanSources ?? []);
  const [scanFilters, setScanFilters] = useState<ScreeningsFilters>(initial?.scanFilters ?? DEFAULT_SCREENINGS_FILTERS);
  const [conditionEnabled, setConditionEnabled] = useState(initial?.conditionEnabled ?? false);
  const [triggerCondition, setTriggerCondition] = useState(initial?.triggerCondition ?? "");
  const [scanRuns, setScanRuns] = useState<ScanRunSummary[]>([]);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const hasAdvanced =
    (initial?.linkedScanRunIds?.length ?? 0) > 0 ||
    (initial?.linkedScanSources?.length ?? 0) > 0 ||
    (initial?.conditionEnabled ?? false) ||
    countScreeningsFilterRules(initial?.scanFilters ?? DEFAULT_SCREENINGS_FILTERS) > 0;
  const [refineOpen, setRefineOpen] = useState(hasAdvanced);

  const effectiveLinkedIds = useMemo(
    () => effectiveLinkedRunIds(linkedScanRunIds, linkedScanSources, scanRuns),
    [linkedScanRunIds, linkedScanSources, scanRuns],
  );

  useEffect(() => {
    void listScanRuns().then((res) => {
      if (res.ok) setScanRuns(res.data);
    });
  }, []);

  const canSubmit = prompt.trim().length > 0 && (!conditionEnabled || triggerCondition.trim().length > 0);

  async function handleSubmit() {
    if (!canSubmit) return;
    setSaving(true);
    setErr(null);
    const res = await onSubmit({
      name: name.trim() || "Untitled Agent",
      prompt: prompt.trim(),
      schedule,
      timezone,
      tradingSession,
      tickers,
      linkedScanRunIds,
      linkedScanSources,
      scanFilters,
      conditionEnabled,
      triggerCondition: conditionEnabled ? triggerCondition.trim() : "",
    });
    // On success the caller reloads the page; keep the spinner until then.
    if (!res.ok) {
      setErr(res.error);
      setSaving(false);
    }
  }

  const inputClass =
    "w-full rounded-md border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-50";
  const busy = saving || disabled;

  return (
    <form
      onSubmit={(e) => { e.preventDefault(); void handleSubmit(); }}
      className="flex min-h-0 flex-1 flex-col"
    >
      <div className="flex min-h-0 flex-1 flex-col gap-6 overflow-y-auto px-4 py-5 sm:px-6">
        {err && (
          <div className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <span className="min-w-0 break-words">{err}</span>
          </div>
        )}

        {/* 01 — What to watch */}
        <div className="flex flex-col gap-3">
          <SectionLabel>01 · What to watch</SectionLabel>
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium text-muted-foreground">Name</label>
            <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Airline Macro Watch" className={inputClass} />
          </div>
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium text-muted-foreground">
              Prompt <span className="font-normal text-muted-foreground/50">— plain English, what to watch for</span>
            </label>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={5}
              placeholder={`e.g. Check MACRO_SENSITIVITY cluster trend for airline stocks (AAL, DAL, UAL). Alert me when the cluster score drops below -0.3. Include which dimensions are driving it and any headlines from the last 14 hours.`}
              className={inputClass}
            />
            {!prompt.trim() && (
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground/40">try</span>
                {PROMPT_IDEAS.map((idea) => (
                  <button
                    key={idea}
                    type="button"
                    onClick={() => setPrompt(idea)}
                    className="rounded-full border border-border bg-muted/30 px-2.5 py-0.5 text-[11px] text-muted-foreground transition-colors hover:border-amber-500/40 hover:text-amber-500"
                  >
                    {idea}
                  </button>
                ))}
              </div>
            )}
          </div>
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium text-muted-foreground">
              Tickers <span className="font-normal text-muted-foreground/50">— focus on specific symbols</span>
            </label>
            <TickerPicker tickers={tickers} onChange={setTickers} suggestionTickers={suggestionTickers} />
          </div>
        </div>

        {/* 02 — When it runs */}
        <div className="flex flex-col gap-3 border-t border-border/60 pt-5">
          <SectionLabel>02 · When it runs</SectionLabel>
          <div data-tour="agent-schedule">
            <RecurrenceScheduler value={schedule} onChange={setSchedule} tradingSession={tradingSession} onTradingSessionChange={setTradingSession} />
          </div>
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium text-muted-foreground">Timezone</label>
            <TimezoneSelect value={timezone} onChange={setTimezone} className={inputClass} />
          </div>
        </div>

        {/* 03 — Refine (collapsible) */}
        <div className="flex flex-col gap-3 border-t border-border/60 pt-5">
          <button type="button" onClick={() => setRefineOpen((v) => !v)} className="flex items-center justify-between gap-2 text-left">
            <SectionLabel>03 · Refine <span className="text-muted-foreground/30">— optional</span></SectionLabel>
            <ChevronDown className={`h-4 w-4 text-muted-foreground/50 transition-transform ${refineOpen ? "rotate-180" : ""}`} />
          </button>
          {refineOpen && (
            <div className="flex flex-col gap-4">
              <div className="flex flex-col gap-1.5">
                <label className="text-xs font-medium text-muted-foreground">
                  Linked screenings <span className="font-normal text-muted-foreground/50">— include scan-run context</span>
                </label>
                <ScanRunPicker
                  pinnedIds={linkedScanRunIds}
                  followedSources={linkedScanSources}
                  onChangePinned={setLinkedScanRunIds}
                  onChangeFollowed={setLinkedScanSources}
                  scanRuns={scanRuns}
                />
              </div>
              {effectiveLinkedIds.length > 0 && (
                <div className="flex flex-col gap-1.5">
                  <label className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                    <Filter className="h-3 w-3" /> Filter tickers
                    <span className="font-normal text-muted-foreground/50">— narrow which tickers the agent focuses on</span>
                  </label>
                  <AgentFilterSection linkedScanRunIds={effectiveLinkedIds} filters={scanFilters} setFilters={setScanFilters} />
                </div>
              )}
              <div className="flex flex-col gap-1.5">
                <label className="inline-flex items-start gap-2 text-xs font-medium text-foreground">
                  <input type="checkbox" checked={conditionEnabled} onChange={(e) => setConditionEnabled(e.target.checked)} className="mt-0.5 h-3.5 w-3.5 rounded border-input" />
                  <span>
                    Only alert when a condition is met
                    <span className="ml-1 font-normal text-muted-foreground/50">— skip the Telegram ping unless your condition is satisfied</span>
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
            </div>
          )}
        </div>
      </div>

      {/* sticky footer */}
      <div className="flex shrink-0 items-center gap-3 border-t border-border bg-card/90 px-4 py-3 backdrop-blur sm:px-6">
        <button
          type="submit"
          disabled={busy || !canSubmit}
          className="inline-flex items-center gap-1.5 rounded-md bg-foreground px-4 py-2 text-sm font-medium text-background transition-opacity hover:opacity-90 disabled:pointer-events-none disabled:opacity-40"
        >
          {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          {saving ? "Saving…" : submitLabel}
        </button>
        <button type="button" onClick={onCancel} className="rounded-md border border-border px-4 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted">
          Cancel
        </button>
        <span className="ml-auto hidden items-center gap-1 font-mono text-[10px] tracking-[0.04em] text-muted-foreground/40 sm:inline-flex">
          <Send className="h-3 w-3" /> telegram
        </span>
      </div>
    </form>
  );
}

/** Mobile-first wrapper: full-screen sheet on phones, centered modal on desktop. */
function AgentFormDialog({
  open,
  onOpenChange,
  mode,
  initial,
  suggestionTickers,
  onSubmit,
  disabled,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  mode: "create" | "edit";
  initial?: Partial<AgentFormValues>;
  suggestionTickers: string[];
  onSubmit: (v: AgentFormValues) => Promise<AgentSubmitResult>;
  disabled?: boolean;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        // The "Filter tickers" wizard renders its option list in a body-level
        // portal (to escape overflow clipping). Without this guard, clicking a
        // filter option registers as a pointer-down outside the dialog and Radix
        // dismisses the whole form. Keep the dialog open for those interactions.
        onInteractOutside={(e) => {
          const target = e.detail.originalEvent.target as HTMLElement | null;
          if (target?.closest("[data-filter-portal]")) e.preventDefault();
        }}
        className="left-0 top-0 flex h-[100dvh] max-h-[100dvh] w-full max-w-xl translate-x-0 translate-y-0 flex-col gap-0 overflow-hidden rounded-none border-0 bg-card p-0 sm:left-[50%] sm:top-[50%] sm:h-auto sm:max-h-[88vh] sm:translate-x-[-50%] sm:translate-y-[-50%] sm:rounded-2xl sm:border"
      >
        <div className="flex shrink-0 items-center gap-2 border-b border-border px-4 py-3.5 sm:px-6">
          <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />
          <DialogTitle className="font-mono text-[11px] font-semibold uppercase tracking-[0.16em] text-amber-500">
            {mode === "create" ? "New agent" : "Edit agent"}
          </DialogTitle>
        </div>
        {open && (
          <AgentForm
            initial={initial}
            suggestionTickers={suggestionTickers}
            submitLabel={mode === "create" ? "Save & activate" : "Save changes"}
            onSubmit={onSubmit}
            onCancel={() => onOpenChange(false)}
            disabled={disabled}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

/** Build the server-action payload shared by create + update. */
function toScreeningPayload(v: AgentFormValues) {
  return {
    name: v.name,
    prompt: v.prompt,
    schedule: v.schedule,
    timezone: v.timezone,
    tickers: v.tickers,
    linked_scan_run_ids: v.linkedScanRunIds,
    linked_scan_sources: v.linkedScanSources,
    scan_filters: countScreeningsFilterRules(v.scanFilters) > 0 ? v.scanFilters : null,
    trading_session: (v.tradingSession as TradingSession) ?? "none",
    condition_enabled: v.conditionEnabled,
    trigger_condition: v.conditionEnabled ? v.triggerCondition : null,
  };
}

/** Map a stored screening to the form's initial values. */
function screeningToFormInitial(s: ScheduledScreening): Partial<AgentFormValues> {
  return {
    name: s.name,
    prompt: s.prompt,
    schedule: s.schedule,
    timezone: s.timezone,
    tradingSession: s.trading_session ?? null,
    tickers: s.tickers ?? [],
    linkedScanRunIds: s.linked_scan_run_ids ?? [],
    linkedScanSources: s.linked_scan_sources ?? [],
    scanFilters: (s.scan_filters as ScreeningsFilters | null) ?? DEFAULT_SCREENINGS_FILTERS,
    conditionEnabled: s.condition_enabled ?? false,
    triggerCondition: s.trigger_condition ?? "",
  };
}

// ── Run history ─────────────────────────────────────────────────────────────

type RunStateMeta = {
  label: string;
  Icon: typeof CheckCircle2;
  iconClass: string;
  badgeClass: string;
};

/** Classify a persisted run into a display state. Mirrors the Telegram
 * delivery logic in services/agent/engine.py (_format_telegram_message). */
function runStateMeta(r: ScreeningResult): RunStateMeta {
  if (r.status === "error") {
    return {
      label: "Failed",
      Icon: AlertTriangle,
      iconClass: "text-destructive",
      badgeClass: "bg-destructive/10 text-destructive",
    };
  }
  if (r.status === "skipped") {
    return {
      label: "Skipped",
      Icon: MinusCircle,
      iconClass: "text-muted-foreground",
      badgeClass: "bg-muted text-muted-foreground",
    };
  }
  if (r.status === "running") {
    return {
      label: "Running",
      Icon: Loader2,
      iconClass: "text-muted-foreground animate-spin",
      badgeClass: "bg-muted text-muted-foreground",
    };
  }
  if (r.triggered) {
    return {
      label: "Triggered",
      Icon: Bell,
      iconClass: "text-amber-600 dark:text-amber-400",
      badgeClass: "bg-amber-500/10 text-amber-600 dark:text-amber-400",
    };
  }
  return {
    label: "No trigger",
    Icon: CheckCircle2,
    iconClass: "text-emerald-600 dark:text-emerald-400",
    badgeClass: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
  };
}

function formatRunTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function RunHistory({ screeningId }: { screeningId: string }) {
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [runs, setRuns] = useState<ScreeningResult[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    const res = await getScreeningResults(screeningId, 15);
    if (res.ok) setRuns(res.data.filter((r) => !r.is_test));
    else setErr(res.error);
    setLoading(false);
  }, [screeningId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return (
      <div className="mt-3 flex items-center gap-2 border-t border-border pt-3 text-xs text-muted-foreground">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        Loading run history…
      </div>
    );
  }

  if (err) {
    return (
      <div className="mt-3 border-t border-border pt-3 text-xs text-destructive">{err}</div>
    );
  }

  if (runs.length === 0) {
    return (
      <div className="mt-3 border-t border-border pt-3 text-xs text-muted-foreground/70">
        No runs yet — this agent hasn&apos;t fired on schedule.
      </div>
    );
  }

  return (
    <div className="mt-3 flex flex-col gap-1.5 border-t border-border pt-3">
      <div className="mb-0.5 flex items-center justify-between">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Recent runs
        </span>
        <button
          type="button"
          onClick={() => void load()}
          className="text-[11px] text-muted-foreground/70 transition-colors hover:text-foreground"
        >
          Refresh
        </button>
      </div>
      {runs.map((r) => {
        const meta = runStateMeta(r);
        return (
          <div
            key={r.id}
            className="flex min-w-0 items-start gap-2.5 rounded-lg border border-border/60 bg-muted/30 px-3 py-2"
          >
            <meta.Icon className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${meta.iconClass}`} />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className={`inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-medium ${meta.badgeClass}`}>
                  {meta.label}
                </span>
                <span className="text-[11px] text-muted-foreground/60">
                  {formatRunTime(r.run_at)}
                </span>
              </div>
              {r.summary && (
                <p className="mt-1 text-xs leading-relaxed text-foreground/80 line-clamp-3">
                  {r.summary}
                </p>
              )}
            </div>
          </div>
        );
      })}
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
  const [showHistory, setShowHistory] = useState(false);

  // Re-render once a minute so the next-run countdown actually advances.
  const [, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick((n) => n + 1), 60_000);
    return () => clearInterval(id);
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

  async function handleEditSubmit(v: AgentFormValues): Promise<AgentSubmitResult> {
    const res = await updateScheduledScreening(screening.id, toScreeningPayload(v));
    if (res.ok) {
      window.location.reload();
      return { ok: true };
    }
    return { ok: false, error: res.error };
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
    track("agent_run", { agent_id: screening.id, manual: true });

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

  const active = screening.is_active;
  const marketHours = screening.trading_session && screening.trading_session !== "none";
  const filterCount = screening.scan_filters ? countScreeningsFilterRules(screening.scan_filters) : 0;
  const nextRun = active ? nextRuns(screening.schedule, 1)[0] : undefined;

  // Left signal strip: paused = muted, recently triggered = amber, healthy = emerald.
  const stripClass = !active
    ? "bg-muted-foreground/25"
    : screening.last_triggered
      ? "bg-amber-500"
      : "bg-emerald-500";

  return (
    <>
      <div
        className={`group relative overflow-hidden rounded-xl border bg-card transition-all duration-200 ${
          deleting
            ? "pointer-events-none border-border opacity-50"
            : "border-border hover:border-foreground/15 hover:shadow-[0_4px_28px_-12px_rgba(0,0,0,0.3)]"
        }`}
      >
        {/* signal strip */}
        <span
          aria-hidden
          className={`absolute inset-y-0 left-0 w-[3px] ${stripClass} ${active && !screening.last_triggered ? "animate-signal-pulse" : ""}`}
        />

        <div className="flex min-w-0 items-start gap-3 py-3.5 pl-5 pr-3 sm:pr-4">
          <div className="min-w-0 flex-1">
            {/* row 1 — name · state · next-run */}
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <span className="truncate text-sm font-semibold text-foreground">{screening.name}</span>
              <span className={`rounded border px-1.5 py-px font-mono text-[9px] uppercase tracking-[0.1em] ${
                active
                  ? "border-emerald-500/30 bg-emerald-500/5 text-emerald-600 dark:text-emerald-400"
                  : "border-border bg-muted/50 text-muted-foreground"
              }`}>
                {active ? "live" : "paused"}
              </span>
              {screening.last_triggered && (
                <span className="inline-flex items-center gap-1 rounded border border-amber-500/30 bg-amber-500/5 px-1.5 py-px font-mono text-[9px] uppercase tracking-[0.1em] text-amber-600 dark:text-amber-400">
                  <Bell className="h-2.5 w-2.5" /> fired
                </span>
              )}
              <span className="ml-auto shrink-0 font-mono text-[11px] tabular-nums text-muted-foreground/70">
                {active ? `next ${fmtCountdown(nextRun)}` : "—"}
              </span>
            </div>

            {/* row 2 — prompt */}
            <p className="mt-1.5 line-clamp-2 text-[13px] leading-relaxed text-muted-foreground">{screening.prompt}</p>

            {/* row 3 — mono meta strip */}
            <div className="mt-2.5 flex flex-wrap items-center gap-1.5 font-mono text-[10px] tracking-[0.03em]">
              <span className="inline-flex items-center gap-1 text-muted-foreground/60">
                <Clock className="h-3 w-3 shrink-0" />
                {describeCron(screening.schedule)}
              </span>
              {(screening.tickers ?? []).map((t) => (
                <span key={t} className="rounded bg-muted px-1.5 py-px font-medium text-foreground/80">{t}</span>
              ))}
              {marketHours && (
                <span className="rounded border border-border px-1.5 py-px text-muted-foreground/70">mkt hrs</span>
              )}
              {screening.condition_enabled && (
                <span
                  className="rounded border border-amber-500/30 bg-amber-500/5 px-1.5 py-px text-amber-600 dark:text-amber-400"
                  title={screening.trigger_condition ?? undefined}
                >
                  cond
                </span>
              )}
              {(screening.linked_scan_sources ?? []).length > 0 && (
                <span
                  className="inline-flex items-center gap-1 rounded border border-emerald-500/30 bg-emerald-500/5 px-1.5 py-px text-emerald-600 dark:text-emerald-400"
                  title={(screening.linked_scan_sources ?? []).map(formatSourceLabel).join(", ")}
                >
                  <Link2 className="h-2.5 w-2.5" /> {screening.linked_scan_sources.length} live
                </span>
              )}
              {(screening.linked_scan_run_ids ?? []).length > 0 && (
                <span className="inline-flex items-center gap-1 rounded border border-border px-1.5 py-px text-muted-foreground/70">
                  <Link2 className="h-2.5 w-2.5" /> {screening.linked_scan_run_ids.length} pin
                </span>
              )}
              {filterCount > 0 && (
                <span className="inline-flex items-center gap-1 rounded border border-border px-1.5 py-px text-muted-foreground/70">
                  <Filter className="h-2.5 w-2.5" /> {filterCount}
                </span>
              )}
            </div>

            {/* last-run inline status */}
            {screening.last_run_at && (
              <p className="mt-2 font-mono text-[10px] text-muted-foreground/50">
                {screening.last_triggered ? "⚡ triggered" : "✓ no trigger"} · last {formatRunTime(screening.last_run_at)} · {screening.timezone}
              </p>
            )}

            {testing && (
              <div className="mt-3 flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                Queued — waiting for the agent runner to pick up…
              </div>
            )}
            {testError && (
              <div className="mt-3 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
                {testError}
              </div>
            )}
            {testResult && (
              <div className={`mt-3 rounded-lg border px-3 py-2.5 text-xs ${
                testResult.triggered ? "border-amber-500/30 bg-amber-500/5" : "border-border bg-muted/50"
              }`}>
                <div className="mb-1 flex items-center gap-1.5">
                  <span className={`font-mono text-[10px] uppercase tracking-[0.1em] ${testResult.triggered ? "text-amber-600 dark:text-amber-400" : "text-muted-foreground"}`}>
                    {testResult.triggered ? "triggered" : "not triggered"}
                  </span>
                </div>
                {testResult.summary && <p className="leading-relaxed text-foreground/80">{testResult.summary}</p>}
              </div>
            )}

            {showHistory && <RunHistory screeningId={screening.id} />}
          </div>

          {/* actions — one primary "Run" + overflow menu */}
          <div className="flex shrink-0 items-center gap-1">
            <button
              type="button"
              onClick={() => void handleTestRun()}
              disabled={testing}
              title="Test run now"
              className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border px-2.5 font-mono text-[11px] text-foreground transition-colors hover:border-amber-500/40 hover:bg-amber-500/5 hover:text-amber-600 disabled:opacity-40 dark:hover:text-amber-400"
            >
              {testing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Zap className="h-3.5 w-3.5" />}
              <span className="hidden sm:inline">Run</span>
            </button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  title="More actions"
                  className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                >
                  <MoreHorizontal className="h-4 w-4" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-44">
                <DropdownMenuItem onSelect={() => setEditing(true)}>
                  <Pencil className="mr-2 h-3.5 w-3.5" /> Edit
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => setShowHistory((v) => !v)}>
                  <History className="mr-2 h-3.5 w-3.5" /> {showHistory ? "Hide history" : "Run history"}
                </DropdownMenuItem>
                <DropdownMenuItem disabled={toggling} onSelect={() => void handleToggle()}>
                  {active ? <Pause className="mr-2 h-3.5 w-3.5" /> : <Play className="mr-2 h-3.5 w-3.5" />}
                  {active ? "Pause" : "Resume"}
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  disabled={deleting}
                  onSelect={() => void handleDelete()}
                  className="text-destructive focus:text-destructive"
                >
                  <Trash2 className="mr-2 h-3.5 w-3.5" /> Delete
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </div>

      <AgentFormDialog
        open={editing}
        onOpenChange={setEditing}
        mode="edit"
        initial={screeningToFormInitial(screening)}
        suggestionTickers={suggestionTickers}
        onSubmit={handleEditSubmit}
      />
    </>
  );
}
