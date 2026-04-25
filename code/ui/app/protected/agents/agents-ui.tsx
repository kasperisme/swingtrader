"use client";

import { useState } from "react";
import { Bot, Pause, Play, Trash2, Plus, Clock, AlertCircle, Zap, Loader2 } from "lucide-react";
import {
  type ScheduledScreening,
  type ScreeningResult,
  createScheduledScreening,
  toggleScreening,
  deleteScheduledScreening,
  testRunScreening,
  pollTestResult,
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

const SCHEDULE_PRESETS: { label: string; cron: string }[] = [
  { label: "Weekdays 7:00 AM ET", cron: "0 7 * * 1-5" },
  { label: "Weekdays 8:00 AM ET", cron: "0 8 * * 1-5" },
  { label: "Every 4 hours", cron: "0 */4 * * *" },
  { label: "Hourly", cron: "0 * * * *" },
  { label: "Every 15 minutes", cron: "*/15 * * * *" },
  { label: "Daily midnight", cron: "0 0 * * *" },
];

export function AgentsUI({ screenings, limits, error }: Props) {
  const [showForm, setShowForm] = useState(false);
  const atLimit = limits ? limits.used >= limits.limit : true;

  return (
    <div className="flex flex-col gap-6 w-full">
      {error && (
        <div className="flex items-start gap-3 rounded-xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
          {error}
        </div>
      )}

      {/* Usage + new button */}
      <div className="flex items-center justify-between">
        {limits && (
          <p className="text-sm text-muted-foreground">
            <span className="font-semibold text-foreground">{limits.used}</span>
            <span className="text-muted-foreground/60"> / {limits.limit}</span>
            {" "}active agents
            <span className="ml-2 text-xs text-muted-foreground/60">({limits.plan} plan)</span>
          </p>
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

      {showForm && (
        <CreateForm
          onClose={() => setShowForm(false)}
          atLimit={atLimit}
        />
      )}

      {/* Agent list */}
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
    </div>
  );
}

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
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Schedule</label>
            <select
              value={schedule}
              onChange={(e) => setSchedule(e.target.value)}
              className={inputClass}
            >
              {SCHEDULE_PRESETS.map((p) => (
                <option key={p.cron} value={p.cron}>{p.label}</option>
              ))}
            </select>
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

  const preset = SCHEDULE_PRESETS.find((p) => p.cron === screening.schedule);

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
              {preset?.label ?? screening.schedule}
            </span>
            <span>{screening.timezone}</span>
            {screening.last_run_at && (
              <span>Last run {new Date(screening.last_run_at).toLocaleString()}</span>
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
