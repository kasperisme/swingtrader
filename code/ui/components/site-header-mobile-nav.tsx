"use client";

import { useEffect, useId, useState } from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import { Menu, X, LogOut, UserCircle } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { cn } from "@/lib/utils";
import { CavemanToggle } from "@/components/caveman-toggle";
import { HelpChatTrigger } from "@/components/help-chat";
import {
  FREE_SERVICE_LINKS,
  INSIGHTS_LINKS,
} from "@/components/site-header-public-nav";

/**
 * The authed user's own workspace, as one section.
 *
 * This used to be two: an "Ops center" heading over a single "Overview" link,
 * and an "Operations" heading over the rest — with Insights and Free services
 * sitting between them, so the two halves of the same area were separated by
 * two unrelated sections. On desktop the split earns its keep (Overview is a
 * top-level link, Operations is a dropdown); in a flat drawer it was a heading
 * introducing one item.
 */
const operationsLinks = [
  { href: "/protected", label: "Overview" },
  { href: "/protected/workspace", label: "Workspace" },
  { href: "/protected/agents", label: "Agents" },
  { href: "/protected/trades", label: "Trades" },
] as const;

const publicLinks = [
  { href: "/pricing", label: "Pricing" },
  { href: "/docs", label: "Docs" },
  { href: "/blog", label: "Blog" },
] as const;

const linkClass =
  "block rounded-xl px-3 py-2.5 text-sm font-medium text-foreground transition-colors hover:bg-muted cursor-pointer";

const sectionLabelClass =
  "mb-2 px-3 text-xs font-semibold uppercase tracking-widest text-amber-500";

function NavLink({ href, label, onClick }: { href: string; label: string; onClick: () => void }) {
  return (
    <li>
      <Link href={href} className={linkClass} onClick={onClick}>
        {label}
      </Link>
    </li>
  );
}

type Props = {
  isAuthed: boolean;
  userEmail?: string | null;
};

