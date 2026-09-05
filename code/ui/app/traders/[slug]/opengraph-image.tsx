import { ImageResponse } from "next/og";
import { isSanityConfigured, sanityFetch } from "@/lib/sanity/client";
import { traderBySlugQuery } from "@/lib/sanity/queries";
import type { Trader } from "@/lib/sanity/types";

export const alt = "Trader profile";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default async function Image({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const trader = isSanityConfigured
    ? await sanityFetch<Trader | null>(traderBySlugQuery, { slug })
    : null;

  const meta = [trader?.style, trader?.lifespan, trader?.nationality]
    .filter(Boolean)
    .join("  ·  ");

  return new ImageResponse(
    (
      <div
        style={{
          height: "100%",
          width: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          background: "#09090b",
          padding: "64px 72px",
          fontFamily: "sans-serif",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column" }}>
          <div
            style={{
              fontSize: 22,
              letterSpacing: 4,
              textTransform: "uppercase",
              color: "#f59e0b",
            }}
          >
            Famous Traders
          </div>
          <div
            style={{
              fontSize: 76,
              fontWeight: 600,
              color: "#fafafa",
              marginTop: 18,
              lineHeight: 1.05,
            }}
          >
            {trader?.name ?? slug}
          </div>
          {meta ? (
            <div style={{ fontSize: 26, color: "#71717a", marginTop: 16 }}>{meta}</div>
          ) : null}
        </div>

        <div style={{ display: "flex", flexDirection: "column" }}>
          {trader?.knownFor ? (
            <div
              style={{
                fontSize: 32,
                color: "#a1a1aa",
                maxWidth: 1000,
                lineHeight: 1.3,
              }}
            >
              {trader.knownFor}
            </div>
          ) : null}
          <div style={{ fontSize: 24, color: "#52525b", marginTop: 28 }}>
            newsimpactscreener.com
          </div>
        </div>
      </div>
    ),
    size,
  );
}
