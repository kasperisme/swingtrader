import { connection } from "next/server";
import { createServiceClient } from "@/lib/supabase/service";

// Aggregate ad-attribution for email leads, split by utm_content (the feature
// variant). No PII — counts only. Read via the service client so RLS on the
// subscription tables doesn't hide rows from this admin view.

type Sub = {
  metadata: { utm?: Record<string, string> } | null;
  source: string | null;
  created_at: string;
};

const WINDOW_DAYS = 30;

async function load() {
  const service = createServiceClient();
  const since = new Date(Date.now() - WINDOW_DAYS * 86_400_000).toISOString();
  const [screening, briefing] = await Promise.all([
    service
      .schema("swingtrader")
      .from("market_screening_email_subscriptions")
      .select("metadata, source, created_at")
      .gte("created_at", since)
      .limit(5000),
    service
      .schema("swingtrader")
      .from("news_briefing_subscriptions")
      .select("metadata, source, created_at")
      .gte("created_at", since)
      .limit(5000),
  ]);
  return {
    screening: (screening.data ?? []) as Sub[],
    briefing: (briefing.data ?? []) as Sub[],
  };
}

function contentOf(s: Sub): string {
  return s.metadata?.utm?.utm_content || "— organic / no utm —";
}

export default async function AttributionPage() {
  await connection(); // live read at request time (opt out of static prerender)
  const { screening, briefing } = await load();

  const rows = new Map<string, { screening: number; briefing: number }>();
  const bump = (key: string, which: "screening" | "briefing") => {
    const r = rows.get(key) ?? { screening: 0, briefing: 0 };
    r[which] += 1;
    rows.set(key, r);
  };
  for (const s of screening) bump(contentOf(s), "screening");
  for (const s of briefing) bump(contentOf(s), "briefing");

  const ranked = [...rows.entries()]
    .map(([content, c]) => ({ content, ...c, total: c.screening + c.briefing }))
    .sort((a, b) => b.total - a.total);

  const totals = ranked.reduce(
    (a, r) => ({
      screening: a.screening + r.screening,
      briefing: a.briefing + r.briefing,
      total: a.total + r.total,
    }),
    { screening: 0, briefing: 0, total: 0 },
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Ad attribution</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Email leads by <code>utm_content</code> — last {WINDOW_DAYS} days.
          Counts only (no emails). {totals.total} lead
          {totals.total === 1 ? "" : "s"} total.
        </p>
      </div>

      <div className="overflow-hidden rounded-xl border border-border">
        <table className="w-full text-sm">
          <thead className="bg-muted/40 text-left text-xs uppercase text-muted-foreground">
            <tr>
              <th className="px-4 py-3 font-medium">utm_content</th>
              <th className="px-4 py-3 text-right font-medium">Market screening</th>
              <th className="px-4 py-3 text-right font-medium">News briefing</th>
              <th className="px-4 py-3 text-right font-medium">Total</th>
            </tr>
          </thead>
          <tbody>
            {ranked.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-4 py-8 text-center text-muted-foreground">
                  No leads yet in the last {WINDOW_DAYS} days.
                </td>
              </tr>
            ) : (
              ranked.map((r) => (
                <tr key={r.content} className="border-t border-border/60">
                  <td className="px-4 py-3 font-mono">{r.content}</td>
                  <td className="px-4 py-3 text-right tabular-nums">{r.screening}</td>
                  <td className="px-4 py-3 text-right tabular-nums">{r.briefing}</td>
                  <td className="px-4 py-3 text-right font-semibold tabular-nums">{r.total}</td>
                </tr>
              ))
            )}
          </tbody>
          {ranked.length > 0 && (
            <tfoot className="border-t border-border bg-muted/30 font-semibold">
              <tr>
                <td className="px-4 py-3">All</td>
                <td className="px-4 py-3 text-right tabular-nums">{totals.screening}</td>
                <td className="px-4 py-3 text-right tabular-nums">{totals.briefing}</td>
                <td className="px-4 py-3 text-right tabular-nums">{totals.total}</td>
              </tr>
            </tfoot>
          )}
        </table>
      </div>

      <p className="text-xs text-muted-foreground">
        Cross-reference with CTR / cost-per-click in Ads Manager for the same{" "}
        <code>utm_content</code> to see which feature is both more clickable and
        more convertible. Pixel <code>Lead</code> events fire client-side on each
        subscribe.
      </p>
    </div>
  );
}
