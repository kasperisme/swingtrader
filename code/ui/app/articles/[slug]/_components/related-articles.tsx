import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { createClient as createSupabaseClient } from "@supabase/supabase-js";

import { createClient } from "@/lib/supabase/server";

type CandidateRow = {
  id: number;
  slug: string | null;
  title: string | null;
  publisher: string | null;
  image_url: string | null;
  published_at: string | null;
  created_at: string;
  search_tags: string[] | null;
};

export type RelatedArticle = {
  id: number;
  slug: string;
  title: string;
  publisher: string | null;
  image_url: string | null;
  published_at: string;
  overlap_count: number;
  shared_tags: string[];
};

// Tags shaped like a ticker symbol (1-6 uppercase letters). Topic tags are
// everything else — lowercase keywords like "drones", "ai", "rate_cuts".
const TICKER_TAG_RE = /^[A-Z]{1,6}$/;
// Weights so topical relevance dominates: an article sharing one topic
// (e.g. "drones") ranks above an article sharing three tickers by accident.
const TOPIC_TAG_WEIGHT = 3;
const TICKER_TAG_WEIGHT = 1;

function isTopicTag(tag: string): boolean {
  return !TICKER_TAG_RE.test(tag);
}

function scoreShared(shared: string[]): number {
  let score = 0;
  for (const t of shared) {
    score += isTopicTag(t) ? TOPIC_TAG_WEIGHT : TICKER_TAG_WEIGHT;
  }
  return score;
}

// ── Data ───────────────────────────────────────────────────────────────────

async function createServerDataClient() {
  // Service-role first so the related list renders for anonymous visitors too
  // (RLS blocks anon reads on swingtrader.news_articles). Falls back to
  // user-scoped client when the env doesn't have a service secret configured.
  const secretKey = process.env.SUPABASE_SECRET_KEY;
  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
  if (secretKey && supabaseUrl) {
    return createSupabaseClient(supabaseUrl, secretKey, {
      auth: { persistSession: false, autoRefreshToken: false },
    });
  }
  return createClient();
}

/**
 * Fetch candidates that share at least one search_tag with the current
 * article, score by overlap count + recency, return top N.
 *
 * Why tag overlap over impact-vector cosine: the `search_tags` array carries
 * the same human-meaningful labels that drive the topic-cluster discovery on
 * the article tag chips, so the recommendations feel consistent with what
 * the reader can already see on the page. GIN index on search_tags makes
 * `&&` (overlap) cheap. Vector cosine would be more semantically rich but
 * requires a precomputed embedding column we don't have yet.
 */
export async function fetchRelatedArticles({
  articleId,
  tags,
  limit = 6,
  windowDays = 30,
}: {
  articleId: number;
  tags: string[];
  limit?: number;
  windowDays?: number;
}): Promise<RelatedArticle[]> {
  if (!tags || tags.length === 0) return [];

  const supabase = await createServerDataClient();
  const sinceIso = new Date(
    Date.now() - windowDays * 24 * 60 * 60 * 1000,
  ).toISOString();

  // Over-fetch (limit * 5) so we have headroom to re-score by overlap count.
  // The DB sort is by published_at only — final ranking happens in JS.
  const { data, error } = await supabase
    .schema("swingtrader")
    .from("news_articles")
    .select(
      "id, slug, title, publisher, image_url, published_at, created_at, search_tags",
    )
    .neq("id", articleId)
    .eq("processing_status", "complete")
    .overlaps("search_tags", tags)
    .gte("published_at", sinceIso)
    .not("slug", "is", null)
    .not("title", "is", null)
    .order("published_at", { ascending: false })
    .limit(limit * 5);

  if (error || !data) return [];

  const tagSet = new Set(tags);
  const subjectHasTopics = tags.some(isTopicTag);
  const scored: Array<RelatedArticle & { _score: number }> = [];
  for (const row of data as CandidateRow[]) {
    if (!row.slug || !row.title) continue;
    const candidateTags = row.search_tags ?? [];
    const shared = candidateTags.filter((t) => tagSet.has(t));
    if (shared.length === 0) continue;

    // Require ≥1 shared TOPIC tag when the subject has any topic tags. This
    // prevents the "Zacks broad-coverage" failure mode where two articles
    // share 13 ticker symbols by accident (every Zacks daily-roundup
    // mentions the same megacaps) but have nothing topical in common.
    const sharedTopics = shared.filter(isTopicTag);
    if (subjectHasTopics && sharedTopics.length === 0) continue;

    // Sort shared tags: topic tags first (more meaningful for the chip row).
    shared.sort((a, b) => {
      const aTopic = isTopicTag(a);
      const bTopic = isTopicTag(b);
      if (aTopic !== bTopic) return aTopic ? -1 : 1;
      return a.localeCompare(b);
    });

    scored.push({
      id: row.id,
      slug: row.slug,
      title: row.title,
      publisher: row.publisher,
      image_url: row.image_url,
      published_at: row.published_at ?? row.created_at,
      overlap_count: shared.length,
      shared_tags: shared,
      _score: scoreShared(shared),
    });
  }

  // Final sort: weighted score descending (topic tags count 3×), then recency.
  scored.sort((a, b) => {
    if (b._score !== a._score) return b._score - a._score;
    return (
      new Date(b.published_at).getTime() - new Date(a.published_at).getTime()
    );
  });

  // Strip the internal _score before returning.
  return scored.slice(0, limit).map(({ _score, ...rest }) => rest);
}

