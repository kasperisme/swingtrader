"use client";

import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { ChevronDown, ChevronRight, Loader2, Send, Sparkles } from "lucide-react";
import { ChatMarkdown } from "@/components/chat-markdown";
import type { OhlcBar } from "@/components/ticker-charts/types";
import type {
  ChartAiChatMessage,
  PersonaReport,
} from "@/app/actions/chart-workspace";

const REVIEW_PERSONA_COLORS: Record<string, string> = {
  entry_quality: "#3b82f6",
  exit_quality: "#a855f7",
  risk_management: "#ef4444",
  lesson: "#10b981",
};

function scoreColor(v: number): string {
  if (v >= 62) return "#10b981";
  if (v >= 42) return "#f59e0b";
  return "#ef4444";
}

function ScoreChip({ label, value }: { label: string; value: number }) {
  return (
    <span
      title={`${label}: ${value}/100`}
      className="text-[9px] font-mono tabular-nums tracking-tight"
      style={{ color: scoreColor(value) }}
    >
      {label}
      <span className="font-bold">{value}</span>
    </span>
  );
}

function ReviewPersonaSection({ report, loading }: { report: PersonaReport; loading?: boolean }) {
  const [open, setOpen] = useState(false);
  const color = REVIEW_PERSONA_COLORS[report.id] ?? "#6b7280";
  return (
    <div style={{ borderLeft: `2px solid ${color}50` }}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2.5 px-3 py-2 hover:bg-muted/15 transition-colors cursor-pointer"
      >
        <span className="w-[5px] h-[5px] rounded-full flex-shrink-0" style={{ background: color }} />
        <span className="text-[11px] font-medium flex-1 text-left" style={{ color }}>
          {report.label}
        </span>
        {loading && <Loader2 className="w-2.5 h-2.5 animate-spin" style={{ color: `${color}60` }} />}
        <span className="flex items-center gap-2 mr-1">
          {loading ? (
            <span className="text-[9px] text-muted-foreground/20 font-mono tracking-widest">···</span>
          ) : report.scores ? (
            <>
              <ScoreChip label="EX:" value={report.scores.confidence} />
              <ScoreChip label="TI:" value={report.scores.short_term} />
              <ScoreChip label="RM:" value={report.scores.long_term} />
            </>
          ) : null}
        </span>
        {open ? (
          <ChevronDown className="w-3 h-3 text-muted-foreground/35 flex-shrink-0" />
        ) : (
          <ChevronRight className="w-3 h-3 text-muted-foreground/35 flex-shrink-0" />
        )}
      </button>
      {open && (
        <div className="px-3 pb-3 pt-1" style={{ borderTop: `1px solid ${color}15` }}>
          {report.error ? (
            <p className="text-[11px] text-red-400 mt-1.5">{report.error}</p>
          ) : (
            <div className="mt-1.5">
              <ChatMarkdown content={report.analysis || "…"} variant="persona" />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ReviewPersonaReports({
  reports,
  loadingIds,
}: {
  reports: PersonaReport[];
  loadingIds?: Set<string>;
}) {
  if (!reports.length) return null;
  return (
    <div className="flex flex-col mt-2 rounded-lg overflow-hidden border border-border/40 divide-y divide-border/25">
      {reports.map((r) => (
        <ReviewPersonaSection key={r.id} report={r} loading={loadingIds?.has(r.id)} />
      ))}
    </div>
  );
}

const PROMPT_CHIPS = [
  "What was the biggest mistake here?",
  "What did I do well?",
  "Was the entry timed correctly?",
  "Did I exit too early or too late?",
  "What's the single rule I should apply next time?",
];

export interface TradeReviewChatProps {
  closingTradeId: number;
  ticker: string;
  ohlcData: OhlcBar[];
  messages: ChartAiChatMessage[];
  setMessages: Dispatch<SetStateAction<ChartAiChatMessage[]>>;
  /** Auto-kick the first review when there's no chat history. */
  autoStart?: boolean;
}

export function TradeReviewChat({
  closingTradeId,
  ticker,
  ohlcData,
  messages,
  setMessages,
  autoStart = false,
}: TradeReviewChatProps) {
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [streamingPersonas, setStreamingPersonas] = useState<PersonaReport[]>([]);
  const [loadingPersonaIds, setLoadingPersonaIds] = useState<Set<string>>(new Set());
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const autoStartedRef = useRef(false);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  async function executeStream(history: ChartAiChatMessage[]) {
    setLoading(true);
    setStreamingPersonas([]);
    setLoadingPersonaIds(new Set());

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    let assistantContent = "";
    const collectedPersonas: PersonaReport[] = [];

    try {
      const res = await fetch("/api/ai/trade-review", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify({ closingTradeId, ohlcData, messages: history }),
      });

      if (!res.ok) {
        const errText = await res.text().catch(() => res.statusText);
        throw new Error(`${res.status}: ${errText}`);
      }
      if (!res.body) throw new Error("No response body");

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.trim()) continue;
          let msg: Record<string, unknown>;
          try {
            msg = JSON.parse(line) as Record<string, unknown>;
          } catch {
            continue;
          }

          if (msg.type === "specialists_requested") {
            const ids = (msg.personas as string[]) ?? [];
            const personaLabels: Record<string, string> = {
              entry_quality: "Entry Quality",
              exit_quality: "Exit Quality",
              risk_management: "Risk Management",
              lesson: "Lesson",
            };
            setStreamingPersonas(
              ids.map((id) => ({ id, label: personaLabels[id] ?? id, analysis: "", error: null })),
            );
            setLoadingPersonaIds(new Set(ids));
          } else if (msg.type === "persona") {
            const report: PersonaReport = {
              id: msg.id as string,
              label: msg.label as string,
              analysis: msg.analysis as string,
              error: (msg.error as string | null) ?? null,
              scores: (msg.scores as PersonaReport["scores"]) ?? undefined,
            };
            collectedPersonas.push(report);
            setStreamingPersonas((prev) => prev.map((p) => (p.id === report.id ? report : p)));
            setLoadingPersonaIds((prev) => {
              const next = new Set(prev);
              next.delete(report.id);
              return next;
            });
          } else if (msg.type === "analysis") {
            assistantContent = msg.content as string;
            setMessages((prev) => {
              const copy = [...prev];
              copy[copy.length - 1] = { role: "assistant", content: assistantContent };
              return copy;
            });
          } else if (msg.type === "error") {
            setMessages((prev) => [
              ...prev,
              { role: "assistant", content: `Error: ${String(msg.message)}` },
            ]);
          }
        }
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name !== "AbortError") {
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: `Error: ${err.message}` },
        ]);
      }
    } finally {
      setLoading(false);
      setMessages((prev) => {
        const copy = [...prev];
        const last = copy[copy.length - 1];
        if (last?.role === "assistant" && collectedPersonas.length) {
          copy[copy.length - 1] = { ...last, personaReports: collectedPersonas };
        }
        return copy;
      });
      setStreamingPersonas([]);
      setLoadingPersonaIds(new Set());
    }
  }

  async function send(text?: string) {
    const value = (text ?? input).trim();
    if (!value || loading) return;
    const userMsg: ChartAiChatMessage = { role: "user", content: value };
    const historyAfterUser = [...messages, userMsg];
    setMessages([...historyAfterUser, { role: "assistant", content: "" }]);
    setInput("");
    await executeStream(historyAfterUser);
  }

  async function kickoff() {
    if (loading) return;
    setMessages([{ role: "assistant", content: "" }]);
    await executeStream([]);
  }

  useEffect(() => {
    if (!autoStart) return;
    if (autoStartedRef.current) return;
    if (messages.length > 0) return;
    autoStartedRef.current = true;
    void kickoff();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoStart]);

  return (
    <div className="flex flex-col bg-background flex-1 min-h-0">
      <div className="shrink-0 flex items-center justify-between px-4 py-2.5 border-b border-border/60">
        <div className="flex items-center gap-2">
          <div className="w-5 h-5 rounded-md bg-zinc-800 border border-zinc-700/60 flex items-center justify-center">
            <Sparkles className="w-3 h-3 text-amber-400/90" />
          </div>
          <span className="text-[11px] font-medium text-foreground/70 tracking-tight">
            Post-Trade Review
          </span>
          <span className="text-[10px] text-muted-foreground/40 font-mono">·</span>
          <span className="text-[11px] font-mono font-medium text-foreground/50">{ticker}</span>
        </div>
      </div>

      {messages.length === 0 && !loading && (
        <div className="flex-1 px-4 py-6 flex flex-col items-start gap-3">
          <p className="text-[12px] text-foreground/70">
            Run the AI review of this closed position. Four specialist reviewers will grade the entry,
            exit, risk management, and pull out the key lesson.
          </p>
          <button
            type="button"
            onClick={() => void kickoff()}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-[12px] font-medium bg-amber-500/15 text-amber-400 border border-amber-500/30 hover:bg-amber-500/25 transition-colors"
          >
            <Sparkles className="w-3.5 h-3.5" />
            Run review
          </button>
        </div>
      )}

      {messages.length > 0 && (
        <div className="flex flex-col gap-4 px-4 py-4 overflow-y-auto flex-1 min-h-0">
          {messages.map((m, i) => (
            <div
              key={i}
              className={`flex flex-col gap-1 ${m.role === "user" ? "items-end" : "items-start"}`}
            >
              {m.role === "user" ? (
                <div className="bg-zinc-800/70 border border-zinc-700/40 text-foreground/85 rounded-2xl rounded-br-sm px-3.5 py-2 max-w-[82%] text-[12px] leading-relaxed">
                  {m.content}
                </div>
              ) : (
                <div className="w-full max-w-[92%]">
                  {loading && i === messages.length - 1 && streamingPersonas.length === 0 && !m.content && (
                    <div className="flex items-center gap-2 text-[11px] text-muted-foreground/50 mt-2.5 ml-1">
                      <Loader2 className="w-3 h-3 animate-spin" />
                      <span className="tracking-tight">Reviewing…</span>
                    </div>
                  )}
                  {loading && i === messages.length - 1 && streamingPersonas.length > 0 && (
                    <ReviewPersonaReports
                      reports={streamingPersonas}
                      loadingIds={loadingPersonaIds}
                    />
                  )}
                  {!loading && m.personaReports && m.personaReports.length > 0 && (
                    <ReviewPersonaReports reports={m.personaReports} />
                  )}
                  {loading && i === messages.length - 1 && streamingPersonas.length > 0 && loadingPersonaIds.size === 0 && !m.content && (
                    <div className="flex items-center gap-2 text-[11px] text-muted-foreground/50 mt-2.5 ml-1">
                      <Loader2 className="w-3 h-3 animate-spin" />
                      <span className="tracking-tight">Synthesizing review…</span>
                    </div>
                  )}
                  {m.content ? (
                    <div className="mt-2.5">
                      <ChatMarkdown content={m.content} variant="analysis" />
                    </div>
                  ) : null}
                </div>
              )}
            </div>
          ))}
          <div ref={bottomRef} />
        </div>
      )}

      {messages.length > 0 && (
        <div className="shrink-0 px-3 pt-2 pb-1 flex flex-wrap gap-1.5">
          {PROMPT_CHIPS.map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => setInput(p)}
              disabled={loading}
              className="text-[11px] px-2.5 py-1 rounded-lg border border-zinc-700/50 text-muted-foreground/60 hover:text-foreground/80 hover:border-zinc-600/70 hover:bg-zinc-800/30 transition-colors cursor-pointer tracking-tight disabled:opacity-40"
            >
              {p}
            </button>
          ))}
        </div>
      )}

      <form
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
        className="shrink-0 flex items-center gap-2 px-3 py-2.5 border-t border-border/40 mt-auto"
      >
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={`Ask about the ${ticker} trade…`}
          className="flex-1 bg-transparent text-[12px] text-foreground placeholder:text-muted-foreground/35 focus:outline-none"
          disabled={loading}
        />
        <button
          type="submit"
          disabled={loading || !input.trim()}
          aria-label="Send message"
          className="w-7 h-7 flex items-center justify-center rounded-lg bg-zinc-800 border border-zinc-700/60 text-foreground/60 hover:text-foreground hover:border-zinc-600 disabled:opacity-30 disabled:cursor-not-allowed transition-colors cursor-pointer"
        >
          {loading ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <Send className="w-3.5 h-3.5" />
          )}
        </button>
      </form>
    </div>
  );
}
