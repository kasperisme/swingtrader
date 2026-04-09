import { notFound } from "next/navigation";
import { Suspense } from "react";
import { PortableText } from "next-sanity";
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
      <div className="max-w-2xl">
        <h1 className="text-3xl font-semibold tracking-tight">Page unavailable</h1>
        <p className="mt-4 text-sm leading-6 text-muted-foreground">
          Sanity is not configured. Add <code>NEXT_PUBLIC_SANITY_PROJECT_ID</code> and{" "}
          <code>NEXT_PUBLIC_SANITY_DATASET</code> in <code>code/ui/.env.local</code>.
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
    <article className="max-w-2xl">
      {page.section ? (
        <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
          {page.section}
        </p>
      ) : null}
      <h1 className="mt-2 text-3xl font-semibold tracking-tight md:text-4xl">{page.title}</h1>
      {page.description ? (
        <p className="mt-4 text-base leading-7 text-muted-foreground">{page.description}</p>
      ) : null}

      {page.body?.length > 0 ? (
        <div className="mt-10 space-y-4 text-sm leading-7 text-foreground/95 [&_a]:text-primary [&_a]:underline [&_a:hover]:opacity-80 [&_code]:rounded [&_code]:bg-muted [&_code]:px-1 [&_code]:py-0.5 [&_code]:text-xs [&_h2]:mt-10 [&_h2]:text-xl [&_h2]:font-semibold [&_h2]:tracking-tight [&_h3]:mt-8 [&_h3]:text-base [&_h3]:font-semibold [&_li]:leading-7 [&_ul]:mt-3 [&_ul]:list-disc [&_ul]:pl-5 [&_ul]:space-y-2">
          <PortableText value={page.body} />
        </div>
      ) : (
        <p className="mt-10 text-sm text-muted-foreground">Content coming soon.</p>
      )}
    </article>
  );
}

export default function DocPageDetail({ params }: Props) {
  return (
    <Suspense
      fallback={
        <div className="max-w-2xl text-sm text-muted-foreground animate-pulse">
          Loading doc page...
        </div>
      }
    >
      <DocPageDetailData params={params} />
    </Suspense>
  );
}
