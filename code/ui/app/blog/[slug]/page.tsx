import Link from "next/link";
import { headers } from "next/headers";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { ShareButtons } from "./share-buttons";
import { CavemanModeToggle } from "@/components/caveman-mode-toggle";
import { CavemanContent } from "@/components/caveman-content";
import { isSanityConfigured, sanityFetch } from "@/lib/sanity/client";
import { blogPostBySlugQuery } from "@/lib/sanity/queries";
import type { BlogPost } from "@/lib/sanity/types";

function formatDate(date: string): string {
  const parsed = new Date(date);
  if (Number.isNaN(parsed.getTime())) return "Unscheduled";
  return new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "long",
    day: "2-digit",
  }).format(parsed);
}

type Props = {
  params: Promise<{ slug: string }>;
};

export default async function BlogPostPage({ params }: Props) {
  if (!isSanityConfigured) {
    return (
      <div className="mx-auto max-w-3xl px-6 py-20">
        <h1 className="text-3xl font-semibold tracking-tight">Blog post unavailable</h1>
        <p className="mt-4 text-sm leading-6 text-muted-foreground">
          Sanity is not configured yet. Add `NEXT_PUBLIC_SANITY_PROJECT_ID` and
          `NEXT_PUBLIC_SANITY_DATASET` in `code/ui/.env.local`.
        </p>
      </div>
    );
  }

  const { slug } = await params;
  const post = await sanityFetch<BlogPost | null>(blogPostBySlugQuery, { slug });

  if (!post) {
    notFound();
  }

  const headersList = await headers();
  const host = headersList.get("host") ?? "www.newsimpactscreener.com";
  const protocol = host.startsWith("localhost") ? "http" : "https";
  const canonicalUrl = `${protocol}://${host}/blog/${slug}`;

  return (
    <div className="mx-auto max-w-3xl px-4 py-12 sm:px-6 md:py-20">
      {/* Back link */}
      <Link
        href="/blog"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
      >
        ← All posts
      </Link>

      <article className="mt-8">
        {/* Meta */}
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <time dateTime={post.publishedAt}>{formatDate(post.publishedAt)}</time>
          {post.readingTimeMinutes != null && post.readingTimeMinutes > 0 && (
            <>
              <span aria-hidden>·</span>
              <span>{post.readingTimeMinutes} min read</span>
            </>
          )}
          {post.authorName && (
            <>
              <span aria-hidden>·</span>
              <span>{post.authorName}</span>
            </>
          )}
        </div>

        {/* Title */}
        <h1 className="mt-4 text-3xl font-bold tracking-tight leading-tight md:text-4xl">
          {post.title}
        </h1>

        {/* Excerpt / lede */}
        {post.excerpt && (
          <p className="mt-5 text-lg leading-8 text-muted-foreground border-l-4 border-primary/30 pl-4">
            {post.excerpt}
          </p>
        )}

        {/* Divider + share + caveman toggle */}
        <div className="my-8 flex items-center gap-4">
          <hr className="flex-1 border-border" />
          <Suspense>
            <CavemanModeToggle />
          </Suspense>
          <ShareButtons title={post.title} url={canonicalUrl} />
        </div>

        {/* Body */}
        <div className="prose-custom space-y-5">
          <Suspense
            fallback={
              <div className="animate-pulse space-y-3">
                <div className="h-4 rounded bg-muted w-3/4" />
                <div className="h-4 rounded bg-muted w-full" />
                <div className="h-4 rounded bg-muted w-5/6" />
              </div>
            }
          >
            <CavemanContent
              body={post.body}
              cavemanBody={post.cavemanBody}
              emptyFallback="Post content is not available yet."
            />
          </Suspense>
        </div>
      </article>

      {/* Footer nav */}
      <div className="mt-16 pt-8 border-t border-border flex items-center justify-between gap-4 flex-wrap">
        <Link
          href="/blog"
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          ← Back to all posts
        </Link>
        <ShareButtons title={post.title} url={canonicalUrl} />
      </div>
    </div>
  );
}
