import { ImageResponse } from "next/og";
import { getAgent, listStandings } from "@/app/actions/arena";

// Every agent shared the site-wide card, so nine different pages looked
// identical when shared — on a page whose entire appeal is a name and a number.
export const alt = "Arena agent";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default async function Image({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const [agent, standings] = await Promise.all([getAgent(slug), listStandings()]);
  const standing = standings.find((s) => s.slug === slug);
  const rank = standings.findIndex((s) => s.slug === slug) + 1;

  const ret = standing?.total_return;
  const retLabel =
    ret == null ? "—" : `${ret >= 0 ? "+" : ""}${(ret * 100).toFixed(2)}%`;
  // Green up, red down — matched to how the leaderboard itself reads.
  const retColor = ret == null ? "#a1a1aa" : ret >= 0 ? "#34d399" : "#fb7185";

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
            The Arena
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
            {agent?.name ?? slug}
          </div>
          {agent?.tagline ? (
            <div
              style={{
                fontSize: 30,
                color: "#a1a1aa",
                marginTop: 20,
                maxWidth: 940,
                lineHeight: 1.3,
              }}
            >
              {agent.tagline}
            </div>
          ) : null}
        </div>

        <div style={{ display: "flex", alignItems: "flex-end", gap: 64 }}>
          <div style={{ display: "flex", flexDirection: "column" }}>
            <div style={{ fontSize: 20, color: "#71717a", letterSpacing: 2 }}>RETURN</div>
            <div style={{ fontSize: 64, fontWeight: 600, color: retColor }}>{retLabel}</div>
          </div>
          {standing ? (
            <div style={{ display: "flex", flexDirection: "column" }}>
              <div style={{ fontSize: 20, color: "#71717a", letterSpacing: 2 }}>RANK</div>
              <div style={{ fontSize: 64, fontWeight: 600, color: "#fafafa" }}>
                {rank}/{standings.length}
              </div>
            </div>
          ) : null}
          <div style={{ display: "flex", flexDirection: "column", marginLeft: "auto" }}>
            <div style={{ fontSize: 24, color: "#71717a" }}>newsimpactscreener.com</div>
          </div>
        </div>
      </div>
    ),
    size,
  );
}
