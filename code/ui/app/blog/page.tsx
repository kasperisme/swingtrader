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
    <div className="mx-auto max-w-4xl px-6 py-14 md:py-20">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-3xl font-semibold tracking-tight">Blog</h1>
      </div>

      {posts.length === 0 ? (
        <p className="mt-8 text-sm text-muted-foreground">No posts published yet.</p>
      ) : (
        <div className="mt-8 space-y-4">
          {posts.map((post) => (
            <article key={post._id} className="rounded-xl border border-border bg-card p-6">
              <p className="text-xs text-muted-foreground">{formatDate(post.publishedAt)}</p>
              <h2 className="mt-2 text-xl font-semibold tracking-tight">
                <Link href={`/blog/${post.slug}`} className="transition-colors hover:text-primary">
                  {post.title}
                </Link>
              </h2>
              <p className="mt-3 text-sm leading-6 text-muted-foreground">{post.excerpt}</p>
              <p className="mt-3 text-xs text-muted-foreground">
                {post.authorName ? `By ${post.authorName}` : "By News Impact Screener"}
              </p>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
