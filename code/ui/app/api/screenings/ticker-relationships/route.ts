import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

function asRecord(v: unknown): Record<string, unknown> {
  if (!v) return {};
  if (typeof v === "string") {
    try { return asRecord(JSON.parse(v)); } catch { return {}; }
  }
  return typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}

export async function GET() {
  const supabase = await createClient();

  const { data, error } = await supabase
    .schema("swingtrader")
    .from("news_impact_heads")
    .select("scores_json, reasoning_json")
    .eq("cluster", "TICKER_RELATIONSHIPS");

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  // Aggregate edges across all articles
  const edgeMap = new Map<
    string,
    { from: string; to: string; rel_type: string; strengthSum: number; count: number; notes: string[] }
  >();

  for (const row of data ?? []) {
    const scores = asRecord((row as any).scores_json);
    const reasoning = asRecord((row as any).reasoning_json);

    for (const [key, rawStrength] of Object.entries(scores)) {
      const parts = key.split("__");
      if (parts.length !== 3) continue;
      const [from, to, rel_type] = parts as [string, string, string];
      const strength = Math.max(0, Math.min(1, Number(rawStrength) || 0));

      const existing = edgeMap.get(key);
      const note = typeof reasoning[key] === "string" ? (reasoning[key] as string) : "";
      if (existing) {
        existing.strengthSum += strength;
        existing.count++;
        if (note && !existing.notes.includes(note)) existing.notes.push(note);
      } else {
        edgeMap.set(key, { from, to, rel_type, strengthSum: strength, count: 1, notes: note ? [note] : [] });
      }
    }
  }

  const edges = Array.from(edgeMap.values()).map(({ from, to, rel_type, strengthSum, count, notes }) => ({
    from,
    to,
    rel_type,
    strength: strengthSum / count,
    count,
    note: notes[0] ?? "",
  }));

  return NextResponse.json(edges, {
    headers: { "Cache-Control": "s-maxage=300, stale-while-revalidate=60" },
  });
}
