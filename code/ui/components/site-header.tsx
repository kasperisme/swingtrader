import Image from "next/image";
import Link from "next/link";
import { createClient } from "@/lib/supabase/server";
import { Button } from "@/components/ui/button";
import { LogoutButton } from "@/components/logout-button";

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

function HeaderShell({ children }: { children: React.ReactNode }) {
  return (
    <header className="w-full border-b border-border">
      <div className="mx-auto flex h-16 w-full max-w-7xl items-center justify-between px-6 lg:px-8">
        {children}
      </div>
    </header>
  );
}

export function SiteHeaderFallback() {
  return (
    <HeaderShell>
      <Logo />
      <div className="flex items-center gap-3">
        <Link
          href="/blog"
          className="text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
        >
          Blog
        </Link>
        <Button asChild size="sm" variant="outline">
          <Link href="/auth/login">Sign in</Link>
        </Button>
      </div>
    </HeaderShell>
  );
}

export async function SiteHeader() {
  const supabase = await createClient();
  const { data } = await supabase.auth.getClaims();
  const user = data?.claims;
  const isAuthed = Boolean(user);

  return (
    <HeaderShell>
      <div className="flex items-center gap-6">
        <Logo />
        {isAuthed ? (
          <nav className="hidden items-center gap-4 md:flex">
            <Link
              href="/docs"
              className="text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
            >
              Docs
            </Link>
            <Link
              href="/blog"
              className="text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
            >
              Blog
            </Link>
            <Link
              href="/protected"
              className="text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
            >
              Articles
            </Link>
            <Link
              href="/protected/news-trends"
              className="text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
            >
              News Trends
            </Link>
            <Link
              href="/protected/vectors"
              className="text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
            >
              Vectors
            </Link>
            <Link
              href="/protected/screenings"
              className="text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
            >
              Screenings
            </Link>
          </nav>
        ) : null}
      </div>

      {isAuthed ? (
        <div className="flex items-center gap-3">
          <span className="hidden text-sm text-muted-foreground md:inline">
            {String(user?.email ?? "")}
          </span>
          <LogoutButton />
        </div>
      ) : (
        <div className="flex items-center gap-2">
          <Link
            href="/blog"
            className="text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
          >
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
