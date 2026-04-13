import Link from "next/link";
import { Suspense } from "react";
import { isSanityConfigured, sanityFetch } from "@/lib/sanity/client";
import { docPagePreviewsQuery } from "@/lib/sanity/queries";
import type { DocPagePreview } from "@/lib/sanity/types";
import { DocsSidebar } from "./_components/docs-sidebar";
import { DocsMobileNav } from "./_components/docs-mobile-nav";

const SECTION_ORDER = [
  "Getting Started",
  "How It Works",
  "Clusters & Dimensions",
];

function groupBySection(pages: DocPagePreview[]) {
  const map = new Map<string, DocPagePreview[]>();
  for (const page of pages) {
    const key = page.section ?? "General";
    if (!map.has(key)) map.set(key, []);
    map.get(key)!.push(page);
  }
  return Array.from(map.entries())
    .map(([section, pages]) => ({ section, pages }))
    .sort((a, b) => {
      const ai = SECTION_ORDER.indexOf(a.section);
      const bi = SECTION_ORDER.indexOf(b.section);
      if (ai === -1 && bi === -1) return a.section.localeCompare(b.section);
      if (ai === -1) return 1;
      if (bi === -1) return -1;
      return ai - bi;
    });
}

export default function DocsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="mx-auto flex max-w-7xl">
        {/* Desktop sidebar — aligned with blog: clear hierarchy, readable nav */}
        <aside className="sticky top-16 hidden h-[calc(100vh-64px)] w-64 shrink-0 overflow-y-auto border-r border-border bg-muted/20 lg:block">
          <div className="px-4 pb-4 pt-8">
            <Link
              href="/docs/getting-started"
              className="block rounded-md px-2 py-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            >
              <p className="text-xs font-semibold uppercase tracking-widest text-amber-500">Docs</p>
              <p className="mt-1 text-sm font-semibold tracking-tight text-foreground">
                Documentation
              </p>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                Guides, methodology, and reference.
              </p>
            </Link>
          </div>
          <div className="px-3 pb-8">
            <Suspense
              fallback={
                <div className="space-y-3 text-xs text-muted-foreground animate-pulse px-1">
                  <div className="h-3 w-20 rounded bg-muted" />
                  <div className="h-3 w-28 rounded bg-muted" />
                  <div className="h-3 w-24 rounded bg-muted" />
                </div>
              }
            >
              <DocsNavData mode="desktop" />
            </Suspense>
          </div>
        </aside>

        {/* Content — padding rhythm matches blog posts */}
        <main className="min-w-0 flex-1">
          <div className="lg:hidden">
            <Suspense fallback={null}>
              <DocsNavData mode="mobile" />
            </Suspense>
          </div>
          <div className="px-4 py-12 sm:px-6 md:py-20">
            <Suspense
              fallback={
                <div className="mx-auto max-w-3xl text-sm text-muted-foreground animate-pulse">
                  Loading docs…
                </div>
              }
            >
              {children}
            </Suspense>
          </div>
        </main>
      </div>
    </div>
  );
}

async function DocsNavData({ mode }: { mode: "mobile" | "desktop" }) {
  const pages = isSanityConfigured
    ? await sanityFetch<DocPagePreview[]>(docPagePreviewsQuery)
    : [];
  const grouped = groupBySection(pages);
  return mode === "mobile" ? (
    <DocsMobileNav grouped={grouped} />
  ) : (
    <DocsSidebar grouped={grouped} />
  );
}
