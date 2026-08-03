"use server";

import { createServiceClient } from "@/lib/supabase/service";

/**
 * Topic hubs — permanent, auto-updating deep-dive pages over the article corpus.
 *
 * A topic is a saved query (theme_tags AND lens_tickers), so a newly-scored
 * article joins the moment it matches — there is no generation step to run and
 * nothing to keep in sync. Two speeds:
 *   · the FEED  (topic_article_v)      — live, ~30ms
 *   · the ARC   (topic_claim_stats)    — materialized, refreshed after each ingest
 * The arc can't be live: it scans a topic's whole history, and the REST role caps
 * statements at 8s.
 */

const SCHEMA = "swingtrader";

export type Topic = {
  slug: string;
  title: string;
  subtitle: string | null;
  theme_tags: string[];
  lens_tickers: string[];
  visual_archetype: string;
  scene: string | null;
  accent: string;
  hero_tickers: string[] | null;
  seo_description: string | null;
};

export type TopicClaim = {
  claim: string;
  impact: number;
  article_ts: string;
  article_title: string | null;
  article_slug: string | null;
  tickers: string[] | null;
};

export type TopicArticle = {
  article_id: number;
  title: string;
  article_slug: string | null;
  published_at: string;
  matched_tickers: string[] | null;
};

export type TopicStats = {
  articleCount: number;
  claimCount: number;
  firstSeen: string | null;
  lastSeen: string | null;
};

const TOPIC_COLS =
  "slug,title,subtitle,theme_tags,lens_tickers,visual_archetype,scene,accent,hero_tickers,seo_description";

export async function listTopics(): Promise<Topic[]> {
  const sb = createServiceClient();
  const { data, error } = await sb
    .schema(SCHEMA)
    .from("topics")
    .select(TOPIC_COLS)
    .eq("is_published", true)
    .order("slug");
  if (error) throw error;
  return (data ?? []) as Topic[];
}

export async function getTopicBySlug(slug: string): Promise<Topic | null> {
  const sb = createServiceClient();
  const { data, error } = await sb
    .schema(SCHEMA)
    .from("topics")
    .select(TOPIC_COLS)
    .eq("slug", slug)
    .eq("is_published", true)
    .maybeSingle();
  if (error) throw error;
  return (data as Topic) ?? null;
}

/**
 * Near-duplicate claims are the norm, not the exception: the same development is
 * written up by a dozen outlets in slightly different words, and a wire story
 * resurfaces for days. Collapse on a content-word fingerprint so the page shows a
 * development once — the same approach `fetch_week_notes.py` uses for the reels.
 */
