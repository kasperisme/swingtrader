import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { warmEmbedding } from "@/lib/embeddings/query-embedding";

// Module-scoped guard so a flurry of mounts (Strict Mode, multiple tabs hitting
// the same instance) collapses into one HF call. The pod stays warm for
// several minutes after a hit, so we don't need to repeat sooner than that.
let lastWarmedAt = 0;
let inflight: Promise<void> | null = null;
const COOLDOWN_MS = 60_000;

async function warmOnce(): Promise<void> {
  const now = Date.now();
  if (now - lastWarmedAt < COOLDOWN_MS) return;
  if (inflight) return inflight;
  inflight = warmEmbedding()
    .then(() => {
      lastWarmedAt = Date.now();
    })
    .catch((err) => {
      console.error("[semantic-search/warmup] failed:", err);
    })
    .finally(() => {
      inflight = null;
    });
  return inflight;
}

export async function POST() {
  const supabase = await createClient();
  const { data: claims, error: claimsError } = await supabase.auth.getClaims();
  if (claimsError || !claims?.claims) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  await warmOnce();
  return new NextResponse(null, { status: 204 });
}
