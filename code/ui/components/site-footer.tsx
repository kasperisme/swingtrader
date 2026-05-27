import Link from "next/link";
import { ThemeSwitcher } from "@/components/theme-switcher";

/** Canonical X (Twitter) profile for metadata and footer links. */
export const SITE_X_PROFILE_URL = "https://x.com/newsimpactscrnr";
const X_HANDLE = "@newsimpactscrnr";

/** Canonical Instagram profile for metadata and footer links. */
export const SITE_INSTAGRAM_PROFILE_URL = "https://instagram.com/newsimpactscreener";
export const SITE_INSTAGRAM_HANDLE = "@newsimpactscreener";
const INSTAGRAM_HANDLE = SITE_INSTAGRAM_HANDLE;

export function SiteFooter() {
  return (
    <footer className="w-full border-t border-border">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-3 px-4 py-8 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between sm:gap-x-6 sm:gap-y-4 lg:px-6">
        <div className="flex min-w-0 flex-wrap items-center gap-x-1 gap-y-0.5 text-xs text-muted-foreground">
          <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />
          <span className="ml-1 font-semibold text-foreground">newsimpactscreener</span>
          <span className="ml-2">— news connected to markets.</span>
        </div>
        <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2 text-xs text-muted-foreground sm:gap-x-5">
          <a
            href={SITE_X_PROFILE_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="transition-colors hover:text-foreground cursor-pointer"
          >
            {X_HANDLE} on X
          </a>
          <a
            href={SITE_INSTAGRAM_PROFILE_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="transition-colors hover:text-foreground cursor-pointer"
          >
            {INSTAGRAM_HANDLE} on Instagram
          </a>
          <Link href="/terms" className="transition-colors hover:text-foreground">
            Terms
          </Link>
          <Link href="/privacy" className="transition-colors hover:text-foreground">
            Privacy
          </Link>
          <ThemeSwitcher />
        </div>
      </div>
    </footer>
  );
}
