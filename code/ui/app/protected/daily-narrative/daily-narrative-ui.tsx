"use client";

import { useState } from "react";
import type {
  ArticleSource,
  DailyNarrativeRow,
  PortfolioWatchItem,
  ScreeningUpdateItem,
  AlertWatchItem,
} from "./page";

// ── Helpers ───────────────────────────────────────────────────────────────────

function sentimentColor(score: number): string {
  if (score >= 0.4) return "text-green-600 dark:text-green-400";
  if (score <= -0.4) return "text-red-500 dark:text-red-400";
  return "text-muted-foreground";
}

function sentimentLabel(score: number): string {
  if (score >= 0.6) return "Bullish";
  if (score >= 0.2) return "Mildly bullish";
  if (score <= -0.6) return "Bearish";
  if (score <= -0.2) return "Mildly bearish";
  return "Neutral";
}

function actionBadge(action: PortfolioWatchItem["action"]) {
  const styles = {
    monitor: "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300",
    review: "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300",
    urgent: "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300",
  };
  return (
    <span
      className={`inline-block rounded px-2 py-0.5 text-xs font-semibold uppercase tracking-wide ${styles[action]}`}
    >
      {action}
    </span>
  );
}

function alertTypeBadge(type: AlertWatchItem["alert_type"]) {
  const labels: Record<string, string> = {
    stop_loss: "Stop Loss",
    take_profit: "Take Profit",
    price_alert: "Price Alert",
  };
  return (
    <span className="inline-block rounded bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-800 dark:bg-red-900/30 dark:text-red-300">
      {labels[type] ?? type}
    </span>
  );
}

function pctAwayColor(pct: number | null, direction: AlertWatchItem["alert_type"]): string {
  if (pct === null) return "text-muted-foreground";
  const isClose = Math.abs(pct) <= 2;
  return isClose ? "text-red-500 font-bold" : "text-muted-foreground";
}

// ── Section components ────────────────────────────────────────────────────────

