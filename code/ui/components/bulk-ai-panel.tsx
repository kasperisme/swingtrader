"use client";

import { useEffect, useRef, useState } from "react";
import { Loader2, Sparkles, AlertCircle, Send, CheckCircle2 } from "lucide-react";
import ReactMarkdown from "react-markdown";
import type {
  BulkAnalysisJob,
  BulkChartGranularity,
} from "@/app/actions/screenings";
import type { ChartAiChatMessage } from "@/app/actions/chart-workspace";
import type { ChartGranularity } from "@/components/chart-date-range-picker";

const GRANULARITY_LABELS: Record<BulkChartGranularity, string> = {
  "1hour": "1H",
  "4hour": "4H",
  "1day": "1D",
  "1week": "1W",
};

const BULK_DEFAULT_PROMPT =
  "Run a swing-trading technical analysis. Highlight setup quality, key levels, and any risks.";

interface BulkAiPanelProps {
  job: BulkAnalysisJob | null;
  starting: boolean;
  error: string | null;
  onStart: (userPrompt: string) => Promise<void> | void;
  /** Number of tickers in the current scope, for context in the empty state. */
  tickerCount: number;
  /**
   * Number of filter rules currently active. When > 0, the panel tells the
   * user the run will respect those filters (the snapshot is taken at submit
   * time and stored on the job's ticker_subset).
   */
  activeFilterCount?: number;
  /** Current chart bar size from the Charts tab (snapshotted at submit). */
  chartGranularity?: ChartGranularity;
  /** Custom range from the chart picker, when set. */
  chartDateRange?: { from: string; to: string };
  /** Disabled when no run is selected (no rows to analyze). */
  disabled?: boolean;
}

export function BulkAiPanel({
  job,
  starting,
  error,
  onStart,
  tickerCount,
  activeFilterCount = 0,
  chartGranularity = "1day",
  chartDateRange,
  disabled = false,
}: BulkAiPanelProps) {
  const inFlight = job?.status === "queued" || job?.status === "running";
  const [draft, setDraft] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const threadEndRef = useRef<HTMLDivElement | null>(null);

  const messages = job?.bulk_chat_messages ?? [];
  const hasAssistant = messages.some((m) => m.role === "assistant");

  // Seed the draft from the previous job's prompt when entering this view.
  useEffect(() => {
    setDraft((prev) => prev || job?.user_prompt || "");
  }, [job?.user_prompt]);

  useEffect(() => {
    threadEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, job?.status, job?.completed_tickers]);

  const canSubmit = !disabled && !starting && !inFlight;

  const handleSubmit = async () => {
    if (!canSubmit) return;
    const prompt = draft.trim() || BULK_DEFAULT_PROMPT;
    await onStart(prompt);
  };

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="shrink-0 px-3 pt-3 pb-2 space-y-2 border-b border-border/60">
        <StatusBanner
          job={job}
          starting={starting}
          tickerCount={tickerCount}
          activeFilterCount={activeFilterCount}
          chartGranularity={chartGranularity}
          chartDateRange={chartDateRange}
        />
        {error ? (
          <div className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-[12px] text-destructive">
            <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
            <span className="min-w-0 break-words">{error}</span>
          </div>
        ) : null}
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto px-3 py-3">
        {messages.length > 0 ? (
          <div className="flex flex-col gap-3">
            {messages.map((m, i) => (
              <BulkChatBubble key={i} message={m} />
            ))}
            {inFlight ? (
              <div className="flex items-center gap-2 text-[11px] text-muted-foreground/60 pl-1">
                <Loader2 className="w-3 h-3 animate-spin" />
                Analyzing tickers…
              </div>
            ) : null}
            {(job?.status === "done" || job?.status === "error") && !hasAssistant ? (
              <div className="flex items-center gap-2 text-[11px] text-muted-foreground/60 pl-1">
                <Loader2 className="w-3 h-3 animate-spin" />
                Writing summary…
              </div>
            ) : null}
            <div ref={threadEndRef} />
          </div>
        ) : (
          <EmptyHint
            tickerCount={tickerCount}
            activeFilterCount={activeFilterCount}
            chartGranularity={chartGranularity}
            chartDateRange={chartDateRange}
            starting={starting}
            error={error}
          />
        )}
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

function BulkChatBubble({ message }: { message: ChartAiChatMessage }) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="bg-zinc-800/70 border border-zinc-700/40 text-foreground/85 rounded-2xl rounded-br-sm px-3.5 py-2 max-w-[88%] text-[12px] leading-relaxed whitespace-pre-wrap break-words">
          {message.content}
        </div>
      </div>
    );
  }
  return (
    <div className="flex flex-col items-start gap-1 max-w-[95%]">
      {message.source === "bulk_analysis" ? (
        <span className="text-[10px] uppercase tracking-widest text-muted-foreground/50">
          Bulk run summary
        </span>
      ) : null}
      <BulkSummaryMarkdown content={message.content} />
    </div>
  );
}

