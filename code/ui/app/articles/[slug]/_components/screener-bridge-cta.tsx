"use client";

import { ArrowUpRight, Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { EmailSubscribeModal } from "@/components/EmailSubscribeModal";

type Props = {
  /** Article tickers that appear in the screening's current results. */
  matchedTickers: string[];
  screeningSlug: string;
  screeningName: string;
  /** Public Telegram join URL, if configured. Button is omitted when absent. */
  telegramUrl?: string | null;
};

/**
 * Bridge from an article to the recurring screener subscription. When article
 * tickers show up in the screening's latest run we name them; otherwise the
 * block still renders the offer without the dynamic line.
 */
export function ScreenerBridgeCTA({
  matchedTickers,
  screeningSlug,
  screeningName,
  telegramUrl,
}: Props) {
  return (
    <section className="overflow-hidden rounded-2xl border border-border/60 border-l-[3px] border-l-emerald-500 bg-card/40 p-6 sm:p-8">
      <p className="inline-flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.2em] text-emerald-500/90">
        <span className="h-px w-6 bg-emerald-500/60" />
        Screener bridge
      </p>

      {matchedTickers.length > 0 ? (
        <p className="mt-4 max-w-2xl text-lg font-semibold leading-snug tracking-tight text-foreground">
          {matchedTickers.map((t, i) => (
            <span key={t}>
              <span className="font-mono text-emerald-400">{t}</span>
              {i < matchedTickers.length - 1 ? (
                <span className="text-muted-foreground">, </span>
              ) : null}
            </span>
          ))}{" "}
          showed up in this week&rsquo;s {screeningName} screen.
        </p>
      ) : (
        <p className="mt-4 max-w-2xl text-lg font-semibold leading-snug tracking-tight text-foreground">
          Catch the names this kind of story moves — before the chart does.
        </p>
      )}

      <p className="mt-3 max-w-2xl text-sm leading-relaxed text-muted-foreground">
        Get the full {screeningName} results every Friday at 4PM ET — free via
        email{telegramUrl ? " or Telegram" : ""}.
      </p>

      <div className="mt-6 flex flex-wrap items-center gap-3">
        <EmailSubscribeModal
          screeningSlug={screeningSlug}
          screeningName={screeningName}
          source="article_bridge"
          trigger={
            <Button>
              Subscribe to {screeningName}
              <ArrowUpRight className="ml-1.5 h-4 w-4" />
            </Button>
          }
        />
        {telegramUrl ? (
          <a
            href={telegramUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex h-10 items-center gap-1.5 rounded-md border border-border/70 bg-background px-4 text-sm font-medium text-foreground transition-colors hover:border-border hover:text-emerald-400"
          >
            <Send className="h-4 w-4" />
            Join Telegram
          </a>
        ) : null}
      </div>
    </section>
  );
}
