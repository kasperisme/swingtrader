"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
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
    <div className="border-b border-border lg:hidden">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between px-6 py-3 text-sm font-medium"
      >
        <span className="truncate text-muted-foreground">
          {currentPage ? currentPage.title : "Browse docs"}
        </span>
        <svg
          className={`ml-2 h-4 w-4 shrink-0 text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {open && (
        <nav className="border-t border-border bg-background px-6 pb-4 pt-3">
          {grouped.map(({ section, pages }) => (
            <div key={section} className="mb-4">
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
                        className={`block rounded-md px-3 py-2 text-sm transition-colors ${
                          isActive
                            ? "bg-muted font-medium text-foreground"
                            : "text-muted-foreground hover:bg-muted/60 hover:text-foreground"
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
      )}
    </div>
  );
}
