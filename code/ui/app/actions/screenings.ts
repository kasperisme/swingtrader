"use server";

import { createClient } from "@/lib/supabase/server";

type ScreeningActionError = { ok: false; error: string };
type ScreeningActionSuccess<T> = { ok: true; data: T };

function asRecord(v: unknown): Record<string, unknown> {
  if (!v) return {};
  if (typeof v === "string") {
    try {
      return asRecord(JSON.parse(v));
    } catch {
      return {};
    }
  }
  return typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}

function asNumberMap(v: unknown): Record<string, number> {
  if (!v) return {};
  if (typeof v === "string") {
    try {
      return asNumberMap(JSON.parse(v));
    } catch {
      return {};
    }
  }
  if (typeof v !== "object") return {};
  const out: Record<string, number> = {};
  for (const [k, raw] of Object.entries(v as Record<string, unknown>)) {
    const n = Number(raw);
    if (Number.isFinite(n)) out[String(k).trim().toUpperCase()] = n;
  }
  return out;
}

export type ScreeningTickerEdge = {
  from: string;
  to: string;
  rel_type: string;
  strength: number;
  count: number;
  note: string;
};

export async function screeningsGetTickerRelationships(): Promise<
  ScreeningActionSuccess<ScreeningTickerEdge[]> | ScreeningActionError
> {
  const supabase = await createClient();
  const { data, error } = await supabase
    .schema("swingtrader")
    .from("news_impact_heads")
    .select("scores_json, reasoning_json")
    .eq("cluster", "TICKER_RELATIONSHIPS");

  if (error) {
    return { ok: false, error: error.message };
  }

  const edgeMap = new Map<
    string,
    { from: string; to: string; rel_type: string; strengthSum: number; count: number; notes: string[] }
  >();

  for (const row of data ?? []) {
    const scores = asRecord((row as { scores_json?: unknown }).scores_json);
    const reasoning = asRecord((row as { reasoning_json?: unknown }).reasoning_json);

    for (const [key, rawStrength] of Object.entries(scores)) {
      const parts = key.split("__");
      if (parts.length !== 3) continue;
      const [from, to, rel_type] = parts as [string, string, string];
      const strength = Math.max(0, Math.min(1, Number(rawStrength) || 0));

      const existing = edgeMap.get(key);
      const note = typeof reasoning[key] === "string" ? (reasoning[key] as string) : "";
      if (existing) {
        existing.strengthSum += strength;
        existing.count++;
        if (note && !existing.notes.includes(note)) existing.notes.push(note);
      } else {
        edgeMap.set(key, {
          from,
          to,
          rel_type,
          strengthSum: strength,
          count: 1,
          notes: note ? [note] : [],
        });
      }
    }
  }

  const edges = Array.from(edgeMap.values()).map(
    ({ from, to, rel_type, strengthSum, count, notes }) => ({
      from,
      to,
      rel_type,
      strength: strengthSum / count,
      count,
      note: notes[0] ?? "",
    }),
  );

  return { ok: true, data: edges };
}

export type ScreeningNewsImpactArticle = {
  impact_json: Record<string, number>;
  published_at: string;
  ticker_sentiment: Record<string, number>;
};

export async function screeningsGetNewsImpacts(): Promise<
  ScreeningActionSuccess<ScreeningNewsImpactArticle[]> | ScreeningActionError
> {
  const supabase = await createClient();
  const [vectorsRes, headsRes] = await Promise.all([
    supabase
      .schema("swingtrader")
      .from("news_trends_article_base_v")
      .select("article_id, impact_jsonb, published_at")
      .order("published_at", { ascending: true }),
    supabase
      .schema("swingtrader")
      .from("news_impact_heads")
      .select("article_id, scores_json")
      .eq("cluster", "TICKER_SENTIMENT"),
  ]);

  if (vectorsRes.error) {
    return { ok: false, error: vectorsRes.error.message };
  }
  if (headsRes.error) {
    return { ok: false, error: headsRes.error.message };
  }

  const tickerSentimentByArticleId = new Map<number, Record<string, number>>();
  for (const row of headsRes.data ?? []) {
    const articleId = Number((row as { article_id?: unknown }).article_id);
    if (!Number.isFinite(articleId)) continue;
    tickerSentimentByArticleId.set(
      articleId,
      asNumberMap((row as { scores_json?: unknown }).scores_json),
    );
  }

  const articles = (vectorsRes.data ?? []).map((row) => {
    const r = row as {
      article_id: unknown;
      impact_jsonb?: unknown;
      published_at?: unknown;
    };
    const parsedImpact =
      r.impact_jsonb && typeof r.impact_jsonb === "object"
        ? (r.impact_jsonb as Record<string, number>)
        : {};
    return {
      impact_json: parsedImpact,
      published_at: String(r.published_at ?? ""),
      ticker_sentiment: tickerSentimentByArticleId.get(Number(r.article_id)) ?? {},
    };
  });

  return { ok: true, data: articles };
}

