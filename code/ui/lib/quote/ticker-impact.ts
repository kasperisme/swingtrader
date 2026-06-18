import "server-only";
import { createServiceClient } from "@/lib/supabase/service";

/**
 * A news catalyst for a ticker, scored by the NIS pipeline. Powers the public
 * quote page's hero: scored events plotted on the price chart + the "what moved
 * {ticker}" ranked list. This is the differentiator over Yahoo/TradingView —
 * every event carries an impact magnitude (across the 9 impact dimensions) and a
 * ticker-level sentiment, not just a headline.
 */
export type ScoredNewsEvent = {
  articleId: number;
  title: string | null;
  url: string | null;
  source: string | null;
  slug: string | null;
  /** ISO timestamp used to place the marker on the price axis. */
  publishedAt: string | null;
  /** Mean ticker-level sentiment for this article, -1..+1 (null if unscored). */
  sentiment: number | null;
  /** Sum of |dimension| across the impact vector — "how loud" the article is. */
  impactMagnitude: number;
  /** Highest-weight impact dimensions (e.g. ["earnings", "guidance"]). */
  topDimensions: string[];
};

const SCHEMA = "swingtrader";

function clamp(n: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, Math.floor(n)));
}

/** top_dimensions is stored as [key, value] pairs; accept a flat list too. */
function topDimsFrom(raw: unknown, n = 3): string[] {
  if (!Array.isArray(raw)) return [];
  const out: string[] = [];
  for (const d of raw) {
    if (Array.isArray(d) && d.length) out.push(String(d[0]));
    else if (d != null && typeof d !== "object") out.push(String(d));
  }
  return out.filter(Boolean).slice(0, n);
}

/**
 * Impact-ranked, time-spread news catalysts for a ticker. Delegates selection
 * to the get_ticker_impact_news RPC (top-k per ISO week by stored impact
 * magnitude), so the pool is the loudest catalysts spread across the whole
 * window — not just the most-recent days. Public read (service-role) so
 * /quote/[symbol] renders for logged-out visitors, mirroring /articles.
 */
export async function getTickerImpactNews(
  symbol: string,
  opts: { days?: number; limit?: number; perBucket?: number } = {},
): Promise<ScoredNewsEvent[]> {
  const ticker = symbol.trim().toUpperCase();
  if (!ticker) return [];
  const supabase = createServiceClient();
  const { data, error } = await supabase.schema(SCHEMA).rpc("get_ticker_impact_news", {
    p_ticker: ticker,
    p_days: clamp(opts.days ?? 365, 1, 400),
    p_limit: clamp(opts.limit ?? 150, 1, 400),
    p_per_bucket: clamp(opts.perBucket ?? 2, 1, 10),
  });
  if (error || !Array.isArray(data)) return [];

  const events: ScoredNewsEvent[] = [];
  for (const row of data as Record<string, unknown>[]) {
    const articleId = Number(row.article_id);
    if (!Number.isFinite(articleId)) continue;
    const sentiment =
      row.sentiment != null && Number.isFinite(Number(row.sentiment))
        ? Number(row.sentiment)
        : null;
    events.push({
      articleId,
      title: row.title != null ? String(row.title) : null,
      url: row.url != null ? String(row.url) : null,
      source: row.source != null ? String(row.source) : null,
      slug: row.slug != null ? String(row.slug) : null,
      publishedAt: row.published_at != null ? String(row.published_at) : null,
      sentiment,
      impactMagnitude: Number(row.impact_magnitude) || 0,
      topDimensions: topDimsFrom(row.top_dimensions),
    });
  }
  return events;
}
