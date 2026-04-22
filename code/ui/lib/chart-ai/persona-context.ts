import { createClient } from "@/lib/supabase/server";

export type SentimentContext = {
  windows: { days: number; avg_sentiment: number | null; weighted_sentiment: number | null; mention_count: number }[];
  recentHeadlines: { title: string | null; sentiment_score: number; confidence: number | null; published_at: string | null }[];
};

export type EarningsQuarter = {
  date: string;
  eps: number | null;
  epsEstimated: number | null;
  revenue: number | null;
  revenueEstimated: number | null;
  beat: boolean;
};

export type FmpKeyMetrics = {
  roe: number | null;
  roic: number | null;
  currentRatio: number | null;
  debtToEquity: number | null;
  peRatioTTM: number | null;
  priceToSalesTTM: number | null;
  shortRatio: number | null;
};

export type RiskContext = {
  financialStructure: Record<string, number> | null;
  macroSensitivity: Record<string, number> | null;
  geoTradeExposure: Record<string, number> | null;
  supplyChainExposure: Record<string, number> | null;
  valuationPositioning: Record<string, number> | null;
  beta: number | null;
  keyMetrics: FmpKeyMetrics | null;
};

export type FundamentalsContext = {
  companyProfile: { sector: string | null; industry: string | null; marketCap: number | null; description: string | null } | null;
  growthProfile: Record<string, number> | null;
  businessModel: Record<string, number> | null;
  earnings: EarningsQuarter[] | null;
  keyMetrics: FmpKeyMetrics | null;
};

async function fmpFetch<T>(path: string, revalidate = 3600): Promise<T | null> {
  const apiKey = process.env.FMP_API_KEY;
  if (!apiKey) return null;
  try {
    const res = await fetch(
      `https://financialmodelingprep.com${path}&apikey=${encodeURIComponent(apiKey)}`,
      { next: { revalidate } },
    );
    if (!res.ok) return null;
    return await res.json() as T;
  } catch {
    return null;
  }
}

async function fetchFmpEarnings(ticker: string): Promise<EarningsQuarter[] | null> {
  const raw = await fmpFetch<unknown[]>(
    `/api/v3/historical/earning_calendar/${encodeURIComponent(ticker)}?limit=8`,
  );
  if (!Array.isArray(raw) || raw.length === 0) return null;
  const quarters: EarningsQuarter[] = [];
  for (const row of raw) {
    const r = row as Record<string, unknown>;
    const eps = r.eps != null ? Number(r.eps) : null;
    const epsEst = r.epsEstimated != null ? Number(r.epsEstimated) : null;
    const rev = r.revenue != null ? Number(r.revenue) : null;
    const revEst = r.revenueEstimated != null ? Number(r.revenueEstimated) : null;
    const date = r.date ? String(r.date) : null;
    if (!date) continue;
    quarters.push({
      date,
      eps: Number.isFinite(eps) ? eps : null,
      epsEstimated: Number.isFinite(epsEst) ? epsEst : null,
      revenue: Number.isFinite(rev) ? rev : null,
      revenueEstimated: Number.isFinite(revEst) ? revEst : null,
      beat: eps != null && epsEst != null && eps >= epsEst,
    });
  }
  return quarters.length > 0 ? quarters : null;
}

async function fetchFmpKeyMetrics(ticker: string): Promise<FmpKeyMetrics | null> {
  const [ttmRaw, quarterlyRaw] = await Promise.all([
    fmpFetch<unknown[]>(`/api/v3/key-metrics-ttm/${encodeURIComponent(ticker)}?limit=1`),
    fmpFetch<unknown[]>(`/api/v3/key-metrics/${encodeURIComponent(ticker)}?period=quarter&limit=2`),
  ]);

  const n = (v: unknown) => (v != null && Number.isFinite(Number(v)) ? Number(v) : null);

  const ttm = Array.isArray(ttmRaw) && ttmRaw.length > 0 ? ttmRaw[0] as Record<string, unknown> : null;
  const q = Array.isArray(quarterlyRaw) && quarterlyRaw.length > 0 ? quarterlyRaw[0] as Record<string, unknown> : null;

  if (!ttm && !q) return null;

  return {
    roe: n(q?.roe ?? ttm?.roeTTM),
    roic: n(q?.roic ?? ttm?.roicTTM),
    currentRatio: n(q?.currentRatio ?? ttm?.currentRatioTTM),
    debtToEquity: n(q?.debtToEquity ?? ttm?.debtToEquityTTM),
    peRatioTTM: n(ttm?.peRatioTTM),
    priceToSalesTTM: n(ttm?.priceToSalesRatioTTM),
    shortRatio: n(ttm?.shortRatioTTM ?? q?.shortRatio),
  };
}

