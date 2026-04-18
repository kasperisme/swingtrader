"use client";

import { useState, useRef, useEffect } from "react";
import { Bot, Send, Loader2, Trash2 } from "lucide-react";
import ReactMarkdown from "react-markdown";
import type { ChartAnnotation } from "@/components/ticker-charts/types";
import type { OhlcBar } from "@/components/ticker-charts/types";
import { ANNOTATION_COLORS } from "@/components/ticker-charts/types";

type Message = { role: "user" | "assistant"; content: string };

interface ChartAiChatProps {
  symbol: string;
  ohlcData: OhlcBar[];
  onAnnotations: (annotations: ChartAnnotation[]) => void;
}

const ROLE_LABELS: Record<string, string> = {
  support: "Support", resistance: "Resistance", entry: "Entry",
  stop: "Stop", target: "Target", info: "Info",
};

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

export function ChartAiChat({ symbol, ohlcData, onAnnotations }: ChartAiChatProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [currentAnnotations, setCurrentAnnotations] = useState<ChartAnnotation[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  async function send() {
    const text = input.trim();
    if (!text || loading) return;

    const userMsg: Message = { role: "user", content: text };
    setMessages(prev => [...prev, userMsg]);
    setInput("");
    setLoading(true);

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    const history: Message[] = [...messages, userMsg];
    let assistantContent = "";
    let newAnnotations: ChartAnnotation[] = [];

    try {
      const res = await fetch("/api/ai/chart", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify({ symbol, ohlcData, messages: history }),
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

      setMessages(prev => [...prev, { role: "assistant", content: "" }]);

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

            console.log("[ChartAI] firstLine:", firstLine.slice(0, 120));
            if (firstLine.startsWith("A:")) {
              try {
                newAnnotations = JSON.parse(firstLine.slice(2)) as ChartAnnotation[];
                console.log("[ChartAI] parsed annotations:", newAnnotations);
                setCurrentAnnotations(newAnnotations);
                onAnnotations(newAnnotations);
              } catch (e) {
                console.error("[ChartAI] annotation parse error:", e, "raw:", firstLine.slice(2, 200));
              }
            } else {
              // No annotation line — treat as text
              assistantContent += firstLine;
              setMessages(prev => {
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
          setMessages(prev => {
            const copy = [...prev];
            copy[copy.length - 1] = { role: "assistant", content: snapshot };
            return copy;
          });
        }
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name !== "AbortError") {
        setMessages(prev => [...prev, { role: "assistant", content: `Error: ${err.message}` }]);
      }
    } finally {
      setLoading(false);
    }

    // Attach annotation pills to the final assistant message
    if (newAnnotations.length) {
      setMessages(prev => {
        const copy = [...prev];
        const last = copy[copy.length - 1];
        if (last?.role === "assistant") {
          copy[copy.length - 1] = { ...last };
        }
        return copy;
      });
    }
  }

  function clear() {
    abortRef.current?.abort();
    setMessages([]);
    setCurrentAnnotations([]);
    onAnnotations([]);
    setInput("");
  }

  return (
    <div className="flex flex-col border-t border-border bg-background">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-border">
        <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
          <Bot className="w-3.5 h-3.5" />
          Chart AI · {symbol}
        </div>
        {(messages.length > 0 || currentAnnotations.length > 0) && (
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

      {/* Messages */}
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
                  <div className="prose prose-sm prose-invert max-w-none text-xs leading-relaxed
                    prose-p:my-1 prose-ul:my-1 prose-li:my-0 prose-strong:text-foreground
                    prose-headings:text-foreground prose-headings:text-xs">
                    <ReactMarkdown>{m.content || (loading && i === messages.length - 1 ? "…" : "")}</ReactMarkdown>
                  </div>
                  {i === messages.length - 1 && currentAnnotations.length > 0 && (
                    <AnnotationPills annotations={currentAnnotations} />
                  )}
                </div>
              )}
            </div>
          ))}
          {loading && messages[messages.length - 1]?.role === "user" && (
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Loader2 className="w-3 h-3 animate-spin" />
              Analysing chart…
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      )}

      {/* Input */}
      <form
        onSubmit={e => { e.preventDefault(); void send(); }}
        className="flex items-center gap-2 px-4 py-2"
      >
        <input
          type="text"
          value={input}
          onChange={e => setInput(e.target.value)}
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
