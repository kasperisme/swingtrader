import { ArrowUpRight, Instagram, Play } from "lucide-react";
import { getInstagramFeed, type InstagramPost } from "@/lib/instagram/behold";
import {
  SITE_INSTAGRAM_HANDLE,
  SITE_INSTAGRAM_PROFILE_URL,
} from "@/components/site-footer";

function FollowButton() {
  return (
    <a
      href={SITE_INSTAGRAM_PROFILE_URL}
      target="_blank"
      rel="noopener noreferrer"
      className="group/btn inline-flex items-center gap-2 self-start rounded-full border border-amber-500/40 bg-amber-500/10 px-4 py-2 text-sm font-semibold text-amber-300 transition-colors hover:border-amber-400/60 hover:bg-amber-500/15"
    >
      <Instagram className="h-4 w-4" />
      Follow {SITE_INSTAGRAM_HANDLE}
      <ArrowUpRight className="h-4 w-4 transition-transform duration-200 group-hover/btn:translate-x-0.5 group-hover/btn:-translate-y-0.5" />
    </a>
  );
}

function PostTile({ post, hero = false }: { post: InstagramPost; hero?: boolean }) {
  return (
    <a
      href={post.permalink}
      target="_blank"
      rel="noopener noreferrer"
      aria-label={post.caption || "View Instagram post"}
      className={[
        "group/tile relative block overflow-hidden rounded-2xl border border-border bg-background/60",
        hero
          ? "col-span-2 row-span-2 aspect-[4/5] sm:aspect-auto"
          : "aspect-square sm:aspect-auto",
      ].join(" ")}
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={post.imageUrl}
        alt={post.caption || "Instagram post"}
        loading="lazy"
        className="h-full w-full object-cover transition-transform duration-500 ease-out group-hover/tile:scale-[1.04]"
      />

      {/* Reels/video marker */}
      {post.isVideo && (
        <span className="absolute right-3 top-3 inline-flex items-center justify-center rounded-full bg-black/55 p-1.5 backdrop-blur-sm ring-1 ring-white/15">
          <Play className="h-3 w-3 fill-white text-white" />
        </span>
      )}

      {/* Caption reveal */}
      <div className="pointer-events-none absolute inset-x-0 bottom-0 translate-y-2 bg-gradient-to-t from-black/80 via-black/35 to-transparent p-3 opacity-0 transition-all duration-300 ease-out group-hover/tile:translate-y-0 group-hover/tile:opacity-100">
        {post.caption && (
          <p className={`${hero ? "line-clamp-3 text-sm" : "line-clamp-2 text-xs"} leading-snug text-white/90`}>
            {post.caption}
          </p>
        )}
        <span className="mt-1.5 inline-flex items-center gap-1 text-[11px] font-medium uppercase tracking-wider text-amber-300">
          View
          <ArrowUpRight className="h-3 w-3" />
        </span>
      </div>
    </a>
  );
}

/**
 * Landing-page Instagram section. Renders the latest posts from the Behold feed
 * in an asymmetric bento (latest post featured) linking to Instagram; falls back
 * to a follow CTA when no feed is configured (BEHOLD_FEED_ID unset) or fetch fails.
 */
export async function InstagramSection() {
  const feed = await getInstagramFeed(5);
  const [hero, ...rest] = feed?.posts ?? [];

  return (
    <section id="instagram" className="border-t border-border py-16 md:py-24">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        {/* Editorial header — label/heading left, CTA right */}
        <div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
          <div className="max-w-xl">
            <p className="inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-widest text-amber-500">
              <Instagram className="h-3.5 w-3.5" />
              Instagram
            </p>
            <h2 className="mt-3 text-2xl font-bold tracking-tight sm:text-3xl">
              Markets, in your feed
            </h2>
            <p className="mt-3 text-sm leading-6 text-muted-foreground">
              Daily regime reads, top-story breakdowns, and watchlist setups —
              the screener&apos;s signal, in 30 seconds a day.
            </p>
          </div>
          <FollowButton />
        </div>

        {hero && (
          <div className="mt-10 grid grid-cols-2 gap-3 sm:grid-cols-4 sm:grid-rows-2 sm:h-[460px]">
            <PostTile key={hero.id} post={hero} hero />
            {rest.slice(0, 4).map((post) => (
              <PostTile key={post.id} post={post} />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