function asNumberMap(v: unknown): Record<string, number> | null {
  if (!v || typeof v !== "object" || Array.isArray(v)) return null;
  const out: Record<string, number> = {};
  for (const [k, raw] of Object.entries(v as Record<string, unknown>)) {
    const n = Number(raw);
    if (Number.isFinite(n)) out[k] = n;
  }
  return Object.keys(out).length > 0 ? out : null;
}

export type DimensionTrendEntry = {
  dimension_key: string;
  companyExposure: number;
  avgTrend14d: number | null;
  avgTrendRecent7d: number | null;
  avgTrendPrior7d: number | null;
};

export type NewsTrendContext = {
  entries: DimensionTrendEntry[];
  totalDimensionsAnalysed: number;
  hasCompanyProfile: boolean;
};

export async function fetchNewsTrendContext(ticker: string): Promise<NewsTrendContext> {
  const supabase = await createClient();

  const cutoff = new Date();
  cutoff.setUTCDate(cutoff.getUTCDate() - 14);
  const cutoffStr = cutoff.toISOString().slice(0, 10);

  const midpoint = new Date();
  midpoint.setUTCDate(midpoint.getUTCDate() - 7);
  const midpointStr = midpoint.toISOString().slice(0, 10);

  // Get company's dimension exposure profile
  const vectorsRes = await supabase
    .schema("swingtrader")
    .from("company_vectors")
    .select("dimensions_json")
    .eq("ticker", ticker)
    .order("date", { ascending: false })
    .limit(1);

  const dims = !vectorsRes.error && vectorsRes.data?.[0]
    ? asNumberMap((vectorsRes.data[0] as Record<string, unknown>).dimensions_json)
    : null;

  // Derive top dimensions: company-specific if available, else most active from the trend view
  let topDims: string[];
  let hasCompanyProfile = false;

  if (dims) {
    topDims = Object.entries(dims)
      .filter(([, v]) => v > 0.25)
      .sort(([, a], [, b]) => b - a)
      .slice(0, 12)
      .map(([k]) => k);
    hasCompanyProfile = topDims.length > 0;
  } else {
    topDims = [];
  }

  // Fallback: if no company profile, find the most active dimensions by article volume
  if (topDims.length === 0) {
    const activeRes = await supabase
      .from("news_trends_dimension_daily_v")
      .select("dimension_key, article_count")
      .gte("bucket_day", cutoffStr)
      .order("article_count", { ascending: false })
      .limit(200);

    if (!activeRes.error && Array.isArray(activeRes.data)) {
      const counts: Record<string, number> = {};
      for (const row of activeRes.data as { dimension_key: string; article_count: number }[]) {
        counts[row.dimension_key] = (counts[row.dimension_key] ?? 0) + (row.article_count ?? 0);
      }
      topDims = Object.entries(counts)
        .sort(([, a], [, b]) => b - a)
        .slice(0, 12)
        .map(([k]) => k);
    }
  }

  if (topDims.length === 0) return { entries: [], totalDimensionsAnalysed: 0, hasCompanyProfile: false };

  // Fetch last 14 days of dimension trend data for selected dimensions
  const trendRes = await supabase
    .from("news_trends_dimension_daily_v")
    .select("bucket_day, dimension_key, dimension_weighted_avg")
    .gte("bucket_day", cutoffStr)
    .in("dimension_key", topDims)
    .order("bucket_day", { ascending: false });

  const rows = (!trendRes.error && Array.isArray(trendRes.data))
    ? trendRes.data as { bucket_day: string; dimension_key: string; dimension_weighted_avg: number | null }[]
    : [];

  // Aggregate per dimension
  const recent7: Record<string, number[]> = {};
  const prior7: Record<string, number[]> = {};
  for (const row of rows) {
    const v = row.dimension_weighted_avg;
    if (v == null) continue;
    const bucket = row.bucket_day as string;
    const dim = row.dimension_key as string;
    if (bucket >= midpointStr) {
      (recent7[dim] ??= []).push(v);
    } else {
      (prior7[dim] ??= []).push(v);
    }
  }

  const avg = (arr: number[] | undefined) =>
    arr && arr.length > 0 ? arr.reduce((s, v) => s + v, 0) / arr.length : null;

  const entries: DimensionTrendEntry[] = topDims.map((key) => ({
    dimension_key: key,
    companyExposure: dims?.[key] ?? 0,
    avgTrend14d: avg([...(recent7[key] ?? []), ...(prior7[key] ?? [])]),
    avgTrendRecent7d: avg(recent7[key]),
    avgTrendPrior7d: avg(prior7[key]),
  }));

  return { entries, totalDimensionsAnalysed: topDims.length, hasCompanyProfile };
}

