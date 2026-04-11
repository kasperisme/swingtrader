import { Suspense } from "react";
import { createClient } from "@/lib/supabase/server";
import { NewsTrendsUI, type ArticleImpact } from "./news-trends-ui";

async function fetchImpactData(): Promise<ArticleImpact[]> {
  const supabase = await createClient();
  const pageSize = 1000;
  let from = 0;
  const allRows: any[] = [];

  while (true) {
    const to = from + pageSize - 1;
    const { data, error } = await supabase
      .schema("swingtrader")
      .from("news_impact_vectors")
      .select("impact_json, created_at, news_articles(id, published_at, title, url, source, slug, image_url, created_at)")
      .order("created_at", { ascending: true })
      .range(from, to);

    if (error) {
      console.error("Failed to fetch news impact vectors:", error);
      return [];
    }

    const rows = data ?? [];
    if (rows.length === 0) break;
    allRows.push(...rows);

    if (rows.length < pageSize) break;
    from += pageSize;
  }

  return allRows.map((row: any) => ({
    impact_json: row.impact_json,
    id: row.news_articles?.id ?? null,
    published_at: row.news_articles?.published_at ?? row.created_at,
    title: row.news_articles?.title ?? null,
    url: row.news_articles?.url ?? null,
    source: row.news_articles?.source ?? null,
    slug: row.news_articles?.slug ?? null,
    image_url: row.news_articles?.image_url ?? null,
    created_at: row.news_articles?.created_at ?? row.created_at,
  }));
}

async function TrendsData() {
  const articles = await fetchImpactData();

  return <NewsTrendsUI articles={articles} />;
}

export default function NewsTrendsPage() {
  return (
    <div className="flex-1 w-full flex flex-col gap-6">
      <div>
        <p className="text-xs font-semibold uppercase tracking-widest text-amber-500">Narrative momentum</p>
        <h1 className="mt-1 text-2xl font-bold tracking-tight">News Dimension Trends</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Moving average of news impact scores across dimension clusters — track
          what narratives are gaining or losing momentum.
        </p>
      </div>

      <Suspense
        fallback={
          <div className="text-sm text-muted-foreground animate-pulse">
            Loading trends…
          </div>
        }
      >
        <TrendsData />
      </Suspense>
    </div>
  );
}
