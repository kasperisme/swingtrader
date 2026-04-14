import Link from "next/link";
import { ThemeSwitcher } from "@/components/theme-switcher";

/** Canonical X (Twitter) profile for metadata and footer links. */
export const SITE_X_PROFILE_URL = "https://x.com/newsimpactscrnr";
const X_HANDLE = "@newsimpactscrnr";

export function SiteFooter() {
  return (
    <footer className="w-full border-t border-border">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4 px-6 py-8 lg:px-8">
        <div className="flex items-center gap-1 text-xs text-muted-foreground">
          <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />
          <span className="ml-1 font-semibold text-foreground">newsimpactscreener</span>
          <span className="ml-2">— news connected to markets.</span>
        </div>
        <div className="flex items-center gap-6 text-xs text-muted-foreground">
          <a
            href={SITE_X_PROFILE_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="transition-colors hover:text-foreground cursor-pointer"
          >
            {X_HANDLE} on X
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
