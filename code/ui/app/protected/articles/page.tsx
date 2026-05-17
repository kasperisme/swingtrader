import { redirect } from "next/navigation";
import { Suspense } from "react";
import { createClient } from "@/lib/supabase/server";
import type { ArticleGridItem } from "@/components/articles-grid";
import {
  ArticlesSearchPanel,
  EditorialSkeleton,
} from "./articles-search-panel";
import { getOnboardingTours } from "@/app/actions/onboarding";
import { PageTour } from "@/app/protected/_components/page-tour";

async function ArticlesData() {
  const supabase = await createClient();
  const { data: claims, error: claimsError } = await supabase.auth.getClaims();

  if (claimsError || !claims?.claims) {
    redirect("/auth/login");
  }

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

  return <ArticlesSearchPanel initialArticles={(data ?? []) as ArticleGridItem[]} />;
}

async function ArticlesTourMount() {
  const tours = await getOnboardingTours();
  return <PageTour tourKey="articles" autoStart={!tours.articles} />;
}

export default function ArticlesPage() {
  return (
    <div className="flex w-full flex-1 flex-col gap-8">
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
            command bar to query the corpus semantically — 90-day lookback.
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

      <Suspense fallback={<EditorialSkeleton mode="feed" />}>
        <ArticlesData />
      </Suspense>
      <Suspense fallback={null}>
        <ArticlesTourMount />
      </Suspense>
    </div>
  );
}