export async function fetchSentimentContext(ticker: string): Promise<SentimentContext> {
  const supabase = await createClient();
  const windows: SentimentContext["windows"] = [];
  const recentHeadlines: SentimentContext["recentHeadlines"] = [];

  const [sentimentRes, windowsRes] = await Promise.all([
    supabase.schema("swingtrader").rpc("get_relationship_node_sentiment", {
      p_ticker: ticker,
      p_page: 1,
      p_page_size: 8,
    }),
    supabase.schema("swingtrader").rpc("get_relationship_node_sentiment_windows", { p_ticker: ticker }),
  ]);

  if (!sentimentRes.error && Array.isArray(sentimentRes.data)) {
    for (const row of sentimentRes.data) {
      recentHeadlines.push({
        title: String((row as Record<string, unknown>).article_title ?? ""),
        sentiment_score: Number((row as Record<string, unknown>).sentiment_score ?? 0),
        confidence: (row as Record<string, unknown>).confidence == null ? null : Number((row as Record<string, unknown>).confidence),
        published_at: (row as Record<string, unknown>).published_at ? String((row as Record<string, unknown>).published_at) : null,
      });
    }
  }

  if (!windowsRes.error && Array.isArray(windowsRes.data)) {
    for (const row of windowsRes.data) {
      const days = Number((row as Record<string, unknown>).days ?? 0);
      if ([10, 21, 50, 200].includes(days)) {
        windows.push({
          days,
          avg_sentiment: (row as Record<string, unknown>).avg_sentiment == null ? null : Number((row as Record<string, unknown>).avg_sentiment),
          weighted_sentiment: (row as Record<string, unknown>).weighted_sentiment == null ? null : Number((row as Record<string, unknown>).weighted_sentiment),
          mention_count: Number((row as Record<string, unknown>).mention_count ?? 0),
        });
      }
    }
  }

  return { windows, recentHeadlines };
}

