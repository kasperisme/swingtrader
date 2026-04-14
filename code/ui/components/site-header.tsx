import Image from "next/image";
import Link from "next/link";
import { createClient } from "@/lib/supabase/server";
import { Button } from "@/components/ui/button";
import { LogoutButton } from "@/components/logout-button";
import { SiteHeaderMobileNav } from "@/components/site-header-mobile-nav";
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
    <header className="sticky top-0 z-[9999] px-4 pt-4 pb-2">
      <div className="mx-auto flex h-14 w-full max-w-7xl items-center justify-between rounded-2xl border border-border bg-background/80 px-4 shadow-lg backdrop-blur-md lg:px-6">
        {children}
      </div>
    </header>
  );
}

export function SiteHeaderFallback() {
  return (
    <HeaderShell>
      <div className="flex min-w-0 flex-1 items-center gap-3">
        <Logo />
        {/* Fallback hamburger placeholder — same size, invisible */}
        <div className="h-8 w-8 md:hidden" />
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {/* Desktop-only inline links */}
        <Link href="/docs" className={`${navLinkClass} hidden md:inline`}>Docs</Link>
        <Link href="/blog" className={`${navLinkClass} hidden md:inline`}>Blog</Link>
        <Button asChild size="sm" variant="outline" className="hidden md:inline-flex">
          <Link href="/auth/login">Sign in</Link>
        </Button>
        <Button asChild size="sm" className="hidden md:inline-flex">
          <Link href="/auth/sign-up">Sign up</Link>
        </Button>
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
      <div className="flex min-w-0 flex-1 items-center gap-3 md:gap-6">
        <Logo />

        {/* Hamburger — always visible on mobile, handles both authed + unauthed */}
        <SiteHeaderMobileNav isAuthed={isAuthed} userEmail={user?.email} />

        {/* Desktop authenticated nav */}
        {isAuthed && (
          <nav className="hidden min-w-0 items-center gap-4 md:flex">
            <Link href="/protected" className={navLinkClass}>Articles</Link>
            <Link href="/protected/news-trends" className={navLinkClass}>News Trends</Link>
            <Link href="/protected/vectors" className={navLinkClass}>Vectors</Link>
            <Link href="/protected/screenings" className={navLinkClass}>Screenings</Link>
            <Link href="/protected/daily-narrative" className={navLinkClass}>Daily Narrative</Link>
            <Link href="/protected/trades" className={navLinkClass}>Trades</Link>
          </nav>
        )}
      </div>

      {/* Right side — desktop only */}
      {isAuthed ? (
        <div className="hidden shrink-0 items-center gap-3 md:flex">
          <Link href="/docs" className={navLinkClass}>Docs</Link>
          <Link href="/blog" className={navLinkClass}>Blog</Link>
          <CavemanToggle />
          <Link
            href="/protected/profile"
            className="text-sm text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
          >
            {user?.email ?? ""}
          </Link>
          <LogoutButton />
        </div>
      ) : (
        <div className="hidden shrink-0 items-center gap-2 md:flex">
          <Link href="/docs" className={navLinkClass}>Docs</Link>
          <Link href="/blog" className={navLinkClass}>Blog</Link>
          <CavemanToggle />
          <Button asChild size="sm" variant="outline">
            <Link href="/auth/login">Sign in</Link>
          </Button>
          <Button asChild size="sm">
            <Link href="/auth/sign-up">Sign up</Link>
          </Button>
        </div>
      )}
    </HeaderShell>
  );
}
