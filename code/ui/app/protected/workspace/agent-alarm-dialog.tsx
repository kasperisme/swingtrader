"use client";

import { useEffect, useMemo, useState, useTransition } from "react";
import {
  Bell,
  CheckCircle2,
  Clock,
  Loader2,
  Plus,
  Sparkles,
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  createScheduledScreening,
  listScheduledScreenings,
  updateScheduledScreening,
  type ScheduledScreening,
} from "@/app/actions/screenings-agent";

type Mode = "existing" | "new";

const SCHEDULE_PRESETS: Array<{
  id: string;
  label: string;
  detail: string;
  cron: string;
}> = [
  {
    id: "daily-premarket",
    label: "Daily · pre-market",
    detail: "07:00 ET, weekdays",
    cron: "0 7 * * 1-5",
  },
  {
    id: "hourly-market",
    label: "Hourly · market hours",
    detail: "09:00–16:00 ET, weekdays",
    cron: "0 9-16 * * 1-5",
  },
  {
    id: "every-4h",
    label: "Every 4 hours",
    detail: "Around the clock",
    cron: "0 */4 * * *",
  },
  {
    id: "every-15m",
    label: "Every 15 min · market hours",
    detail: "Tight tape — trader plan",
    cron: "*/15 9-16 * * 1-5",
  },
];

function describeCron(cron: string): string {
  const preset = SCHEDULE_PRESETS.find((p) => p.cron === cron);
  if (preset) return preset.label;
  return cron;
}

