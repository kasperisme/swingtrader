import { Suspense } from "react";
import { createClient } from "@/lib/supabase/server";
import { createServiceClient } from "@/lib/supabase/service";
import type { ArticleGridItem } from "@/components/articles-grid";
import {
  ArticlesSearchPanel,
  EditorialSkeleton,
} from "./articles-search-panel";
import { getOnboardingTours } from "@/app/actions/onboarding";
import { PageTour } from "@/app/protected/_components/page-tour";
import {
  TrendingScoreboard,
  TrendingScoreboardSkeleton,
} from "@/components/trending-scoreboard";

async function ArticlesData({ initialTag }: { initialTag?: string }) {
  // Use service-role client so logged-out visitors can read the public
  // news_articles table (RLS blocks anon reads on the swingtrader schema).
  const supabase = createServiceClient();

  const { data, error } = await supabase
    .schema("swingtrader")
    .from("news_articles")
    .select("id, slug, title, url, source, image_url, published_at, created_at")
    .order("published_at", { ascending: false, nullsFirst: false })
    .order("created_at", { ascending: false })
    .limit(24);

  if (error) {
    return (
      <div className="border-l-2 border-destructive/60 py-6 pl-4 text-sm text-muted-foreground">
        Unable to load articles right now.
      </div>
    );
  }

  return (
    <ArticlesSearchPanel
      initialArticles={(data ?? []) as ArticleGridItem[]}
      initialTag={initialTag}
    />
  );
}

async function ArticlesTourMount() {
  const supabase = await createClient();
  const { data: claims } = await supabase.auth.getClaims();
  if (!claims?.claims?.sub) return null;
  const tours = await getOnboardingTours();
  return <PageTour tourKey="articles" autoStart={!tours.articles} />;
}

export default async function ArticlesPage({
  searchParams,
}: {
  searchParams: Promise<{ tag?: string }>;
}) {
  const params = await searchParams;
  const initialTag =
    typeof params.tag === "string" ? params.tag.trim() : undefined;

  return (
    <div className="mx-auto flex w-full min-w-0 max-w-7xl flex-1 flex-col gap-8 px-4 py-8 sm:px-6 lg:px-8">
      <header className="grid gap-6 border-b border-border/60 pb-6 md:grid-cols-[1fr_auto] md:items-end">
        <div>
          <p className="mb-3 inline-flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.2em] text-amber-500/80">
            <span className="h-px w-6 bg-amber-500/60" />
            The Tape
          </p>
          <h1 className="text-3xl font-bold leading-[1.05] tracking-tight md:text-5xl">
            Articles
          </h1>
          <p className="mt-3 max-w-[55ch] text-sm leading-relaxed text-muted-foreground">
            Latest stories from the ingestion pipeline, ranked by recency. Use the
            command bar to search headlines, tags, and body text — matches any
            keyword, ranked by relevance. 90-day lookback.
          </p>
        </div>
        <div className="hidden items-baseline gap-3 font-mono text-[11px] uppercase tracking-[0.2em] text-muted-foreground md:flex">
          <span>Press</span>
          <kbd className="rounded border border-border/60 bg-card/60 px-1.5 py-0.5 text-[11px] tracking-normal text-foreground">
            /
          </kbd>
          <span>to search</span>
        </div>
      </header>

      <Suspense fallback={<TrendingScoreboardSkeleton />}>
        <TrendingScoreboard windowDays={7} limit={20} collapsed={6} />
      </Suspense>

      <Suspense fallback={<EditorialSkeleton mode="feed" />}>
        <ArticlesData initialTag={initialTag} />
      </Suspense>
      <Suspense fallback={null}>
        <ArticlesTourMount />
      </Suspense>
    </div>
  );
}
