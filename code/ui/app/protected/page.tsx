import { redirect } from "next/navigation";

import { createClient } from "@/lib/supabase/server";
import Link from "next/link";
import { Suspense } from "react";

type ScannedArticle = {
  id: number;
  title: string | null;
  url: string | null;
  source: string | null;
  created_at: string;
  image_url: string | null;
};

function formatScannedAt(iso: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return "Unknown time";
  return new Intl.DateTimeFormat("en-GB", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "UTC",
  }).format(parsed);
}

async function ProtectedArticlesData() {
  const supabase = await createClient();
  const { data: claims, error: claimsError } = await supabase.auth.getClaims();

  if (claimsError || !claims?.claims) {
    redirect("/auth/login");
  }

  const { data: articles, error: articlesError } = await supabase
    .schema("swingtrader")
    .from("news_articles")
    .select("id, title, url, source, created_at, image_url")
    .order("created_at", { ascending: false })
    .limit(25);

  const latestArticles: ScannedArticle[] = articles ?? [];

  return (
    <>
      {articlesError ? (
        <div className="rounded-md border p-4 text-sm text-muted-foreground">
          Unable to load scanned articles right now.
        </div>
      ) : latestArticles.length === 0 ? (
        <div className="rounded-md border p-4 text-sm text-muted-foreground">
          No scanned articles found yet.
        </div>
      ) : (
        <div className="grid gap-3">
          {latestArticles.map((article) => (
            <article
              key={article.id}
              className="flex gap-4 overflow-hidden rounded-lg border p-4"
            >
              <div className="relative h-[5.5rem] w-28 shrink-0 overflow-hidden rounded-md bg-muted">
                {article.image_url ? (
                  <img
                    src={article.image_url}
                    alt=""
                    className="h-full w-full object-cover"
                    loading="lazy"
                  />
                ) : (
                  <div className="flex h-full w-full items-center justify-center text-[10px] text-muted-foreground">
                    No image
                  </div>
                )}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-[11px] uppercase tracking-wide text-muted-foreground">
                    {article.source || "Unknown source"}
                  </p>
                  <time className="shrink-0 text-[11px] text-muted-foreground">
                    {formatScannedAt(article.created_at)}
                  </time>
                </div>
                {article.url ? (
                  <Link
                    href={article.url}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-1 block text-sm font-medium hover:underline"
                  >
                    {article.title || article.url}
                  </Link>
                ) : (
                  <p className="mt-1 text-sm font-medium">
                    {article.title || "Untitled article"}
                  </p>
                )}
              </div>
            </article>
          ))}
        </div>
      )}
    </>
  );
}

export default function ProtectedPage() {
  return (
    <div className="flex-1 w-full flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold">Latest Scanned Articles</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Most recently ingested records from{" "}
          <code className="font-mono">swingtrader.news_articles</code>.
        </p>
      </div>
      <Suspense
        fallback={
          <div className="rounded-md border p-4 text-sm text-muted-foreground">
            Loading latest scanned articles...
          </div>
        }
      >
        <ProtectedArticlesData />
      </Suspense>
    </div>
  );
}
