"use server";

import { createServiceClient } from "@/lib/supabase/service";

/**
 * The ticker directory behind the public /quote index.
 *
 * /quote/[symbol] pages are generated for any symbol, but only the ones with
 * real scored coverage are worth listing (and are what the sitemap indexes), so
 * this ranks by how much impact-scored news each ticker actually carries in a
 * recent window. Delegated to the get_top_covered_tickers RPC, which reads the
 * materialized ticker_coverage_daily rollup — reading the live view instead cost
 * ~5-8s per call, against the REST role's 8s budget.
 *
 * Service-role read so the index renders logged-out, mirroring /articles.
 */

const SCHEMA = "swingtrader";

export type CoveredTicker = {
  ticker: string;
  /** Articles mentioning the ticker in the window. */
  mentionCount: number;
  /** Of those, how many carry a ticker-level sentiment score. */
  scoredCount: number;
  /** Scored-count-weighted mean sentiment, -1..+1 (null if nothing scored). */
  avgSentiment: number | null;
  /** Most recent day with coverage (ISO date). */
  lastDay: string | null;
  /** Known for the subset of symbols in the `tickers` universe; else null. */
  companyName: string | null;
  sector: string | null;
};

export type CoveredTickerPage = {
  items: CoveredTicker[];
  /** Matches across the whole result set, not just this page. */
  total: number;
};

export async function listCoveredTickers(
  opts: { days?: number; limit?: number; offset?: number; search?: string } = {},
): Promise<CoveredTickerPage> {
  const supabase = createServiceClient();
  const search = (opts.search ?? "").trim();
  const { data, error } = await supabase.schema(SCHEMA).rpc("get_top_covered_tickers", {
    p_days: Math.max(1, Math.min(Math.floor(opts.days ?? 30), 120)),
    p_limit: Math.max(1, Math.min(Math.floor(opts.limit ?? 50), 200)),
    p_offset: Math.max(0, Math.min(Math.floor(opts.offset ?? 0), 100000)),
    p_search: search || null,
  });
  if (error || !Array.isArray(data)) return { items: [], total: 0 };

  const items: CoveredTicker[] = [];
  for (const row of data as Record<string, unknown>[]) {
    const ticker = typeof row.ticker === "string" ? row.ticker.trim().toUpperCase() : "";
    if (!ticker) continue;
    items.push({
      ticker,
      mentionCount: Number(row.mention_count ?? 0),
      scoredCount: Number(row.scored_count ?? 0),
      avgSentiment:
        row.avg_sentiment != null && Number.isFinite(Number(row.avg_sentiment))
          ? Number(row.avg_sentiment)
          : null,
      lastDay: row.last_day != null ? String(row.last_day) : null,
      companyName:
        typeof row.company_name === "string" && row.company_name.trim()
          ? row.company_name.trim()
          : null,
      sector:
        typeof row.sector === "string" && row.sector.trim() ? row.sector.trim() : null,
    });
  }

  // total_count rides along on every row; an empty result has no rows to carry
  // it, which is exactly the zero case.
  const rows = data as Record<string, unknown>[];
  const total = rows.length > 0 ? Number(rows[0].total_count ?? 0) : 0;

  return { items, total: Number.isFinite(total) ? total : 0 };
}
