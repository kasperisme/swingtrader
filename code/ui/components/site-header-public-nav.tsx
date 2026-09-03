"use client";

import Link from "next/link";
import { ChevronDown } from "lucide-react";
import { navDropdownItemClass, navDropdownPanelRightClass } from "@/components/site-header-nav-classes";

/**
 * The public half of the desktop header: the two menus every visitor gets,
 * logged in or not.
 *
 * These used to be flat links, which left /topics and /quote with no nav entry
 * at all — the hubs were only reachable from an article you'd already opened.
 * Grouping them keeps the header from growing a link per hub:
 *   · Insights      — the free research surfaces (read something)
 *   · Free services — the no-account products (sign up for something)
 */

export const INSIGHTS_LINKS = [
  { href: "/articles", label: "Articles" },
  { href: "/topics", label: "Topics" },
  { href: "/quote", label: "Quotes" },
  // Nine AI agents trading $100k paper accounts against each other on different
  // slices of this data. It is the most legible thing on the site — a
  // leaderboard needs no explanation — so it sits above the write-ups.
  { href: "/arena", label: "The Arena" },
  // The reference layer behind the arena: who each agent is modelled on.
  { href: "/traders", label: "Famous Traders" },
  // The strategy lab's published write-ups. Last because it is the most
  // specialist of the five, and unlike the others it is mostly negative
  // results — worth finding, not worth leading with.
  { href: "/research", label: "Research" },
] as const;

export const FREE_SERVICE_LINKS = [
  { href: "/briefings", label: "Daily News Briefing" },
  { href: "/marketscreenings", label: "Market Screenings" },
] as const;

// Sits in the header's right cluster next to the plain text links, so it matches
// their weight rather than the uppercase left-side (authed) dropdown triggers.
const publicTriggerClass =
  "inline-flex cursor-pointer list-none items-center gap-1 rounded-md px-1 py-1.5 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground [&::-webkit-details-marker]:hidden";

function closeContainingDetails(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return;
  const details = target.closest("details");
  if (details) details.open = false;
}

function NavDropLink({ href, children }: { href: string; children: React.ReactNode }) {
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

function PublicMenu({
  label,
  links,
}: {
  label: string;
  links: readonly { href: string; label: string }[];
}) {
  return (
    // Shared `name` puts these in the same exclusive group as the authed
    // dropdowns, so opening one closes any other header menu.
    <details className="group relative hidden md:block" name="desktop-main-nav">
      <summary className={publicTriggerClass}>
        <span>{label}</span>
        <ChevronDown className="h-3.5 w-3.5 transition-transform duration-200 group-open:rotate-180" />
      </summary>
      <div className={navDropdownPanelRightClass}>
        {links.map(({ href, label: itemLabel }) => (
          <NavDropLink key={href} href={href}>
            {itemLabel}
          </NavDropLink>
        ))}
      </div>
    </details>
  );
}

export function SiteHeaderPublicNav() {
  return (
    <>
      <PublicMenu label="Insights" links={INSIGHTS_LINKS} />
      <PublicMenu label="Free services" links={FREE_SERVICE_LINKS} />
    </>
  );
}
