"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronDown } from "lucide-react";
import type { DocPagePreview } from "@/lib/sanity/types";

type Props = {
  grouped: { section: string; pages: DocPagePreview[] }[];
};

export function DocsMobileNav({ grouped }: Props) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  const currentPage = grouped
    .flatMap((g) => g.pages)
    .find((p) => pathname === `/docs/${p.slug}`);

  return (
    <div className="border-b border-border bg-muted/15 lg:hidden">
      <button
        type="button"
        id="docs-mobile-nav-trigger"
        aria-expanded={open}
        aria-controls="docs-mobile-nav-panel"
        onClick={() => setOpen((o) => !o)}
        className="flex min-h-11 w-full items-center justify-between gap-3 px-4 py-3 text-left text-sm font-medium transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset sm:px-6"
      >
        <span className="min-w-0 truncate text-foreground">
          {currentPage ? currentPage.title : "Browse documentation"}
        </span>
        <ChevronDown
          className={`h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-200 ${open ? "rotate-180" : ""}`}
          aria-hidden
        />
      </button>

      {open ? (
        <nav
          id="docs-mobile-nav-panel"
          role="region"
          aria-labelledby="docs-mobile-nav-trigger"
          className="border-t border-border bg-background px-4 pb-4 pt-3 sm:px-6"
        >
          {grouped.map(({ section, pages }) => (
            <div key={section} className="mb-4 last:mb-0">
              <p className="mb-1.5 text-xs font-semibold uppercase tracking-widest text-muted-foreground">
                {section}
              </p>
              <ul className="space-y-0.5">
                {pages.map((page) => {
                  const href = `/docs/${page.slug}`;
                  const isActive = pathname === href;
                  return (
                    <li key={page._id}>
                      <Link
                        href={href}
                        onClick={() => setOpen(false)}
                        className={`block min-h-11 rounded-md px-3 py-2.5 text-sm leading-snug transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ${
                          isActive
                            ? "bg-primary/10 font-medium text-foreground border border-primary/20"
                            : "text-muted-foreground hover:bg-muted/80 hover:text-foreground border border-transparent"
                        }`}
                      >
                        {page.title}
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </nav>
      ) : null}
    </div>
  );
}
