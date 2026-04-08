import { AuthButton } from "@/components/auth-button";
import { EnvVarWarning } from "@/components/env-var-warning";
import { ThemeSwitcher } from "@/components/theme-switcher";
import { createClient } from "@/lib/supabase/server";
import { hasEnvVars } from "@/lib/utils";
import Image from "next/image";
import Link from "next/link";
import { Suspense } from "react";
import { ArrowRight } from "lucide-react";

type NewsArticle = {
  id: number;
  title: string | null;
  url: string | null;
  source: string | null;
  created_at: string;
};

function articleImageUrl(article: NewsArticle): string | null {
  if (!article.url) return null;
  return `https://www.google.com/s2/favicons?sz=256&domain_url=${encodeURIComponent(article.url)}`;
}

function formatArticleDate(iso: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return "Unknown date";
  return new Intl.DateTimeFormat("en-GB", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    timeZone: "UTC",
  }).format(parsed);
}

async function LatestNewsArticles() {
  const supabase = await createClient();
  const { data: articles, error } = await supabase
    .schema("swingtrader")
    .from("news_articles")
    .select("id, title, url, source, created_at")
    .order("created_at", { ascending: false })
    .limit(8);

  const latestArticles: NewsArticle[] = articles ?? [];

  if (error) {
    return (
      <p className="mt-4 text-sm text-muted-foreground">
        Unable to load articles right now.
      </p>
    );
  }

  if (latestArticles.length === 0) {
    return (
      <p className="mt-4 text-sm text-muted-foreground">
        No articles available yet.
      </p>
    );
  }

  return (
    <div className="mt-5 overflow-hidden [mask-image:linear-gradient(to_right,transparent,black_8%,black_92%,transparent)]">
      <div className="flex w-max gap-4 animate-news-roll hover:[animation-play-state:paused]">
        {[...latestArticles, ...latestArticles].map((article, idx) => (
          <article
            key={`${article.id}-${idx}`}
            className="w-[290px] shrink-0 rounded-xl border bg-card overflow-hidden"
          >
            <div className="h-36 bg-muted flex items-center justify-center">
              {articleImageUrl(article) ? (
                <img
                  src={articleImageUrl(article) ?? ""}
                  alt={`${article.source || "Article"} logo`}
                  className="h-full w-full object-cover p-6"
                  loading="lazy"
                />
              ) : (
                <span className="text-xs text-muted-foreground">No image</span>
              )}
            </div>
            <div className="p-3">
              <div className="flex items-center justify-between gap-3">
                <p className="text-[11px] uppercase tracking-wide text-muted-foreground truncate">
                  {article.source || "Unknown source"}
                </p>
                <time className="text-[11px] text-muted-foreground shrink-0">
                  {formatArticleDate(article.created_at)}
                </time>
              </div>
              {article.url ? (
                <a
                  href={article.url}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-1.5 block text-sm font-medium leading-snug hover:underline line-clamp-2"
                >
                  {article.title || article.url}
                </a>
              ) : (
                <p className="mt-1.5 text-sm font-medium leading-snug line-clamp-2">
                  {article.title || "Untitled article"}
                </p>
              )}
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}

async function LandingHeader() {
  const supabase = await createClient();
  const { data, error } = await supabase.auth.getClaims();
  const isLoggedIn = !error && !!data?.claims;

  return (
    <nav className="w-full flex justify-center border-b border-b-foreground/10 h-16">
      <div className="w-full max-w-7xl flex justify-between items-center p-3 px-5 text-sm">
        <div className="flex gap-5 items-center font-semibold">
          <Link href="/" className="inline-flex items-center gap-2">
            <Image src="/icon.png" alt="newsimpactscreener logo" width={20} height={20} className="rounded-sm" />
            newsimpactscreener
          </Link>
          {isLoggedIn && (
            <>
              <Link
                href="/protected/vectors"
                className="text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
              >
                Vectors
              </Link>
              <Link
                href="/protected/news-trends"
                className="text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
              >
                News Trends
              </Link>
              <Link
                href="/protected/screenings"
                className="text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
              >
                Screenings
              </Link>
            </>
          )}
        </div>
        {!hasEnvVars ? (
          <EnvVarWarning />
        ) : (
          <div className="flex items-center gap-4">
            {!isLoggedIn && (
              <Link
                href="/auth/login"
                className="text-muted-foreground hover:text-foreground transition-colors"
              >
                Login
              </Link>
            )}
            <Suspense>
              <AuthButton />
            </Suspense>
          </div>
        )}
      </div>
    </nav>
  );
}

export default function Home() {

  return (
    <main className="min-h-screen flex flex-col items-center bg-background">
      <div className="flex-1 w-full flex flex-col items-center">
        <Suspense
          fallback={
            <nav className="w-full flex justify-center border-b border-b-foreground/10 h-16">
              <div className="w-full max-w-7xl flex justify-between items-center p-3 px-5 text-sm">
                <Link href="/" className="font-semibold inline-flex items-center gap-2">
                  <Image src="/icon.png" alt="newsimpactscreener logo" width={20} height={20} className="rounded-sm" />
                  newsimpactscreener
                </Link>
              </div>
            </nav>
          }
        >
          <LandingHeader />
        </Suspense>

        <section className="w-full max-w-7xl px-5 py-16 md:py-24">
          <div className="max-w-3xl">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-4">
              Quant Signals Platform
            </p>
            <h1 className="text-4xl md:text-5xl font-bold tracking-tight">
              Discover market narratives, factor shifts, and screening signals.
            </h1>
            <p className="mt-5 text-base md:text-lg text-muted-foreground">
              newsimpactscreener turns scored news and company vectors into an actionable daily view across
              sectors, dimensions, and custom screens.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link
                href="/protected/vectors"
                className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
              >
                Open Dashboard
                <ArrowRight size={14} />
              </Link>
              <Link
                href="/auth/login"
                className="inline-flex items-center gap-2 rounded-md border border-input bg-background px-4 py-2 text-sm font-medium hover:bg-accent hover:text-accent-foreground transition-colors"
              >
                Sign in
              </Link>
            </div>
          </div>
        </section>

        <section className="w-full max-w-7xl px-5 pb-20 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Link
            href="/protected/vectors"
            className="rounded-xl border p-5 hover:bg-muted/30 transition-colors"
          >
            <p className="text-sm font-semibold">Company Vectors</p>
            <p className="mt-2 text-xs text-muted-foreground">
              Inspect factor exposures and cluster-level sensitivity across the universe.
            </p>
          </Link>
          <Link
            href="/protected/news-trends"
            className="rounded-xl border p-5 hover:bg-muted/30 transition-colors"
          >
            <p className="text-sm font-semibold">News Trends</p>
            <p className="mt-2 text-xs text-muted-foreground">
              Track rolling impact momentum by narrative dimension over time.
            </p>
          </Link>
          <Link
            href="/protected/screenings"
            className="rounded-xl border p-5 hover:bg-muted/30 transition-colors"
          >
            <p className="text-sm font-semibold">Screenings</p>
            <p className="mt-2 text-xs text-muted-foreground">
              Filter and shortlist candidates based on your custom setup and risk profile.
            </p>
          </Link>
        </section>

        <section className="w-full max-w-7xl px-5 pb-20">
          <div className="rounded-xl border p-5 md:p-6">
            <div className="flex items-center justify-between gap-4">
              <h2 className="text-lg font-semibold">Latest News Articles</h2>
              <Link
                href="/protected/news-trends"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                View trend analytics
              </Link>
            </div>
            <Suspense
              fallback={
                <p className="mt-4 text-sm text-muted-foreground">
                  Loading latest articles...
                </p>
              }
            >
              <LatestNewsArticles />
            </Suspense>
          </div>
        </section>

        <footer className="w-full flex items-center justify-center border-t text-xs gap-8 py-10">
          <span className="text-muted-foreground">Built for research-focused swing trading workflows.</span>
          <ThemeSwitcher />
        </footer>
      </div>
    </main>
  );
}
