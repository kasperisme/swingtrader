/**
 * The one place the site's canonical origin is defined.
 *
 * It used to be defaulted independently in ~10 files, and the two defaults
 * disagreed: `robots.ts`, `sitemap.ts` and `llms.txt` said the apex host while
 * every page's canonical said `www`. The apex redirects to `www`, so every
 * URL in the sitemap was a redirect and Search Console reported 1,600
 * submitted / 0 indexed. Import `SITE_URL` here instead of re-deriving it.
 *
 * `NEXT_PUBLIC_SITE_URL` still wins for local/staging, but the production
 * apex is normalised up to `www` so a half-configured env can't reintroduce
 * the split-host problem.
 */

const PRODUCTION_ORIGIN = "https://www.newsimpactscreener.com";

function normalizeOrigin(raw: string): string {
  const trimmed = raw.trim().replace(/\/+$/, "");
  if (!trimmed) return PRODUCTION_ORIGIN;
  try {
    const url = new URL(trimmed);
    // Canonical host is www — never let the apex through.
    if (url.hostname === "newsimpactscreener.com") {
      url.hostname = "www.newsimpactscreener.com";
    }
    return url.origin;
  } catch {
    return PRODUCTION_ORIGIN;
  }
}

/** Canonical origin, no trailing slash. Use for every absolute URL we emit. */
export const SITE_URL = normalizeOrigin(
  process.env.NEXT_PUBLIC_SITE_URL ?? PRODUCTION_ORIGIN,
);

/** Absolute URL for a site-relative path. */
export function absoluteUrl(path: string): string {
  return `${SITE_URL}${path.startsWith("/") ? path : `/${path}`}`;
}

/**
 * `metadataBase` for the root layout. Vercel preview deployments set
 * VERCEL_URL to a hashed `*.vercel.app` host — using that in production would
 * leak the preview origin into every OG/Twitter card.
 */
export const METADATA_BASE = new URL(
  process.env.VERCEL_ENV === "production" || !process.env.VERCEL_URL
    ? SITE_URL
    : `https://${process.env.VERCEL_URL}`,
);

/** Display name of the publisher/brand. */
export const SITE_NAME = "News Impact Screener";

/** Canonical social profiles — the `sameAs` set that ties the brand to a real
 *  entity. Defined here (not in the footer component) so `robots.ts`,
 *  `sitemap.ts` and structured data can read them without pulling in React. */
export const SITE_X_PROFILE_URL = "https://x.com/newsimpactscrnr";
export const SITE_X_HANDLE = "@newsimpactscrnr";
export const SITE_INSTAGRAM_PROFILE_URL =
  "https://instagram.com/newsimpactscreener";
export const SITE_INSTAGRAM_HANDLE = "@newsimpactscreener";

export const SITE_SAME_AS = [
  SITE_X_PROFILE_URL,
  SITE_INSTAGRAM_PROFILE_URL,
];

/**
 * The named human behind the analysis.
 *
 * Stock analysis is a YMYL ("your money or your life") topic, which Google
 * holds to a higher trust bar than most. An anonymous site publishing
 * per-ticker valuation calls has no way to clear it. This is the attribution
 * the About page, the `Person` structured data and every article byline read
 * from — one definition, so they can never drift apart.
 */
export const AUTHOR = {
  name: "Kasper Rasmussen",
  /** Shown under the name on /about and used as `jobTitle`. */
  role: "Founder & analyst",
  /** The canonical URL for the person entity. */
  url: `${SITE_URL}/about`,
  /** Basename (no extension) of the portrait in `public/`. Optional — the
   *  About page falls back to a monogram when no matching file is present. */
  photoBasename: "kasper-rasmussen",
  /**
   * Optional background paragraph. Everything the About page states about the
   * platform is verifiable from the product itself; this is the one field only
   * Kasper can write. Leave it empty and the section simply doesn't render —
   * better an absent claim than an invented one.
   */
  background: "",
} as const;

/**
 * IndexNow key. Bing, Yandex, Seznam and Naver accept a push notification the
 * moment a URL changes instead of waiting to re-crawl — which matters most for
 * a site whose crawl rate is near zero. The key is verified by fetching
 * `{SITE_URL}/{INDEXNOW_KEY}.txt`, which is served from `public/`.
 * Not a secret: it only proves whoever submits URLs controls this host.
 */
export const INDEXNOW_KEY = "40d5c39cbe5757e2babe5c6c8a03dfd4";
export const INDEXNOW_KEY_LOCATION = `${SITE_URL}/${INDEXNOW_KEY}.txt`;