function BulkSummaryMarkdown({ content }: { content: string }) {
  return (
    <div className="text-[12px] leading-relaxed text-foreground/85 [&_p]:mb-2 [&_p:last-child]:mb-0 [&_ul]:mb-2 [&_ul]:pl-4 [&_ul]:list-disc [&_ol]:mb-2 [&_ol]:pl-4 [&_ol]:list-decimal [&_li]:mb-0.5 [&_strong]:font-semibold [&_strong]:text-foreground">
      <ReactMarkdown
        components={{
          p: ({ children }) => <p>{children}</p>,
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

function EmptyHint({
  tickerCount,
  activeFilterCount,
  chartGranularity,
  chartDateRange,
  starting,
  error,
}: {
  tickerCount: number;
  activeFilterCount: number;
  chartGranularity: ChartGranularity;
  chartDateRange?: { from: string; to: string };
  starting: boolean;
  error: string | null;
}) {
  if (starting || error) return null;
  return (
    <p className="text-[12px] text-muted-foreground leading-relaxed">
      Run the same prompt across{" "}
      {activeFilterCount > 0 ? "the filtered" : "every"} ticker in this
      screening. When the run finishes, a summary appears here; each ticker also
      gets its own analysis in the per-ticker chat.
      {activeFilterCount > 0
        ? " Active filters are snapshotted at submit time."
        : null}{" "}
      Uses chart bar size{" "}
      <span className="font-semibold text-foreground">
        {GRANULARITY_LABELS[chartGranularity]}
      </span>
      {chartDateRange?.from && chartDateRange?.to
        ? ` (${chartDateRange.from} → ${chartDateRange.to})`
        : ""}
      . Ready for{" "}
      <span className="font-semibold text-foreground">{tickerCount}</span>{" "}
      {tickerCount === 1 ? "ticker" : "tickers"}.
    </p>
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
  activeFilterCount,
  chartGranularity,
  chartDateRange,
}: {
  job: BulkAnalysisJob | null;
  starting: boolean;
  tickerCount: number;
  activeFilterCount: number;
  chartGranularity: ChartGranularity;
  chartDateRange?: { from: string; to: string };
}) {
  const granLabel = GRANULARITY_LABELS[chartGranularity];
  const rangeHint =
    chartDateRange?.from && chartDateRange?.to
      ? ` · ${chartDateRange.from}–${chartDateRange.to}`
      : "";
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
          {tickerCount === 1 ? "ticker" : "tickers"}
          {activeFilterCount > 0 ? (
            <>
              {" "}matching your{" "}
              <span className="font-semibold text-foreground">
                {activeFilterCount}
              </span>{" "}
              active {activeFilterCount === 1 ? "filter" : "filters"}
            </>
          ) : null}
          {" "}at{" "}
          <span className="font-semibold text-foreground">{granLabel}</span>
          {rangeHint}.
        </span>
      </Banner>
    );
  }

  if (job.status === "queued") {
    return (
      <Banner tone="info" icon={<Loader2 className="w-3.5 h-3.5 animate-spin" />}>
        <span>
          Queued — worker picks up within a minute (
          {job.total_tickers || tickerCount} tickers,{" "}
          {GRANULARITY_LABELS[job.chart_granularity ?? chartGranularity]}
          {job.chart_date_from && job.chart_date_to
            ? ` ${job.chart_date_from}–${job.chart_date_to}`
            : ""}
          ).
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
