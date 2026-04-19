"use client";

import { useState, useRef, useEffect, type Dispatch, type SetStateAction } from "react";
import { Bot, Send, Loader2, Trash2 } from "lucide-react";
import ReactMarkdown from "react-markdown";
import type { ChartAnnotation } from "@/components/ticker-charts/types";
import type { OhlcBar } from "@/components/ticker-charts/types";
import { ANNOTATION_COLORS } from "@/components/ticker-charts/types";
import type { ChartAiChatMessage } from "@/app/actions/chart-workspace";
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
};

function PersonaBadges({ personas }: { personas: PersonaId[] }) {
  if (!personas.length) return null;
  return (
    <div className="flex flex-wrap gap-1 mt-1">
      {personas.map((p) => (
        <span
          key={p}
          className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-full border font-medium"
          style={{ borderColor: PERSONA_COLORS[p], color: PERSONA_COLORS[p] }}
        >
          <span className="w-1.5 h-1.5 rounded-full" style={{ background: PERSONA_COLORS[p] }} />
          {PERSONA_LABELS[p]}
        </span>
      ))}
    </div>
  );
}

function parsePersonas(content: string): { personas: PersonaId[]; text: string } {
  const match = content.match(/^<!-- personas:([a-z|]+) -->\n?/);
  if (!match) return { personas: [], text: content };
  const personas = match[1].split("|") as PersonaId[];
  const text = content.slice(match[0].length);
  return { personas, text };
}

function AnnotationPills({ annotations }: { annotations: ChartAnnotation[] }) {
  if (!annotations.length) return null;
  return (
    <div className="flex flex-wrap gap-1 mt-1.5">
      {annotations.map((a) => (
        <span
          key={a.id}
          className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-full border"
          style={{ borderColor: ANNOTATION_COLORS[a.role], color: ANNOTATION_COLORS[a.role] }}
        >
          <span className="w-1.5 h-1.5 rounded-full" style={{ background: ANNOTATION_COLORS[a.role] }} />
          {ROLE_LABELS[a.role] ?? a.role}
          {a.label ? ` · ${a.label}` : ""}
          {a.type === "horizontal" ? ` ${"price" in a ? a.price.toFixed(2) : ""}` : ""}
        </span>
      ))}
    </div>
  );
}

interface ChartAiChatProps {
  symbol: string;
  ohlcData: OhlcBar[];
  annotations?: ChartAnnotation[];
  onAnnotations: (annotations: ChartAnnotation[]) => void;
  messages: ChartAiChatMessage[];
  setMessages: Dispatch<SetStateAction<ChartAiChatMessage[]>>;
}

