import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { Lock } from "lucide-react";

import { createClient } from "@/lib/supabase/server";
import { CLUSTERS, DIMENSION_MAP } from "@/app/protected/vectors/dimensions";

function clusterDocSlug(clusterId: string): string {
  return "/docs/cluster-" + clusterId.toLowerCase().replace(/_/g, "-");
}

type ArticleRow = {
  id: number;
  title: string | null;
  url: string | null;
  source: string | null;
  created_at: string;
  image_url: string | null;
};

type CompanyVectorRow = {
  ticker: string;
  vector_date: string;
  dimensions_json: unknown;
  metadata_json: unknown;
};

type RankedStock = {
  ticker: string;
  score: number;
  sector: string;
};

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
    if (Number.isFinite(n)) out[k] = n;
  }
  return out;
}

function asObject(v: unknown): Record<string, unknown> {
  if (!v) return {};
  if (typeof v === "string") {
    try {
      return asObject(JSON.parse(v));
    } catch {
      return {};
    }
  }
  if (typeof v !== "object") return {};
  return v as Record<string, unknown>;
}

function formatUTC(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "Unknown";
  return new Intl.DateTimeFormat("en-GB", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "UTC",
  }).format(d);
}

async function fetchLatestCompanyVectors(): Promise<CompanyVectorRow[]> {
  const supabase = await createClient();
  const { data, error } = await supabase
    .schema("swingtrader")
    .from("company_vectors")
    .select("ticker, vector_date, dimensions_json, metadata_json")
    .order("ticker", { ascending: true })
    .order("vector_date", { ascending: false });

  if (error || !data) return [];

  const seen = new Set<string>();
  const rows: CompanyVectorRow[] = [];
  for (const row of data as CompanyVectorRow[]) {
    if (seen.has(row.ticker)) continue;
    seen.add(row.ticker);
    rows.push(row);
  }
  return rows;
}

function rankImpactedStocks(
  impact: Record<string, number>,
  vectors: CompanyVectorRow[],
): { winners: RankedStock[]; losers: RankedStock[] } {
  const ranked: RankedStock[] = [];

  for (const row of vectors) {
    const dims = asNumberMap(row.dimensions_json);
    let total = 0;
    let used = 0;

    for (const [key, impactScore] of Object.entries(impact)) {
      const sensitivity = dims[key];
      if (!Number.isFinite(sensitivity) || !Number.isFinite(impactScore)) continue;
      total += sensitivity * impactScore;
      used += 1;
    }

    if (used === 0) continue;
    const metadata = asObject(row.metadata_json);
    ranked.push({
      ticker: row.ticker,
      score: total / used,
      sector: String(metadata.sector ?? ""),
    });
  }

  ranked.sort((a, b) => b.score - a.score);
  const winners = ranked.filter((r) => r.score > 0).slice(0, 10);
  const losers = ranked
    .filter((r) => r.score < 0)
    .slice()
    .sort((a, b) => a.score - b.score)
    .slice(0, 10);
  return { winners, losers };
}

function computeClusterProfile(impact: Record<string, number>): Array<{ id: string; label: string; score: number; docSlug: string }> {
  return CLUSTERS.map((cluster) => {
    const vals = cluster.dimensions
      .map((d) => impact[d.key])
      .filter((v): v is number => Number.isFinite(v));
    const score = vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : 0;
    return { id: cluster.id, label: cluster.label, score, docSlug: clusterDocSlug(cluster.id) };
  }).sort((a, b) => Math.abs(b.score) - Math.abs(a.score));
}

function scoreClass(v: number): string {
  if (v > 0.03) return "text-emerald-600";
  if (v < -0.03) return "text-rose-600";
  return "text-muted-foreground";
}