export function AgentAlarmDialog({
  ticker,
  open,
  onClose,
}: {
  ticker: string | null;
  open: boolean;
  onClose: () => void;
}) {
  const [mode, setMode] = useState<Mode>("existing");
  const [screenings, setScreenings] = useState<ScheduledScreening[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, startTransition] = useTransition();
  const [actionError, setActionError] = useState<string | null>(null);
  const [justAddedTo, setJustAddedTo] = useState<string | null>(null);

  // Create-form state
  const [name, setName] = useState("");
  const [prompt, setPrompt] = useState("");
  const [scheduleId, setScheduleId] = useState(SCHEDULE_PRESETS[1].id);

  useEffect(() => {
    if (!open || !ticker) return;
    setActionError(null);
    setJustAddedTo(null);
    setLoadError(null);
    setScreenings(null);

    let cancelled = false;
    void listScheduledScreenings().then((res) => {
      if (cancelled) return;
      if (!res.ok) {
        setLoadError(res.error);
        return;
      }
      setScreenings(res.data);
      // Auto-flip to "create new" when user has no agents — fewer dead-ends.
      if (res.data.length === 0) setMode("new");
      else setMode("existing");
    });

    setName(`${ticker} — alert`);
    setPrompt(
      `Watch ${ticker} for material news — earnings, guidance, downgrades, sector moves, or technical breakouts. Surface anything that would change a swing-trade thesis.`,
    );
    setScheduleId(SCHEDULE_PRESETS[1].id);

    return () => {
      cancelled = true;
    };
  }, [open, ticker]);

  const selectedSchedule = useMemo(
    () =>
      SCHEDULE_PRESETS.find((p) => p.id === scheduleId) ?? SCHEDULE_PRESETS[1],
    [scheduleId],
  );

  function addTickerToScreening(screening: ScheduledScreening) {
    if (!ticker) return;
    const already = screening.tickers.includes(ticker);
    if (already) return;
    setActionError(null);
    startTransition(async () => {
      const next = [...screening.tickers, ticker];
      const res = await updateScheduledScreening(screening.id, {
        tickers: next,
      });
      if (!res.ok) {
        setActionError(res.error);
        return;
      }
      setScreenings((prev) =>
        prev
          ? prev.map((s) => (s.id === screening.id ? res.data : s))
          : prev,
      );
      setJustAddedTo(screening.id);
    });
  }

  function submitCreate() {
    if (!ticker) return;
    const trimmedName = name.trim();
    const trimmedPrompt = prompt.trim();
    if (trimmedName.length < 2) {
      setActionError("Name needs at least 2 characters.");
      return;
    }
    if (trimmedPrompt.length < 10) {
      setActionError("Prompt is too short — describe what to watch for.");
      return;
    }
    setActionError(null);
    startTransition(async () => {
      const res = await createScheduledScreening({
        name: trimmedName,
        prompt: trimmedPrompt,
        schedule: selectedSchedule.cron,
        timezone: "America/New_York",
        tickers: [ticker],
      });
      if (!res.ok) {
        setActionError(res.error);
        return;
      }
      setJustAddedTo(res.data.id);
      setScreenings((prev) => (prev ? [res.data, ...prev] : [res.data]));
      setMode("existing");
    });
  }

  if (!ticker) return null;

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-lg gap-0 overflow-hidden p-0">
        <DialogHeader className="space-y-3 border-b border-border/60 px-6 pb-4 pt-6">
          <div className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.2em] text-amber-500/80">
            <Bell className="h-3 w-3" />
            Agent alarm
          </div>
          <DialogTitle className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-xl font-semibold tracking-tight">
            <span>Set up an alarm for</span>
            <span className="rounded-md border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 font-mono text-base text-amber-500">
              {ticker}
            </span>
          </DialogTitle>
          <p className="text-sm leading-relaxed text-muted-foreground">
            Add this ticker to one of your existing screenings, or wire up a
            new scheduled agent that watches it.
          </p>

          <ModeToggle
            mode={mode}
            onChange={setMode}
            existingCount={screenings?.length ?? 0}
          />
        </DialogHeader>

        <div className="max-h-[60vh] overflow-y-auto px-6 py-5">
          {mode === "existing" ? (
            <ExistingList
              ticker={ticker}
              screenings={screenings}
              loadError={loadError}
              busy={busy}
              justAddedTo={justAddedTo}
              onAdd={addTickerToScreening}
              onSwitchToCreate={() => setMode("new")}
            />
          ) : (
            <CreateNewForm
              name={name}
              prompt={prompt}
              scheduleId={scheduleId}
              onChangeName={setName}
              onChangePrompt={setPrompt}
              onChangeSchedule={setScheduleId}
            />
          )}

          {actionError && (
            <p className="mt-4 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-400">
              {actionError}
            </p>
          )}
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-border/60 bg-muted/20 px-6 py-3">
          <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
            {mode === "new"
              ? describeCron(selectedSchedule.cron)
              : screenings
                ? `${screenings.length} agent${screenings.length === 1 ? "" : "s"}`
                : "Loading…"}
          </p>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-md px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
            >
              Close
            </button>
            {mode === "new" && (
              <button
                type="button"
                onClick={submitCreate}
                disabled={busy}
                className="inline-flex items-center gap-1.5 rounded-md bg-amber-500 px-3.5 py-1.5 text-xs font-semibold text-black transition-colors hover:bg-amber-400 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {busy ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <Sparkles className="h-3 w-3" />
                )}
                Create agent
              </button>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function ModeToggle({
  mode,
  onChange,
  existingCount,
}: {
  mode: Mode;
  onChange: (m: Mode) => void;
  existingCount: number;
}) {
  const base =
    "flex-1 inline-flex items-center justify-center gap-1.5 rounded-sm px-3 py-1.5 font-mono text-[10px] uppercase tracking-[0.18em] transition-colors";
  const active = "bg-foreground text-background";
  const inactive = "text-muted-foreground hover:text-foreground";
  return (
    <div
      role="tablist"
      aria-label="Alarm setup mode"
      className="inline-flex w-full items-center gap-1 rounded-md border border-border bg-background/60 p-0.5"
    >
      <button
        role="tab"
        aria-selected={mode === "existing"}
        type="button"
        onClick={() => onChange("existing")}
        className={`${base} ${mode === "existing" ? active : inactive}`}
      >
        Add to existing
        {existingCount > 0 && (
          <span className="font-sans tabular-nums">· {existingCount}</span>
        )}
      </button>
      <button
        role="tab"
        aria-selected={mode === "new"}
        type="button"
        onClick={() => onChange("new")}
        className={`${base} ${mode === "new" ? active : inactive}`}
      >
        Create new
      </button>
    </div>
  );
}

