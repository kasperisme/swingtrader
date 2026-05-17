import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { ArrowLeft, ArrowUpRight, Lock } from "lucide-react";
import { createClient as createSupabaseClient } from "@supabase/supabase-js";

import { createClient } from "@/lib/supabase/server";
import { CLUSTERS, DIMENSION_MAP } from "@/app/protected/vectors/dimensions";

type ArticleRow = {
  id: number;
  slug: string | null;
  title: string | null;
  url: string | null;
  source: string | null;
  publisher: string | null;
  published_at: string | null;
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
  if (v > 0.03) return "text-emerald-500";
  if (v < -0.03) return "text-rose-500";
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

function formatAgeSince(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "Unknown age";
  const diffMs = Date.now() - d.getTime();
  if (diffMs < 0) return "Just now";
  const minute = 60_000;
  const hour = 60 * minute;
  const day = 24 * hour;
  const week = 7 * day;
  if (diffMs < hour) return `${Math.max(1, Math.floor(diffMs / minute))}m ago`;
  if (diffMs < day) return `${Math.floor(diffMs / hour)}h ago`;
  if (diffMs < week) return `${Math.floor(diffMs / day)}d ago`;
  return `${Math.floor(diffMs / week)}w ago`;
}

function computeClusterProfile(impact: Record<string, number>) {
  return CLUSTERS.map((cluster) => {
    const vals = cluster.dimensions
      .map((d) => impact[d.key])
      .filter((v): v is number => Number.isFinite(v));
    const score = vals.length
      ? vals.reduce((a, b) => a + b, 0) / vals.length
      : 0;
    return {
      id: cluster.id,
      label: cluster.label,
      score,
      docSlug: clusterDocSlug(cluster.id),
    };
  }).sort((a, b) => Math.abs(b.score) - Math.abs(a.score));
}

async function fetchRankedStocks(impact: Record<string, number>) {
  if (Object.keys(impact).length === 0)
    return { winners: [] as RankedStock[], losers: [] as RankedStock[] };
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
    ranked.push({
      ticker: row.ticker,
      score: total / used,
      sector: String(meta.sector ?? ""),
    });
  }
  ranked.sort((a, b) => b.score - a.score);
  return {
    winners: ranked.filter((r) => r.score > 0).slice(0, 10),
    losers: ranked
      .filter((r) => r.score < 0)
      .sort((a, b) => a.score - b.score)
      .slice(0, 10),
  };
}

function Eyebrow({ label, meta }: { label: string; meta?: string }) {
  return (
    <div className="mb-5 flex flex-wrap items-baseline gap-x-4 gap-y-1">
      <p className="inline-flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.2em] text-amber-500/80">
        <span className="h-px w-6 bg-amber-500/60" />
        {label}
      </p>
      {meta ? (
        <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
          {meta}
        </p>
      ) : null}
    </div>
  );
}

function SignedBar({ score, max }: { score: number; max: number }) {
  const denom = Math.max(max, 0.0001);
  const pct = Math.min(50, (Math.abs(score) / denom) * 50);
  const isPos = score >= 0;
  return (
    <div className="relative h-1.5 w-full overflow-hidden rounded-sm bg-muted/50">
      <div className="absolute left-1/2 top-0 h-full w-px bg-border" />
      <div
        className={
          isPos
            ? "absolute top-0 h-full bg-emerald-500/80"
            : "absolute top-0 h-full bg-rose-500/80"
        }
        style={{
          left: isPos ? "50%" : `${50 - pct}%`,
          width: `${pct}%`,
        }}
      />
    </div>
  );
}

