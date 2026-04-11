import Image from "next/image";
import Link from "next/link";
import { createClient } from "@/lib/supabase/server";
import { Button } from "@/components/ui/button";
import { LogoutButton } from "@/components/logout-button";
import { SiteHeaderMobileNav } from "@/components/site-header-mobile-nav";

function Logo() {
  return (
    <Link href="/" className="inline-flex items-center gap-2">
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

const headerNavLinkClass =
  "text-sm font-medium text-muted-foreground transition-colors hover:text-foreground cursor-pointer";

function HeaderShell({ children }: { children: React.ReactNode }) {
  return (
    <header className="sticky top-0 z-50 px-4 pt-4 pb-0">
      <div className="mx-auto flex h-14 w-full max-w-7xl items-center justify-between rounded-2xl border border-border bg-background/80 px-4 shadow-lg backdrop-blur-md lg:px-6">
        {children}
      </div>
    </header>
  );
}

export function SiteHeaderFallback() {
  return (
    <HeaderShell>
      <Logo />
      <div className="flex shrink-0 items-center gap-3">
        <Link href="/docs" className={headerNavLinkClass}>
          Docs
        </Link>
        <Link href="/blog" className={headerNavLinkClass}>
          Blog
        </Link>
        <Button asChild size="sm" variant="outline">
          <Link href="/auth/login">Sign in</Link>
        </Button>
        <Button asChild size="sm">
          <Link href="/auth/sign-up">Sign up</Link>
        </Button>
      </div>
    </HeaderShell>
  );
}

export async function SiteHeader() {
  const supabase = await createClient();
  // Use getUser() (not getClaims) so protected links only show after Auth validates
  // the session; stale JWTs in cookies must not reveal /protected nav when logged out.
  const {
    data: { user },
  } = await supabase.auth.getUser();
  const isAuthed = Boolean(user);

  return (
    <HeaderShell>
      <div className="flex min-w-0 flex-1 items-center gap-3 md:gap-6">
        <Logo />
        {isAuthed ? <SiteHeaderMobileNav userEmail={user?.email} /> : null}
        {isAuthed ? (
          <nav className="hidden min-w-0 items-center gap-4 md:flex">
            <Link href="/protected" className={headerNavLinkClass}>
              Articles
            </Link>
            <Link href="/protected/news-trends" className={headerNavLinkClass}>
              News Trends
            </Link>
            <Link href="/protected/vectors" className={headerNavLinkClass}>
              Vectors
            </Link>
            <Link href="/protected/screenings" className={headerNavLinkClass}>
              Screenings
            </Link>
            <Link href="/protected/trades" className={headerNavLinkClass}>
              Trades
            </Link>
          </nav>
        ) : null}
      </div>

      {isAuthed ? (
        <div className="flex shrink-0 items-center gap-2 sm:gap-3">
          <Link href="/docs" className={`${headerNavLinkClass} hidden md:inline`}>
            Docs
          </Link>
          <Link href="/blog" className={`${headerNavLinkClass} hidden md:inline`}>
            Blog
          </Link>
          <Link
            href="/protected/profile"
            className="hidden text-sm text-muted-foreground hover:text-foreground transition-colors md:inline cursor-pointer"
          >
            {user?.email ?? ""}
          </Link>
          <LogoutButton />
        </div>
      ) : (
        <div className="flex shrink-0 items-center gap-2">
          <Link href="/docs" className={headerNavLinkClass}>
            Docs
          </Link>
          <Link href="/blog" className={headerNavLinkClass}>
            Blog
          </Link>
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
