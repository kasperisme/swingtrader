import Link from "next/link";
import { ThemeSwitcher } from "@/components/theme-switcher";
import {
  SITE_X_PROFILE_URL,
  SITE_X_HANDLE,
  SITE_INSTAGRAM_PROFILE_URL,
  SITE_INSTAGRAM_HANDLE,
} from "@/lib/site";

// Single-sourced in lib/site.ts so structured data, robots.ts and sitemap.ts
// can read the same profiles without importing a React component.
export {
  SITE_X_PROFILE_URL,
  SITE_INSTAGRAM_PROFILE_URL,
  SITE_INSTAGRAM_HANDLE,
} from "@/lib/site";

const X_HANDLE = SITE_X_HANDLE;
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
          <Link href="/about" className="transition-colors hover:text-foreground">
            About
          </Link>
          <Link href="/briefings" className="transition-colors hover:text-foreground">
            Briefings
          </Link>
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
