"use client";

import Link from "next/link";
import { ChevronDown } from "lucide-react";
import {
  navDropdownItemClass,
  navDropdownPanelClass,
  navDropdownTriggerClass,
} from "@/components/site-header-nav-classes";

function closeContainingDetails(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return;
  const details = target.closest("details");
  if (details) details.open = false;
}

function NavDropLink({
  href,
  children,
}: {
  href: string;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      className={navDropdownItemClass}
      onClick={(e) => closeContainingDetails(e.currentTarget)}
    >
      {children}
    </Link>
  );
}

export function SiteHeaderDesktopAuthedNav() {
  return (
    <nav className="hidden min-w-0 items-center gap-2 md:flex">
      <Link href="/protected" className="text-sm font-medium text-foreground transition-colors hover:text-amber-500 cursor-pointer">
        Portfolio
      </Link>
      <details className="group relative" name="desktop-main-nav">
        <summary className={navDropdownTriggerClass}>
          <span>Research</span>
          <ChevronDown className="ml-1 h-3.5 w-3.5 transition-transform duration-200 group-open:rotate-180" />
        </summary>
        <div className={navDropdownPanelClass}>
          <NavDropLink href="/protected/articles">Articles</NavDropLink>
          <NavDropLink href="/protected/news-trends">News Trends</NavDropLink>
          <NavDropLink href="/protected/charts">Charts</NavDropLink>
          <NavDropLink href="/protected/relationships">Explore</NavDropLink>
        </div>
      </details>
      <details className="group relative" name="desktop-main-nav">
        <summary className={navDropdownTriggerClass}>
          <span>Operations</span>
          <ChevronDown className="ml-1 h-3.5 w-3.5 transition-transform duration-200 group-open:rotate-180" />
        </summary>
        <div className={navDropdownPanelClass}>
          <NavDropLink href="/protected/screenings">Screenings</NavDropLink>
          <NavDropLink href="/protected/daily-narrative">Daily Narrative</NavDropLink>
          <NavDropLink href="/protected/trades">Trades</NavDropLink>
        </div>
      </details>
    </nav>
  );
}
