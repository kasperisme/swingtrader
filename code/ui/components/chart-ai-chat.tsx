"use client";

import { useState, useRef, useEffect, type Dispatch, type SetStateAction } from "react";
import { Bot, Send, Loader2, Trash2, ChevronDown, ChevronRight, Crosshair, Check, Sparkles } from "lucide-react";
import ReactMarkdown from "react-markdown";
import type { ChartAnnotation } from "@/components/ticker-charts/types";
import type { OhlcBar } from "@/components/ticker-charts/types";
import { ANNOTATION_COLORS } from "@/components/ticker-charts/types";
import type { ChartAiChatMessage, PersonaReport } from "@/app/actions/chart-workspace";
import type { PersonaId } from "@/lib/chart-ai/personas";
import { PERSONA_LABELS } from "@/lib/chart-ai/personas";

const ROLE_LABELS: Record<string, string> = {
  support: "Support",
  resistance: "Resistance",
  entry: "Entry",
  stop: "Stop",
  target: "Target",
  info: "Info",
};

const PERSONA_COLORS: Record<PersonaId, string> = {
  technical: "#3b82f6",
  sentiment: "#f59e0b",
  risk: "#ef4444",
  fundamentals: "#10b981",
  newsTrend: "#a855f7",
};

const PROMPT_CHIPS = [
  "What is the next entry point?",
  "Where are key support levels?",
  "Is the trend bullish or bearish?",
  "What's the risk/reward here?",
  "Draw the trade setup",
];

// --- helpers ---

function findRolePrice(annotations: ChartAnnotation[], role: string, zoneEdge: "top" | "bottom"): number | null {
  const ann = annotations.find((a) => a.role === role);
  if (!ann) return null;
  if (ann.type === "horizontal") return ann.price;
  if (ann.type === "zone") return zoneEdge === "top" ? ann.priceTop : ann.priceBottom;
  return null;
}

function findEntryPrice(annotations: ChartAnnotation[]): number | null {
  return findRolePrice(annotations, "entry", "bottom");
}

function findTargetPrice(annotations: ChartAnnotation[]): number | null {
  return findRolePrice(annotations, "target", "top");
}

function findStopPrice(annotations: ChartAnnotation[]): number | null {
  return findRolePrice(annotations, "stop", "bottom");
}

function isHighConfidence(reports: PersonaReport[]): boolean {
  const withScores = reports.filter((r) => r.scores);
  if (!withScores.length) return false;
  const avg = (fn: (r: PersonaReport) => number) =>
    withScores.reduce((s, r) => s + fn(r), 0) / withScores.length;
  return avg((r) => r.scores!.confidence) >= 65 && avg((r) => r.scores!.short_term) >= 60;
}

function parseDirection(content: string): "long" | "short" | null {
  const m = content.match(/\*\*Verdict\*\*:\s*(BULLISH|BEARISH)/i);
  if (!m) return null;
  return m[1].toUpperCase() === "BULLISH" ? "long" : "short";
}

function scoreColor(v: number): string {
  if (v >= 62) return "#10b981";
  if (v >= 42) return "#f59e0b";
  return "#ef4444";
}

// --- markdown renderers ---

function PersonaMarkdown({ content }: { content: string }) {
  return (
    <ReactMarkdown
      components={{
        p: ({ children }) => (
          <p className="text-[11px] leading-relaxed text-muted-foreground mb-1.5 last:mb-0">{children}</p>
        ),
        strong: ({ children }) => (
          <strong className="font-semibold text-foreground/90">{children}</strong>
        ),
        ul: ({ children }) => <ul className="mb-1.5 space-y-0.5">{children}</ul>,
        ol: ({ children }) => <ol className="mb-1.5 space-y-0.5 list-decimal pl-3">{children}</ol>,
        li: ({ children }) => (
          <li className="text-[11px] text-muted-foreground flex gap-2 leading-relaxed">
            <span className="mt-[5px] w-[3px] h-[3px] rounded-full bg-muted-foreground/40 flex-shrink-0" />
            <span>{children}</span>
          </li>
        ),
        h1: ({ children }) => (
          <h1 className="text-[12px] font-semibold text-foreground mt-3 mb-1 first:mt-0">{children}</h1>
        ),
        h2: ({ children }) => (
          <h2 className="text-[11px] font-semibold text-foreground/80 mt-2.5 mb-1 first:mt-0">{children}</h2>
        ),
        h3: ({ children }) => (
          <h3 className="text-[10px] font-medium text-foreground/50 uppercase tracking-widest mt-2 mb-0.5 first:mt-0">
            {children}
          </h3>
        ),
      }}
    >
      {content}
    </ReactMarkdown>
  );
}