function MagnitudeBar({
  value,
  max,
  tone,
}: {
  value: number;
  max: number;
  tone: "pos" | "neg";
}) {
  const pct = Math.min(100, (Math.abs(value) / Math.max(max, 0.0001)) * 100);
  return (
    <div className="h-[3px] w-full overflow-hidden rounded-sm bg-muted/40">
      <div
        className={
          tone === "pos"
            ? "h-full bg-emerald-500/75"
            : "h-full bg-rose-500/75"
        }
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

function ScoreText({ value, digits = 3 }: { value: number; digits?: number }) {
  const sign = value >= 0 ? "+" : "";
  return (
    <span className={`font-mono text-xs tabular-nums ${scoreClass(value)}`}>
      {sign}
      {value.toFixed(digits)}
    </span>
  );
}

function ClusterProfile({
  rows,
}: {
  rows: Array<{ id: string; label: string; score: number; docSlug: string }>;
}) {
  const max = rows.reduce((m, r) => Math.max(m, Math.abs(r.score)), 0);
  return (
    <ul className="space-y-3.5">
      {rows.map((c) => (
        <li key={c.id}>
          <div className="mb-1 flex items-baseline justify-between gap-3">
            <Link
              href={c.docSlug}
              className="truncate text-sm text-foreground/90 hover:text-amber-400"
            >
              {c.label}
            </Link>
            <ScoreText value={c.score} />
          </div>
          <SignedBar score={c.score} max={max} />
        </li>
      ))}
    </ul>
  );
}

function DimensionList({
  rows,
}: {
  rows: Array<{ key: string; score: number }>;
}) {
  if (rows.length === 0) {
    return (
      <p className="text-sm text-muted-foreground/80">
        No impact vector found for this article yet.
      </p>
    );
  }
  const max = rows.reduce((m, r) => Math.max(m, Math.abs(r.score)), 0);
  return (
    <ul className="space-y-3">
      {rows.map((d) => {
        const dim = DIMENSION_MAP[d.key];
        const clusterKey = CLUSTERS.find((c) =>
          c.dimensions.some((x) => x.key === d.key),
        )?.id;
        const href = clusterKey
          ? clusterDocSlug(clusterKey)
          : "/docs/news-impact-scores";
        return (
          <li key={d.key}>
            <div className="mb-1 flex items-baseline justify-between gap-3">
              <Link
                href={href}
                className="truncate text-[13px] text-foreground/85 hover:text-amber-400"
              >
                {dim?.label ?? d.key}
              </Link>
              <ScoreText value={d.score} />
            </div>
            <SignedBar score={d.score} max={max} />
          </li>
        );
      })}
    </ul>
  );
}

function StockLedger({
  rows,
  tone,
}: {
  rows: RankedStock[];
  tone: "pos" | "neg";
}) {
  if (rows.length === 0) {
    return (
      <p className="text-sm text-muted-foreground/80">
        No stock impact ranking available yet.
      </p>
    );
  }
  const max = rows.reduce((m, r) => Math.max(m, Math.abs(r.score)), 0);
  return (
    <ol className="space-y-3">
      {rows.map((s, idx) => (
        <li key={s.ticker} className="grid grid-cols-[1.25rem_1fr_auto] items-baseline gap-3">
          <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground/70">
            {String(idx + 1).padStart(2, "0")}
          </span>
          <div className="min-w-0">
            <div className="mb-1 flex items-baseline justify-between gap-3">
              <span className="truncate text-sm">
                <span className="font-semibold tracking-tight text-foreground">
                  {s.ticker}
                </span>
                {s.sector ? (
                  <span className="ml-2 text-xs text-muted-foreground">
                    {s.sector}
                  </span>
                ) : null}
              </span>
            </div>
            <MagnitudeBar value={s.score} max={max} tone={tone} />
          </div>
          <span
            className={
              tone === "pos"
                ? "font-mono text-xs tabular-nums text-emerald-500"
                : "font-mono text-xs tabular-nums text-rose-500"
            }
          >
            {tone === "pos" ? "+" : ""}
            {s.score.toFixed(3)}
          </span>
        </li>
      ))}
    </ol>
  );
}

function TickerSentimentList({
  rows,
}: {
  rows: Array<{ ticker: string; score: number; reason: string }>;
}) {
  if (rows.length === 0) {
    return (
      <p className="text-sm text-muted-foreground/80">
        No ticker sentiment head found.
      </p>
    );
  }
  return (
    <ul className="divide-y divide-border/40">
      {rows.map((row) => (
        <li key={row.ticker} className="py-3 first:pt-0 last:pb-0">
          <div className="flex items-baseline justify-between gap-3">
            <span className="font-semibold tracking-tight text-foreground">
              {row.ticker}
            </span>
            <ScoreText value={row.score} digits={2} />
          </div>
          {row.reason ? (
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
              {row.reason}
            </p>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

function TickerRelationshipList({
  rows,
}: {
  rows: Array<{
    from: string;
    to: string;
    relType: string;
    score: number;
    reason: string;
  }>;
}) {
  if (rows.length === 0) {
    return (
      <p className="text-sm text-muted-foreground/80">
        No ticker relationship head found.
      </p>
    );
  }
  return (
    <ul className="divide-y divide-border/40">
      {rows.map((row, idx) => (
        <li
          key={`${row.from}-${row.to}-${row.relType}-${idx}`}
          className="py-3 first:pt-0 last:pb-0"
        >
          <div className="flex items-baseline justify-between gap-3">
            <div className="flex min-w-0 items-baseline gap-2">
              <span className="font-semibold tracking-tight text-foreground">
                {row.from}
              </span>
              <span className="font-mono text-[10px] text-muted-foreground/70">
                →
              </span>
              <span className="font-semibold tracking-tight text-foreground">
                {row.to}
              </span>
              <span className="ml-1 rounded-sm border border-border/60 bg-muted/40 px-1.5 py-px font-mono text-[9px] uppercase tracking-wider text-muted-foreground">
                {row.relType}
              </span>
            </div>
            <ScoreText value={row.score} digits={2} />
          </div>
          {row.reason ? (
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
              {row.reason}
            </p>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

function AnalyticsRegion({
  clusterProfile,
  topDimensions,
  winners,
  losers,
  tickerSentiment,
  tickerRelationships,
  locked,
  lockHref,
}: {
  clusterProfile: Array<{
    id: string;
    label: string;
    score: number;
    docSlug: string;
  }>;
  topDimensions: Array<{ key: string; score: number }>;
  winners: RankedStock[];
  losers: RankedStock[];
  tickerSentiment: Array<{ ticker: string; score: number; reason: string }>;
  tickerRelationships: Array<{
    from: string;
    to: string;
    relType: string;
    score: number;
    reason: string;
  }>;
  locked: boolean;
  lockHref: string;
}) {
  return (
    <div className="relative">
      <div
        className={
          locked
            ? "space-y-12 pointer-events-none select-none blur-[3px]"
            : "space-y-12"
        }
      >
        <section>
          <Eyebrow
            label="Impact vectors"
            meta={`${topDimensions.length} dimensions · ${clusterProfile.length} clusters`}
          />
          <div className="grid gap-10 lg:grid-cols-5">
            <div className="lg:col-span-3">
              <h2 className="mb-5 text-base font-semibold tracking-tight text-foreground/90">
                Analytical profile by cluster
              </h2>
              <ClusterProfile rows={clusterProfile} />
            </div>
            <div className="lg:col-span-2 lg:border-l lg:border-border/40 lg:pl-10">
              <h2 className="mb-5 text-base font-semibold tracking-tight text-foreground/90">
                Top impact dimensions
              </h2>
              <DimensionList rows={topDimensions} />
            </div>
          </div>
        </section>

        <section>
          <Eyebrow
            label="Market reaction"
            meta={`${winners.length} bid · ${losers.length} offered`}
          />
          <div className="grid gap-10 md:grid-cols-2">
            <div>
              <div className="mb-5 flex items-baseline justify-between">
                <h2 className="text-base font-semibold tracking-tight text-foreground/90">
                  Most positively impacted
                </h2>
                <span className="font-mono text-[10px] uppercase tracking-widest text-emerald-500/80">
                  Bid
                </span>
              </div>
              <StockLedger rows={winners} tone="pos" />
            </div>
            <div className="md:border-l md:border-border/40 md:pl-10">
              <div className="mb-5 flex items-baseline justify-between">
                <h2 className="text-base font-semibold tracking-tight text-foreground/90">
                  Most negatively impacted
                </h2>
                <span className="font-mono text-[10px] uppercase tracking-widest text-rose-500/80">
                  Offered
                </span>
              </div>
              <StockLedger rows={losers} tone="neg" />
            </div>
          </div>
        </section>

        <section>
          <Eyebrow label="Ticker attribution" meta="Model heads" />
          <div className="grid gap-10 md:grid-cols-2">
            <div>
              <h2 className="mb-5 text-base font-semibold tracking-tight text-foreground/90">
                Sentiment in this article
              </h2>
              <TickerSentimentList rows={tickerSentiment} />
            </div>
            <div className="md:border-l md:border-border/40 md:pl-10">
              <h2 className="mb-5 text-base font-semibold tracking-tight text-foreground/90">
                Relationships in this article
              </h2>
              <TickerRelationshipList rows={tickerRelationships} />
            </div>
          </div>
        </section>
      </div>

      {locked ? (
        <Link
          href={lockHref}
          className="absolute inset-0 flex items-start justify-center pt-16"
        >
          <div className="sticky top-24 inline-flex flex-col items-center gap-3 rounded-lg border border-border/80 bg-background/95 px-6 py-5 text-center shadow-lg backdrop-blur">
            <span className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-amber-500/40 bg-amber-500/10 text-amber-500">
              <Lock size={14} />
            </span>
            <div>
              <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-amber-500/80">
                The Tape · Members only
              </p>
              <p className="mt-2 text-sm font-medium text-foreground">
                Sign up to unlock the full impact analysis
              </p>
              <p className="mt-1 max-w-[36ch] text-xs text-muted-foreground">
                Cluster profile, ranked exposures, and ticker attribution heads.
              </p>
            </div>
          </div>
        </Link>
      ) : null}
    </div>
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
      .select(
        "id, slug, title, url, source, published_at, created_at, image_url,publisher",
      )
      .eq("slug", slug)
      .single<ArticleRow>(),
  ]);
  const isAuthed = Boolean(claims?.claims);
  const article = bySlug.data;
  if (!article || bySlug.error) {
    if (isAuthed) notFound();
    return (
      <div className="mx-auto max-w-5xl px-4 py-12 sm:px-6 sm:py-16">
        <Eyebrow label="The Tape · Article preview" />
        <h1 className="text-3xl font-bold leading-[1.05] tracking-tight md:text-5xl">
          Sign in to view this article
        </h1>
        <p className="mt-4 max-w-[55ch] text-sm leading-relaxed text-muted-foreground">
          Members get the full impact analysis: cluster profile, market reaction
          ledger, and per-ticker attribution.
        </p>
        <div className="mt-6">
          <Link
            href={`/auth/login?next=/articles/${slug}`}
            className="inline-flex items-center gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-4 py-2 text-sm font-medium text-amber-500 transition-colors hover:bg-amber-500/15"
          >
            <Lock size={14} />
            Sign in to unlock
          </Link>
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
  const relationshipHead = heads.find(
    (h) => h.cluster === "TICKER_RELATIONSHIPS",
  );

  const sentimentScores = asNumberMap(sentimentHead?.scores_json ?? {});
  const sentimentReasoning = asStringMap(sentimentHead?.reasoning_json ?? {});
  const tickerSentiment = Object.entries(sentimentScores)
    .map(([ticker, score]) => ({
      ticker,
      score,
      reason: sentimentReasoning[ticker] ?? "",
    }))
    .sort((a, b) => Math.abs(b.score) - Math.abs(a.score))
    .slice(0, 12);

  const relationshipScores = asNumberMap(relationshipHead?.scores_json ?? {});
  const relationshipReasoning = asStringMap(
    relationshipHead?.reasoning_json ?? {},
  );
  const tickerRelationships = Object.entries(relationshipScores)
    .map(([key, score]) => {
      const [from = "", to = "", relType = "related"] = key.split("__");
      return {
        from,
        to,
        relType,
        score,
        reason: relationshipReasoning[key] ?? "",
      };
    })
    .filter((r) => r.from && r.to)
    .sort((a, b) => Math.abs(b.score) - Math.abs(a.score))
    .slice(0, 16);

  const publishedIso = article.published_at ?? article.created_at;

  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-8 sm:px-6 sm:py-10">
      <div className="mb-8">
        <Link
          href="/protected/articles"
          className="inline-flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground transition-colors hover:text-amber-500"
        >
          <ArrowLeft size={12} />
          Back to The Tape
        </Link>
      </div>

      <article className="border-b border-border/60 pb-10">
        <Eyebrow
          label={article.publisher || "Unknown source"}
          meta={`${formatUTC(publishedIso)} UTC · ${formatAgeSince(publishedIso)}`}
        />
        <h1 className="text-3xl font-bold leading-[1.05] tracking-tight md:text-5xl">
          {article.url ? (
            <Link
              href={article.url}
              target="_blank"
              rel="noreferrer"
              className="transition-colors hover:text-amber-400"
            >
              {article.title || "Untitled article"}
            </Link>
          ) : (
            article.title || "Untitled article"
          )}
        </h1>

        {article.image_url ? (
          <div className="relative mt-8 overflow-hidden rounded-xl border border-border/60 bg-muted">
            <img
              src={article.image_url}
              alt=""
              className="h-[240px] w-full object-cover md:h-[420px]"
            />
            <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-background/40 via-transparent to-transparent" />
          </div>
        ) : null}

        {article.url ? (
          <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
            <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
              Source · {article.source || article.publisher || "feed"}
            </p>
            <Link
              href={article.url}
              target="_blank"
              rel="noreferrer"
              className="group inline-flex items-center gap-2 rounded-md border border-border/80 bg-card/40 px-3.5 py-1.5 text-sm font-medium text-foreground transition-colors hover:border-amber-500/40 hover:bg-card/70 hover:text-amber-400"
            >
              Read source
              <ArrowUpRight
                size={14}
                className="transition-transform duration-200 group-hover:-translate-y-px group-hover:translate-x-px"
              />
            </Link>
          </div>
        ) : null}
      </article>

      <div className="mt-12">
        <AnalyticsRegion
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
    <div className="mx-auto w-full max-w-5xl px-4 py-8 sm:px-6 sm:py-10">
      <div className="mb-8 h-3 w-32 animate-pulse rounded bg-muted/60" />
      <div className="border-b border-border/60 pb-10">
        <div className="h-3 w-48 animate-pulse rounded bg-muted/60" />
        <div className="mt-4 h-10 w-3/4 animate-pulse rounded bg-muted/60" />
        <div className="mt-3 h-10 w-1/2 animate-pulse rounded bg-muted/60" />
        <div className="mt-8 h-[240px] w-full animate-pulse rounded-xl bg-muted/60 md:h-[420px]" />
      </div>
      <div className="mt-12 space-y-10">
        {[0, 1, 2].map((i) => (
          <div key={i}>
            <div className="mb-5 h-3 w-32 animate-pulse rounded bg-muted/60" />
            <div className="grid gap-10 md:grid-cols-2">
              <div className="space-y-3">
                {[0, 1, 2, 3].map((j) => (
                  <div key={j} className="h-4 w-full animate-pulse rounded bg-muted/40" />
                ))}
              </div>
              <div className="space-y-3">
                {[0, 1, 2, 3].map((j) => (
                  <div key={j} className="h-4 w-full animate-pulse rounded bg-muted/40" />
                ))}
              </div>
            </div>
          </div>
        ))}
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
