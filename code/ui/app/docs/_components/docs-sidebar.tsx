"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { DocPagePreview } from "@/lib/sanity/types";

type Props = {
  grouped: { section: string; pages: DocPagePreview[] }[];
};

export function DocsSidebar({ grouped }: Props) {
  const pathname = usePathname();

  return (
    <nav className="flex flex-col gap-6">
      {grouped.map(({ section, pages }) => (
        <div key={section}>
          <p className="mb-2 text-xs font-semibold uppercase tracking-widest text-muted-foreground">
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
                    className={`block rounded-md px-3 py-1.5 text-sm transition-colors ${
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
  );
}