function AnalysisMarkdown({ content }: { content: string }) {
  return (
    <ReactMarkdown
      components={{
        p: ({ children }) => (
          <p className="text-[12px] leading-relaxed text-foreground/70 mb-2 last:mb-0">{children}</p>
        ),
        strong: ({ children }) => (
          <strong className="font-semibold text-foreground">{children}</strong>
        ),
        ul: ({ children }) => <ul className="mb-2 space-y-1">{children}</ul>,
        ol: ({ children }) => <ol className="mb-2 space-y-1 list-decimal pl-4">{children}</ol>,
        li: ({ children }) => (
          <li className="text-[12px] text-foreground/70 flex gap-2.5 leading-relaxed">
            <span className="mt-[5px] w-[3px] h-[3px] rounded-full bg-amber-500/60 flex-shrink-0" />
            <span>{children}</span>
          </li>
        ),
        h1: ({ children }) => (
          <h1 className="text-[13px] font-semibold text-foreground mt-4 mb-1.5 first:mt-0">{children}</h1>
        ),
        h2: ({ children }) => (
          <h2 className="text-[12px] font-semibold text-foreground mt-3 mb-1 first:mt-0">{children}</h2>
        ),
        h3: ({ children }) => (
          <h3 className="text-[10px] font-medium text-foreground/45 uppercase tracking-widest mt-3 mb-1 first:mt-0">
            {children}
          </h3>
        ),
      }}
    >
      {content}
    </ReactMarkdown>
  );
}

// --- sub-components ---

function ScoreChip({ label, value }: { label: string; value: number }) {
  return (
    <span
      title={`${label}: ${value}/100`}
      className="text-[9px] font-mono tabular-nums tracking-tight"
      style={{ color: scoreColor(value) }}
    >
      {label}<span className="font-bold">{value}</span>
    </span>
  );
}

function PersonaBadges({ personas }: { personas: PersonaId[] }) {
  if (!personas.length) return null;
  return (
    <div className="flex flex-wrap gap-1 mt-2">
      {personas.map((p) => (
        <span
          key={p}
          className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full font-medium tracking-tight"
          style={{
            background: `${PERSONA_COLORS[p]}12`,
            color: PERSONA_COLORS[p],
            border: `1px solid ${PERSONA_COLORS[p]}28`,
          }}
        >
          <span className="w-1 h-1 rounded-full" style={{ background: PERSONA_COLORS[p] }} />
          {PERSONA_LABELS[p]}
        </span>
      ))}
    </div>
  );
}

