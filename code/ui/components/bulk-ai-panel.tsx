"use client";

import { useEffect, useRef, useState } from "react";
import { Loader2, Sparkles, AlertCircle, Send, CheckCircle2 } from "lucide-react";
import type { BulkAnalysisJob } from "@/app/actions/screenings";

const BULK_DEFAULT_PROMPT =
  "Run a swing-trading technical analysis. Highlight setup quality, key levels, and any risks.";

interface BulkAiPanelProps {
  job: BulkAnalysisJob | null;
  starting: boolean;
  error: string | null;
  onStart: (userPrompt: string) => Promise<void> | void;
  /** Number of tickers in the current scope, for context in the empty state. */
  tickerCount: number;
  /** Disabled when no run is selected (no rows to analyze). */
  disabled?: boolean;
}

export function BulkAiPanel({
  job,
  starting,
  error,
  onStart,
  tickerCount,
  disabled = false,
}: BulkAiPanelProps) {
  const inFlight = job?.status === "queued" || job?.status === "running";
  const [draft, setDraft] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  // Seed the draft from the previous job's prompt when entering this view.
  useEffect(() => {
    setDraft((prev) => prev || job?.user_prompt || "");
  }, [job?.user_prompt]);

  const canSubmit = !disabled && !starting && !inFlight;

  const handleSubmit = async () => {
    if (!canSubmit) return;
    const prompt = draft.trim() || BULK_DEFAULT_PROMPT;
    await onStart(prompt);
  };

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="flex-1 min-h-0 overflow-y-auto px-3 py-3 space-y-3">
        <StatusBanner job={job} starting={starting} tickerCount={tickerCount} />

        {error ? (
          <div className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-[12px] text-destructive">
            <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
            <span className="min-w-0 break-words">{error}</span>
          </div>
        ) : null}

        {job?.user_prompt ? (
          <div className="rounded-md border border-border bg-muted/20 px-3 py-2">
            <div className="text-[10px] uppercase tracking-widest text-muted-foreground/70 mb-1">
              Last prompt
            </div>
            <p className="text-[12px] text-foreground/80 whitespace-pre-wrap break-words leading-relaxed">
              {job.user_prompt}
            </p>
          </div>
        ) : null}

        {!job && !starting && !error ? (
          <p className="text-[12px] text-muted-foreground leading-relaxed">
            Run the same prompt across every ticker in this screening. Each
            ticker gets its own per-ticker analysis written back to its row,
            so you can review them in the regular chat afterwards.
          </p>
        ) : null}
      </div>

      <div className="border-t border-border px-3 py-2 space-y-2 shrink-0 bg-background">
        <textarea
          ref={textareaRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
              e.preventDefault();
              void handleSubmit();
            }
          }}
          placeholder={BULK_DEFAULT_PROMPT}
          rows={3}
          maxLength={2000}
          disabled={!canSubmit}
          className="w-full text-[12px] rounded-md border border-input bg-background px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-ring resize-none disabled:opacity-60"
        />
        <div className="flex items-center justify-between gap-2">
          <span className="text-[11px] text-muted-foreground">
            ⌘/Ctrl+Enter to start · {draft.length}/2000
          </span>
          <button
            type="button"
            onClick={() => void handleSubmit()}
            disabled={!canSubmit}
            className="inline-flex items-center gap-1.5 text-[12px] px-2.5 py-1.5 rounded-md border border-foreground bg-foreground text-background hover:opacity-90 disabled:pointer-events-none disabled:opacity-50"
          >
            {starting || inFlight ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : job?.status === "done" || job?.status === "error" ? (
              <Sparkles className="w-3.5 h-3.5" />
            ) : (
              <Send className="w-3.5 h-3.5" />
            )}
            {startLabel(job, starting, inFlight)}
          </button>
        </div>
      </div>
    </div>
  );
}

function startLabel(
  job: BulkAnalysisJob | null,
  starting: boolean,
  inFlight: boolean,
): string {
  if (starting) return "Starting…";
  if (inFlight) return "Running";
  if (job?.status === "done") return "Re-analyze all";
  if (job?.status === "error") return "Retry";
  return "Analyze all";
}

function StatusBanner({
  job,
  starting,
  tickerCount,
}: {
  job: BulkAnalysisJob | null;
  starting: boolean;
  tickerCount: number;
}) {
  if (starting) {
    return (
      <Banner tone="info" icon={<Loader2 className="w-3.5 h-3.5 animate-spin" />}>
        <span>Queuing bulk analysis…</span>
      </Banner>
    );
  }

  if (!job) {
    return (
      <Banner tone="neutral" icon={<Sparkles className="w-3.5 h-3.5" />}>
        <span>
          Ready — will analyze{" "}
          <span className="font-semibold text-foreground">
            {tickerCount}
          </span>{" "}
          {tickerCount === 1 ? "ticker" : "tickers"}.
        </span>
      </Banner>
    );
  }

  if (job.status === "queued") {
    return (
      <Banner tone="info" icon={<Loader2 className="w-3.5 h-3.5 animate-spin" />}>
        <span>
          Queued — worker picks up within a minute (
          {job.total_tickers || tickerCount} tickers).
        </span>
      </Banner>
    );
  }

  if (job.status === "running") {
    const total = job.total_tickers || 0;
    const done = job.completed_tickers || 0;
    return (
      <Banner tone="info" icon={<Loader2 className="w-3.5 h-3.5 animate-spin" />}>
        <span>
          Running{" "}
          <span className="font-mono tabular-nums">
            {done}/{total || "…"}
          </span>
          {job.failed_tickers > 0 ? (
            <span className="text-destructive ml-1.5">
              · {job.failed_tickers} failed
            </span>
          ) : null}
        </span>
      </Banner>
    );
  }

  if (job.status === "done") {
    const total = job.total_tickers || 0;
    const succeeded = Math.max(0, (job.completed_tickers ?? 0) - (job.failed_tickers ?? 0));
    return (
      <Banner tone="success" icon={<CheckCircle2 className="w-3.5 h-3.5" />}>
        <span>
          Done —{" "}
          <span className="font-mono tabular-nums">
            {succeeded}/{total}
          </span>{" "}
          succeeded
          {job.failed_tickers > 0 ? (
            <span className="text-destructive ml-1.5">
              · {job.failed_tickers} failed
            </span>
          ) : null}
          .
        </span>
      </Banner>
    );
  }

  if (job.status === "error") {
    return (
      <Banner tone="error" icon={<AlertCircle className="w-3.5 h-3.5" />}>
        <span>{job.error_message || "Previous job errored."}</span>
      </Banner>
    );
  }

  return null;
}

function Banner({
  tone,
  icon,
  children,
}: {
  tone: "info" | "success" | "error" | "neutral";
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  const cls =
    tone === "info"
      ? "border-primary/30 bg-primary/5 text-primary"
      : tone === "success"
        ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
        : tone === "error"
          ? "border-destructive/30 bg-destructive/5 text-destructive"
          : "border-border bg-muted/30 text-muted-foreground";
  return (
    <div className={`flex items-start gap-2 rounded-md border px-3 py-2 text-[12px] ${cls}`}>
      <span className="shrink-0 mt-0.5">{icon}</span>
      <span className="min-w-0 break-words">{children}</span>
    </div>
  );
}
