"use server";

import { createServiceClient } from "@/lib/supabase/service";

/**
 * Reads for the public research lab.
 *
 * Every query goes through a `*_public_v` view, which filters to
 * `published = true`. Draft research — which is most of it, and by design —
 * cannot reach these functions, so a rendering mistake cannot leak a
 * half-finished campaign onto the site.
 */

export type ResearchNote = {
  slug: string;
  title: string;
  summary: string | null;
  body_md: string;
  result_kind: string;
  tags: string[] | null;
  created_at: string;
  updated_at: string;
};

export type ResearchChart = {
  slug: string;
  title: string;
  caption: string;
  kind: string;
  sample_window: string;
  public_url: string;
  width: number | null;
  height: number | null;
  campaign_run_id: string | null;
  genome_hash: string | null;
  note_slug: string | null;
  trials_considered: number | null;
  sort_order: number;
  /** Pre-computed in the view so a template cannot forget to check it. */
  is_in_sample: boolean;
};

export type LeaderboardRow = {
  genome_hash: string;
  campaign_run_id: string;
  dev_sharpe: number | null;
  holdout_sharpe: number | null;
  trials_considered: number;
  deflated_sharpe: number;
  pbo: number | null;
  gate_passed: boolean;
  prefilter: string;
  dev_start: string;
  dev_end: string;
};

export async function listResearchNotes(): Promise<ResearchNote[]> {
  const sb = createServiceClient();
  const { data, error } = await sb
    .schema("swingtrader")
    .from("research_public_v")
    .select("*")
    .order("updated_at", { ascending: false });
  if (error) {
    console.error("listResearchNotes", error.message);
    return [];
  }
  return (data ?? []) as ResearchNote[];
}

export async function getResearchNote(slug: string): Promise<ResearchNote | null> {
  const sb = createServiceClient();
  const { data, error } = await sb
    .schema("swingtrader")
    .from("research_public_v")
    .select("*")
    .eq("slug", slug)
    .maybeSingle();
  if (error) {
    console.error("getResearchNote", error.message);
    return null;
  }
  return (data as ResearchNote) ?? null;
}

export async function listChartsForNote(slug: string): Promise<ResearchChart[]> {
  const sb = createServiceClient();
  const { data, error } = await sb
    .schema("swingtrader")
    .from("research_charts_public_v")
    .select("*")
    .eq("note_slug", slug)
    .order("sort_order", { ascending: true });
  if (error) {
    console.error("listChartsForNote", error.message);
    return [];
  }
  return (data ?? []) as ResearchChart[];
}

/**
 * Ordered by OUT-OF-SAMPLE Sharpe in the view. Ranking by the in-sample number
 * would put the most overfitted strategy on top, which is the opposite of what
 * this page is for.
 */
export async function listLeaderboard(limit = 25): Promise<LeaderboardRow[]> {
  const sb = createServiceClient();
  const { data, error } = await sb
    .schema("swingtrader")
    .from("research_leaderboard_v")
    .select("*")
    .limit(limit);
  if (error) {
    console.error("listLeaderboard", error.message);
    return [];
  }
  return (data ?? []) as LeaderboardRow[];
}

export type ResearchStats = {
  notes: number;
  figures: number;
  strategies: number;
  /** Total configurations searched across every published campaign. */
  configurations: number;
};

/**
 * Headline counts for the lab. Reads the same public views as everything else,
 * so a draft campaign cannot inflate the numbers on the front page.
 */
export async function getResearchStats(): Promise<ResearchStats> {
  const sb = createServiceClient().schema("swingtrader");
  const [notes, figures, strategies] = await Promise.all([
    sb.from("research_public_v").select("slug", { count: "exact", head: true }),
    sb.from("research_charts_public_v").select("slug", { count: "exact", head: true }),
    sb.from("research_leaderboard_v").select("genome_hash", { count: "exact", head: true }),
  ]);

  // Configurations are summed over distinct published runs — summing the
  // per-strategy column would count one run's trial budget once per strategy.
  const { data: rows } = await sb
    .from("research_leaderboard_v")
    .select("campaign_run_id, trials_considered");
  const perRun = new Map<string, number>();
  for (const r of (rows ?? []) as { campaign_run_id: string; trials_considered: number }[]) {
    perRun.set(r.campaign_run_id, Math.max(perRun.get(r.campaign_run_id) ?? 0, r.trials_considered));
  }

  return {
    notes: notes.count ?? 0,
    figures: figures.count ?? 0,
    strategies: strategies.count ?? 0,
    configurations: [...perRun.values()].reduce((a, b) => a + b, 0),
  };
}

export type ResearchArtifact = {
  note_slug: string;
  name: string;
  description: string;
  available: boolean;
  reason: string | null;
  public_url: string | null;
  bytes: number | null;
  sha256: string | null;
  sort_order: number;
};

/**
 * The files a write-up cites. Unavailable ones are returned too — a replicator
 * needs to know that the price panel is vendor-licensed before they start, not
 * after they go looking for a download that was never coming.
 */
export async function listArtifactsForNote(slug: string): Promise<ResearchArtifact[]> {
  const sb = createServiceClient();
  const { data, error } = await sb
    .schema("swingtrader")
    .from("research_artifacts_public_v")
    .select("*")
    .eq("note_slug", slug)
    .order("sort_order", { ascending: true });
  if (error) {
    console.error("listArtifactsForNote", error.message);
    return [];
  }
  return (data ?? []) as ResearchArtifact[];
}