function ExistingList({
  ticker,
  screenings,
  loadError,
  busy,
  justAddedTo,
  onAdd,
  onSwitchToCreate,
}: {
  ticker: string;
  screenings: ScheduledScreening[] | null;
  loadError: string | null;
  busy: boolean;
  justAddedTo: string | null;
  onAdd: (screening: ScheduledScreening) => void;
  onSwitchToCreate: () => void;
}) {
  if (loadError) {
    return (
      <p className="rounded-md border border-rose-500/30 bg-rose-500/5 px-3 py-2 text-xs text-rose-400">
        {loadError}
      </p>
    );
  }

  if (screenings === null) {
    return (
      <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading your agents…
      </div>
    );
  }

  if (screenings.length === 0) {
    return (
      <div className="flex flex-col items-start gap-3 border-l-2 border-amber-500/40 py-4 pl-4">
        <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-amber-500/80">
          No agents yet
        </p>
        <p className="max-w-[42ch] text-sm leading-relaxed text-muted-foreground">
          You haven&apos;t set up any scheduled screenings. Create one now —
          {" "}
          {ticker} will be its first ticker.
        </p>
        <button
          type="button"
          onClick={onSwitchToCreate}
          className="inline-flex items-center gap-1.5 rounded-sm border border-amber-500/50 bg-amber-500/10 px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.18em] text-amber-500 transition-colors hover:bg-amber-500/15"
        >
          <Plus className="h-3 w-3" />
          Create the first one
        </button>
      </div>
    );
  }

  return (
    <ul className="divide-y divide-border/40">
      {screenings.map((s) => {
        const already = s.tickers.includes(ticker);
        const added = justAddedTo === s.id;
        return (
          <li key={s.id} className="grid grid-cols-[1fr_auto] gap-x-4 py-3">
            <div className="min-w-0">
              <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                <span className="truncate text-sm font-medium tracking-tight">
                  {s.name}
                </span>
                {!s.is_active && (
                  <span className="font-mono text-[9px] uppercase tracking-[0.18em] text-muted-foreground/70">
                    Paused
                  </span>
                )}
              </div>
              <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 font-mono text-[10px] uppercase tracking-[0.15em] text-muted-foreground">
                <Clock className="h-3 w-3" />
                {describeCron(s.schedule)}
                <span className="text-muted-foreground/40">·</span>
                <span className="tabular-nums normal-case tracking-normal">
                  {s.tickers.length} ticker{s.tickers.length === 1 ? "" : "s"}
                </span>
              </p>
            </div>
            <div className="self-center">
              {already ? (
                <span className="inline-flex items-center gap-1 font-mono text-[10px] uppercase tracking-[0.18em] text-emerald-500/90">
                  <CheckCircle2 className="h-3 w-3" />
                  Included
                </span>
              ) : added ? (
                <span className="inline-flex items-center gap-1 font-mono text-[10px] uppercase tracking-[0.18em] text-emerald-500">
                  <CheckCircle2 className="h-3 w-3" />
                  Added
                </span>
              ) : (
                <button
                  type="button"
                  onClick={() => onAdd(s)}
                  disabled={busy}
                  className="inline-flex items-center gap-1 rounded-md border border-border bg-background px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.18em] text-foreground transition-colors hover:border-amber-500/50 hover:bg-amber-500/10 hover:text-amber-400 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {busy ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <Plus className="h-3 w-3" />
                  )}
                  Add {ticker}
                </button>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function CreateNewForm({
  name,
  prompt,
  scheduleId,
  onChangeName,
  onChangePrompt,
  onChangeSchedule,
}: {
  name: string;
  prompt: string;
  scheduleId: string;
  onChangeName: (v: string) => void;
  onChangePrompt: (v: string) => void;
  onChangeSchedule: (id: string) => void;
}) {
  return (
    <div className="space-y-5">
      <div>
        <label
          htmlFor="agent-name"
          className="mb-1.5 block font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground"
        >
          Name
        </label>
        <input
          id="agent-name"
          type="text"
          value={name}
          onChange={(e) => onChangeName(e.target.value)}
          className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm outline-none transition-colors focus:border-amber-500/60"
          placeholder="AAPL — earnings watch"
        />
      </div>

      <div>
        <label
          className="mb-1.5 block font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground"
        >
          Schedule
        </label>
        <div className="grid grid-cols-2 gap-2">
          {SCHEDULE_PRESETS.map((p) => {
            const selected = p.id === scheduleId;
            return (
              <button
                key={p.id}
                type="button"
                onClick={() => onChangeSchedule(p.id)}
                className={`text-left rounded-md border px-3 py-2 transition-colors ${
                  selected
                    ? "border-amber-500/60 bg-amber-500/10"
                    : "border-border bg-background hover:border-foreground/30"
                }`}
              >
                <div className="text-sm font-medium tracking-tight">
                  {p.label}
                </div>
                <div className="mt-0.5 font-mono text-[10px] text-muted-foreground">
                  {p.detail}
                </div>
              </button>
            );
          })}
        </div>
      </div>

      <div>
        <label
          htmlFor="agent-prompt"
          className="mb-1.5 block font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground"
        >
          What should the agent watch for?
        </label>
        <textarea
          id="agent-prompt"
          value={prompt}
          onChange={(e) => onChangePrompt(e.target.value)}
          rows={4}
          className="w-full resize-none rounded-md border border-border bg-background px-3 py-2 text-sm leading-relaxed outline-none transition-colors focus:border-amber-500/60"
        />
      </div>
    </div>
  );
}
