import Link from "next/link";
import { isSanityConfigured, sanityFetch } from "@/lib/sanity/client";
import { docPagePreviewsQuery } from "@/lib/sanity/queries";
import type { DocPagePreview } from "@/lib/sanity/types";
import { DocsSidebar } from "./_components/docs-sidebar";

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

export default async function DocsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pages = isSanityConfigured
    ? await sanityFetch<DocPagePreview[]>(docPagePreviewsQuery)
    : [];
  const grouped = groupBySection(pages);

  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="mx-auto flex max-w-7xl">
        {/* Sidebar */}
        <aside className="sticky top-[49px] hidden h-[calc(100vh-49px)] w-60 shrink-0 overflow-y-auto border-r border-border px-4 py-8 lg:block">
          <DocsSidebar grouped={grouped} />
        </aside>

        {/* Content */}
        <main className="min-w-0 flex-1 px-6 py-10 md:px-10 md:py-14">
          {children}
        </main>
      </div>
    </div>
  );
}
