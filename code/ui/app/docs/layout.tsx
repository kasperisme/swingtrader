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
        {/* Desktop sidebar */}
        <aside className="sticky top-16 hidden h-[calc(100vh-64px)] w-60 shrink-0 overflow-y-auto border-r border-border px-4 py-8 lg:block">
          <Suspense
            fallback={
              <div className="space-y-3 text-xs text-muted-foreground animate-pulse">
                <div className="h-3 w-20 rounded bg-muted" />
                <div className="h-3 w-28 rounded bg-muted" />
                <div className="h-3 w-24 rounded bg-muted" />
              </div>
            }
          >
            <DocsNavData mode="desktop" />
          </Suspense>
        </aside>

        {/* Content */}
        <main className="min-w-0 flex-1">
          {/* Mobile nav — inside content area, not a separate top bar */}
          <div className="lg:hidden">
            <Suspense fallback={null}>
              <DocsNavData mode="mobile" />
            </Suspense>
          </div>
          <div className="px-4 py-8 sm:px-6 md:px-10 md:py-14">
            <Suspense
              fallback={
                <div className="max-w-2xl text-sm text-muted-foreground animate-pulse">
                  Loading docs...
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