function SourcesList({ sources }: { sources?: ArticleSource[] }) {
  if (!sources?.length) return null;
  return (
    <ul className="mt-2 space-y-1 border-t border-border pt-2">
      {sources.map((s) => (
        <li key={s.article_id} className="text-xs text-muted-foreground">
          {s.url ? (
            <a
              href={s.url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-blue-600 hover:underline dark:text-blue-400"
            >
              {s.title?.trim() || `Article ${s.article_id}`}
            </a>
          ) : (
            <span>{s.title?.trim() || `Article ${s.article_id}`}</span>
          )}
        </li>
      ))}
    </ul>
  );
}

function EmptyState({ label }: { label: string }) {
  return (
    <p className="text-sm text-muted-foreground italic py-3">
      No {label} hits in this narrative window.
    </p>
  );
}

function PortfolioSection({ items }: { items: PortfolioWatchItem[] }) {
  if (!items.length) return <EmptyState label="portfolio" />;
  return (
    <div className="flex flex-col gap-3">
      {items.map((item) => (
        <div
          key={item.ticker}
          className="rounded-lg border border-border bg-card p-4 flex gap-4 items-start"
        >
          <div className="min-w-[64px]">
            <span className="text-base font-bold">{item.ticker}</span>
            <div className={`text-xs mt-0.5 ${sentimentColor(item.sentiment)}`}>
              {sentimentLabel(item.sentiment)}{" "}
              <span className="opacity-60">
                ({item.sentiment >= 0 ? "+" : ""}
                {item.sentiment.toFixed(2)})
              </span>
            </div>
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-sm leading-relaxed">{item.narrative}</div>
            <SourcesList sources={item.sources} />
          </div>
          <div className="shrink-0">{actionBadge(item.action)}</div>
        </div>
      ))}
    </div>
  );
}

function ScreeningSection({ items }: { items: ScreeningUpdateItem[] }) {
  if (!items.length) return <EmptyState label="screening candidate" />;
  return (
    <div className="flex flex-col gap-3">
      {items.map((item) => (
        <div
          key={item.ticker}
          className="rounded-lg border border-border bg-card p-4 flex gap-4 items-start"
        >
          <span className="min-w-[64px] text-base font-bold">{item.ticker}</span>
          <div className="flex-1 min-w-0">
            <p className="text-sm leading-relaxed">{item.narrative}</p>
            <SourcesList sources={item.sources} />
          </div>
        </div>
      ))}
    </div>
  );
}

function AlertSection({ items }: { items: AlertWatchItem[] }) {
  if (!items.length) return <EmptyState label="alert" />;
  return (
    <div className="flex flex-col gap-3">
      {items.map((item, i) => (
        <div
          key={`${item.ticker}-${i}`}
          className="rounded-lg border border-red-200 bg-red-50 dark:border-red-900/40 dark:bg-red-950/20 p-4 flex gap-4 items-start"
        >
          <div className="min-w-[64px]">
            <span className="text-base font-bold">{item.ticker}</span>
            <div className="mt-0.5">{alertTypeBadge(item.alert_type)}</div>
          </div>
          <div className="flex-1">
            <div className="flex items-center gap-3 mb-1">
              <span className="text-sm font-semibold">
                Alert @ ${item.alert_price.toFixed(2)}
              </span>
              {item.pct_away !== null && (
                <span className={`text-sm ${pctAwayColor(item.pct_away, item.alert_type)}`}>
                  {item.pct_away >= 0 ? "+" : ""}
                  {item.pct_away.toFixed(1)}% away
                </span>
              )}
            </div>
            <p className="text-sm leading-relaxed text-muted-foreground">{item.narrative}</p>
            <SourcesList sources={item.sources} />
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Main UI ───────────────────────────────────────────────────────────────────

export function DailyNarrativeUI({ narratives }: { narratives: DailyNarrativeRow[] }) {
  const [selectedIdx, setSelectedIdx] = useState(0);

  if (!narratives.length) {
    return (
      <div className="rounded-lg border border-border bg-card p-8 text-center text-muted-foreground">
        <p className="font-medium text-foreground text-lg mb-2">No narratives yet</p>
        <p className="text-sm max-w-md mx-auto">
          The daily narrative is generated each weekday pre-market by the Mac Mini job.
          Run <code className="font-mono text-xs bg-muted rounded px-1">scripts/run_daily_narrative.py</code>{" "}
          manually to generate today&apos;s narrative, or wait for the cron job.
        </p>
      </div>
    );
  }

  const current = narratives[selectedIdx];
  const portfolioItems = (current.portfolio_section ?? []) as PortfolioWatchItem[];
  const screeningItems = (current.screening_section ?? []) as ScreeningUpdateItem[];
  const alertItems = (current.alert_warnings ?? []) as AlertWatchItem[];

  const generatedAt = new Date(current.generated_at).toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "America/New_York",
  });

  return (
    <div className="flex flex-col gap-6">
      {/* Date selector */}
      {narratives.length > 1 && (
        <div className="flex gap-2 flex-wrap">
          {narratives.map((n, i) => (
            <button
              key={n.id}
              onClick={() => setSelectedIdx(i)}
              className={`rounded-md px-3 py-1.5 text-sm font-medium border transition-colors ${
                i === selectedIdx
                  ? "bg-foreground text-background border-foreground"
                  : "border-border bg-card text-muted-foreground hover:text-foreground"
              }`}
            >
              {new Date(n.narrative_date + "T12:00:00").toLocaleDateString("en-US", {
                weekday: "short",
                month: "short",
                day: "numeric",
              })}
            </button>
          ))}
        </div>
      )}

      {/* Meta */}
      <div className="flex items-center gap-3 text-xs text-muted-foreground">
        <span>Generated at {generatedAt} ET</span>
        {current.model && (
          <>
            <span>·</span>
            <span className="font-mono">{current.model}</span>
          </>
        )}
        {current.latency_ms && (
          <>
            <span>·</span>
            <span>{(current.latency_ms / 1000).toFixed(1)}s</span>
          </>
        )}
      </div>

      {/* Alert Watch — prominent at the top if there are urgent items */}
      {alertItems.length > 0 && (
        <section>
          <h2 className="text-sm font-semibold uppercase tracking-widest text-red-500 mb-3">
            Alert Watch
          </h2>
          <AlertSection items={alertItems} />
        </section>
      )}

      {/* Portfolio Watch */}
      <section>
        <h2 className="text-sm font-semibold uppercase tracking-widest text-amber-500 mb-3">
          Portfolio Watch
        </h2>
        <PortfolioSection items={portfolioItems} />
      </section>

      {/* Screening Update */}
      <section>
        <h2 className="text-sm font-semibold uppercase tracking-widest text-blue-500 mb-3">
          Screening Update
        </h2>
        <ScreeningSection items={screeningItems} />
      </section>

      {/* Market Pulse */}
      {current.market_pulse && (
        <section>
          <h2 className="text-sm font-semibold uppercase tracking-widest text-purple-500 mb-3">
            Market Pulse
          </h2>
          <div className="rounded-lg border border-border bg-card p-5 text-sm leading-relaxed">
            {current.market_pulse}
            <SourcesList sources={current.market_pulse_sources ?? undefined} />
          </div>
        </section>
      )}
    </div>
  );
}
