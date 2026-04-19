import { createClient } from "@/lib/supabase/server";

export type SentimentContext = {
  windows: { days: number; avg_sentiment: number | null; weighted_sentiment: number | null; mention_count: number }[];
  recentHeadlines: { title: string | null; sentiment_score: number; confidence: number | null; published_at: string | null }[];
};

export type RiskContext = {
  financialStructure: Record<string, number> | null;
  macroSensitivity: Record<string, number> | null;
  geoTradeExposure: Record<string, number> | null;
  supplyChainExposure: Record<string, number> | null;
  valuationPositioning: Record<string, number> | null;
  beta: number | null;
};

export type FundamentalsContext = {
  companyProfile: { sector: string | null; industry: string | null; marketCap: number | null; description: string | null } | null;
  growthProfile: Record<string, number> | null;
  businessModel: Record<string, number> | null;
};

function asNumberMap(v: unknown): Record<string, number> | null {
  if (!v || typeof v !== "object" || Array.isArray(v)) return null;
  const out: Record<string, number> = {};
  for (const [k, raw] of Object.entries(v as Record<string, unknown>)) {
    const n = Number(raw);
    if (Number.isFinite(n)) out[k] = n;
  }
  return Object.keys(out).length > 0 ? out : null;
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

  const [vectorsRes, tickerRes] = await Promise.all([
    supabase.schema("swingtrader").from("company_vectors").select("dimensions_json").eq("ticker", ticker).order("date", { ascending: false }).limit(1),
    supabase.schema("swingtrader").from("tickers").select("beta").eq("symbol", ticker).limit(1),
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

  return { financialStructure, macroSensitivity, geoTradeExposure, supplyChainExposure, valuationPositioning, beta };
}

export async function fetchFundamentalsContext(ticker: string): Promise<FundamentalsContext> {
  const supabase = await createClient();
  let companyProfile: FundamentalsContext["companyProfile"] = null;
  let growthProfile: Record<string, number> | null = null;
  let businessModel: Record<string, number> | null = null;

  const [profileRes, vectorsRes] = await Promise.all([
    supabase.schema("swingtrader").from("tickers").select("sector, industry, market_cap, company_name").eq("symbol", ticker).limit(1),
    supabase.schema("swingtrader").from("company_vectors").select("dimensions_json").eq("ticker", ticker).order("date", { ascending: false }).limit(1),
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

  return { companyProfile, growthProfile, businessModel };
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
  const section = (label: string, data: Record<string, number> | null) => {
    if (!data) return;
    lines.push(`\n${label}:`);
    for (const [k, v] of Object.entries(data)) {
      lines.push(`- ${k}: ${v.toFixed(3)}`);
    }
  };
  section("Financial Structure", ctx.financialStructure);
  section("Macro Sensitivity", ctx.macroSensitivity);
  section("Geography/Trade Exposure", ctx.geoTradeExposure);
  section("Supply Chain Exposure", ctx.supplyChainExposure);
  section("Valuation Positioning", ctx.valuationPositioning);
  if (ctx.beta != null) lines.push(`\nBeta: ${ctx.beta.toFixed(2)}`);
  const hasData = ctx.financialStructure || ctx.macroSensitivity || ctx.geoTradeExposure || ctx.supplyChainExposure || ctx.valuationPositioning || ctx.beta != null;
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
  if (ctx.growthProfile) {
    lines.push("\nGrowth Profile:");
    for (const [k, v] of Object.entries(ctx.growthProfile)) lines.push(`- ${k}: ${v.toFixed(3)}`);
  }
  if (ctx.businessModel) {
    lines.push("\nBusiness Model:");
    for (const [k, v] of Object.entries(ctx.businessModel)) lines.push(`- ${k}: ${v.toFixed(3)}`);
  }
  const hasData = ctx.companyProfile || ctx.growthProfile || ctx.businessModel;
  if (!hasData) lines.push("No fundamental data available for this ticker.");
  return lines.join("\n");
}