export async function fetchRiskContext(ticker: string): Promise<RiskContext> {
  const supabase = await createClient();
  let financialStructure: Record<string, number> | null = null;
  let macroSensitivity: Record<string, number> | null = null;
  let geoTradeExposure: Record<string, number> | null = null;
  let supplyChainExposure: Record<string, number> | null = null;
  let valuationPositioning: Record<string, number> | null = null;
  let beta: number | null = null;

  const [vectorsRes, tickerRes, keyMetrics] = await Promise.all([
    supabase.schema("swingtrader").from("company_vectors").select("dimensions_json").eq("ticker", ticker).order("date", { ascending: false }).limit(1),
    supabase.schema("swingtrader").from("tickers").select("beta").eq("symbol", ticker).limit(1),
    fetchFmpKeyMetrics(ticker).catch(() => null),
  ]);

  if (!vectorsRes.error && vectorsRes.data?.[0]) {
    const dims = asNumberMap((vectorsRes.data[0] as Record<string, unknown>).dimensions_json);
    if (dims) {
      const pick = (prefix: string) => {
        const out: Record<string, number> = {};
        for (const [k, v] of Object.entries(dims)) {
          if (k.startsWith(prefix + "_") || k === prefix) out[k] = v;
        }
        return Object.keys(out).length > 0 ? out : null;
      };
      financialStructure = pick("financial_structure");
      macroSensitivity = pick("macro_sensitivity");
      geoTradeExposure = pick("geography_trade");
      supplyChainExposure = pick("supply_chain_exposure");
      valuationPositioning = pick("valuation_positioning");
    }
  }

  if (!tickerRes.error && tickerRes.data?.[0]) {
    beta = (tickerRes.data[0] as Record<string, unknown>).beta == null ? null : Number((tickerRes.data[0] as Record<string, unknown>).beta);
  }

  return { financialStructure, macroSensitivity, geoTradeExposure, supplyChainExposure, valuationPositioning, beta, keyMetrics };
}

export async function fetchFundamentalsContext(ticker: string): Promise<FundamentalsContext> {
  const supabase = await createClient();
  let companyProfile: FundamentalsContext["companyProfile"] = null;
  let growthProfile: Record<string, number> | null = null;
  let businessModel: Record<string, number> | null = null;

  const [profileRes, vectorsRes, earnings, keyMetrics] = await Promise.all([
    supabase.schema("swingtrader").from("tickers").select("sector, industry, market_cap, company_name").eq("symbol", ticker).limit(1),
    supabase.schema("swingtrader").from("company_vectors").select("dimensions_json").eq("ticker", ticker).order("date", { ascending: false }).limit(1),
    fetchFmpEarnings(ticker).catch(() => null),
    fetchFmpKeyMetrics(ticker).catch(() => null),
  ]);

  if (!profileRes.error && profileRes.data?.[0]) {
    const r = profileRes.data[0] as Record<string, unknown>;
    companyProfile = {
      sector: r.sector ? String(r.sector) : null,
      industry: r.industry ? String(r.industry) : null,
      marketCap: r.market_cap == null ? null : Number(r.market_cap),
      description: null,
    };
  }

  if (!vectorsRes.error && vectorsRes.data?.[0]) {
    const dims = asNumberMap((vectorsRes.data[0] as Record<string, unknown>).dimensions_json);
    if (dims) {
      const pick = (prefix: string) => {
        const out: Record<string, number> = {};
        for (const [k, v] of Object.entries(dims)) {
          if (k.startsWith(prefix + "_") || k === prefix) out[k] = v;
        }
        return Object.keys(out).length > 0 ? out : null;
      };
      growthProfile = pick("growth_profile");
      businessModel = pick("business_model");
    }
  }

  return { companyProfile, growthProfile, businessModel, earnings, keyMetrics };
}

export function formatSentimentContext(ctx: SentimentContext): string {
  const lines: string[] = ["## Sentiment Data"];
  if (ctx.windows.length > 0) {
    lines.push("Rolling sentiment windows:");
    for (const w of ctx.windows) {
      const avg = w.avg_sentiment?.toFixed(2) ?? "n/a";
      const wtd = w.weighted_sentiment?.toFixed(2) ?? "n/a";
      lines.push(`- ${w.days}d: avg=${avg}, confidence-weighted=${wtd}, mentions=${w.mention_count}`);
    }
  }
  if (ctx.recentHeadlines.length > 0) {
    lines.push("\nRecent scored headlines:");
    for (const h of ctx.recentHeadlines.slice(0, 5)) {
      const date = h.published_at ? h.published_at.slice(0, 10) : "unknown date";
      const score = h.sentiment_score.toFixed(2);
      const title = h.title ?? "(no title)";
      lines.push(`- [${date}] sentiment=${score} — ${title}`);
    }
  }
  if (ctx.windows.length === 0 && ctx.recentHeadlines.length === 0) {
    lines.push("No sentiment data available for this ticker.");
  }
  return lines.join("\n");
}

