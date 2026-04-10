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
      .from("news_impact_vectors")
      .select("article_id, impact_json, created_at, news_articles(published_at)")
      .order("created_at", { ascending: true }),
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
      impact_json?: unknown;
      created_at?: unknown;
      news_articles?: { published_at?: unknown } | null;
    };
    return {
      impact_json:
        r.impact_json && typeof r.impact_json === "object"
          ? (r.impact_json as Record<string, number>)
          : {},
      published_at: String(r.news_articles?.published_at ?? r.created_at ?? ""),
      ticker_sentiment: tickerSentimentByArticleId.get(Number(r.article_id)) ?? {},
    };
  });

  return { ok: true, data: articles };
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
