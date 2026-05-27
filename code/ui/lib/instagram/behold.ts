/**
 * Latest Instagram posts via Behold (https://behold.so).
 *
 * Instagram's Basic Display API was shut down (Dec 2024); the official Graph
 * API needs a Business account, Meta app review, and 60-day token refreshes.
 * Behold handles that auth churn and exposes a public JSON feed we fetch
 * server-side and render with our own markup.
 *
 * Setup: create a feed at behold.so, then set BEHOLD_FEED_ID to the feed id
 * (the trailing segment of the feed URL `https://feeds.behold.so/<id>`).
 * Without it, callers get null and the UI degrades to a plain "Follow" CTA.
 */

export type InstagramPost = {
  id: string;
  permalink: string;
  /** Best available still image (post image, or video poster frame). */
  imageUrl: string;
  caption: string;
  isVideo: boolean;
};

export type InstagramFeed = {
  username: string | null;
  posts: InstagramPost[];
};

/** Behold post shape (only the fields we use; the payload has more). */
type BeholdSize = { mediaUrl?: string };
type BeholdPost = {
  id?: string;
  permalink?: string;
  mediaType?: string; // IMAGE | VIDEO | CAROUSEL_ALBUM
  mediaUrl?: string;
  thumbnailUrl?: string;
  caption?: string;
  prunedCaption?: string;
  sizes?: { small?: BeholdSize; medium?: BeholdSize; large?: BeholdSize; full?: BeholdSize };
};

function pickImageUrl(p: BeholdPost): string | null {
  // Prefer Behold's resized variants (stable behold.pictures CDN — these are
  // the post image or the video/reel poster). thumbnailUrl/mediaUrl point at
  // Instagram's CDN whose URLs rotate, so use them only as a last resort.
  const candidates = [
    p.sizes?.medium?.mediaUrl,
    p.sizes?.small?.mediaUrl,
    p.sizes?.large?.mediaUrl,
    p.sizes?.full?.mediaUrl,
    p.thumbnailUrl,
    p.mediaUrl,
  ];
  return candidates.find((u): u is string => typeof u === "string" && u.length > 0) ?? null;
}

function normalize(raw: unknown): InstagramFeed | null {
  // Behold returns either a bare array (legacy) or { posts, profile } (current).
  const rawPosts: BeholdPost[] = Array.isArray(raw)
    ? (raw as BeholdPost[])
    : Array.isArray((raw as { posts?: unknown })?.posts)
      ? ((raw as { posts: BeholdPost[] }).posts)
      : [];

  // Behold exposes the handle at the top level; older payloads nested it.
  const username =
    (raw as { username?: string })?.username ??
    (raw as { profile?: { username?: string } })?.profile?.username ??
    null;

  const posts: InstagramPost[] = rawPosts
    .map((p) => {
      const imageUrl = pickImageUrl(p);
      if (!p.permalink || !imageUrl) return null;
      return {
        id: p.id ?? p.permalink,
        permalink: p.permalink,
        imageUrl,
        caption: (p.prunedCaption ?? p.caption ?? "").trim(),
        isVideo: (p.mediaType ?? "").toUpperCase() === "VIDEO",
      } satisfies InstagramPost;
    })
    .filter((p): p is InstagramPost => p !== null);

  if (posts.length === 0) return null;
  return { username, posts };
}

/**
 * Fetch the latest Instagram posts. Returns null when no feed is configured or
 * the fetch fails, so the UI can fall back to a follow CTA. Cached for an hour
 * (also keeps Instagram CDN image URLs reasonably fresh).
 */
export async function getInstagramFeed(limit = 6): Promise<InstagramFeed | null> {
  const feedId = process.env.BEHOLD_FEED_ID?.trim();
  if (!feedId) return null;

  try {
    const res = await fetch(`https://feeds.behold.so/${feedId}`, {
      next: { revalidate: 3600 },
    });
    if (!res.ok) {
      console.error("[instagram] behold fetch failed:", res.status);
      return null;
    }
    const feed = normalize(await res.json());
    if (!feed) return null;
    return { ...feed, posts: feed.posts.slice(0, limit) };
  } catch (err) {
    console.error("[instagram] behold fetch error:", err);
    return null;
  }
}
