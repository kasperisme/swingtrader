import { NextResponse } from "next/server";
import { createServiceClient } from "@/lib/supabase/service";

/**
 * Podcast RSS feed — generated on request from swingtrader.podcast_episodes.
 *
 * The analytics pipeline writes one row per published episode (audio_url,
 * cover_url, duration, GUID, etc. all live in Supabase). This route turns
 * that table into a valid Apple Podcasts / Spotify RSS feed at
 *   https://<host>/podcast/feed.xml
 *
 * Cached at the edge for 10 min to keep load off Postgres while staying
 * fresh enough for podcast clients (which typically poll every ~1h anyway).
 */

const FEED_TITLE = "The Impact Tape";
const FEED_LINK = "https://newsimpactscreener.com";
const FEED_DESCRIPTION =
  "Daily AI-generated market intelligence for swing traders.";
const FEED_AUTHOR = "newsimpactscreener.com";
const DEFAULT_COVER = "https://www.newsimpactscreener.com/icon.png";

interface EpisodeRow {
  date: string;
  title: string | null;
  description: string | null;
  audio_url: string | null;
  cover_url: string | null;
  duration_seconds: number | null;
  file_size_bytes: number | null;
  guid: string | null;
  published_at: string | null;
}

function xmlEscape(value: string | null | undefined): string {
  if (!value) return "";
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

function rfc2822(timestamp: string | null, fallbackDate: string): string {
  const dt = timestamp
    ? new Date(timestamp)
    : new Date(`${fallbackDate}T13:00:00Z`);
  return dt.toUTCString();
}

function renderItem(ep: EpisodeRow): string {
  if (!ep.audio_url || !ep.guid) return ""; // skip incomplete rows

  const title = xmlEscape(ep.title || `The Impact Tape — ${ep.date}`);
  const description = ep.description || "";
  const audioUrl = xmlEscape(ep.audio_url);
  const coverUrl = xmlEscape(ep.cover_url || DEFAULT_COVER);
  const guid = xmlEscape(ep.guid);
  const length = ep.file_size_bytes ?? 0;
  const duration = ep.duration_seconds ?? 0;
  const pubDate = rfc2822(ep.published_at, ep.date);

  return `
    <item>
      <title>${title}</title>
      <description><![CDATA[${description}]]></description>
      <enclosure url="${audioUrl}" length="${length}" type="audio/mpeg"/>
      <pubDate>${pubDate}</pubDate>
      <itunes:duration>${duration}</itunes:duration>
      <itunes:image href="${coverUrl}"/>
      <itunes:explicit>no</itunes:explicit>
      <guid isPermaLink="false">${guid}</guid>
    </item>`;
}

function renderFeed(episodes: EpisodeRow[]): string {
  const items = episodes.map(renderItem).filter(Boolean).join("\n");
  const lastBuildDate = new Date().toUTCString();

  return `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
  xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
  xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>${xmlEscape(FEED_TITLE)}</title>
    <link>${FEED_LINK}</link>
    <atom:link href="${FEED_LINK}/podcast/feed.xml" rel="self" type="application/rss+xml"/>
    <description>${xmlEscape(FEED_DESCRIPTION)}</description>
    <itunes:author>${xmlEscape(FEED_AUTHOR)}</itunes:author>
    <itunes:category text="Business">
      <itunes:category text="Investing"/>
    </itunes:category>
    <itunes:image href="${DEFAULT_COVER}"/>
    <language>en-us</language>
    <itunes:explicit>no</itunes:explicit>
    <lastBuildDate>${lastBuildDate}</lastBuildDate>${items}
  </channel>
</rss>
`;
}

export async function GET() {
  try {
    const supabase = createServiceClient();
    const { data, error } = await supabase
      .schema("swingtrader")
      .from("podcast_episodes")
      .select(
        "date, title, description, audio_url, cover_url, duration_seconds, file_size_bytes, guid, published_at",
      )
      .eq("status", "published")
      .order("published_at", { ascending: false, nullsFirst: false })
      .order("date", { ascending: false })
      .limit(100);

    if (error) {
      console.error("[podcast/feed.xml] supabase error", error);
      return new NextResponse("Internal error", { status: 500 });
    }

    const xml = renderFeed((data ?? []) as EpisodeRow[]);
    return new NextResponse(xml, {
      status: 200,
      headers: {
        "Content-Type": "application/rss+xml; charset=utf-8",
        // Edge cache for 10 minutes; podcast clients poll on their own schedule.
        "Cache-Control": "public, s-maxage=600, stale-while-revalidate=3600",
      },
    });
  } catch (err) {
    console.error("[podcast/feed.xml] unexpected", err);
    return new NextResponse("Internal error", { status: 500 });
  }
}
