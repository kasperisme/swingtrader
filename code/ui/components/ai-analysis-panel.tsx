"use client";

import { useState, useRef, useEffect } from "react";
import { Bot, X, Loader2, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import ReactMarkdown from "react-markdown";
import { fmpGetQuote, fmpGetOhlc, type FmpOhlcBar } from "@/app/actions/fmp";

const responseCache = new Map<string, string>();

interface AiAnalysisPanelProps {
  title: string;
  system: string;
  userMessage: string;
  symbol: string;
  cacheKey: string;
  model?: string;
  onClose: () => void;
}

function formatQuoteSection(data: unknown): string {
  if (!data || !Array.isArray(data) || !data[0]) return "";
  const q = data[0] as Record<string, unknown>;
  const lines: string[] = ["\n## Live Quote"];
  if (q.price != null) lines.push(`Price: $${Number(q.price).toFixed(2)}`);
  if (q.changePercentage != null) lines.push(`Change today: ${Number(q.changePercentage).toFixed(2)}%`);
  if (q.volume != null) lines.push(`Volume: ${Number(q.volume).toLocaleString()}`);
  if (q.marketCap != null) lines.push(`Market cap: $${(Number(q.marketCap) / 1e9).toFixed(2)}B`);
  if (q.priceAvg50 != null) lines.push(`50-day avg: $${Number(q.priceAvg50).toFixed(2)}`);
  if (q.priceAvg200 != null) lines.push(`200-day avg: $${Number(q.priceAvg200).toFixed(2)}`);
  if (q.yearHigh != null) lines.push(`52w high: $${Number(q.yearHigh).toFixed(2)}`);
  if (q.yearLow != null) lines.push(`52w low: $${Number(q.yearLow).toFixed(2)}`);
  return lines.join("\n");
}

function formatOhlcSection(bars: FmpOhlcBar[]): string {
  if (!bars.length) return "";
  const recent = bars.slice(-30);
  const lines: string[] = ["\n## Recent Daily OHLC (last 30 sessions)"];
  lines.push("Date | Open | High | Low | Close | Volume");
  for (const b of recent) {
    const date = b.date.slice(0, 10);
    lines.push(`${date} | ${b.open.toFixed(2)} | ${b.high.toFixed(2)} | ${b.low.toFixed(2)} | ${b.close.toFixed(2)} | ${b.volume.toLocaleString()}`);
  }
  return lines.join("\n");
}

export function AiAnalysisPanel({
  title,
  system,
  userMessage,
  symbol,
  cacheKey,
  model,
  onClose,
}: AiAnalysisPanelProps) {
  const cached = responseCache.get(cacheKey);
  const [output, setOutput] = useState(cached ?? "");
  const [loading, setLoading] = useState(!cached);
  const [loadingStage, setLoadingStage] = useState<"market data" | "analysing">("market data");
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  async function run() {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setOutput("");
    setError(null);
    setLoading(true);
    setLoadingStage("market data");
    responseCache.delete(cacheKey);

    try {
      const [quoteResult, ohlcResult] = await Promise.all([
        fmpGetQuote(symbol),
        fmpGetOhlc(symbol, "1day"),
      ]);

      const quoteSection = quoteResult.ok ? formatQuoteSection(quoteResult.data) : "";
      const ohlcSection = ohlcResult.ok ? formatOhlcSection(ohlcResult.data) : "";
      const enrichedMessage = `${userMessage}${quoteSection}${ohlcSection}`;

      setLoadingStage("analysing");

      const res = await fetch("/api/ai", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify({
          model,
          system,
          messages: [{ role: "user", content: enrichedMessage }],
        }),
      });

      if (!res.ok) {
        const text = await res.text().catch(() => res.statusText);
        throw new Error(`${res.status}: ${text || res.statusText}`);
      }
      if (!res.body) throw new Error("No response body");

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let accumulated = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const chunk = decoder.decode(value, { stream: true });
        accumulated += chunk;
        setOutput((prev) => prev + chunk);
      }

      if (accumulated) responseCache.set(cacheKey, accumulated);
    } catch (err: unknown) {
      if (err instanceof Error && err.name !== "AbortError") {
        setError(err.message);
      }
    } finally {
      setLoading(false);
    }
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { if (!cached) run(); }, []);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
      <div className="relative w-full max-w-lg rounded-xl border border-border bg-background shadow-2xl flex flex-col max-h-[80vh]">

        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-border shrink-0">
          <div className="flex items-center gap-2.5 font-semibold">
            <Bot className="w-4 h-4 text-primary" />
            {title}
          </div>
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              onClick={run}
              disabled={loading}
              title="Re-run"
            >
              <RotateCcw className="w-3.5 h-3.5" />
            </Button>
            <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onClose}>
              <X className="w-3.5 h-3.5" />
            </Button>
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-5 py-4 min-h-[180px]">
          {loading && !output && !error && (
            <div className="flex flex-col items-center justify-center gap-3 py-12 text-muted-foreground">
              <Loader2 className="w-7 h-7 animate-spin text-primary" />
              <span className="text-sm capitalize">{loadingStage}…</span>
            </div>
          )}
          {error && (
            <div className="flex flex-col gap-3 py-4">
              <p className="text-sm text-destructive bg-destructive/10 border border-destructive/20 rounded-md p-3 break-all">{error}</p>
              <button
                type="button"
                onClick={run}
                className="self-start flex items-center gap-1.5 text-xs px-3 py-1.5 rounded border border-border hover:bg-muted transition-colors"
              >
                <RotateCcw className="w-3 h-3" />
                Retry
              </button>
            </div>
          )}
          {output && (
            <div className="text-sm leading-relaxed text-foreground prose prose-sm prose-invert max-w-none
              prose-headings:font-semibold prose-headings:text-foreground
              prose-h1:text-base prose-h2:text-sm prose-h3:text-sm
              prose-p:my-1.5 prose-p:leading-relaxed
              prose-ul:my-1.5 prose-ul:pl-4 prose-li:my-0.5
              prose-ol:my-1.5 prose-ol:pl-4
              prose-strong:text-foreground prose-strong:font-semibold
              prose-code:text-xs prose-code:bg-muted prose-code:px-1 prose-code:py-0.5 prose-code:rounded
              prose-hr:border-border prose-hr:my-3">
              <ReactMarkdown>{output}</ReactMarkdown>
              {loading && <span className="inline-block w-1.5 h-4 bg-primary ml-0.5 animate-pulse align-middle" />}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
