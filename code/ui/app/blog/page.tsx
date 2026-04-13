import Link from "next/link";
import { isSanityConfigured, sanityFetch } from "@/lib/sanity/client";
import { blogPostPreviewsQuery } from "@/lib/sanity/queries";
import type { BlogPostPreview } from "@/lib/sanity/types";

function formatDate(date: string): string {
  const parsed = new Date(date);
  if (Number.isNaN(parsed.getTime())) return "Unscheduled";
  return new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "short",
    day: "2-digit",
  }).format(parsed);
}

export default async function BlogPage() {
  if (!isSanityConfigured) {
    return (
      <div className="mx-auto max-w-3xl px-6 py-20">
        <h1 className="text-3xl font-semibold tracking-tight">Blog</h1>
        <p className="mt-4 text-sm leading-6 text-muted-foreground">
          Sanity is not configured yet. Set `NEXT_PUBLIC_SANITY_PROJECT_ID` and
          `NEXT_PUBLIC_SANITY_DATASET` in `code/ui/.env.local` to enable blog content.
        </p>
      </div>
    );
  }

  const posts = await sanityFetch<BlogPostPreview[]>(blogPostPreviewsQuery);

  return (
    <div className="mx-auto max-w-4xl px-4 py-12 sm:px-6 md:py-20">
      {/* Header */}
      <div className="mb-12">
        <h1 className="text-4xl font-bold tracking-tight">Blog</h1>
        <p className="mt-3 text-base text-muted-foreground">
          Market analysis, news impact breakdowns, and swing trading insights.
        </p>
      </div>

      {posts.length === 0 ? (
        <p className="text-sm text-muted-foreground">No posts published yet.</p>
      ) : (
        <div className="divide-y divide-border">
          {posts.map((post, index) => (
            <article key={post._id} className={index === 0 ? "pb-10" : "py-10"}>
              {/* Meta row */}
              <div className="flex items-center gap-3 text-xs text-muted-foreground">
                <time dateTime={post.publishedAt}>{formatDate(post.publishedAt)}</time>
                {post.readingTimeMinutes != null && post.readingTimeMinutes > 0 && (
                  <>
                    <span aria-hidden>·</span>
                    <span>{post.readingTimeMinutes} min read</span>
                  </>
                )}
              </div>

              {/* Title */}
              <h2 className="mt-3 text-2xl font-semibold tracking-tight leading-snug">
                <Link
                  href={`/blog/${post.slug}`}
                  className="hover:text-primary transition-colors"
                >
                  {post.title}
                </Link>
              </h2>

              {/* Excerpt */}
              {post.excerpt && (
                <p className="mt-3 text-base leading-7 text-muted-foreground line-clamp-3">
                  {post.excerpt}
                </p>
              )}

              {/* Footer row */}
              <div className="mt-5 flex items-center justify-between">
                <p className="text-xs text-muted-foreground">
                  {post.authorName ? `By ${post.authorName}` : "By News Impact Screener"}
                </p>
                <Link
                  href={`/blog/${post.slug}`}
                  className="text-xs font-medium text-primary hover:underline"
                >
                  Read more →
                </Link>
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
