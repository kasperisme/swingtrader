import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { Lock } from "lucide-react";
import { createClient as createSupabaseClient } from "@supabase/supabase-js";

import { createClient } from "@/lib/supabase/server";
import { CLUSTERS, DIMENSION_MAP } from "@/app/protected/vectors/dimensions";

type ArticleRow = {
  id: number;
  slug: string | null;
  title: string | null;
  url: string | null;
  source: string | null;
  created_at: string;
  image_url: string | null;
};

type CompanyVectorRow = {
  ticker: string;
  dimensions_json: unknown;
  metadata_json: unknown;
};

type RankedStock = { ticker: string; score: number; sector: string };
type HeadRow = {
  cluster: string;
  scores_json: unknown;
  reasoning_json: unknown;
};

function clusterDocSlug(clusterId: string): string {
  return "/docs/cluster-" + clusterId.toLowerCase().replace(/_/g, "-");
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

function asStringMap(v: unknown): Record<string, string> {
  const obj = asObject(v);
  const out: Record<string, string> = {};
  for (const [k, raw] of Object.entries(obj)) {
    out[k] = String(raw ?? "");
  }
  return out;
}

async function createServerDataClient() {
  const secretKey = process.env.SUPABASE_SECRET_KEY;
  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
  if (secretKey && supabaseUrl) {
    return createSupabaseClient(supabaseUrl, secretKey, {
      auth: { persistSession: false, autoRefreshToken: false },
    });
  }
  return createClient();
}

function scoreClass(v: number): string {
  if (v > 0.03) return "text-emerald-600";
  if (v < -0.03) return "text-rose-600";
  return "text-muted-foreground";
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

function computeClusterProfile(impact: Record<string, number>) {
  return CLUSTERS.map((cluster) => {
    const vals = cluster.dimensions
      .map((d) => impact[d.key])
      .filter((v): v is number => Number.isFinite(v));
    const score = vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : 0;
    return { id: cluster.id, label: cluster.label, score, docSlug: clusterDocSlug(cluster.id) };
  }).sort((a, b) => Math.abs(b.score) - Math.abs(a.score));
}

async function fetchRankedStocks(impact: Record<string, number>) {
  if (Object.keys(impact).length === 0) return { winners: [] as RankedStock[], losers: [] as RankedStock[] };
  const supabase = await createClient();
  const { data, error } = await supabase
    .schema("swingtrader")
    .from("company_vectors")
    .select("ticker, dimensions_json, metadata_json")
    .order("ticker", { ascending: true })
    .order("vector_date", { ascending: false });
  if (error || !data) return { winners: [], losers: [] };

  const seen = new Set<string>();
  const rows: CompanyVectorRow[] = [];
  for (const row of data as CompanyVectorRow[]) {
    if (seen.has(row.ticker)) continue;
    seen.add(row.ticker);
    rows.push(row);
  }

  const ranked: RankedStock[] = [];
  for (const row of rows) {
    const dims = asNumberMap(row.dimensions_json);
    let total = 0;
    let used = 0;
    for (const [k, s] of Object.entries(impact)) {
      const d = dims[k];
      if (!Number.isFinite(d) || !Number.isFinite(s)) continue;
      total += d * s;
      used += 1;
    }
    if (!used) continue;
    const meta = asObject(row.metadata_json);
    ranked.push({ ticker: row.ticker, score: total / used, sector: String(meta.sector ?? "") });
  }
  ranked.sort((a, b) => b.score - a.score);
  return {
    winners: ranked.filter((r) => r.score > 0).slice(0, 10),
    losers: ranked.filter((r) => r.score < 0).sort((a, b) => a.score - b.score).slice(0, 10),
  };
}

function AnalyticsBlock({
  clusterProfile,
  topDimensions,
  winners,
  losers,
  tickerSentiment,
  tickerRelationships,
  locked,
  lockHref,
}: {
  clusterProfile: Array<{ id: string; label: string; score: number; docSlug: string }>;
  topDimensions: Array<{ key: string; score: number }>;
  winners: RankedStock[];
  losers: RankedStock[];
  tickerSentiment: Array<{ ticker: string; score: number; reason: string }>;
  tickerRelationships: Array<{ from: string; to: string; relType: string; score: number; reason: string }>;
  locked: boolean;
  lockHref: string;
}) {
  return (
    <>
      <section className="grid gap-4 lg:grid-cols-2">
        <div className="relative rounded-xl border bg-card p-5">
          <h2 className="text-lg font-semibold">Analytical profile by cluster</h2>
          <div className={locked ? "mt-4 space-y-2 blur-[2.5px] pointer-events-none select-none" : "mt-4 space-y-2"}>
            {clusterProfile.map((c) => (
              <div key={c.id} className="flex items-center justify-between text-sm">
                <Link href={c.docSlug} className="hover:underline underline-offset-4">{c.label}</Link>
                <span className={`font-mono ${scoreClass(c.score)}`}>{c.score >= 0 ? "+" : ""}{c.score.toFixed(3)}</span>
              </div>
            ))}
          </div>
          {locked ? (
            <Link href={lockHref} className="absolute inset-0 flex items-center justify-center">
              <span className="inline-flex items-center gap-2 rounded-md border border-border bg-background/95 px-3 py-1.5 text-xs font-medium text-foreground shadow-sm">
                <Lock size={14} />
                Sign up to unlock
              </span>
            </Link>
          ) : null}
        </div>
        <div className="relative rounded-xl border bg-card p-5">
          <h2 className="text-lg font-semibold">Top impact dimensions</h2>
          <div className={locked ? "mt-4 space-y-2 blur-[2.5px] pointer-events-none select-none" : "mt-4 space-y-2"}>
            {topDimensions.length === 0 ? (
              <p className="text-sm text-muted-foreground">No impact vector found for this article yet.</p>
            ) : topDimensions.map((d) => {
              const dim = DIMENSION_MAP[d.key];
              const clusterKey = CLUSTERS.find((c) => c.dimensions.some((x) => x.key === d.key))?.id;
              const href = clusterKey ? clusterDocSlug(clusterKey) : "/docs/news-impact-scores";
              return (
                <div key={d.key} className="flex items-center justify-between text-sm">
                  <Link href={href} className="truncate pr-2 hover:underline underline-offset-4">{dim?.label ?? d.key}</Link>
                  <span className={`font-mono shrink-0 ${scoreClass(d.score)}`}>{d.score >= 0 ? "+" : ""}{d.score.toFixed(3)}</span>
                </div>
              );
            })}
          </div>
          {locked ? (
            <Link href={lockHref} className="absolute inset-0 flex items-center justify-center">
              <span className="inline-flex items-center gap-2 rounded-md border border-border bg-background/95 px-3 py-1.5 text-xs font-medium text-foreground shadow-sm">
                <Lock size={14} />
                Sign up to unlock
              </span>
            </Link>
          ) : null}
        </div>
      </section>
      <section className="mt-4 grid gap-4 lg:grid-cols-2">
        <div className="relative rounded-xl border bg-card p-5">
          <h2 className="text-lg font-semibold">Most positively impacted stocks</h2>
          <div className={locked ? "mt-4 space-y-2 blur-[2.5px] pointer-events-none select-none" : "mt-4 space-y-2"}>
            {winners.length === 0 ? <p className="text-sm text-muted-foreground">No stock impact ranking available yet.</p> : winners.map((s) => (
              <div key={s.ticker} className="flex items-center justify-between text-sm">
                <span><span className="font-medium">{s.ticker}</span>{s.sector ? <span className="text-muted-foreground"> · {s.sector}</span> : null}</span>
                <span className="font-mono text-emerald-600">+{s.score.toFixed(3)}</span>
              </div>
            ))}
          </div>
          {locked ? (
            <Link href={lockHref} className="absolute inset-0 flex items-center justify-center">
              <span className="inline-flex items-center gap-2 rounded-md border border-border bg-background/95 px-3 py-1.5 text-xs font-medium text-foreground shadow-sm">
                <Lock size={14} />
                Sign up to unlock
              </span>
            </Link>
          ) : null}
        </div>
        <div className="relative rounded-xl border bg-card p-5">
          <h2 className="text-lg font-semibold">Most negatively impacted stocks</h2>
          <div className={locked ? "mt-4 space-y-2 blur-[2.5px] pointer-events-none select-none" : "mt-4 space-y-2"}>
            {losers.length === 0 ? <p className="text-sm text-muted-foreground">No stock impact ranking available yet.</p> : losers.map((s) => (
              <div key={s.ticker} className="flex items-center justify-between text-sm">
                <span><span className="font-medium">{s.ticker}</span>{s.sector ? <span className="text-muted-foreground"> · {s.sector}</span> : null}</span>
                <span className="font-mono text-rose-600">{s.score.toFixed(3)}</span>
              </div>
            ))}
          </div>
          {locked ? (
            <Link href={lockHref} className="absolute inset-0 flex items-center justify-center">
              <span className="inline-flex items-center gap-2 rounded-md border border-border bg-background/95 px-3 py-1.5 text-xs font-medium text-foreground shadow-sm">
                <Lock size={14} />
                Sign up to unlock
              </span>
            </Link>
          ) : null}
        </div>
      </section>
      <section className="mt-4 grid gap-4 lg:grid-cols-2">
        <div className="relative rounded-xl border bg-card p-5">
          <h2 className="text-lg font-semibold">Ticker sentiment in this article</h2>
          <div className={locked ? "mt-4 space-y-2 blur-[2.5px] pointer-events-none select-none" : "mt-4 space-y-2"}>
            {tickerSentiment.length === 0 ? (
              <p className="text-sm text-muted-foreground">No ticker sentiment head found.</p>
            ) : tickerSentiment.map((row) => (
              <div key={row.ticker} className="text-sm">
                <div className="flex items-center justify-between gap-3">
                  <span className="font-medium">{row.ticker}</span>
                  <span className={`font-mono ${scoreClass(row.score)}`}>
                    {row.score >= 0 ? "+" : ""}{row.score.toFixed(2)}
                  </span>
                </div>
                {row.reason ? <p className="mt-1 text-xs text-muted-foreground">{row.reason}</p> : null}
              </div>
            ))}
          </div>
          {locked ? (
            <Link href={lockHref} className="absolute inset-0 flex items-center justify-center">
              <span className="inline-flex items-center gap-2 rounded-md border border-border bg-background/95 px-3 py-1.5 text-xs font-medium text-foreground shadow-sm">
                <Lock size={14} />
                Sign up to unlock
              </span>
            </Link>
          ) : null}
        </div>
        <div className="relative rounded-xl border bg-card p-5">
          <h2 className="text-lg font-semibold">Ticker relationships in this article</h2>
          <div className={locked ? "mt-4 space-y-2 blur-[2.5px] pointer-events-none select-none" : "mt-4 space-y-2"}>
            {tickerRelationships.length === 0 ? (
              <p className="text-sm text-muted-foreground">No ticker relationship head found.</p>
            ) : tickerRelationships.map((row, idx) => (
              <div key={`${row.from}-${row.to}-${row.relType}-${idx}`} className="text-sm">
                <div className="flex items-center justify-between gap-3">
                  <span className="font-medium">
                    {row.from} {"->"} {row.to} <span className="text-muted-foreground">({row.relType})</span>
                  </span>
                  <span className={`font-mono ${scoreClass(row.score)}`}>
                    {row.score >= 0 ? "+" : ""}{row.score.toFixed(2)}
                  </span>
                </div>
                {row.reason ? <p className="mt-1 text-xs text-muted-foreground">{row.reason}</p> : null}
              </div>
            ))}
          </div>
          {locked ? (
            <Link href={lockHref} className="absolute inset-0 flex items-center justify-center">
              <span className="inline-flex items-center gap-2 rounded-md border border-border bg-background/95 px-3 py-1.5 text-xs font-medium text-foreground shadow-sm">
                <Lock size={14} />
                Sign up to unlock
              </span>
            </Link>
          ) : null}
        </div>
      </section>
    </>
  );
}

async function ArticleData({ params }: { params: Promise<{ slug?: string }> }) {
  const resolvedParams = await params;
  const slug = String(resolvedParams?.slug ?? "").trim();
  if (!slug) return <ArticlePageFallback />;

  const authClient = await createClient();
  const dataClient = await createServerDataClient();
  const [{ data: claims }, bySlug] = await Promise.all([
    authClient.auth.getClaims(),
    dataClient
      .schema("swingtrader")
      .from("news_articles")
      .select("id, slug, title, url, source, created_at, image_url")
      .eq("slug", slug)
      .single<ArticleRow>(),
  ]);
  const isAuthed = Boolean(claims?.claims);
  const article = bySlug.data;
  if (!article || bySlug.error) {
    if (isAuthed) notFound();
    return (
      <div className="mx-auto max-w-5xl px-4 py-8 sm:px-6 sm:py-10">
        <div className="rounded-xl border bg-card p-6">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">Article preview</p>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight">Sign in to view this article</h1>
          <div className="mt-5">
            <Link href={`/auth/login?next=/articles/${slug}`} className="inline-flex items-center gap-2 rounded-md border border-border bg-background px-4 py-2 text-sm font-medium hover:bg-muted">
              <Lock size={15} />
              Sign in to unlock
            </Link>
          </div>
        </div>
      </div>
    );
  }

  const [vector, headsRes] = await Promise.all([
    dataClient
      .schema("swingtrader")
      .from("news_impact_vectors")
      .select("impact_json")
      .eq("article_id", article.id)
      .single<{ impact_json: unknown }>(),
    dataClient
      .schema("swingtrader")
      .from("news_impact_heads")
      .select("cluster, scores_json, reasoning_json")
      .eq("article_id", article.id),
  ]);
  const impact = asNumberMap(vector.data?.impact_json ?? {});
  const topDimensions = Object.entries(impact)
    .map(([key, score]) => ({ key, score }))
    .sort((a, b) => Math.abs(b.score) - Math.abs(a.score))
    .slice(0, 12);
  const clusterProfile = computeClusterProfile(impact);
  const { winners, losers } = await fetchRankedStocks(impact);
  const heads = (headsRes.data ?? []) as HeadRow[];
  const sentimentHead = heads.find((h) => h.cluster === "TICKER_SENTIMENT");
  const relationshipHead = heads.find((h) => h.cluster === "TICKER_RELATIONSHIPS");

  const sentimentScores = asNumberMap(sentimentHead?.scores_json ?? {});
  const sentimentReasoning = asStringMap(sentimentHead?.reasoning_json ?? {});
  const tickerSentiment = Object.entries(sentimentScores)
    .map(([ticker, score]) => ({ ticker, score, reason: sentimentReasoning[ticker] ?? "" }))
    .sort((a, b) => Math.abs(b.score) - Math.abs(a.score))
    .slice(0, 12);

  const relationshipScores = asNumberMap(relationshipHead?.scores_json ?? {});
  const relationshipReasoning = asStringMap(relationshipHead?.reasoning_json ?? {});
  const tickerRelationships = Object.entries(relationshipScores)
    .map(([key, score]) => {
      const [from = "", to = "", relType = "related"] = key.split("__");
      return { from, to, relType, score, reason: relationshipReasoning[key] ?? "" };
    })
    .filter((r) => r.from && r.to)
    .sort((a, b) => Math.abs(b.score) - Math.abs(a.score))
    .slice(0, 16);

  return (
    <div className="mx-auto max-w-5xl px-4 py-8 sm:px-6 sm:py-10">
      <div className="mb-6">
        <Link href="/" className="text-sm text-muted-foreground hover:text-foreground">← Back to home</Link>
      </div>
      <article className="rounded-xl border bg-card p-4 sm:p-6">
        <p className="text-xs uppercase tracking-wide text-muted-foreground">{article.source || "Unknown source"} · scanned {formatUTC(article.created_at)} UTC</p>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight">{article.title || "Untitled article"}</h1>
        {article.image_url ? <div className="mt-4 overflow-hidden rounded-lg border"><img src={article.image_url} alt="" className="h-56 w-full object-cover" /></div> : null}
        <div className="mt-4">{article.url ? <Link href={article.url} target="_blank" rel="noreferrer" className="text-sm font-medium underline-offset-4 hover:underline">Read original article →</Link> : <p className="text-sm text-muted-foreground">Original article URL not available.</p>}</div>
      </article>

      <div className="relative mt-8">
        <AnalyticsBlock
          clusterProfile={clusterProfile}
          topDimensions={topDimensions}
          winners={winners}
          losers={losers}
          tickerSentiment={tickerSentiment}
          tickerRelationships={tickerRelationships}
          locked={!isAuthed}
          lockHref={`/auth/sign-up?next=/articles/${slug}`}
        />
      </div>
    </div>
  );
}

function ArticlePageFallback() {
  return (
    <div className="mx-auto max-w-5xl px-4 py-8 sm:px-6 sm:py-10">
      <div className="rounded-xl border bg-card p-6 text-sm text-muted-foreground animate-pulse">
        Loading article analytics...
      </div>
    </div>
  );
}

export default function ArticlePage({
  params,
}: {
  params: Promise<{ slug?: string }>;
}) {
  return (
    <Suspense fallback={<ArticlePageFallback />}>
      <ArticleData params={params} />
    </Suspense>
  );
}