/** One row per (head, ticker) from `ticker_sentiment_heads_v` — same source as Explore → Relationships → Sentiment. */
export type ScreeningTickerSentimentHeadRow = {
  article_id: number;
  ticker: string;
  sentiment_score: number;
  article_ts: string;
};

const TICKER_SENTIMENT_HEAD_TICKER_CHUNK = 40;

/**
 * Loads ticker sentiment rows from `swingtrader.ticker_sentiment_heads_v` for the given symbols.
 * Matches the Explore relationship panel sentiment feed (view over TICKER_SENTIMENT heads + articles).
 */
export async function screeningsGetTickerSentimentHeadRows(
  symbols: string[],
): Promise<ScreeningActionSuccess<ScreeningTickerSentimentHeadRow[]> | ScreeningActionError> {
  const tickers = [...new Set(symbols.map((s) => s.trim().toUpperCase()).filter(Boolean))];
  if (tickers.length === 0) {
    return { ok: true, data: [] };
  }

  const supabase = await createClient();
  const since = new Date();
  since.setUTCDate(since.getUTCDate() - 120);
  const sinceIso = since.toISOString();

  const out: ScreeningTickerSentimentHeadRow[] = [];

  for (let i = 0; i < tickers.length; i += TICKER_SENTIMENT_HEAD_TICKER_CHUNK) {
    const chunk = tickers.slice(i, i + TICKER_SENTIMENT_HEAD_TICKER_CHUNK);
    const { data, error } = await supabase
      .schema("swingtrader")
      .from("ticker_sentiment_heads_v")
      .select("article_id, ticker, sentiment_score, article_ts")
      .in("ticker", chunk)
      .gte("article_ts", sinceIso);

    if (error) {
      return { ok: false, error: error.message };
    }

    for (const raw of data ?? []) {
      const row = raw as {
        article_id?: unknown;
        ticker?: unknown;
        sentiment_score?: unknown;
        article_ts?: unknown;
      };
      const articleId = Number(row.article_id);
      const ticker = String(row.ticker ?? "").trim().toUpperCase();
      const sentimentScore = Number(row.sentiment_score);
      const articleTs = row.article_ts != null ? String(row.article_ts) : "";
      if (!Number.isFinite(articleId) || !ticker || !Number.isFinite(sentimentScore) || !articleTs) continue;
      out.push({
        article_id: articleId,
        ticker,
        sentiment_score: sentimentScore,
        article_ts: articleTs,
      });
    }
  }

  return { ok: true, data: out };
}

export async function screeningsUpsertDismissNote(input: {
  scanRowId: number;
  runId: number;
  ticker: string;
  status?: "active" | "dismissed" | "watchlist" | "pipeline";
  highlighted?: boolean;
  comment?: string | null;
  metadataJson?: Record<string, unknown>;
}): Promise<ScreeningActionSuccess<true> | ScreeningActionError> {
  const { scanRowId, runId, ticker, status, highlighted, comment, metadataJson } = input;
  if (!scanRowId || typeof scanRowId !== "number") {
    return { ok: false, error: "scanRowId required" };
  }
  if (!runId || typeof runId !== "number") {
    return { ok: false, error: "runId required" };
  }
  if (!ticker || typeof ticker !== "string") {
    return { ok: false, error: "ticker required" };
  }

  const supabase = await createClient();
  const {
    data: { user },
    error: authError,
  } = await supabase.auth.getUser();
  if (authError || !user) {
    return { ok: false, error: "Unauthorized" };
  }

  const { error } = await supabase
    .schema("swingtrader")
    .from("user_scan_row_notes")
    .upsert(
      {
        scan_row_id: scanRowId,
        run_id: runId,
        ticker,
        user_id: user.id,
        status: status ?? "active",
        highlighted: highlighted ?? false,
        comment: comment ?? null,
        metadata_json: metadataJson ?? {},
        updated_at: new Date().toISOString(),
      },
      { onConflict: "scan_row_id,user_id" },
    );

  if (error) return { ok: false, error: error.message };
  return { ok: true, data: true };
}

