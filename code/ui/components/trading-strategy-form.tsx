"use client";

import { useState, useTransition } from "react";
import { Check, Loader2 } from "lucide-react";
import { saveTradingStrategy } from "@/app/actions/trading-strategy";

const MAX_CHARS = 2000;

const PLACEHOLDER = `Describe how you trade — the AI agents will follow your approach.

Examples:
• I trade momentum breakouts from tight bases, targeting 10–20% moves in 5–15 days.
• I prefer low-risk entries near the 21-day EMA with a stop just below the 50-day.
• I focus on high-growth stocks with strong earnings and institutional sponsorship (CAN SLIM).
• I avoid earnings events and hold cash when the market is in a correction.
• Risk per trade: 0.5–1% of portfolio. I target at least 3:1 reward/risk.`;

export function TradingStrategyForm({ initialStrategy }: { initialStrategy: string }) {
  const [value, setValue] = useState(initialStrategy);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const isDirty = value.trim() !== initialStrategy.trim();
  const charsLeft = MAX_CHARS - value.length;

  function handleSave() {
    if (!isDirty || isPending) return;
    setError(null);
    setSaved(false);
    startTransition(async () => {
      const result = await saveTradingStrategy(value);
      if (result.ok) {
        setSaved(true);
        setTimeout(() => setSaved(false), 2500);
      } else {
        setError(result.error ?? "Failed to save");
      }
    });
  }

  return (
    <div className="flex flex-col gap-3">
      <textarea
        value={value}
        onChange={(e) => {
          if (e.target.value.length <= MAX_CHARS) setValue(e.target.value);
        }}
        placeholder={PLACEHOLDER}
        rows={8}
        className="w-full resize-none rounded-xl border border-border bg-background px-4 py-3 text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-amber-500/50 focus:border-amber-500/50 transition-colors leading-relaxed"
      />
      <div className="flex items-center justify-between gap-4">
        <span className={`text-xs tabular-nums ${charsLeft < 100 ? "text-amber-500" : "text-muted-foreground/50"}`}>
          {charsLeft} characters remaining
        </span>
        <div className="flex items-center gap-3">
          {error && <p className="text-xs text-rose-500">{error}</p>}
          {saved && (
            <span className="flex items-center gap-1 text-xs text-emerald-500">
              <Check className="w-3 h-3" />
              Saved
            </span>
          )}
          <button
            type="button"
            onClick={handleSave}
            disabled={!isDirty || isPending}
            className="flex items-center gap-1.5 rounded-lg bg-amber-500 px-4 py-2 text-xs font-semibold text-black transition-opacity hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {isPending && <Loader2 className="w-3 h-3 animate-spin" />}
            {isPending ? "Saving…" : "Save strategy"}
          </button>
        </div>
      </div>
    </div>
  );
}
