import type Anthropic from "@anthropic-ai/sdk";
import type { SupabaseClient } from "@supabase/supabase-js";
import {
  expandSearchTagCandidates,
  tagCandidatesFromQuery,
} from "@/lib/news/search-tags";
import type {
  ChartAnnotation,
  AnnotationRole,
  OhlcBar,
} from "@/components/ticker-charts/types";

// ---------------------------------------------------------------------------
// Annotation parsing + OHLC formatting (shared by every chart-ai route)
// ---------------------------------------------------------------------------

export type RawAnnotation = {
  type?: string;
  role?: string;
  label?: string;
  price?: number;
  price_top?: number;
  price_bottom?: number;
  from_date?: string;
  from_price?: number;
  to_date?: string;
  to_price?: number;
};

export function parseAnnotations(raw: RawAnnotation[]): ChartAnnotation[] {
  const out: ChartAnnotation[] = [];
  for (const r of raw) {
    const role = (r.role ?? "info") as AnnotationRole;
    const id = crypto.randomUUID();
    if (r.type === "horizontal" && r.price != null) {
      out.push({ id, type: "horizontal", price: r.price, role, label: r.label });
    } else if (r.type === "zone" && r.price_top != null && r.price_bottom != null) {
      out.push({
        id,
        type: "zone",
        priceTop: r.price_top,
        priceBottom: r.price_bottom,
        role,
        label: r.label,
      });
    } else if (
      r.type === "trend_line" &&
      r.from_date &&
      r.from_price != null &&
      r.to_date &&
      r.to_price != null
    ) {
      out.push({
        id,
        type: "trend_line",
        fromDate: r.from_date,
        fromPrice: r.from_price,
        toDate: r.to_date,
        toPrice: r.to_price,
        role,
        label: r.label,
      });
    }
  }
  return out;
}

export function formatAnnotationList(annotations: ChartAnnotation[]): string {
  return annotations
    .map((a) => {
      if (a.type === "horizontal") {
        return `- horizontal ${a.role} at $${a.price}${a.label ? ` "${a.label}"` : ""}`;
      }
      if (a.type === "zone") {
        return `- zone ${a.role} $${a.priceBottom}–$${a.priceTop}${a.label ? ` "${a.label}"` : ""}`;
      }
      if (a.type === "trend_line") {
        return `- trend_line ${a.role} from ${a.fromDate} $${a.fromPrice} to ${a.toDate} $${a.toPrice}${a.label ? ` "${a.label}"` : ""}`;
      }
      return "";
    })
    .filter(Boolean)
    .join("\n");
}

export function ohlcSummary(bars: OhlcBar[], maxBars = 60): string {
  const recent = bars.slice(-maxBars);
  const lines = ["date,open,high,low,close,volume"];
  for (const b of recent) {
    lines.push(`${b.date.slice(0, 10)},${b.open},${b.high},${b.low},${b.close},${b.volume}`);
  }
  return lines.join("\n");
}

// ---------------------------------------------------------------------------
// search_ticker_news — Claude tool + implementation
// ---------------------------------------------------------------------------

export const SEARCH_NEWS_TOOL: Anthropic.Tool = {
  name: "search_ticker_news",
  description:
    "Search recent news articles for the current ticker. By default returns articles tagged with this ticker; pass `tags` or `query` to narrow to a theme/event (e.g. earnings, lawsuit, AI, guidance, FDA). Tickers should be uppercase symbols; themes are short words or phrases that get slugified. Returns title, source, date, URL, and snippet. Call once to scan recent news, or call multiple times with different filters to drill into specific catalysts.",
  input_schema: {
    type: "object",
    properties: {
      query: {
        type: "string",
        description:
          "Optional free-text query — tokens are auto-converted to tags (uppercase short tokens become ticker tags, longer words become theme slugs). Use this for natural-language follow-ups. Combined with the current ticker by default.",
      },
      tags: {
        type: "array",
        items: { type: "string" },
        description:
          "Optional explicit tag list to AND with the current ticker. Use uppercase symbols for tickers (AAPL) and lowercase words/phrases for themes (earnings, ai, lawsuit, guidance_cut). Leave empty to search just this ticker's news.",
      },
      include_ticker: {
        type: "boolean",
        description:
          "Whether to include the current ticker in the tag filter. Defaults to true. Set false only when explicitly searching cross-market themes.",
      },
      limit: {
        type: "integer",
        minimum: 1,
        maximum: 25,
        description: "Maximum number of articles to return. Default 10.",
      },
      days_back: {
        type: "integer",
        minimum: 1,
        maximum: 180,
        description: "Only return articles from the last N days. Default 30.",
      },
    },
  },
};

export type NewsArticleResult = {
  title: string;
  source: string | null;
  published_at: string | null;
  url: string | null;
  snippet: string | null;
};

export type SearchTickerNewsResult = {
  ticker: string;
  tags: string[];
  count: number;
  articles: NewsArticleResult[];
  note?: string;
};

