"use client";

import { useEffect, useId, useState } from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import { Menu, X, LogOut } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import { CavemanToggle } from "@/components/caveman-toggle";

const portfolioLinks = [
  { href: "/protected", label: "Portfolio" },
] as const;

const researchLinks = [
  { href: "/protected/articles", label: "Articles" },
  { href: "/protected/news-trends", label: "News Trends" },
  { href: "/protected/charts", label: "Charts" },
  { href: "/protected/relations", label: "Relations" },
] as const;

const operationsLinks = [
  { href: "/protected/screenings", label: "Screenings" },
  { href: "/protected/agents", label: "Agents" },
  { href: "/protected/daily-narrative", label: "Daily Narrative" },
  { href: "/protected/trades", label: "Trades" },
] as const;

const publicLinks = [
  { href: "/pricing", label: "Pricing" },
  { href: "/docs", label: "Docs" },
  { href: "/blog", label: "Blog" },
  { href: "/changelog", label: "Changelog" },
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
  const router = useRouter();

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
    router.push("/auth/login");
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

          {/* Drawer */}
          <div
            id={panelId}
            role="dialog"
            aria-modal="true"
            aria-label="Site navigation"
            className="absolute inset-y-0 left-0 flex w-[min(100%,20rem)] flex-col border-r border-border bg-card shadow-2xl"
          >
            {/* Drawer header */}
            <div className="flex h-16 shrink-0 items-center justify-between border-b border-border px-5">
              <div className="flex items-center gap-2">
                <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />
                <span className="text-sm font-semibold tracking-tight">newsimpactscreener</span>
              </div>
              <button
                type="button"
                className="inline-flex h-8 w-8 cursor-pointer items-center justify-center rounded-lg border border-border bg-background transition-colors hover:bg-muted"
                onClick={close}
                aria-label="Close navigation menu"
              >
                <X className="h-4 w-4" aria-hidden />
              </button>
            </div>

            {/* Nav content */}
            <nav className="min-h-0 flex-1 overflow-y-auto p-4 space-y-6">
              {isLoggedIn ? (
                <>
                  <div>
                    <p className={sectionLabelClass}>Ops center</p>
                    <ul className="space-y-0.5">
                      {portfolioLinks.map(({ href, label }) => (
                        <NavLink key={href} href={href} label={label} onClick={close} />
                      ))}
                    </ul>
                  </div>

                  <div>
                    <p className={sectionLabelClass}>Research</p>
                    <ul className="space-y-0.5">
                      {researchLinks.map(({ href, label }) => (
                        <NavLink key={href} href={href} label={label} onClick={close} />
                      ))}
                    </ul>
                  </div>

                  <div>
                    <p className={sectionLabelClass}>Operations</p>
                    <ul className="space-y-0.5">
                      {operationsLinks.map(({ href, label }) => (
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
                      <NavLink href="/protected/profile" label="Profile" onClick={close} />
                    </ul>
                  </div>
                </>
              ) : (
                <div>
                  <p className={sectionLabelClass}>Navigation</p>
                  <ul className="space-y-0.5">
                    {publicLinks.map(({ href, label }) => (
                      <NavLink key={href} href={href} label={label} onClick={close} />
                    ))}
                  </ul>
                </div>
              )}
            </nav>

            {/* Caveman toggle */}
            <div className="shrink-0 border-t border-border px-4 py-3">
              <p className={cn(sectionLabelClass, "mb-2")}>Mode</p>
              <CavemanToggle showLabels className="w-full justify-center" />
            </div>

            {/* Drawer footer */}
            <div className="shrink-0 border-t border-border p-4">
              {isLoggedIn ? (
                <div className="space-y-2">
                  {email && (
                    <p className="truncate px-3 text-xs text-muted-foreground">{email}</p>
                  )}
                  <button
                    type="button"
                    onClick={handleLogout}
                    className={cn(
                      linkClass,
                      "flex w-full items-center gap-2 text-muted-foreground hover:text-foreground",
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