export function SiteHeaderMobileNav({ isAuthed, userEmail }: Props) {
  const [open, setOpen] = useState(false);
  const [isLoggedIn, setIsLoggedIn] = useState(isAuthed);
  const [email, setEmail] = useState(userEmail);
  const panelId = useId();

  const close = () => setOpen(false);

  // Keep auth state in sync client-side so protected links always reflect
  // the real session (handles client-side logins/logouts and stale SSR props).
  useEffect(() => {
    const supabase = createClient();

    supabase.auth.getSession().then(({ data: { session } }) => {
      setIsLoggedIn(Boolean(session?.user));
      setEmail(session?.user?.email ?? null);
    });

    const { data: { subscription } } = supabase.auth.onAuthStateChange((_, session) => {
      setIsLoggedIn(Boolean(session?.user));
      setEmail(session?.user?.email ?? null);
    });

    return () => subscription.unsubscribe();
  }, []);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  useEffect(() => {
    document.body.style.overflow = open ? "hidden" : "";
    return () => { document.body.style.overflow = ""; };
  }, [open]);

  const handleLogout = async () => {
    close();
    const supabase = createClient();
    await supabase.auth.signOut();
    window.location.href = "/auth/login";
  };

  return (
    <>
      {/* Hamburger — always shown on mobile */}
      <button
        type="button"
        className="inline-flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-lg border border-border bg-background/80 transition-colors hover:bg-muted md:hidden"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen(true)}
        aria-label="Open navigation menu"
      >
        <Menu className="h-4 w-4" aria-hidden />
      </button>

      {open && createPortal(
        <div className="fixed inset-0 z-[10000]">
          {/* Backdrop */}
          <button
            type="button"
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            aria-label="Close menu"
            onClick={close}
          />

          {/* Close — outside the panel, on the backdrop.
              It used to own a 64px header band inside the drawer, which cost a
              tenth of the screen to hold one 32px button and pushed the links
              down. Out here the nav starts at the top edge and fills the whole
              height.

              Vertically centred on the drawer, so it reads as a handle on the
              panel's edge rather than a stray control floating in the corner,
              and it sits where a thumb already rests.

              The offset clamps: `20rem` normally puts it just clear of the
              drawer, but on a viewport narrower than the drawer itself (where
              the panel goes full-width) `100% - 3rem` keeps it on screen at the
              panel's right edge instead of off it. Escape and a backdrop tap
              close too, so this is never the only way out. */}
          <button
            type="button"
            className="absolute left-[min(calc(100%-3rem),20rem)] top-1/2 ml-2 inline-flex h-9 w-9 -translate-y-1/2 cursor-pointer items-center justify-center rounded-lg border border-border bg-background text-foreground shadow-lg transition-colors hover:bg-muted"
            onClick={close}
            aria-label="Close navigation menu"
          >
            <X className="h-4 w-4" aria-hidden />
          </button>

          {/* Drawer */}
          <div
            id={panelId}
            role="dialog"
            aria-modal="true"
            aria-label="Site navigation"
            className="absolute inset-y-0 left-0 flex w-[min(100%,20rem)] flex-col border-r border-border bg-card shadow-2xl"
          >
            {/* Nav content */}
            <nav className="min-h-0 flex-1 overflow-y-auto p-4 space-y-6">
              {isLoggedIn ? (
                <>
                  <div>
                    <p className={sectionLabelClass}>Operations</p>
                    <ul className="space-y-0.5">
                      {operationsLinks.map(({ href, label }) => (
                        <NavLink key={href} href={href} label={label} onClick={close} />
                      ))}
                    </ul>
                  </div>

                  <div>
                    <p className={sectionLabelClass}>Insights</p>
                    <ul className="space-y-0.5">
                      {INSIGHTS_LINKS.map(({ href, label }) => (
                        <NavLink key={href} href={href} label={label} onClick={close} />
                      ))}
                    </ul>
                  </div>

                  <div>
                    <p className={sectionLabelClass}>Free services</p>
                    <ul className="space-y-0.5">
                      {FREE_SERVICE_LINKS.map(({ href, label }) => (
                        <NavLink key={href} href={href} label={label} onClick={close} />
                      ))}
                    </ul>
                  </div>

                  <div>
                    <p className={sectionLabelClass}>More</p>
                    <ul className="space-y-0.5">
                      {publicLinks.map(({ href, label }) => (
                        <NavLink key={href} href={href} label={label} onClick={close} />
                      ))}
                    </ul>
                  </div>
                </>
              ) : (
                <>
                  <div>
                    <p className={sectionLabelClass}>Insights</p>
                    <ul className="space-y-0.5">
                      {INSIGHTS_LINKS.map(({ href, label }) => (
                        <NavLink key={href} href={href} label={label} onClick={close} />
                      ))}
                    </ul>
                  </div>
                  <div>
                    <p className={sectionLabelClass}>Free services</p>
                    <ul className="space-y-0.5">
                      {FREE_SERVICE_LINKS.map(({ href, label }) => (
                        <NavLink key={href} href={href} label={label} onClick={close} />
                      ))}
                    </ul>
                  </div>
                  <div>
                    <p className={sectionLabelClass}>Navigation</p>
                    <ul className="space-y-0.5">
                      {publicLinks.map(({ href, label }) => (
                        <NavLink key={href} href={href} label={label} onClick={close} />
                      ))}
                    </ul>
                  </div>
                </>
              )}
            </nav>

            {/* Footer utilities — Ask AI and the reading-mode toggle share a row.
                Both are controls rather than destinations, and neither needs a
                line of its own: stacked they cost two bands plus a "Mode" label
                to announce what the toggle already shows. Pinned below the
                scroll area so they stay reachable at any scroll position. */}
            <div className="shrink-0 border-t border-border px-4 py-3">
              <div className="flex items-center justify-between gap-3">
                {isLoggedIn ? (
                  <span onClick={close}>
                    <HelpChatTrigger className="-ml-2 inline-flex cursor-pointer items-center gap-2 rounded-xl px-2 py-2 text-sm font-medium text-amber-600 transition-colors hover:bg-muted dark:text-amber-400" />
                  </span>
                ) : (
                  /* Holds the toggle hard right for signed-out users too. */
                  <span aria-hidden />
                )}
                <CavemanToggle showLabels />
              </div>
            </div>

            {/* Drawer footer */}
            <div className="shrink-0 border-t border-border p-4">
              {isLoggedIn ? (
                /* Profile sits here rather than under "More" with Pricing,
                   Docs and Blog. Those are marketing pages any visitor can
                   read; Profile is this account, which is what the rest of
                   this footer is already about — the address above it and the
                   way out below it. */
                <div className="flex items-center justify-between gap-2">
                  {/* The address IS the profile link. A "Profile" row under the
                      email was a label for the thing directly above it, and the
                      address says whose account it is better than the word does.
                      Falls back to "Profile" only if the email is unavailable. */}
                  <Link
                    href="/protected/profile"
                    onClick={close}
                    className={cn(
                      linkClass,
                      "flex min-w-0 flex-1 items-center gap-2 text-muted-foreground hover:text-foreground",
                    )}
                  >
                    <UserCircle className="h-4 w-4 shrink-0" />
                    <span className="truncate">{email ?? "Profile"}</span>
                  </Link>
                  <button
                    type="button"
                    onClick={handleLogout}
                    aria-label="Sign out"
                    title="Sign out"
                    className={cn(
                      linkClass,
                      "flex shrink-0 items-center gap-2 text-muted-foreground hover:text-foreground",
                    )}
                  >
                    <LogOut className="h-4 w-4" />
                    Sign out
                  </button>
                </div>
              ) : (
                <div className="flex flex-col gap-2">
                  <Link
                    href="/auth/login"
                    onClick={close}
                    className="block rounded-xl border border-border px-4 py-2.5 text-center text-sm font-semibold transition-colors hover:bg-muted cursor-pointer"
                  >
                    Sign in
                  </Link>
                  <Link
                    href="/auth/sign-up"
                    onClick={close}
                    className="block rounded-xl bg-violet-600 px-4 py-2.5 text-center text-sm font-semibold text-white transition-colors hover:bg-violet-500 cursor-pointer"
                  >
                    Sign up
                  </Link>
                </div>
              )}
            </div>
          </div>
        </div>,
        document.body
      )}
    </>
  );
}
