import Image from "next/image";
import Link from "next/link";
import { UserCircle } from "lucide-react";
import { createClient } from "@/lib/supabase/server";
import { Button } from "@/components/ui/button";
import { SiteHeaderMobileNav } from "@/components/site-header-mobile-nav";
import { SiteHeaderDesktopAuthedNav } from "@/components/site-header-desktop-authed-nav";
import { CavemanToggle } from "@/components/caveman-toggle";

function Logo() {
  return (
    <Link href="/" className="inline-flex items-center gap-2 shrink-0 cursor-pointer">
      <Image
        src="/icon.png"
        alt="newsimpactscreener logo"
        width={20}
        height={20}
        className="rounded-sm"
      />
      <span className="text-sm font-semibold tracking-tight">
        newsimpactscreener
      </span>
    </Link>
  );
}

const navLinkClass =
  "text-sm font-medium text-muted-foreground transition-colors hover:text-foreground cursor-pointer";
function HeaderShell({ children }: { children: React.ReactNode }) {
  return (
    <header className="sticky top-0 z-50 px-4 pt-4 pb-2">
      <div className="mx-auto flex h-14 w-full max-w-7xl items-center justify-between rounded-2xl border border-border bg-background/80 px-4 shadow-lg backdrop-blur-md lg:px-6">
        {children}
      </div>
    </header>
  );
}

export function SiteHeaderFallback() {
  return (
    <HeaderShell>
      <div className="flex min-w-0 flex-1 items-center">
        <Logo />
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <Link href="/pricing" className={`${navLinkClass} hidden md:inline`}>Pricing</Link>
        <Link href="/docs" className={`${navLinkClass} hidden md:inline`}>Docs</Link>
        <Link href="/blog" className={`${navLinkClass} hidden md:inline`}>Blog</Link>
        <Link href="/changelog" className={`${navLinkClass} hidden md:inline`}>Changelog</Link>
        <Button asChild size="sm" variant="outline" className="hidden md:inline-flex">
          <Link href="/auth/login">Sign in</Link>
        </Button>
        <Button asChild size="sm" className="hidden md:inline-flex">
          <Link href="/auth/sign-up">Sign up</Link>
        </Button>
        {/* Fallback hamburger placeholder — reserves space, invisible */}
        <div className="h-8 w-8 md:hidden" />
      </div>
    </HeaderShell>
  );
}

export async function SiteHeader() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  const isAuthed = Boolean(user);

  return (
    <HeaderShell>
      {/* Left: logo + desktop dropdown nav */}
      <div className="flex min-w-0 flex-1 items-center gap-3 md:gap-6">
        <Logo />
        {isAuthed && <SiteHeaderDesktopAuthedNav />}
      </div>

      {/* Right: desktop links + hamburger (mobile only, always rightmost) */}
      {isAuthed ? (
        <div className="flex shrink-0 items-center gap-3">
          <Link href="/pricing" className={`${navLinkClass} hidden md:inline`}>Pricing</Link>
          <Link href="/docs" className={`${navLinkClass} hidden md:inline`}>Docs</Link>
          <Link href="/blog" className={`${navLinkClass} hidden md:inline`}>Blog</Link>
          <Link href="/changelog" className={`${navLinkClass} hidden md:inline`}>Changelog</Link>
          <CavemanToggle className="hidden md:flex" />
          <Link
            href="/protected/profile"
            className="hidden md:inline-flex items-center justify-center h-8 w-8 rounded-lg border border-border bg-background/80 text-muted-foreground transition-colors hover:text-foreground hover:bg-muted"
            aria-label="Profile"
          >
            <UserCircle className="h-4 w-4" />
          </Link>
          <SiteHeaderMobileNav isAuthed={isAuthed} userEmail={user?.email} />
        </div>
      ) : (
        <div className="flex shrink-0 items-center gap-2">
          <Link href="/pricing" className={`${navLinkClass} hidden md:inline`}>Pricing</Link>
          <Link href="/docs" className={`${navLinkClass} hidden md:inline`}>Docs</Link>
          <Link href="/blog" className={`${navLinkClass} hidden md:inline`}>Blog</Link>
          <Link href="/changelog" className={`${navLinkClass} hidden md:inline`}>Changelog</Link>
          <CavemanToggle className="hidden md:flex" />
          <Button asChild size="sm" variant="outline" className="hidden md:inline-flex">
            <Link href="/auth/login">Sign in</Link>
          </Button>
          <Button asChild size="sm" className="hidden md:inline-flex">
            <Link href="/auth/sign-up">Sign up</Link>
          </Button>
          <SiteHeaderMobileNav isAuthed={isAuthed} userEmail={user?.email} />
        </div>
      )}
    </HeaderShell>
  );
}
