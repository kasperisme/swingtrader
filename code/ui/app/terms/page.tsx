import { notFound } from "next/navigation";
import { Suspense } from "react";
import { PortableText } from "@portabletext/react";
import { isSanityConfigured, sanityFetch } from "@/lib/sanity/client";
import { legalPageBySlugQuery } from "@/lib/sanity/queries";
import { portableTextComponents } from "@/lib/sanity/portable-text-components";
import type { LegalPage } from "@/lib/sanity/types";

export const metadata = {
  title: "Terms of Service | News Impact Screener",
  description: "Terms of service for News Impact Screener.",
};

async function TermsContent() {
  if (!isSanityConfigured) {
    return (
      <div className="mx-auto max-w-3xl">
        <h1 className="text-3xl font-bold tracking-tight">Terms of Service</h1>
        <p className="mt-4 text-sm text-muted-foreground">Content unavailable — Sanity is not configured.</p>
      </div>
    );
  }

  const page = await sanityFetch<LegalPage | null>(legalPageBySlugQuery, { slug: "terms" });

  if (!page) notFound();

  return (
    <div className="mx-auto max-w-3xl">
      <h1 className="text-3xl font-bold tracking-tight leading-tight md:text-4xl">{page.title}</h1>

      {page.updatedAt ? (
        <p className="mt-3 text-sm text-muted-foreground">
          Last updated: {new Date(page.updatedAt).toLocaleDateString("en-US", { year: "numeric", month: "long", day: "numeric" })}
        </p>
      ) : null}

      {page.description ? (
        <p className="mt-5 text-lg leading-8 text-muted-foreground border-l-4 border-primary/30 pl-4">
          {page.description}
        </p>
      ) : null}

      <div className="my-8 border-b border-border" aria-hidden />

      <div className="prose prose-neutral dark:prose-invert max-w-none space-y-5 text-base">
        <PortableText value={page.body} components={portableTextComponents} />
      </div>
    </div>
  );
}

export default function TermsPage() {
  return (
    <main className="container mx-auto px-4 py-16">
      <Suspense fallback={<div className="mx-auto max-w-3xl text-sm text-muted-foreground animate-pulse">Loading…</div>}>
        <TermsContent />
      </Suspense>
    </main>
  );
}
