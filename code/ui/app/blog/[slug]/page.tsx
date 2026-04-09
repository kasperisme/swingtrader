import { notFound } from "next/navigation";
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

  return (
    <div className="mx-auto max-w-3xl px-6 py-14 md:py-20">
      <article className="mt-6">
        <p className="text-xs text-muted-foreground">{formatDate(post.publishedAt)}</p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight md:text-4xl">{post.title}</h1>
        <p className="mt-3 text-sm text-muted-foreground">
          {post.authorName ? `By ${post.authorName}` : "By News Impact Screener"}
        </p>

        {post.excerpt ? (
          <p className="mt-6 rounded-lg border border-border bg-card p-4 text-sm leading-6 text-muted-foreground">
            {post.excerpt}
          </p>
        ) : null}

        <div className="mt-8 space-y-4 text-base leading-7 text-foreground/95">
          {post.bodyText ? (
            post.bodyText.split("\n").map((paragraph, index) => (
              <p key={`${post._id}-${index}`}>{paragraph}</p>
            ))
          ) : (
            <p>Post content is not available yet.</p>
          )}
        </div>
      </article>
    </div>
  );
}
