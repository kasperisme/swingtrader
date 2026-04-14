"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { DocPagePreview } from "@/lib/sanity/types";
import { CavemanToggle } from "@/components/caveman-toggle";

type Props = {
  grouped: { section: string; pages: DocPagePreview[] }[];
};

export function DocsSidebar({ grouped }: Props) {
  const pathname = usePathname();

  return (
    <nav className="flex flex-col gap-6 border-t border-border pt-6" aria-label="Documentation sections">
      {grouped.map(({ section, pages }) => (
        <div key={section}>
          <p className="mb-2 px-2 text-xs font-semibold uppercase tracking-widest text-muted-foreground">
            {section}
          </p>
          <ul className="flex flex-col gap-0.5">
            {pages.map((page) => {
              const href = `/docs/${page.slug}`;
              const isActive = pathname === href;
              return (
                <li key={page._id}>
                  <Link
                    href={href}
                    className={`block min-h-10 rounded-md px-3 py-2 text-sm leading-snug transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ${
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

      {/* Caveman mode toggle */}
      <div className="border-t border-border pt-4">
        <p className="mb-2 px-2 text-xs font-semibold uppercase tracking-widest text-muted-foreground">
          Reading mode
        </p>
        <CavemanToggle showLabels className="w-full justify-center" />
      </div>
    </nav>
  );
}