async function ArticleData({ id }: { id: number }) {
  const supabase = await createClient();

  const [{ data: article, error: articleError }, { data: vectorRow }, { data: claims }] =
    await Promise.all([
      supabase
        .schema("swingtrader")
        .from("news_articles")
        .select("id, title, url, source, created_at, image_url")
        .eq("id", id)
        .single<ArticleRow>(),
      supabase
        .schema("swingtrader")
        .from("news_impact_vectors")
        .select("impact_json")
        .eq("article_id", id)
        .single<{ impact_json: unknown }>(),
      supabase.auth.getClaims(),
    ]);

  if (articleError || !article) notFound();
  const isAuthed = Boolean(claims?.claims);

  const impact = asNumberMap(vectorRow?.impact_json ?? {});
  const topDimensions = Object.entries(impact)
    .map(([key, score]) => ({ key, score }))
    .sort((a, b) => Math.abs(b.score) - Math.abs(a.score))
    .slice(0, 12);
  const clusterProfile = computeClusterProfile(impact);

  let winners: RankedStock[] = [];
  let losers: RankedStock[] = [];
  if (Object.keys(impact).length > 0) {
    const vectors = await fetchLatestCompanyVectors();
    const ranked = rankImpactedStocks(impact, vectors);
    winners = ranked.winners;
    losers = ranked.losers;
  }

  const topCluster = clusterProfile[0] ?? null;
  const topDimension = topDimensions[0] ?? null;
  const strongestWinner = winners[0] ?? null;
  const strongestLoser = losers[0] ?? null;
  const topStock =
    strongestWinner && strongestLoser
      ? Math.abs(strongestWinner.score) >= Math.abs(strongestLoser.score)
        ? strongestWinner
        : strongestLoser
      : strongestWinner ?? strongestLoser;

  return (
    <div className="mx-auto max-w-5xl px-6 py-10">
      <div className="mb-6">
        <Link href="/" className="text-sm text-muted-foreground hover:text-foreground">
          ← Back to home
        </Link>
      </div>

      <article className="rounded-xl border bg-card p-6">
        <p className="text-xs uppercase tracking-wide text-muted-foreground">
          {article.source || "Unknown source"} · scanned {formatUTC(article.created_at)} UTC
        </p>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight">
          {article.title || "Untitled article"}
        </h1>

        {article.image_url ? (
          <div className="mt-4 overflow-hidden rounded-lg border">
            <img src={article.image_url} alt="" className="h-56 w-full object-cover" />
          </div>
        ) : null}

        <div className="mt-4">
          {article.url ? (
            <Link
              href={article.url}
              target="_blank"
              rel="noreferrer"
              className="text-sm font-medium text-foreground underline-offset-4 hover:underline"
            >
              Read original article →
            </Link>
          ) : (
            <p className="text-sm text-muted-foreground">Original article URL not available.</p>
          )}
        </div>
      </article>

      {!isAuthed ? (
        <section className="mt-8 grid gap-4 md:grid-cols-3">
          <div className="rounded-xl border bg-card p-5">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">Most impacted cluster</p>
            {topCluster ? (
              <div className="mt-2">
                <p className="text-sm font-semibold">{topCluster.label}</p>
                <p className={`mt-1 font-mono text-sm ${scoreClass(topCluster.score)}`}>
                  {topCluster.score >= 0 ? "+" : ""}
                  {topCluster.score.toFixed(3)}
                </p>
              </div>
            ) : (
              <p className="mt-2 text-sm text-muted-foreground">No cluster signal yet.</p>
            )}
          </div>
          <div className="rounded-xl border bg-card p-5">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">Most impacted dimension</p>
            {topDimension ? (
              <div className="mt-2">
                <p className="text-sm font-semibold break-words">{topDimension.key}</p>
                <p className={`mt-1 font-mono text-sm ${scoreClass(topDimension.score)}`}>
                  {topDimension.score >= 0 ? "+" : ""}
                  {topDimension.score.toFixed(3)}
                </p>
              </div>
            ) : (
              <p className="mt-2 text-sm text-muted-foreground">No dimension signal yet.</p>
            )}
          </div>
          <div className="rounded-xl border bg-card p-5">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">Most impacted stock</p>
            {topStock ? (
              <div className="mt-2">
                <p className="text-sm font-semibold">
                  {topStock.ticker}
                  {topStock.sector ? <span className="text-muted-foreground"> · {topStock.sector}</span> : null}
                </p>
                <p className={`mt-1 font-mono text-sm ${scoreClass(topStock.score)}`}>
                  {topStock.score >= 0 ? "+" : ""}
                  {topStock.score.toFixed(3)}
                </p>
              </div>
            ) : (
              <p className="mt-2 text-sm text-muted-foreground">No stock impact ranking yet.</p>
            )}
          </div>
        </section>
      ) : null}

      <div className="relative mt-8">
        {!isAuthed ? (
          <div className="pointer-events-none blur-[2.5px] opacity-70">
            <section className="grid gap-6 lg:grid-cols-2">
              <div className="rounded-xl border bg-card p-5">
                <div className="flex items-center justify-between gap-2">
                  <h2 className="text-lg font-semibold">Analytical profile by cluster</h2>
                  <Link href="/docs/cluster-macro-sensitivity" className="text-xs text-muted-foreground hover:text-foreground">
                    What is this? →
                  </Link>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  Average impact score across dimensions in each cluster.
                </p>
                <div className="mt-4 space-y-2">
                  {clusterProfile.map((c) => (
                    <div key={c.id} className="flex items-center justify-between text-sm">
                      <Link href={c.docSlug} className="text-foreground hover:underline underline-offset-4">
                        {c.label}
                      </Link>
                      <span className={`font-mono ${scoreClass(c.score)}`}>
                        {c.score >= 0 ? "+" : ""}
                        {c.score.toFixed(3)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="rounded-xl border bg-card p-5">
                <div className="flex items-center justify-between gap-2">
                  <h2 className="text-lg font-semibold">Top impact dimensions</h2>
                  <Link href="/docs/news-impact-scores" className="text-xs text-muted-foreground hover:text-foreground">
                    What is this? →
                  </Link>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  Strongest dimension signals extracted from this article.
                </p>
                <div className="mt-4 space-y-2">
                  {topDimensions.length === 0 ? (
                    <p className="text-sm text-muted-foreground">No impact vector found for this article yet.</p>
                  ) : (
                    topDimensions.map((d) => {
                      const dim = DIMENSION_MAP[d.key];
                      const label = dim?.label ?? d.key;
                      const clusterKey = CLUSTERS.find((c) => c.dimensions.some((x) => x.key === d.key))?.id;
                      const href = clusterKey ? clusterDocSlug(clusterKey) : "/docs/news-impact-scores";
                      return (
                        <div key={d.key} className="flex items-center justify-between text-sm">
                          <Link href={href} className="truncate pr-2 hover:underline underline-offset-4" title={d.key}>
                            {label}
                          </Link>
                          <span className={`font-mono shrink-0 ${scoreClass(d.score)}`}>
                            {d.score >= 0 ? "+" : ""}
                            {d.score.toFixed(3)}
                          </span>
                        </div>
                      );
                    })
                  )}
                </div>
              </div>
            </section>

            <section className="mt-6 grid gap-6 lg:grid-cols-2">
              <div className="rounded-xl border bg-card p-5">
                <h2 className="text-lg font-semibold">Most positively impacted stocks</h2>
                <p className="mt-1 text-xs text-muted-foreground">
                  Estimated via dot product of article impact vector and latest company vectors.
                </p>
                <div className="mt-4 space-y-2">
                  {winners.length === 0 ? (
                    <p className="text-sm text-muted-foreground">No stock impact ranking available yet.</p>
                  ) : (
                    winners.map((s) => (
                      <div key={s.ticker} className="flex items-center justify-between text-sm">
                        <span>
                          <span className="font-medium">{s.ticker}</span>
                          {s.sector ? <span className="text-muted-foreground"> · {s.sector}</span> : null}
                        </span>
                        <span className="font-mono text-emerald-600">+{s.score.toFixed(3)}</span>
                      </div>
                    ))
                  )}
                </div>
              </div>

              <div className="rounded-xl border bg-card p-5">
                <h2 className="text-lg font-semibold">Most negatively impacted stocks</h2>
                <p className="mt-1 text-xs text-muted-foreground">
                  Names with the strongest estimated headwind from this article.
                </p>
                <div className="mt-4 space-y-2">
                  {losers.length === 0 ? (
                    <p className="text-sm text-muted-foreground">No stock impact ranking available yet.</p>
                  ) : (
                    losers.map((s) => (
                      <div key={s.ticker} className="flex items-center justify-between text-sm">
                        <span>
                          <span className="font-medium">{s.ticker}</span>
                          {s.sector ? <span className="text-muted-foreground"> · {s.sector}</span> : null}
                        </span>
                        <span className="font-mono text-rose-600">{s.score.toFixed(3)}</span>
                      </div>
                    ))
                  )}
                </div>
              </div>
            </section>
          </div>
        ) : (
          <>
            <section className="grid gap-6 lg:grid-cols-2">
              <div className="rounded-xl border bg-card p-5">
                <div className="flex items-center justify-between gap-2">
                  <h2 className="text-lg font-semibold">Analytical profile by cluster</h2>
                  <Link href="/docs/cluster-macro-sensitivity" className="text-xs text-muted-foreground hover:text-foreground">
                    What is this? →
                  </Link>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  Average impact score across dimensions in each cluster.
                </p>
                <div className="mt-4 space-y-2">
                  {clusterProfile.map((c) => (
                    <div key={c.id} className="flex items-center justify-between text-sm">
                      <Link href={c.docSlug} className="text-foreground hover:underline underline-offset-4">
                        {c.label}
                      </Link>
                      <span className={`font-mono ${scoreClass(c.score)}`}>
                        {c.score >= 0 ? "+" : ""}
                        {c.score.toFixed(3)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="rounded-xl border bg-card p-5">
                <div className="flex items-center justify-between gap-2">
                  <h2 className="text-lg font-semibold">Top impact dimensions</h2>
                  <Link href="/docs/news-impact-scores" className="text-xs text-muted-foreground hover:text-foreground">
                    What is this? →
                  </Link>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  Strongest dimension signals extracted from this article.
                </p>
                <div className="mt-4 space-y-2">
                  {topDimensions.length === 0 ? (
                    <p className="text-sm text-muted-foreground">No impact vector found for this article yet.</p>
                  ) : (
                    topDimensions.map((d) => {
                      const dim = DIMENSION_MAP[d.key];
                      const label = dim?.label ?? d.key;
                      const clusterKey = CLUSTERS.find((c) => c.dimensions.some((x) => x.key === d.key))?.id;
                      const href = clusterKey ? clusterDocSlug(clusterKey) : "/docs/news-impact-scores";
                      return (
                        <div key={d.key} className="flex items-center justify-between text-sm">
                          <Link href={href} className="truncate pr-2 hover:underline underline-offset-4" title={d.key}>
                            {label}
                          </Link>
                          <span className={`font-mono shrink-0 ${scoreClass(d.score)}`}>
                            {d.score >= 0 ? "+" : ""}
                            {d.score.toFixed(3)}
                          </span>
                        </div>
                      );
                    })
                  )}
                </div>
              </div>
            </section>

            <section className="mt-6 grid gap-6 lg:grid-cols-2">
              <div className="rounded-xl border bg-card p-5">
                <h2 className="text-lg font-semibold">Most positively impacted stocks</h2>
                <p className="mt-1 text-xs text-muted-foreground">
                  Estimated via dot product of article impact vector and latest company vectors.
                </p>
                <div className="mt-4 space-y-2">
                  {winners.length === 0 ? (
                    <p className="text-sm text-muted-foreground">No stock impact ranking available yet.</p>
                  ) : (
                    winners.map((s) => (
                      <div key={s.ticker} className="flex items-center justify-between text-sm">
                        <span>
                          <span className="font-medium">{s.ticker}</span>
                          {s.sector ? <span className="text-muted-foreground"> · {s.sector}</span> : null}
                        </span>
                        <span className="font-mono text-emerald-600">+{s.score.toFixed(3)}</span>
                      </div>
                    ))
                  )}
                </div>
              </div>

              <div className="rounded-xl border bg-card p-5">
                <h2 className="text-lg font-semibold">Most negatively impacted stocks</h2>
                <p className="mt-1 text-xs text-muted-foreground">
                  Names with the strongest estimated headwind from this article.
                </p>
                <div className="mt-4 space-y-2">
                  {losers.length === 0 ? (
                    <p className="text-sm text-muted-foreground">No stock impact ranking available yet.</p>
                  ) : (
                    losers.map((s) => (
                      <div key={s.ticker} className="flex items-center justify-between text-sm">
                        <span>
                          <span className="font-medium">{s.ticker}</span>
                          {s.sector ? <span className="text-muted-foreground"> · {s.sector}</span> : null}
                        </span>
                        <span className="font-mono text-rose-600">{s.score.toFixed(3)}</span>
                      </div>
                    ))
                  )}
                </div>
              </div>
            </section>
          </>
        )}

        {!isAuthed ? (
          <div className="absolute inset-0 flex items-center justify-center">
            <Link
              href={`/auth/login?next=/articles/${id}`}
              className="inline-flex items-center gap-2 rounded-md border border-border bg-background/95 px-4 py-2 text-sm font-medium text-foreground shadow-sm transition-colors hover:bg-background"
            >
              <Lock size={15} />
              Unlock full overview
            </Link>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function ArticlePageFallback() {
  return (
    <div className="mx-auto max-w-5xl px-6 py-10">
      <div className="rounded-xl border bg-card p-6 text-sm text-muted-foreground animate-pulse">
        Loading article analytics...
      </div>
    </div>
  );
}

export default async function ArticlePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const articleId = Number(id);
  if (!Number.isFinite(articleId) || articleId <= 0) notFound();

  return (
    <Suspense fallback={<ArticlePageFallback />}>
      <ArticleData id={articleId} />
    </Suspense>
  );
}