function dedupeClaims(rows: TopicClaim[], limit: number): TopicClaim[] {
  const STOP = new Set([
    "the", "a", "an", "of", "to", "in", "for", "and", "is", "are", "has", "have",
    "with", "at", "on", "its", "by", "from", "as", "that", "this", "will", "be",
  ]);
  const fingerprint = (claim: string) =>
    new Set(
      claim
        .toLowerCase()
        .split(/\s+/)
        .map((w) => w.replace(/[.,%$()"']/g, ""))
        .filter((w) => w.length > 2 && !STOP.has(w)),
    );

  const kept: { fp: Set<string>; row: TopicClaim }[] = [];
  for (const row of rows) {
    const fp = fingerprint(row.claim);
    if (fp.size === 0) continue;
    const dup = kept.some(({ fp: seen }) => {
      let overlap = 0;
      for (const w of fp) if (seen.has(w)) overlap += 1;
      return overlap / Math.max(1, Math.min(fp.size, seen.size)) > 0.6;
    });
    if (dup) continue;
    kept.push({ fp, row });
    if (kept.length >= limit) break;
  }
  return kept.map((k) => k.row);
}

const CLAIM_COLS = "claim,impact,article_ts,article_title,article_slug,tickers";

/**
 * The defining claims of the whole arc — ranked by |impact|.
 *
 * Over-fetched then deduped in code rather than DISTINCT-ing in SQL, because
 * near-duplicates differ by wording, not by value.
 */
export async function getTopicKeyClaims(slug: string, limit = 12): Promise<TopicClaim[]> {
  const sb = createServiceClient();
  const { data, error } = await sb
    .schema(SCHEMA)
    .from("topic_claim_stats")
    .select(CLAIM_COLS)
    .eq("topic_slug", slug)
    .order("impact", { ascending: false })
    .limit(limit * 12);
  if (error) throw error;
  const rows = (data ?? []) as TopicClaim[];
  rows.sort((a, b) => Math.abs(b.impact) - Math.abs(a.impact));
  return dedupeClaims(rows, limit);
}

/**
 * What the story has done LATELY.
 *
 * Deliberately separate from the key claims and always rendered with its date: a
 * permanent page that aggregates scored claims will otherwise present a prior
 * quarter's numbers as current. That failure is not hypothetical — NVIDIA's
 * "$119B supply commitments" and Micron's "+346% revenue" both resurfaced in this
 * corpus as though they were this week's news.
 */
export async function getTopicRecentClaims(slug: string, limit = 10): Promise<TopicClaim[]> {
  const sb = createServiceClient();
  const { data, error } = await sb
    .schema(SCHEMA)
    .from("topic_claim_stats")
    .select(CLAIM_COLS)
    .eq("topic_slug", slug)
    .order("article_ts", { ascending: false })
    .limit(limit * 12);
  if (error) throw error;
  return dedupeClaims((data ?? []) as TopicClaim[], limit);
}

/** The live edge — newest matching articles, straight off the membership view. */
export async function getTopicFeed(slug: string, limit = 24): Promise<TopicArticle[]> {
  const sb = createServiceClient();
  const { data, error } = await sb
    .schema(SCHEMA)
    .from("topic_article_v")
    .select("article_id,title,article_slug,published_at,matched_tickers")
    .eq("topic_slug", slug)
    .order("published_at", { ascending: false })
    .limit(limit);
  if (error) throw error;
  return (data ?? []) as TopicArticle[];
}

/**
 * The reverse lookup: which topics does this article belong to?
 *
 * This is the other half of the hub-and-spoke structure. The hub already links
 * down to its articles; without articles linking back up, a crawler sees a pile
 * of unrelated pages instead of a cluster, and none of the authority sitting in
 * ~5k article URLs reaches the hub that is actually meant to rank.
 *
 * Uses the same membership view, so an article appears here under exactly the
 * topics whose page would list it — the two directions cannot disagree.
 */
export async function getTopicsForArticle(articleId: number): Promise<Topic[]> {
  const sb = createServiceClient();
  const { data, error } = await sb
    .schema(SCHEMA)
    .from("topic_article_v")
    .select("topic_slug")
    .eq("article_id", articleId);
  if (error) throw error;

  const slugs = Array.from(new Set((data ?? []).map((r) => (r as { topic_slug: string }).topic_slug)));
  if (slugs.length === 0) return [];

  const { data: topics, error: tErr } = await sb
    .schema(SCHEMA)
    .from("topics")
    .select(TOPIC_COLS)
    .in("slug", slugs)
    .eq("is_published", true);
  if (tErr) throw tErr;
  return (topics ?? []) as Topic[];
}

export async function getTopicStats(slug: string): Promise<TopicStats> {
  const sb = createServiceClient();
  const [articles, claims, oldest, newest] = await Promise.all([
    sb.schema(SCHEMA).from("topic_article_v").select("article_id", { count: "exact", head: true })
      .eq("topic_slug", slug),
    sb.schema(SCHEMA).from("topic_claim_stats").select("article_id", { count: "exact", head: true })
      .eq("topic_slug", slug),
    sb.schema(SCHEMA).from("topic_claim_stats").select("article_ts")
      .eq("topic_slug", slug).order("article_ts", { ascending: true }).limit(1).maybeSingle(),
    sb.schema(SCHEMA).from("topic_claim_stats").select("article_ts")
      .eq("topic_slug", slug).order("article_ts", { ascending: false }).limit(1).maybeSingle(),
  ]);
  return {
    articleCount: articles.count ?? 0,
    claimCount: claims.count ?? 0,
    firstSeen: (oldest.data as { article_ts: string } | null)?.article_ts ?? null,
    lastSeen: (newest.data as { article_ts: string } | null)?.article_ts ?? null,
  };
}