export function formatRiskContext(ctx: RiskContext): string {
  const lines: string[] = ["## Risk Factors"];

  if (ctx.beta != null) lines.push(`Beta: ${ctx.beta.toFixed(2)}`);

  if (ctx.keyMetrics) {
    const km = ctx.keyMetrics;
    lines.push("\nFinancial Health:");
    if (km.currentRatio != null) lines.push(`- Current Ratio: ${km.currentRatio.toFixed(2)}`);
    if (km.debtToEquity != null) lines.push(`- Debt/Equity: ${km.debtToEquity.toFixed(2)}`);
    if (km.roe != null) lines.push(`- ROE: ${(km.roe * 100).toFixed(1)}%`);
    if (km.roic != null) lines.push(`- ROIC: ${(km.roic * 100).toFixed(1)}%`);
    lines.push("\nValuation:");
    if (km.peRatioTTM != null) lines.push(`- P/E (TTM): ${km.peRatioTTM.toFixed(1)}`);
    if (km.priceToSalesTTM != null) lines.push(`- P/S (TTM): ${km.priceToSalesTTM.toFixed(2)}`);
    if (km.shortRatio != null) lines.push(`- Short Ratio: ${km.shortRatio.toFixed(1)} days`);
  }

  const section = (label: string, data: Record<string, number> | null) => {
    if (!data) return;
    lines.push(`\n${label}:`);
    for (const [k, v] of Object.entries(data)) lines.push(`- ${k}: ${v.toFixed(3)}`);
  };
  section("Macro Sensitivity", ctx.macroSensitivity);
  section("Geography/Trade Exposure", ctx.geoTradeExposure);
  section("Supply Chain Exposure", ctx.supplyChainExposure);
  section("Financial Structure (vectors)", ctx.financialStructure);
  section("Valuation Positioning (vectors)", ctx.valuationPositioning);

  const hasData = ctx.beta != null || ctx.keyMetrics || ctx.financialStructure || ctx.macroSensitivity || ctx.geoTradeExposure || ctx.supplyChainExposure || ctx.valuationPositioning;
  if (!hasData) lines.push("No risk data available for this ticker.");
  return lines.join("\n");
}

