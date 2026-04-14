import Link from "next/link";

export type ArticleGridItem = {
  id: number;
  slug: string | null;
  title: string | null;
  url: string | null;
  image_url: string | null;
  source?: string | null;
  published_at: string | null;
  created_at: string;
};

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

export function ArticlesGridFallback() {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {[0, 1, 2, 3].map((i) => (
        <div
          key={i}
          className="animate-pulse rounded-xl border border-border bg-card p-3"
        >
          <div className="h-36 w-full rounded-lg bg-muted" />
          <div className="mt-3 space-y-2">
            <div className="h-3 w-4/5 rounded bg-muted" />
            <div className="h-3 w-2/5 rounded bg-muted" />
          </div>
        </div>
      ))}
    </div>
  );
}

export function ArticlesGrid({ articles }: { articles: ArticleGridItem[] }) {
  if (articles.length === 0) {
    return (
      <div className="py-6 text-sm text-muted-foreground">
        No articles found.
      </div>
    );
  }

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {articles.map((article) => (
        <div
          key={article.id}
          className="group rounded-xl border border-border/80 bg-card/40 p-3 transition-colors duration-200 hover:border-amber-500/30 hover:bg-card/70"
        >
          <div className="relative h-36 w-full overflow-hidden rounded-lg bg-muted">
            {article.image_url ? (
              <img
                src={article.image_url}
                alt=""
                className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-[1.01]"
                loading="lazy"
              />
            ) : (
              <div className="flex h-full w-full items-center justify-center">
                <span className="text-[9px] text-muted-foreground">—</span>
              </div>
            )}
          </div>
          <div className="mt-3 min-w-0">
            {article.source && (
              <p className="mb-1 text-[10px] font-semibold uppercase tracking-widest text-amber-500/70">
                {article.source}
              </p>
            )}
            <Link
              href={article.slug ? `/articles/${article.slug}` : `/articles/${article.id}`}
              className="line-clamp-2 text-sm font-medium leading-snug hover:text-amber-400 transition-colors cursor-pointer"
            >
              {article.title || article.url || "Untitled article"}
            </Link>
            <p className="mt-1.5 text-xs text-muted-foreground">
              {formatAgeSince(article.published_at ?? article.created_at)}
            </p>
          </div>
        </div>
      ))}
    </div>
  );
}
