import "server-only";
import { cacheLife, cacheTag } from "next/cache";

import { createServiceClient } from "@/lib/supabase/service";
import type { ScoreDistribution, ScoreKind } from "@/lib/news/article-verdict";

const KINDS: ReadonlySet<string> = new Set<ScoreKind>(["claim", "ticker", "relationship"]);

async function loadDistribution(days: number): Promise<ScoreDistribution> {
  "use cache";
  // ~10k claims a week at ~20 distinct values: one article more or less moves
  // no percentile, so an hour-scale cache loses nothing and saves a ~0.5s
  // aggregate per page view.
  cacheLife("hours");
  cacheTag("score-distribution");

  const { data, error } = await createServiceClient()
    .schema("swingtrader")
    .rpc("impact_score_distribution", { p_days: days });
  // Throw rather than return {}: a thrown "use cache" call is not cached, so a
  // transient failure costs one render its anchors instead of hiding them for
  // the whole cache lifetime.
  if (error) throw new Error(`impact_score_distribution: ${error.message}`);

  const out: ScoreDistribution = {};
  for (const row of (data ?? []) as Array<{ kind: string; score: number | string; n: number | string }>) {
    if (!KINDS.has(row.kind)) continue;
    const score = Number(row.score);
    const n = Number(row.n);
    if (!Number.isFinite(score) || !Number.isFinite(n)) continue;
    (out[row.kind as ScoreKind] ??= []).push({ score, n });
  }
  return out;
}

/** This week's claim / ticker / relationship score histograms. Empty on failure
 *  — the page then shows rails without percentile captions, never a wrong one. */
export async function getScoreDistribution(days = 7): Promise<ScoreDistribution> {
  try {
    return await loadDistribution(days);
  } catch (err) {
    console.warn("[score-distribution]", err);
    return {};
  }
}
