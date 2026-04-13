import Link from "next/link";
import { headers } from "next/headers";
import { notFound } from "next/navigation";
import { PortableText } from "@portabletext/react";
import { ShareButtons } from "./share-buttons";
import type { PortableTextComponents } from "@portabletext/react";
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

const portableTextComponents: PortableTextComponents = {
  block: {
    normal: ({ children }) => (
      <p className="leading-8 text-foreground/90">{children}</p>
    ),
    h1: ({ children }) => (
      <h1 className="mt-12 mb-4 text-3xl font-bold tracking-tight text-foreground">{children}</h1>
    ),
    h2: ({ children }) => (
      <h2 className="mt-10 mb-3 text-2xl font-semibold tracking-tight text-foreground">{children}</h2>
    ),
    h3: ({ children }) => (
      <h3 className="mt-8 mb-2 text-xl font-semibold tracking-tight text-foreground">{children}</h3>
    ),
    h4: ({ children }) => (
      <h4 className="mt-6 mb-2 text-lg font-semibold text-foreground">{children}</h4>
    ),
    blockquote: ({ children }) => (
      <blockquote className="my-6 border-l-4 border-primary/40 pl-5 italic text-muted-foreground leading-8">
        {children}
      </blockquote>
    ),
  },
  list: {
    bullet: ({ children }) => (
      <ul className="my-5 list-disc pl-6 space-y-2 text-foreground/90 leading-7">{children}</ul>
    ),
    number: ({ children }) => (
      <ol className="my-5 list-decimal pl-6 space-y-2 text-foreground/90 leading-7">{children}</ol>
    ),
  },
  listItem: {
    bullet: ({ children }) => <li>{children}</li>,
    number: ({ children }) => <li>{children}</li>,
  },
  marks: {
    strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
    em: ({ children }) => <em className="italic">{children}</em>,
    code: ({ children }) => (
      <code className="rounded bg-muted px-1.5 py-0.5 text-sm font-mono text-foreground">
        {children}
      </code>
    ),
    link: ({ value, children }) => {
      const href = value?.href ?? "#";
      const isExternal = href.startsWith("http");
      return (
        <a
          href={href}
          target={isExternal ? "_blank" : undefined}
          rel={isExternal ? "noopener noreferrer" : undefined}
          className="text-primary underline underline-offset-4 hover:text-primary/80 transition-colors"
        >
          {children}
        </a>
      );
    },
  },
  types: {
    image: ({ value }) => {
      if (!value?.asset) return null;
      return (
        <figure className="my-8">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={value.asset.url}
            alt={value.alt ?? ""}
            className="w-full rounded-lg border border-border object-cover"
          />
          {value.caption && (
            <figcaption className="mt-2 text-center text-xs text-muted-foreground">
              {value.caption}
            </figcaption>
          )}
        </figure>
      );
    },
  },
};

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

        {/* Divider + share */}
        <div className="my-8 flex items-center gap-4">
          <hr className="flex-1 border-border" />
          <ShareButtons title={post.title} url={canonicalUrl} />
        </div>

        {/* Body */}
        <div className="prose-custom space-y-5">
          {post.body && post.body.length > 0 ? (
            <PortableText value={post.body} components={portableTextComponents} />
          ) : (
            <p className="text-muted-foreground">Post content is not available yet.</p>
          )}
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
