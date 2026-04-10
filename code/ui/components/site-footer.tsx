import { ThemeSwitcher } from "@/components/theme-switcher";

/** Canonical X (Twitter) profile for metadata and footer links. */
export const SITE_X_PROFILE_URL = "https://x.com/newsimpactscrnr";
const X_HANDLE = "@newsimpactscrnr";

export function SiteFooter() {
  return (
    <footer className="w-full flex flex-wrap items-center justify-center border-t border-border mx-auto text-center text-xs gap-x-8 gap-y-3 py-12 px-5">
      <p>
        <a
          href={SITE_X_PROFILE_URL}
          target="_blank"
          rel="noopener noreferrer"
          className="font-medium text-foreground hover:underline"
        >
          {X_HANDLE} on X
        </a>
      </p>
      <p>
        Powered by{" "}
        <a
          href="https://supabase.com/?utm_source=create-next-app&utm_medium=template&utm_term=nextjs"
          target="_blank"
          className="font-bold hover:underline"
          rel="noreferrer"
        >
          Supabase
        </a>
      </p>
      <ThemeSwitcher />
    </footer>
  );
}
