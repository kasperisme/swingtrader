"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { ChatMarkdown } from "@/components/chat-markdown";
import { cn } from "@/lib/utils";

/**
 * Renders a `row_data.llm_analysis` object inside the results table. The bulk
 * analysis worker writes this shape:
 *
 *   { status, comment, analysis_markdown, entry: { direction, price, … } | null }
 *
 * Without this the table cell falls back to `String(value)` → "[object Object]".
 * The cell shows a status pill + the one-line comment + an entry chip, and the
 * (potentially long) `analysis_markdown` is capped behind a "Show analysis"
 * toggle so it never blows up the row height.
 */

export type LlmAnalysisEntry = {
  direction?: string | null;
  price?: number | null;
  take_profit?: number | null;
  stop_loss?: number | null;
};

export type LlmAnalysis = {
  status?: string | null;
  comment?: string | null;
  analysis_markdown?: string | null;
  entry?: LlmAnalysisEntry | null;
};

/** Detect the bulk-analysis object so the table can route it here. */
export function isLlmAnalysis(v: unknown): v is LlmAnalysis {
  if (!v || typeof v !== "object" || Array.isArray(v)) return false;
  const o = v as Record<string, unknown>;
  return "analysis_markdown" in o || ("status" in o && "comment" in o);
}

const STATUS_STYLES: Record<string, string> = {
  pipeline: "border-sky-400/40 bg-sky-400/10 text-sky-600 dark:text-sky-300",
  watchlist:
    "border-amber-400/40 bg-amber-400/10 text-amber-600 dark:text-amber-300",
  active:
    "border-border bg-muted/40 text-muted-foreground",
  dismissed:
    "border-red-400/40 bg-red-400/10 text-red-600 dark:text-red-300",
};

function fmtPrice(n: number | null | undefined): string | null {
  if (n === null || n === undefined || !Number.isFinite(Number(n))) return null;
  const v = Number(n);
  return Number.isInteger(v) ? v.toLocaleString() : v.toFixed(2);
}

export function LlmAnalysisCell({ value }: { value: LlmAnalysis }) {
  const [open, setOpen] = useState(false);

  const status = (value.status ?? "").toLowerCase().trim();
  const comment = (value.comment ?? "").trim();
  const markdown = (value.analysis_markdown ?? "").trim();
  const entry = value.entry ?? null;

  const entryPrice = fmtPrice(entry?.price);
  const tp = fmtPrice(entry?.take_profit);
  const sl = fmtPrice(entry?.stop_loss);
  const direction = (entry?.direction ?? "").toLowerCase().trim();

  const hasContent = status || comment || markdown || entryPrice;
  if (!hasContent) return <span className="text-muted-foreground">—</span>;

  return (
    <div className="min-w-[15rem] max-w-[24rem] space-y-1.5 whitespace-normal py-0.5 text-left">
      {(status || entryPrice) && (
        <div className="flex flex-wrap items-center gap-1.5">
          {status && (
            <span
              className={cn(
                "inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide",
                STATUS_STYLES[status] ?? STATUS_STYLES.active,
              )}
            >
              {status}
            </span>
          )}
          {entryPrice && (
            <span className="inline-flex items-center gap-1 rounded-md border border-border bg-background px-1.5 py-0.5 text-[11px] tabular-nums text-foreground/80">
              {direction === "short" ? "Short" : "Long"} @ {entryPrice}
              {tp ? <span className="text-emerald-500">· TP {tp}</span> : null}
              {sl ? <span className="text-red-500">· SL {sl}</span> : null}
            </span>
          )}
        </div>
      )}

      {comment && (
        <p className="text-[12px] leading-5 text-foreground/85">{comment}</p>
      )}

      {markdown && (
        <div>
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            className="inline-flex items-center gap-1 text-[11px] font-medium text-primary/80 transition-colors hover:text-primary"
          >
            {open ? (
              <ChevronDown className="h-3 w-3" />
            ) : (
              <ChevronRight className="h-3 w-3" />
            )}
            {open ? "Hide analysis" : "Show analysis"}
          </button>
          {open && (
            <div className="mt-1.5 max-h-72 overflow-y-auto rounded-md border border-border/70 bg-muted/20 p-2.5">
              <ChatMarkdown content={markdown} variant="analysis" />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