/** Soft-delete a screening run (hides from UI; does not remove rows). */
export async function screeningsSoftDeleteRun(
  runId: number,
): Promise<ScreeningActionSuccess<true> | ScreeningActionError> {
  if (!runId || typeof runId !== "number" || runId < 1) {
    return { ok: false, error: "runId required" };
  }

  const supabase = await createClient();
  const {
    data: { user },
    error: authError,
  } = await supabase.auth.getUser();
  if (authError || !user) {
    return { ok: false, error: "Unauthorized" };
  }

  const { data, error } = await supabase
    .schema("swingtrader")
    .from("user_scan_runs")
    .update({ status: "deleted" })
    .eq("id", runId)
    .eq("user_id", user.id)
    .eq("status", "active")
    .select("id");

  if (error) return { ok: false, error: error.message };
  if (!data?.length) {
    return { ok: false, error: "Screening not found or already removed" };
  }
  return { ok: true, data: true };
}

export type ScreeningRunSummary = {
  id: number;
  scan_date: string;
  source: string | null;
};

export async function screeningsListRuns(): Promise<
  ScreeningActionSuccess<ScreeningRunSummary[]> | ScreeningActionError
> {
  const supabase = await createClient();
  const { data: { user }, error: authError } = await supabase.auth.getUser();
  if (authError || !user) return { ok: false, error: "Unauthorized" };

  const { data, error } = await supabase
    .schema("swingtrader")
    .from("user_scan_runs")
    .select("id, scan_date, source")
    .eq("user_id", user.id)
    .eq("status", "active")
    .order("scan_date", { ascending: false })
    .limit(50);

  if (error) return { ok: false, error: error.message };
  return {
    ok: true,
    data: (data ?? []).map((r) => ({
      id: Number(r.id),
      scan_date: String(r.scan_date ?? ""),
      source: r.source != null ? String(r.source) : null,
    })),
  };
}

export async function screeningsCreateRun(
  name: string,
): Promise<ScreeningActionSuccess<ScreeningRunSummary> | ScreeningActionError> {
  const trimmed = name.trim();
  if (!trimmed) return { ok: false, error: "Name required" };

  const supabase = await createClient();
  const { data: { user }, error: authError } = await supabase.auth.getUser();
  if (authError || !user) return { ok: false, error: "Unauthorized" };

  const scanDate = new Date().toISOString().slice(0, 10);

  const { data, error } = await supabase
    .schema("swingtrader")
    .from("user_scan_runs")
    .insert({
      scan_date: scanDate,
      source: trimmed,
      status: "active",
      market_json: null,
      result_json: null,
      user_id: user.id,
    })
    .select("id, scan_date, source")
    .single();

  if (error) return { ok: false, error: error.message };
  return {
    ok: true,
    data: {
      id: Number((data as { id: number }).id),
      scan_date: scanDate,
      source: trimmed,
    },
  };
}

export async function screeningsAddTicker(
  runId: number,
  ticker: string,
): Promise<ScreeningActionSuccess<{ id: number }> | ScreeningActionError> {
  if (!Number.isFinite(runId) || runId < 1) return { ok: false, error: "Invalid run" };
  const sym = ticker?.trim().toUpperCase();
  if (!sym) return { ok: false, error: "Ticker required" };

  const supabase = await createClient();
  const { data: { user }, error: authError } = await supabase.auth.getUser();
  if (authError || !user) return { ok: false, error: "Unauthorized" };

  const { data: run, error: runErr } = await supabase
    .schema("swingtrader")
    .from("user_scan_runs")
    .select("id, scan_date, status")
    .eq("id", runId)
    .eq("user_id", user.id)
    .maybeSingle();

  if (runErr) return { ok: false, error: runErr.message };
  if (!run) return { ok: false, error: "Screening not found" };
  if (run.status === "deleted") return { ok: false, error: "Screening has been deleted" };

  const scanDate = String(run.scan_date ?? new Date().toISOString().slice(0, 10)).slice(0, 10);

  const { data: inserted, error: insErr } = await supabase
    .schema("swingtrader")
    .from("user_scan_rows")
    .insert({
      run_id: runId,
      scan_date: scanDate,
      dataset: "charts_page",
      symbol: sym,
      row_data: {},
      user_id: user.id,
    })
    .select("id")
    .single();

  if (insErr) return { ok: false, error: insErr.message };
  return { ok: true, data: { id: Number((inserted as { id: number }).id) } };
}
