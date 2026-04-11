import { redirect } from "next/navigation";
import { Suspense } from "react";
import { createClient } from "@/lib/supabase/server";
import {
  ArticlesGrid,
  ArticlesGridFallback,
  type ArticleGridItem,
} from "@/components/articles-grid";

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
      <div className="rounded-md border p-4 text-sm text-muted-foreground">
        Unable to load articles right now.
      </div>
    );
  }

  return <ArticlesGrid articles={(data ?? []) as ArticleGridItem[]} />;
}

export default function ProtectedPage() {
  return (
    <div className="flex-1 w-full flex flex-col gap-6">
      <div>
        <p className="text-xs font-semibold uppercase tracking-widest text-amber-500">Feed</p>
        <h1 className="mt-1 text-2xl font-bold tracking-tight">Latest Articles</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Most recently ingested articles from the news pipeline.
        </p>
      </div>
      <Suspense fallback={<ArticlesGridFallback />}>
        <ArticlesData />
      </Suspense>
    </div>
  );
}