// ── Rendering ──────────────────────────────────────────────────────────────

function formatAgeSince(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const diffMs = Date.now() - d.getTime();
  if (diffMs < 0) return "just now";
  const hour = 3600_000;
  const day = 24 * hour;
  const week = 7 * day;
  if (diffMs < hour) return `${Math.max(1, Math.floor(diffMs / 60_000))}m ago`;
  if (diffMs < day) return `${Math.floor(diffMs / hour)}h ago`;
  if (diffMs < week) return `${Math.floor(diffMs / day)}d ago`;
  return `${Math.floor(diffMs / week)}w ago`;
}

function formatTagLabel(tag: string): string {
  if (/^[A-Z]{1,6}$/.test(tag)) return tag;
  return tag.replace(/_/g, " ");
}

type Props = {
  /**
   * Absolute base URL used for the JSON-LD ItemList entries. Crawlers prefer
   * fully-qualified URLs in structured data. Falls back to a relative path if
   * unset (still valid for the visible <a> tags).
   */
  baseUrl?: string;
  related: RelatedArticle[];
};

/**
 * Visible "Continue reading" section + a JSON-LD ItemList for crawler
 * consumption. Both are server-rendered so Google reads the relationship
 * graph at first paint without depending on client-side hydration.
 */
export function RelatedArticles({ related, baseUrl }: Props) {
  if (related.length === 0) return null;

  const absUrl = (slug: string) =>
    baseUrl ? `${baseUrl.replace(/\/$/, "")}/articles/${slug}` : `/articles/${slug}`;

  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "ItemList",
    name: "Related articles",
    itemListElement: related.map((r, idx) => ({
      "@type": "ListItem",
      position: idx + 1,
      url: absUrl(r.slug),
      name: r.title,
    })),
  };

  return (
    <section
      aria-labelledby="related-articles-heading"
      className="mt-16 border-t border-border/60 pt-10"
    >
      <div className="mb-6 flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <p className="inline-flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.2em] text-amber-500/80">
          <span className="h-px w-6 bg-amber-500/60" />
          Continue reading
        </p>
        <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
          {related.length} related stor{related.length === 1 ? "y" : "ies"}
        </p>
      </div>

      <h2
        id="related-articles-heading"
        className="mb-6 text-base font-semibold tracking-tight text-foreground/90"
      >
        Next reads from the same story arc
      </h2>

      <ul className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
        {related.map((r) => (
          <li key={r.id}>
            <Link
              href={`/articles/${r.slug}`}
              className="group flex h-full flex-col overflow-hidden rounded-xl border border-border/60 bg-card/30 transition-colors hover:border-amber-500/40 hover:bg-card/60"
            >
              {r.image_url ? (
                <div className="relative aspect-[16/9] w-full overflow-hidden bg-muted">
                  <img
                    src={r.image_url}
                    alt=""
                    loading="lazy"
                    className="h-full w-full object-cover transition-transform duration-200 group-hover:scale-[1.02]"
                  />
                </div>
              ) : null}
              <div className="flex flex-1 flex-col gap-2 p-4">
                <div className="flex items-baseline justify-between gap-2">
                  <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
                    {r.publisher || "Feed"}
                  </p>
                  <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
                    {formatAgeSince(r.published_at)}
                  </p>
                </div>
                <h3 className="line-clamp-3 text-sm font-semibold leading-snug text-foreground/95 transition-colors group-hover:text-amber-400">
                  {r.title}
                </h3>
                {r.shared_tags.length > 0 ? (
                  <ul className="mt-auto flex flex-wrap gap-1.5 pt-2">
                    {r.shared_tags.slice(0, 3).map((tag) => (
                      <li
                        key={tag}
                        className="inline-flex items-center rounded-sm border border-border/50 bg-muted/30 px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground"
                      >
                        {formatTagLabel(tag)}
                      </li>
                    ))}
                  </ul>
                ) : null}
                <span className="mt-1 inline-flex items-center gap-1 font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground transition-colors group-hover:text-amber-400">
                  Read
                  <ArrowUpRight
                    size={11}
                    className="transition-transform duration-200 group-hover:-translate-y-px group-hover:translate-x-px"
                  />
                </span>
              </div>
            </Link>
          </li>
        ))}
      </ul>

      {/*
        JSON-LD ItemList — read by Google/Bing crawlers. Renders in the HTML
        source even before hydration, so the related-graph signal is captured
        regardless of JS execution.
      */}
      <script
        type="application/ld+json"
        // eslint-disable-next-line react/no-danger
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />
    </section>
  );
}