export function formatFundamentalsContext(ctx: FundamentalsContext): string {
  const lines: string[] = ["## Fundamentals"];

  if (ctx.companyProfile) {
    lines.push(`Sector: ${ctx.companyProfile.sector ?? "unknown"}, Industry: ${ctx.companyProfile.industry ?? "unknown"}`);
    if (ctx.companyProfile.marketCap != null) {
      const b = ctx.companyProfile.marketCap / 1e9;
      lines.push(`Market Cap: ${b >= 1 ? `$${b.toFixed(1)}B` : `$${(ctx.companyProfile.marketCap / 1e6).toFixed(0)}M`}`);
    }
  }

  if (ctx.earnings && ctx.earnings.length > 0) {
    lines.push("\nEarnings (last quarters, newest first):");
    for (const q of ctx.earnings.slice(0, 6)) {
      const eps = q.eps != null ? `$${q.eps.toFixed(2)}` : "n/a";
      const epsEst = q.epsEstimated != null ? `est $${q.epsEstimated.toFixed(2)}` : "";
      const rev = q.revenue != null
        ? q.revenue >= 1e9 ? `rev $${(q.revenue / 1e9).toFixed(2)}B` : `rev $${(q.revenue / 1e6).toFixed(0)}M`
        : "";
      const beat = q.beat ? "✓ beat" : q.epsEstimated != null ? "✗ miss" : "";
      lines.push(`- ${q.date}: EPS ${eps} ${epsEst} ${beat}  ${rev}`.trim());
    }

    // Compute YoY EPS growth (current vs 4 quarters ago)
    if (ctx.earnings.length >= 5) {
      const cur = ctx.earnings[0].eps;
      const yearAgo = ctx.earnings[4].eps;
      if (cur != null && yearAgo != null && yearAgo !== 0) {
        const yoy = ((cur - yearAgo) / Math.abs(yearAgo)) * 100;
        lines.push(`EPS YoY growth: ${yoy >= 0 ? "+" : ""}${yoy.toFixed(1)}%`);
      }
    }

    // Beat rate
    const beats = ctx.earnings.slice(0, 4).filter((q) => q.beat).length;
    const withEst = ctx.earnings.slice(0, 4).filter((q) => q.epsEstimated != null).length;
    if (withEst > 0) lines.push(`Beat rate (last ${withEst}Q): ${beats}/${withEst}`);
  }

  if (ctx.keyMetrics) {
    const km = ctx.keyMetrics;
    lines.push("\nKey Metrics:");
    if (km.roe != null) lines.push(`- ROE: ${(km.roe * 100).toFixed(1)}%`);
    if (km.roic != null) lines.push(`- ROIC: ${(km.roic * 100).toFixed(1)}%`);
    if (km.currentRatio != null) lines.push(`- Current Ratio: ${km.currentRatio.toFixed(2)}`);
    if (km.debtToEquity != null) lines.push(`- Debt/Equity: ${km.debtToEquity.toFixed(2)}`);
    if (km.peRatioTTM != null) lines.push(`- P/E (TTM): ${km.peRatioTTM.toFixed(1)}`);
    if (km.priceToSalesTTM != null) lines.push(`- P/S (TTM): ${km.priceToSalesTTM.toFixed(2)}`);
  }

  if (ctx.growthProfile) {
    lines.push("\nGrowth Profile (vectors):");
    for (const [k, v] of Object.entries(ctx.growthProfile)) lines.push(`- ${k}: ${v.toFixed(3)}`);
  }
  if (ctx.businessModel) {
    lines.push("\nBusiness Model (vectors):");
    for (const [k, v] of Object.entries(ctx.businessModel)) lines.push(`- ${k}: ${v.toFixed(3)}`);
  }

  const hasData = ctx.companyProfile || ctx.earnings || ctx.keyMetrics || ctx.growthProfile || ctx.businessModel;
  if (!hasData) lines.push("No fundamental data available for this ticker.");
  return lines.join("\n");
}

export function formatNewsTrendContext(ctx: NewsTrendContext): string {
  if (ctx.entries.length === 0) return "No news trend dimension data available for this ticker.";

  const profileNote = ctx.hasCompanyProfile
    ? "company-specific dimensions by exposure"
    : "NOTE: no company vector profile found — showing top market-wide dimensions by article volume instead; exposure column is not applicable";

  const lines: string[] = [
    `## News Trend Context (last 14 days · ${profileNote})`,
    "Columns: dimension | company exposure | 14d avg trend | recent 7d | prior 7d | direction",
  ];

  for (const e of ctx.entries) {
    const fmt = (v: number | null) => v == null ? "n/a" : v.toFixed(3);
    let direction = "stable";
    if (e.avgTrendRecent7d != null && e.avgTrendPrior7d != null) {
      const delta = e.avgTrendRecent7d - e.avgTrendPrior7d;
      if (delta > 0.05) direction = "RISING";
      else if (delta < -0.05) direction = "FALLING";
    } else if (e.avgTrendRecent7d != null) {
      direction = e.avgTrendRecent7d > 0.05 ? "positive" : e.avgTrendRecent7d < -0.05 ? "negative" : "neutral";
    }
    const exposure = ctx.hasCompanyProfile ? e.companyExposure.toFixed(2) : "n/a";
    lines.push(
      `- ${e.dimension_key}: exposure=${exposure} | 14d=${fmt(e.avgTrend14d)} | r7d=${fmt(e.avgTrendRecent7d)} | p7d=${fmt(e.avgTrendPrior7d)} | ${direction}`,
    );
  }
  return lines.join("\n");
}