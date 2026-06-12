"use server";

import { createClient } from "@/lib/supabase/server";
import { fetchAllPaged } from "@/lib/supabase/paginate";
import { getNewsTrendsGate } from "@/app/actions/plan-gate";
import type { HeatmapInputRow } from "@/lib/news-impact-heatmap/aggregate";

export type NewsImpactHeatmapPayload = {
  rows: HeatmapInputRow[];
  nowIso: string;
};

export type NewsImpactHeatmapResult =
  | { ok: true; data: NewsImpactHeatmapPayload }
  | { ok: false; error: string };

function asNumberMap(v: unknown): Record<string, number> {
  if (!v || typeof v !== "object" || Array.isArray(v)) return {};
  const out: Record<string, number> = {};
  for (const [k, raw] of Object.entries(v as Record<string, unknown>)) {
    const n = Number(raw);
    if (Number.isFinite(n)) out[String(k).trim().toUpperCase()] = n;
  }
  return out;
}

/**
 * Raw impact-heads + article-timestamps from `sinceIso` through `now`, ready
 * for client-side heatmap aggregation. Defaults to a 25-hour window (matches
 * the 24-bucket hourly heatmap). No plan/tier filter — pre-launch open access.
 */
export async function getNewsImpactHeatmapData(
  sinceIso?: string,
): Promise<NewsImpactHeatmapResult> {
  const supabase = await createClient();
  const now = new Date();
  let since: Date;
  if (sinceIso) {
    const parsed = new Date(sinceIso);
    since = Number.isFinite(parsed.getTime())
      ? parsed
      : new Date(now.getTime() - 25 * 3_600_000);
  } else {
    since = new Date(now);
    since.setUTCMinutes(0, 0, 0);
    since.setUTCHours(since.getUTCHours() - 25);
  }

  // Enforce the plan's lookback window server-side (no-op during open beta):
  // clamp `since` forward to the tier's allowed cutoff so a client can't request
  // older data than its tier permits.
  const gate = await getNewsTrendsGate();
  if (gate.enabled && gate.fromGte) {
    const floor = new Date(gate.fromGte);
    if (Number.isFinite(floor.getTime()) && since < floor) since = floor;
  }

  const articlesRes = await fetchAllPaged<{
    id: unknown;
    published_at: unknown;
  }>((from, to) =>
    supabase
      .schema("swingtrader")
      .from("news_articles")
      .select("id, published_at")
      .gte("published_at", since.toISOString())
      .order("published_at", { ascending: false })
      .range(from, to),
  );
  if (articlesRes.error) return { ok: false, error: articlesRes.error };

  const publishedById = new Map<number, string>();
  const articleIds: number[] = [];
  for (const r of articlesRes.data) {
    const id = Number(r.id);
    if (!Number.isFinite(id)) continue;
    articleIds.push(id);
    publishedById.set(id, String(r.published_at ?? ""));
  }
  if (articleIds.length === 0) {
    return { ok: true, data: { rows: [], nowIso: now.toISOString() } };
  }

  const CHUNK = 200;
  const heads: Array<{
    article_id: unknown;
    cluster: unknown;
    scores_json: unknown;
    confidence: unknown;
  }> = [];
  for (let i = 0; i < articleIds.length; i += CHUNK) {
    const chunk = articleIds.slice(i, i + CHUNK);
    const headsRes = await fetchAllPaged<{
      article_id: unknown;
      cluster: unknown;
      scores_json: unknown;
      confidence: unknown;
    }>((from, to) =>
      supabase
        .schema("swingtrader")
        .from("news_impact_heads")
        .select("article_id, cluster, scores_json, confidence")
        .in("article_id", chunk)
        .range(from, to),
    );
    if (headsRes.error) return { ok: false, error: headsRes.error };
    heads.push(...headsRes.data);
  }

  const rows: HeatmapInputRow[] = [];
  for (const row of heads) {
    const aid = Number(row.article_id);
    if (!Number.isFinite(aid)) continue;
    const pub = publishedById.get(aid);
    if (!pub) continue;
    const cluster = String(row.cluster ?? "");
    if (!cluster) continue;
    const rawScores = row.scores_json;
    const scores: Record<string, number> | null =
      rawScores && typeof rawScores === "object" && !Array.isArray(rawScores)
        ? asNumberMap(rawScores)
        : null;
    const confNum = Number(row.confidence);
    const conf = Number.isFinite(confNum) ? confNum : null;
    rows.push({
      article_id: aid,
      cluster,
      scores_json: scores,
      confidence: conf,
      published_at: pub,
    });
  }

  return { ok: true, data: { rows, nowIso: now.toISOString() } };
}

