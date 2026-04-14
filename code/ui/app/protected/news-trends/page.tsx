import { Suspense } from "react";
import { createClient } from "@/lib/supabase/server";
import { NewsTrendsUI, type ArticleImpact } from "./news-trends-ui";

function asImpactMap(raw: unknown): Record<string, number> {
  if (!raw) return {};
  if (typeof raw === "object" && !Array.isArray(raw)) {
    const out: Record<string, number> = {};
    for (const [k, v] of Object.entries(raw as Record<string, unknown>)) {
      const n = Number(v);
      if (Number.isFinite(n)) out[k] = n;
    }
    return out;
  }
  if (typeof raw === "string") {
    try {
      return asImpactMap(JSON.parse(raw));
    } catch {
      return {};
    }
  }
  return {};
}

async function fetchImpactData(): Promise<ArticleImpact[]> {
  const supabase = await createClient();
  const pageSize = 1000;
  let from = 0;
  const allRows: any[] = [];

  while (true) {
    const to = from + pageSize - 1;
    const { data, error } = await supabase
      .schema("swingtrader")
      .from("news_trends_article_base_v")
      .select(
        "article_id, published_at, impact_jsonb, confidence_mean, id, title, url, source, slug, image_url, article_created_at",
      )
      .order("published_at", { ascending: true })
      .range(from, to);

    if (error) {
      console.error("Failed to fetch news trends base rows:", error);
      return [];
    }

    const rows = data ?? [];
    if (rows.length === 0) break;
    allRows.push(...rows);

    if (rows.length < pageSize) break;
    from += pageSize;
  }

  return allRows.map((row: any) => {
    return {
      impact_json: asImpactMap(row.impact_jsonb),
      confidence: Number.isFinite(Number(row.confidence_mean))
        ? Number(row.confidence_mean)
        : null,
      id: row.id ?? null,
      published_at: row.published_at,
      title: row.title ?? null,
      url: row.url ?? null,
      source: row.source ?? null,
      slug: row.slug ?? null,
      image_url: row.image_url ?? null,
      created_at: row.article_created_at ?? row.published_at,
    };
  });
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