export async function searchTickerNews(
  supabase: SupabaseClient,
  ticker: string,
  args: {
    query?: unknown;
    tags?: unknown;
    include_ticker?: unknown;
    limit?: unknown;
    days_back?: unknown;
  },
): Promise<SearchTickerNewsResult> {
  const rawLimit = Number(args.limit);
  const limit = Number.isFinite(rawLimit) ? Math.min(Math.max(Math.round(rawLimit), 1), 25) : 10;
  const rawDays = Number(args.days_back);
  const daysBack = Number.isFinite(rawDays) ? Math.min(Math.max(Math.round(rawDays), 1), 180) : 30;
  const lookbackHours = daysBack * 24;
  const includeTicker = args.include_ticker === undefined ? true : Boolean(args.include_ticker);

  const explicit = Array.isArray(args.tags)
    ? (args.tags as unknown[]).flatMap((t) => expandSearchTagCandidates(String(t)))
    : [];
  const fromQuery =
    typeof args.query === "string" ? tagCandidatesFromQuery(args.query) : [];

  const tagSet = new Set<string>();
  if (includeTicker) for (const c of expandSearchTagCandidates(ticker)) tagSet.add(c);
  for (const t of explicit) tagSet.add(t);
  for (const t of fromQuery) tagSet.add(t);
  const tagFilter = [...tagSet];

  if (tagFilter.length === 0) {
    return { ticker, tags: [], count: 0, articles: [], note: "No tags resolved from input." };
  }

  const { data, error } = await supabase.schema("swingtrader").rpc("search_news_by_tags", {
    tag_filter: tagFilter,
    match_count: limit,
    lookback_hours: lookbackHours,
    stream_filter: null,
  });

  if (error) {
    return { ticker, tags: tagFilter, count: 0, articles: [], note: `query failed: ${error.message}` };
  }

  const rows = (data ?? []) as {
    title: string | null;
    url: string | null;
    source: string | null;
    published_at: string | null;
    snippet: string | null;
  }[];

  const articles: NewsArticleResult[] = rows.map((r) => ({
    title: r.title ?? "",
    source: r.source,
    published_at: r.published_at,
    url: r.url,
    snippet: r.snippet,
  }));

  return { ticker, tags: tagFilter, count: articles.length, articles };
}

export function formatLatestArticlesBlock(
  ticker: string,
  articles: NewsArticleResult[],
  daysBack = 30,
): string {
  if (!articles || articles.length === 0) return "";
  const lines = articles.slice(0, 10).map((a, i) => {
    const dateStr = a.published_at ? a.published_at.slice(0, 10) : "—";
    const source = a.source ?? "feed";
    const title = a.title || "(untitled)";
    const snippet = a.snippet ? ` — ${a.snippet}` : "";
    return `${i + 1}. [${dateStr} · ${source}] ${title}${snippet}`;
  });
  return [
    `## Latest news for ${ticker} (last ${daysBack} days)`,
    "",
    "Top headlines pre-loaded for context — cite by index when relevant. Call search_ticker_news for deeper drill-downs.",
    "",
    ...lines,
  ].join("\n");
}

// ---------------------------------------------------------------------------
// draw_on_chart — Claude tool definition
// ---------------------------------------------------------------------------

export const DRAW_CHART_TOOL: Anthropic.Tool = {
  name: "draw_on_chart",
  description:
    "Draw technical analysis annotations on the price chart and provide your analysis. Call this for any analysis or drawing request. Skip it for pure how-to / 'where is X' questions — use show_how_to instead.",
  input_schema: {
    type: "object",
    required: ["annotations", "analysis"],
    properties: {
      annotations: {
        type: "array",
        description:
          "Annotations to draw on the chart. Must include every price level mentioned in the analysis (entries, stops, targets, support, resistance). Never empty.",
        items: {
          type: "object",
          required: ["type", "role"],
          properties: {
            type: {
              type: "string",
              enum: ["horizontal", "zone", "trend_line"],
              description: "horizontal = single price level; zone = price band; trend_line = line between two date/price points",
            },
            role: {
              type: "string",
              enum: ["support", "resistance", "entry", "stop", "target", "info"],
            },
            label: { type: "string", description: "Short label shown on chart" },
            price: { type: "number", description: "Required for type=horizontal" },
            price_top: { type: "number", description: "Required for type=zone" },
            price_bottom: { type: "number", description: "Required for type=zone" },
            from_date: { type: "string", description: "ISO date, required for type=trend_line" },
            from_price: { type: "number", description: "Required for type=trend_line" },
            to_date: { type: "string", description: "ISO date, required for type=trend_line" },
            to_price: { type: "number", description: "Required for type=trend_line" },
          },
        },
      },
      analysis: {
        type: "string",
        description: "Your technical analysis explanation in markdown (supports **bold**, bullet lists, etc.)",
      },
    },
  },
};