export type HeatmapArticle = {
  id: number;
  slug: string | null;
  title: string | null;
  url: string | null;
  image_url: string | null;
  source: string | null;
  published_at: string | null;
  created_at: string;
};

export type HeatmapArticlesResult =
  | { ok: true; data: HeatmapArticle[] }
  | { ok: false; error: string };

/** Hydrates article metadata for a list of IDs and preserves the caller's
 *  order — used by heatmap drill-down where the client has already ranked
 *  rows by impact magnitude. */
export async function getArticlesByIds(
  ids: number[],
): Promise<HeatmapArticlesResult> {
  const unique = Array.from(
    new Set(
      ids.filter((n) => Number.isFinite(n) && n > 0).map((n) => Math.trunc(n)),
    ),
  );
  if (unique.length === 0) return { ok: true, data: [] };

  const supabase = await createClient();
  const { data, error } = await supabase
    .schema("swingtrader")
    .from("news_articles")
    .select("id, slug, title, url, source, image_url, published_at, created_at")
    .in("id", unique);

  if (error) return { ok: false, error: error.message };

  const byId = new Map<number, HeatmapArticle>();
  for (const r of data ?? []) {
    byId.set(Number(r.id), {
      id: Number(r.id),
      slug: (r.slug ?? null) as string | null,
      title: (r.title ?? null) as string | null,
      url: (r.url ?? null) as string | null,
      image_url: (r.image_url ?? null) as string | null,
      source: (r.source ?? null) as string | null,
      published_at: (r.published_at ?? null) as string | null,
      created_at: String(r.created_at ?? ""),
    });
  }
  const ordered: HeatmapArticle[] = [];
  for (const id of ids) {
    const hit = byId.get(id);
    if (hit) ordered.push(hit);
  }
  return { ok: true, data: ordered };
}

export type StoryKeyPoint = { id: string; impact: number; text: string };

export type StoryKeyPointsResult =
  | { ok: true; data: StoryKeyPoint[] }
  | { ok: false; error: string };

function asJsonObject(v: unknown): Record<string, unknown> {
  if (!v) return {};
  if (typeof v === "string") {
    try {
      return asJsonObject(JSON.parse(v));
    } catch {
      return {};
    }
  }
  if (typeof v !== "object" || Array.isArray(v)) return {};
  return v as Record<string, unknown>;
}

function asStringMap(v: unknown): Record<string, string> {
  const obj = asJsonObject(v);
  const out: Record<string, string> = {};
  for (const [k, raw] of Object.entries(obj)) {
    out[k] = String(raw ?? "");
  }
  return out;
}

function asPreservedNumberMap(v: unknown): Record<string, number> {
  const obj = asJsonObject(v);
  const out: Record<string, number> = {};
  for (const [k, raw] of Object.entries(obj)) {
    const n = Number(raw);
    if (Number.isFinite(n)) out[k] = n;
  }
  return out;
}

/** Story key points are persisted as a single news_impact_heads row with
 *  cluster='STORY_KEY_POINTS' — scores_json maps point-id → impact, and
 *  reasoning_json maps point-id → claim text. */
export async function getStoryKeyPointsForArticle(
  articleId: number,
): Promise<StoryKeyPointsResult> {
  if (!Number.isFinite(articleId) || articleId <= 0) {
    return { ok: true, data: [] };
  }
  const supabase = await createClient();
  const { data, error } = await supabase
    .schema("swingtrader")
    .from("news_impact_heads")
    .select("scores_json, reasoning_json")
    .eq("article_id", Math.trunc(articleId))
    .eq("cluster", "STORY_KEY_POINTS")
    .maybeSingle<{ scores_json: unknown; reasoning_json: unknown }>();

  if (error) return { ok: false, error: error.message };
  if (!data) return { ok: true, data: [] };

  const scores = asPreservedNumberMap(data.scores_json ?? {});
  const reasoning = asStringMap(data.reasoning_json ?? {});
  const points = Object.entries(scores)
    .map(([id, impact]) => ({ id, impact, text: reasoning[id] ?? "" }))
    .filter((r) => r.text)
    .sort((a, b) => Math.abs(b.impact) - Math.abs(a.impact))
    .slice(0, 10);

  return { ok: true, data: points };
}
