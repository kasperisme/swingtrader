import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { CavemanModeToggle } from "@/components/caveman-mode-toggle";
import { CavemanContent } from "@/components/caveman-content";
import { isSanityConfigured, sanityFetch } from "@/lib/sanity/client";
import { docPageBySlugQuery, docPageSlugListQuery } from "@/lib/sanity/queries";
import type { DocPage } from "@/lib/sanity/types";

type Props = {
  params: Promise<{ slug: string }>;
};

export async function generateStaticParams() {
  // Next.js Cache Components requires at least one static param.
  const fallback = [{ slug: "getting-started" }];
  if (!isSanityConfigured) return fallback;
  const pages = await sanityFetch<{ slug: string }[]>(docPageSlugListQuery);
  const params = pages.map((p) => ({ slug: p.slug }));
  return params.length > 0 ? params : fallback;
}

export async function generateMetadata({ params }: Props) {
  const { slug } = await params;
  return {
    title: `${slug} | Docs | News Impact Screener`,
  };
}

async function DocPageDetailData({ params }: Props) {
  if (!isSanityConfigured) {
    return (
      <div className="mx-auto max-w-3xl">
        <h1 className="text-3xl font-semibold tracking-tight">Page unavailable</h1>
        <p className="mt-4 text-sm leading-6 text-muted-foreground">
          Sanity is not configured. Add <code className="rounded bg-muted px-1.5 py-0.5 text-xs font-mono">NEXT_PUBLIC_SANITY_PROJECT_ID</code> and{" "}
          <code className="rounded bg-muted px-1.5 py-0.5 text-xs font-mono">NEXT_PUBLIC_SANITY_DATASET</code> in{" "}
          <code className="rounded bg-muted px-1.5 py-0.5 text-xs font-mono">code/ui/.env.local</code>.
        </p>
      </div>
    );
  }

  const { slug } = await params;
  const page = await sanityFetch<DocPage | null>(docPageBySlugQuery, { slug });

  if (!page) {
    notFound();
  }

  return (
    <div className="mx-auto max-w-3xl">
      <Link
        href="/docs/getting-started"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 rounded-sm"
      >
        ← Documentation home
      </Link>

      <article className="mt-8">
        {page.section ? (
          <p className="text-xs font-semibold uppercase tracking-widest text-amber-500">
            {page.section}
          </p>
        ) : null}

        <h1 className="mt-3 text-3xl font-bold tracking-tight leading-tight md:text-4xl">
          {page.title}
        </h1>

        {page.description ? (
          <p className="mt-5 text-lg leading-8 text-muted-foreground border-l-4 border-primary/30 pl-4">
            {page.description}
          </p>
        ) : null}

        <div className="my-8 flex items-center gap-4">
          <div className="flex-1 border-b border-border" aria-hidden />
          <CavemanModeToggle />
        </div>

        <div className="space-y-5 text-base">
          <CavemanContent
            body={page.body ?? []}
            cavemanBody={page.cavemanBody}
          />
        </div>
      </article>

      <div className="mt-16 pt-8 border-t border-border">
        <Link
          href="/docs/getting-started"
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 rounded-sm"
        >
          ← Back to documentation
        </Link>
      </div>
    </div>
  );
}

export default function DocPageDetail({ params }: Props) {
  return (
    <Suspense
      fallback={
        <div className="mx-auto max-w-3xl text-sm text-muted-foreground animate-pulse">
          Loading doc page…
        </div>
      }
    >
      <DocPageDetailData params={params} />
    </Suspense>
  );
}
