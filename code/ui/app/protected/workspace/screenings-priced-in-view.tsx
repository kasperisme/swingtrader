"use client";

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";

import { quotesGetPricedInVote } from "@/app/actions/quotes";
import { fmpGetQuote } from "@/app/actions/fmp";
import { PricedInPanel } from "@/app/quote/[symbol]/_components/priced-in-panel";
import type { PricedInVote } from "@/lib/quote/priced-in-vote";

/**
 * The quote page's priced-in read, scoped to whichever ticker is selected in
 * the workspace.
 *
 * Not every ticker has one: the vote is only published for names the priced-in
 * pass has actually run and whose inputs cleared the gate, so a screening of
 * 119 small caps will miss on most of them. That is a normal state and says so,
 * rather than rendering an empty panel.
 */
export function ScreeningsPricedInView({
  selectedTicker,
}: {
  selectedTicker: string | null;
}) {
  const symbol = selectedTicker?.trim().toUpperCase() ?? "";
  const [vote, setVote] = useState<PricedInVote | null>(null);
  const [livePrice, setLivePrice] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!symbol) {
      setVote(null);
      setLivePrice(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setVote(null);
    setLivePrice(null);

    // The vote decides whether anything renders at all, so the live price is
    // fetched alongside rather than after — one round trip, not two.
    void Promise.all([
      quotesGetPricedInVote(symbol),
      fmpGetQuote(symbol).catch(() => null),
    ]).then(([v, q]) => {
      if (cancelled) return;
      setVote(v);
      // FMP returns a one-element array, the same shape the quote page unwraps.
      const row =
        q?.ok && Array.isArray(q.data)
          ? (q.data[0] as Record<string, unknown> | undefined)
          : undefined;
      const price = Number(row?.price);
      setLivePrice(Number.isFinite(price) ? price : null);
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [symbol]);

  if (!symbol) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground">
        Pick a ticker to see what its price already reflects.
      </p>
    );
  }

  if (loading) {
    return (
      <p
        className="flex items-center justify-center gap-2 py-8 text-sm text-muted-foreground"
        aria-busy="true"
      >
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
        Loading {symbol}…
      </p>
    );
  }

  if (!vote) {
    return (
      <div className="px-4 py-8 text-center text-sm text-muted-foreground">
        <p>
          No published priced-in read for{" "}
          <span className="font-mono text-foreground">{symbol}</span>.
        </p>
        <p className="mt-1 text-xs">
          The pass covers the NYSE + NASDAQ universe on a rolling schedule, and
          only publishes a ticker once enough analyst models agree to be worth
          reporting.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3 p-1">
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          What the price already reflects
        </h3>
        <p className="mt-1 max-w-[70ch] text-xs text-muted-foreground">
          Analysts publish price targets on {symbol}, and they disagree. Where
          the share price actually sits among them shows which of their
          arguments the market is buying — and which it is ignoring.
        </p>
      </div>
      <PricedInPanel vote={vote} livePrice={livePrice} />
    </div>
  );
}