function PersonaReportSection({ report, loading }: { report: PersonaReport; loading?: boolean }) {
  const [open, setOpen] = useState(false);
  const color = PERSONA_COLORS[report.id as PersonaId] ?? "#6b7280";
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
              <ScoreChip label="C:" value={report.scores.confidence} />
              <ScoreChip label="ST:" value={report.scores.short_term} />
              <ScoreChip label="LT:" value={report.scores.long_term} />
            </>
          ) : null}
        </span>
        {open
          ? <ChevronDown className="w-3 h-3 text-muted-foreground/35 flex-shrink-0" />
          : <ChevronRight className="w-3 h-3 text-muted-foreground/35 flex-shrink-0" />}
      </button>
      {open && (
        <div className="px-3 pb-3 pt-1" style={{ borderTop: `1px solid ${color}15` }}>
          {report.error ? (
            <p className="text-[11px] text-red-400 mt-1.5">{report.error}</p>
          ) : (
            <div className="mt-1.5">
              <PersonaMarkdown content={report.analysis || "…"} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function PersonaReports({ reports, loadingIds }: { reports: PersonaReport[]; loadingIds?: Set<string> }) {
  if (!reports.length) return null;
  return (
    <div className="flex flex-col mt-2 rounded-lg overflow-hidden border border-border/40 divide-y divide-border/25">
      {reports.map((r) => (
        <PersonaReportSection key={r.id} report={r} loading={loadingIds?.has(r.id)} />
      ))}
    </div>
  );
}

function parsePersonas(content: string): { personas: PersonaId[]; text: string } {
  const match = content.match(/^<!-- personas:([^-]+?) -->\n?/);
  if (!match) return { personas: [], text: content };
  const personas = match[1].split("|") as PersonaId[];
  const text = content.slice(match[0].length);
  return { personas, text };
}

function AnnotationPills({ annotations }: { annotations: ChartAnnotation[] }) {
  if (!annotations.length) return null;
  return (
    <div className="flex flex-wrap gap-1 mt-2">
      {annotations.map((a) => (
        <span
          key={a.id}
          className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full font-medium"
          style={{
            background: `${ANNOTATION_COLORS[a.role]}10`,
            color: ANNOTATION_COLORS[a.role],
            border: `1px solid ${ANNOTATION_COLORS[a.role]}28`,
          }}
        >
          {ROLE_LABELS[a.role] ?? a.role}
          {a.label ? ` · ${a.label}` : ""}
          {a.type === "horizontal" ? ` ${"price" in a ? a.price.toFixed(2) : ""}` : ""}
        </span>
      ))}
    </div>
  );
}

// --- main component ---

interface ChartAiChatProps {
  symbol: string;
  ohlcData: OhlcBar[];
  annotations?: ChartAnnotation[];
  onAnnotations: (annotations: ChartAnnotation[]) => void;
  messages: ChartAiChatMessage[];
  setMessages: Dispatch<SetStateAction<ChartAiChatMessage[]>>;
  onSaveEntry?: (price: number, direction: "long" | "short", takeProfit: number | null, stopLoss: number | null) => void;
  onLoadingChange?: (loading: boolean) => void;
  /** True when a stream for this ticker is running in the background (e.g. user navigated away and back). */
  isStreaming?: boolean;
  side?: boolean;
}

export function ChartAiChat({
  symbol,
  ohlcData,
  annotations = [],
  onAnnotations,
  messages,
  setMessages,
  onSaveEntry,
  onLoadingChange,
  isStreaming = false,
  side = false,
}: ChartAiChatProps) {
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  // True whenever this component is actively streaming OR a background stream
  // is running for this ticker (user navigated away and came back).
  const busy = loading || isStreaming;
  const [streamingAnnotations, setStreamingAnnotations] = useState<ChartAnnotation[]>([]);
  const [streamingPersonas, setStreamingPersonas] = useState<PersonaReport[]>([]);
  const [loadingPersonaIds, setLoadingPersonaIds] = useState<Set<string>>(new Set());
  const [savedEntryIndices, setSavedEntryIndices] = useState<Set<number>>(new Set());
  const [pendingConfirm, setPendingConfirm] = useState<{ personas: PersonaId[]; question: string } | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  // Core streaming function — shared by send() and handleConfirm().
  // `history` = messages to send to the API (no assistant placeholder).
  // `overridePersonas` = skip router and use this list ([] = no personas).
  async function executeStream(history: ChartAiChatMessage[], overridePersonas?: PersonaId[]) {
    setLoading(true);
    onLoadingChange?.(true);
    setStreamingAnnotations([]);
    setStreamingPersonas([]);
    setLoadingPersonaIds(new Set());
    setPendingConfirm(null);

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    let assistantContent = "";
    let newAnnotations: ChartAnnotation[] = [];
    const collectedPersonas: PersonaReport[] = [];

    try {
      const res = await fetch("/api/ai/chart", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify({
          symbol, ohlcData, annotations, messages: history,
          ...(overridePersonas !== undefined ? { overridePersonas } : {}),
        }),
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
          try { msg = JSON.parse(line) as Record<string, unknown>; }
          catch { continue; }

          if (msg.type === "confirm_specialists") {
            const personas = (msg.personas as string[]).filter((p): p is PersonaId =>
              ["technical", "sentiment", "risk", "fundamentals", "newsTrend"].includes(p)
            );
            const question = (msg.question as string | undefined) ?? "Would you like me to run a full specialist analysis?";
            setPendingConfirm({ personas, question });
          } else if (msg.type === "specialists_requested") {
            const ids = (msg.personas as string[]).filter((p): p is PersonaId =>
              ["technical", "sentiment", "risk", "fundamentals", "newsTrend"].includes(p)
            );
            setStreamingPersonas(ids.map((id) => ({ id, label: PERSONA_LABELS[id], analysis: "", error: null })));
            setLoadingPersonaIds(new Set(ids));
          } else if (msg.type === "persona") {
            const rawScores = msg.scores as { confidence: number; short_term: number; long_term: number } | null;
            const report: PersonaReport = {
              id: msg.id as string,
              label: msg.label as string,
              analysis: msg.analysis as string,
              error: msg.error as string | null,
              scores: rawScores ?? undefined,
            };
            collectedPersonas.push(report);
            setStreamingPersonas((prev) => prev.map((p) => p.id === report.id ? report : p));
            setLoadingPersonaIds((prev) => { const next = new Set(prev); next.delete(report.id); return next; });
          } else if (msg.type === "annotations") {
            newAnnotations = msg.data as ChartAnnotation[];
            setStreamingAnnotations(newAnnotations);
            onAnnotations(newAnnotations);
          } else if (msg.type === "analysis") {
            assistantContent = msg.content as string;
            setMessages((prev) => {
              const copy = [...prev];
              copy[copy.length - 1] = { role: "assistant", content: assistantContent };
              return copy;
            });
          } else if (msg.type === "error") {
            setMessages((prev) => [...prev, { role: "assistant", content: `Error: ${String(msg.message)}` }]);
          }
        }
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name !== "AbortError") {
        setMessages((prev) => [...prev, { role: "assistant", content: `Error: ${err.message}` }]);
      }
    } finally {
      setLoading(false);
      onLoadingChange?.(false);
      setMessages((prev) => {
        const copy = [...prev];
        const last = copy[copy.length - 1];
        if (last?.role === "assistant") {
          copy[copy.length - 1] = {
            ...last,
            ...(newAnnotations.length ? { chartAnnotations: newAnnotations } : {}),
            ...(collectedPersonas.length ? { personaReports: collectedPersonas } : {}),
          };
        }
        return copy;
      });
      setStreamingAnnotations([]);
      setStreamingPersonas([]);
      setLoadingPersonaIds(new Set());
    }
  }

  async function send() {
    const text = input.trim();
    if (!text || busy) return;
    const userMsg: ChartAiChatMessage = { role: "user", content: text };
    const historyAfterUser = [...messages, userMsg];
    setMessages([...historyAfterUser, { role: "assistant", content: "" }]);
    setInput("");
    await executeStream(historyAfterUser);
  }

  // Called when the user clicks Yes/No on the confirmation widget.
  async function handleConfirm(approved: boolean) {
    if (!pendingConfirm) return;
    const overridePersonas = approved ? pendingConfirm.personas : [];
    // history = everything except the empty assistant placeholder
    const history = messages.slice(0, -1);
    setMessages([...history, { role: "assistant", content: "" }]);
    await executeStream(history, overridePersonas);
  }

  function clear() {
    abortRef.current?.abort();
    setMessages([]);
    setStreamingAnnotations([]);
    setStreamingPersonas([]);
    setLoadingPersonaIds(new Set());
    setSavedEntryIndices(new Set());
    onAnnotations([]);
    setInput("");
  }

  return (
    <div className={`flex flex-col bg-background ${side ? "h-full" : "border-t border-border"}`}>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border/60">
        <div className="flex items-center gap-2">
          <div className="w-5 h-5 rounded-md bg-zinc-800 border border-zinc-700/60 flex items-center justify-center">
            <Sparkles className="w-3 h-3 text-amber-400/90" />
          </div>
          <span className="text-[11px] font-medium text-foreground/70 tracking-tight">
            AI Analysis
          </span>
          <span className="text-[10px] text-muted-foreground/40 font-mono">·</span>
          <span className="text-[11px] font-mono font-medium text-foreground/50">{symbol}</span>
        </div>
        {(messages.length > 0 || streamingAnnotations.length > 0) && (
          <button
            type="button"
            onClick={clear}
            className="flex items-center gap-1 text-[10px] text-muted-foreground/50 hover:text-muted-foreground transition-colors cursor-pointer"
            title="Clear conversation and annotations"
          >
            <Trash2 className="w-3 h-3" />
            Clear
          </button>
        )}
      </div>

      {/* Messages */}
      {messages.length > 0 && (
        <div className={`flex flex-col gap-4 px-4 py-4 overflow-y-auto ${side ? "flex-1 min-h-0" : "max-h-[420px]"}`}>
          {messages.map((m, i) => (
            <div key={i} className={`flex flex-col gap-1 ${m.role === "user" ? "items-end" : "items-start"}`}>
              {m.role === "user" ? (
                <div className="bg-zinc-800/70 border border-zinc-700/40 text-foreground/85 rounded-2xl rounded-br-sm px-3.5 py-2 max-w-[82%] text-[12px] leading-relaxed">
                  {m.content}
                </div>
              ) : (
                <div className="w-full max-w-[92%]">
                  {/* Routing/background-stream state */}
                  {busy && i === messages.length - 1 && streamingPersonas.length === 0 && !m.content && (
                    <div className="flex items-center gap-2 text-[11px] text-muted-foreground/50 mt-2.5 ml-1">
                      <Loader2 className="w-3 h-3 animate-spin" />
                      <span className="tracking-tight">Thinking…</span>
                    </div>
                  )}
                  {/* Confirmation widget — router is uncertain, asking user to decide */}
                  {!busy && i === messages.length - 1 && pendingConfirm && !m.content && (
                    <div className="mt-2 space-y-2.5">
                      <p className="text-[12px] text-foreground/70 leading-snug">{pendingConfirm.question}</p>
                      <div className="flex gap-2">
                        <button
                          type="button"
                          onClick={() => void handleConfirm(true)}
                          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium bg-amber-500/15 text-amber-400 border border-amber-500/30 hover:bg-amber-500/25 transition-colors"
                        >
                          <Sparkles className="w-3 h-3" />
                          Yes, run analysis
                        </button>
                        <button
                          type="button"
                          onClick={() => void handleConfirm(false)}
                          className="px-3 py-1.5 rounded-lg text-[11px] font-medium text-muted-foreground border border-border hover:bg-muted/40 transition-colors"
                        >
                          No, skip
                        </button>
                      </div>
                    </div>
                  )}
                  {/* Streaming persona panels (only when this instance owns the stream) */}
                  {busy && i === messages.length - 1 && streamingPersonas.length > 0 && (
                    <PersonaReports reports={streamingPersonas} loadingIds={loadingPersonaIds} />
                  )}
                  {/* Completed persona panels */}
                  {!busy && m.personaReports && m.personaReports.length > 0 && (
                    <PersonaReports reports={m.personaReports} />
                  )}
                  {/* Synthesizing state — all personas done, waiting for orchestrator */}
                  {busy && i === messages.length - 1 && streamingPersonas.length > 0 && loadingPersonaIds.size === 0 && !m.content && (
                    <div className="flex items-center gap-2 text-[11px] text-muted-foreground/50 mt-2.5 ml-1">
                      <Loader2 className="w-3 h-3 animate-spin" />
                      <span className="tracking-tight">Synthesizing…</span>
                    </div>
                  )}
                  {/* Analysis text */}
                  {(m.content || (busy && i === messages.length - 1 && loadingPersonaIds.size > 0)) && (
                    <div className="mt-2.5">
                      <AnalysisMarkdown
                        content={parsePersonas(m.content || (busy && i === messages.length - 1 ? "…" : "")).text}
                      />
                    </div>
                  )}
                  {/* Persona badges */}
                  {parsePersonas(m.content).personas.length > 0 && (
                    <PersonaBadges personas={parsePersonas(m.content).personas} />
                  )}
                  {/* Annotations */}
                  {m.chartAnnotations && m.chartAnnotations.length > 0 && (
                    <AnnotationPills annotations={m.chartAnnotations} />
                  )}
                  {busy && i === messages.length - 1 && streamingAnnotations.length > 0 && (
                    <AnnotationPills annotations={streamingAnnotations} />
                  )}
                  {/* Save entry button */}
                  {!busy && onSaveEntry && m.chartAnnotations && m.personaReports && (() => {
                    const price = findEntryPrice(m.chartAnnotations!);
                    const direction = parseDirection(m.content);
                    if (price === null || direction === null || !isHighConfidence(m.personaReports!)) return null;
                    const takeProfit = findTargetPrice(m.chartAnnotations!);
                    const stopLoss = findStopPrice(m.chartAnnotations!);
                    const saved = savedEntryIndices.has(i);
                    const dirLabel = direction === "long" ? "Long" : "Short";
                    const suffix = [
                      takeProfit != null ? `TP $${takeProfit.toFixed(2)}` : null,
                      stopLoss != null ? `SL $${stopLoss.toFixed(2)}` : null,
                    ].filter(Boolean).join(" · ");
                    return (
                      <button
                        type="button"
                        onClick={() => {
                          onSaveEntry(price, direction, takeProfit, stopLoss);
                          setSavedEntryIndices((prev) => new Set(prev).add(i));
                        }}
                        disabled={saved}
                        className="mt-3 flex items-center gap-2 text-[11px] px-3 py-1.5 rounded-lg font-medium transition-colors cursor-pointer disabled:cursor-default"
                        style={
                          saved
                            ? { background: "#10b98112", color: "#10b981", border: "1px solid #10b98128" }
                            : { background: "#f59e0b0e", color: "#f59e0b", border: "1px solid #f59e0b28" }
                        }
                      >
                        {saved
                          ? <Check className="w-3.5 h-3.5" />
                          : <Crosshair className="w-3.5 h-3.5" />}
                        {saved
                          ? `${dirLabel} entry saved · $${price.toFixed(2)}${suffix ? ` · ${suffix}` : ""}`
                          : `Save ${dirLabel.toLowerCase()} entry · $${price.toFixed(2)}${suffix ? ` · ${suffix}` : ""}`}
                      </button>
                    );
                  })()}
                </div>
              )}
            </div>
          ))}
          <div ref={bottomRef} />
        </div>
      )}

      {/* Empty state — prompt chips */}
      {messages.length === 0 && !busy && (
        <div className="flex-1 px-4 pt-3 pb-1 flex flex-col gap-2">
          <p className="text-[10px] text-muted-foreground/35 font-medium uppercase tracking-widest">Suggested</p>
          <div className="flex flex-wrap gap-1.5">
            {PROMPT_CHIPS.map((prompt) => (
              <button
                key={prompt}
                type="button"
                onClick={() => setInput(prompt)}
                className="text-[11px] px-2.5 py-1.5 rounded-lg border border-zinc-700/50 text-muted-foreground/60 hover:text-foreground/80 hover:border-zinc-600/70 hover:bg-zinc-800/30 transition-colors cursor-pointer tracking-tight"
              >
                {prompt}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Input form */}
      <form
        onSubmit={(e) => { e.preventDefault(); void send(); }}
        className="flex items-center gap-2 px-3 py-2.5 border-t border-border/40 mt-auto"
      >
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={`Ask about ${symbol}…`}
          className="flex-1 bg-transparent text-[12px] text-foreground placeholder:text-muted-foreground/35 focus:outline-none"
          disabled={busy}
        />
        <button
          type="submit"
          disabled={busy || !input.trim()}
          aria-label="Send message"
          className="w-7 h-7 flex items-center justify-center rounded-lg bg-zinc-800 border border-zinc-700/60 text-foreground/60 hover:text-foreground hover:border-zinc-600 disabled:opacity-30 disabled:cursor-not-allowed transition-colors cursor-pointer"
        >
          {busy
            ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
            : <Send className="w-3.5 h-3.5" />}
        </button>
      </form>
    </div>
  );
}