export function ChartAiChat({
  symbol,
  ohlcData,
  annotations = [],
  onAnnotations,
  messages,
  setMessages,
}: ChartAiChatProps) {
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [streamingAnnotations, setStreamingAnnotations] = useState<ChartAnnotation[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  async function send() {
    const text = input.trim();
    if (!text || loading) return;

    const userMsg: ChartAiChatMessage = { role: "user", content: text };
    const historyAfterUser: ChartAiChatMessage[] = [...messages, userMsg];
    setMessages(historyAfterUser);
    setInput("");
    setLoading(true);
    setStreamingAnnotations([]);

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    const history = historyAfterUser;
    let assistantContent = "";
    let newAnnotations: ChartAnnotation[] = [];

    try {
      const res = await fetch("/api/ai/chart", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify({ symbol, ohlcData, annotations, messages: history }),
      });

      if (!res.ok) {
        const errText = await res.text().catch(() => res.statusText);
        throw new Error(`${res.status}: ${errText}`);
      }
      if (!res.body) throw new Error("No response body");

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      let annotationsParsed = false;

      setMessages((prev) => [...prev, { role: "assistant", content: "" }]);

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buf += decoder.decode(value, { stream: true });

        if (!annotationsParsed) {
          const nl = buf.indexOf("\n");
          if (nl !== -1) {
            const firstLine = buf.slice(0, nl);
            buf = buf.slice(nl + 1);
            annotationsParsed = true;

            if (firstLine.startsWith("A:")) {
              try {
                newAnnotations = JSON.parse(firstLine.slice(2)) as ChartAnnotation[];
                setStreamingAnnotations(newAnnotations);
                onAnnotations(newAnnotations);
              } catch {
                /* ignore malformed annotation line */
              }
            } else {
              assistantContent += firstLine;
              setMessages((prev) => {
                const copy = [...prev];
                copy[copy.length - 1] = { role: "assistant", content: assistantContent };
                return copy;
              });
            }
          }
        }

        if (annotationsParsed && buf) {
          assistantContent += buf;
          buf = "";
          const snapshot = assistantContent;
          setMessages((prev) => {
            const copy = [...prev];
            copy[copy.length - 1] = { role: "assistant", content: snapshot };
            return copy;
          });
        }
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name !== "AbortError") {
        setMessages((prev) => [...prev, { role: "assistant", content: `Error: ${err.message}` }]);
      }
    } finally {
      setLoading(false);
      if (newAnnotations.length) {
        setMessages((prev) => {
          const copy = [...prev];
          const last = copy[copy.length - 1];
          if (last?.role === "assistant") {
            copy[copy.length - 1] = {
              ...last,
              chartAnnotations: newAnnotations,
            };
          }
          return copy;
        });
      }
      setStreamingAnnotations([]);
    }
  }

  function clear() {
    abortRef.current?.abort();
    setMessages([]);
    setStreamingAnnotations([]);
    onAnnotations([]);
    setInput("");
  }

  return (
    <div className="flex flex-col border-t border-border bg-background">
      <div className="flex items-center justify-between px-4 py-2 border-b border-border">
        <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
          <Bot className="w-3.5 h-3.5" />
          Chart AI · {symbol} · Multi-Persona
        </div>
        {(messages.length > 0 || streamingAnnotations.length > 0) && (
          <button
            type="button"
            onClick={clear}
            className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground transition-colors"
            title="Clear conversation and annotations"
          >
            <Trash2 className="w-3 h-3" />
            Clear
          </button>
        )}
      </div>

      {messages.length > 0 && (
        <div className="flex flex-col gap-3 px-4 py-3 max-h-64 overflow-y-auto text-sm">
          {messages.map((m, i) => (
            <div key={i} className={`flex flex-col gap-0.5 ${m.role === "user" ? "items-end" : "items-start"}`}>
              {m.role === "user" ? (
                <span className="bg-muted text-foreground rounded-lg px-3 py-1.5 max-w-[80%] text-xs">
                  {m.content}
                </span>
              ) : (
                <div className="max-w-[90%]">
                  <div
                    className="prose prose-sm prose-invert max-w-none text-xs leading-relaxed
                    prose-p:my-1 prose-ul:my-1 prose-li:my-0 prose-strong:text-foreground
                    prose-headings:text-foreground prose-headings:text-xs"
                  >
                    <ReactMarkdown>{parsePersonas(m.content || (loading && i === messages.length - 1 ? "…" : "")).text}</ReactMarkdown>
                  </div>
                  {parsePersonas(m.content).personas.length > 0 && (
                    <PersonaBadges personas={parsePersonas(m.content).personas} />
                  )}
                  {m.chartAnnotations && m.chartAnnotations.length > 0 ? (
                    <AnnotationPills annotations={m.chartAnnotations} />
                  ) : null}
                  {loading &&
                  i === messages.length - 1 &&
                  streamingAnnotations.length > 0 ? (
                    <AnnotationPills annotations={streamingAnnotations} />
                  ) : null}
                </div>
              )}
            </div>
          ))}
          {loading && messages[messages.length - 1]?.role === "user" && (
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Loader2 className="w-3 h-3 animate-spin" />
              Running personas…
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      )}

      <form
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
        className="flex items-center gap-2 px-4 py-2"
      >
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={`Ask about ${symbol}… e.g. "Where's support?" or "Draw the trend"`}
          className="flex-1 bg-muted/40 border border-input rounded-md px-3 py-1.5 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
          disabled={loading}
        />
        <button
          type="submit"
          disabled={loading || !input.trim()}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-foreground text-background text-xs font-medium disabled:opacity-40 hover:opacity-90 transition-opacity"
        >
          {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
        </button>
      </form>
    </div>
  );
}
