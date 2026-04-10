"use client";

import { useEffect, useId, useState } from "react";
import Link from "next/link";
import { Menu, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const primaryLinks = [
  { href: "/protected", label: "Articles" },
  { href: "/protected/news-trends", label: "News Trends" },
  { href: "/protected/vectors", label: "Vectors" },
  { href: "/protected/screenings", label: "Screenings" },
  { href: "/protected/trades", label: "Trades" },
] as const;

const secondaryLinks = [
  { href: "/docs", label: "Docs" },
  { href: "/blog", label: "Blog" },
  { href: "/protected/profile", label: "Profile" },
] as const;

const linkClass =
  "block rounded-md px-3 py-2.5 text-sm font-medium text-foreground transition-colors hover:bg-muted";

export function SiteHeaderMobileNav({ userEmail }: { userEmail: string | null | undefined }) {
  const [open, setOpen] = useState(false);
  const panelId = useId();

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  useEffect(() => {
    if (open) document.body.style.overflow = "hidden";
    else document.body.style.overflow = "";
    return () => {
      document.body.style.overflow = "";
    };
  }, [open]);

  return (
    <>
      <Button
        type="button"
        variant="outline"
        size="icon"
        className="shrink-0 md:hidden"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen(true)}
      >
        <Menu className="h-5 w-5" aria-hidden />
        <span className="sr-only">Open navigation menu</span>
      </Button>

      {open ? (
        <div className="fixed inset-0 z-[100] md:hidden">
          <button
            type="button"
            className="absolute inset-0 bg-black/50"
            aria-label="Close menu"
            onClick={() => setOpen(false)}
          />
          <div
            id={panelId}
            role="dialog"
            aria-modal="true"
            aria-label="Site navigation"
            className={cn(
              "absolute inset-y-0 left-0 flex w-[min(100%,20rem)] flex-col border-r border-border bg-background shadow-lg",
            )}
          >
            <div className="flex h-16 shrink-0 items-center justify-between border-b border-border px-4">
              <span className="text-sm font-semibold">Menu</span>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                onClick={() => setOpen(false)}
                aria-label="Close navigation menu"
              >
                <X className="h-5 w-5" aria-hidden />
              </Button>
            </div>
            <nav
              className="min-h-0 flex-1 overflow-y-auto p-4"
              onClick={(e) => {
                if ((e.target as HTMLElement).closest("a")) setOpen(false);
              }}
            >
              <p className="mb-2 px-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                App
              </p>
              <ul className="space-y-0.5">
                {primaryLinks.map(({ href, label }) => (
                  <li key={href}>
                    <Link href={href} className={linkClass}>
                      {label}
                    </Link>
                  </li>
                ))}
              </ul>
              <div className="my-4 border-t border-border" />
              <p className="mb-2 px-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                More
              </p>
              <ul className="space-y-0.5">
                {secondaryLinks.map(({ href, label }) => (
                  <li key={href}>
                    <Link href={href} className={linkClass}>
                      {label}
                    </Link>
                  </li>
                ))}
              </ul>
              {userEmail ? (
                <p className="mt-4 truncate px-3 text-xs text-muted-foreground">{userEmail}</p>
              ) : null}
            </nav>
          </div>
        </div>
      ) : null}
    </>
  );
}
