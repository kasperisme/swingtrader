import { Suspense } from "react";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { ChevronLeft } from "lucide-react";
import { createClient } from "@/lib/supabase/server";
import { getUserSubscriptionTier } from "@/lib/subscription";
import { PRELAUNCH_OPEN_ACCESS } from "@/lib/launch";
import { tradeReviewBootstrap } from "@/app/actions/trade-reviews";
import { fmpGetOhlc } from "@/app/actions/fmp";
import type { OhlcBar } from "@/components/ticker-charts/types";
import { TradeReviewView } from "./trade-review-view";

function shiftDate(iso: string, days: number): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

async function ReviewData({ closingTradeId }: { closingTradeId: number }) {
  const supabase = await createClient();
  const { data: claims, error: claimsError } = await supabase.auth.getClaims();
  if (claimsError || !claims?.claims) {
    redirect("/auth/login");
  }

  const res = await tradeReviewBootstrap(closingTradeId);
  if (!res.ok) {
    return (
      <div className="rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground">
        <p className="font-medium text-foreground">Can&apos;t review this trade</p>
        <p className="mt-2">{res.error}</p>
        <p className="mt-2 text-xs">
          A review is available once a position is fully closed (net qty back to zero on
          the same ticker, currency, and book). If the table is missing, apply the
          migration{" "}
          <code className="rounded bg-muted px-1 py-0.5 font-mono text-[11px]">
            20260528160000_user_trade_reviews.sql
          </code>
          .
        </p>
      </div>
    );
  }

  const { position, review, positionTrades } = res.data;

  // ~5 trading days of padding on each side — use calendar days as a cheap
  // approximation. The chart fetch trims to whatever bars FMP returns.
  const from = shiftDate(position.openedAt, -10);
  const to = shiftDate(position.closedAt, 10);

  const ohlcRes = await fmpGetOhlc(position.ticker, "1day", { from, to });
  const ohlcData: OhlcBar[] = ohlcRes.ok ? ohlcRes.data : [];

  // AI trade review is a paid/trial feature — Observers see the trade + chart
  // but a locked review panel. Open beta bypasses the gate.
  const tier = await getUserSubscriptionTier(supabase);
  const aiEnabled = PRELAUNCH_OPEN_ACCESS || tier !== "observer";

  return (
    <TradeReviewView
      closingTradeId={closingTradeId}
      position={position}
      initialMessages={review.messages}
      initialSummary={review.summary}
      ohlcData={ohlcData}
      tradeMarkers={positionTrades.map((t) => ({
        date: t.executed_at,
        price: t.price_per_unit,
        side: t.side,
        position_side: position.side,
      }))}
      aiEnabled={aiEnabled}
    />
  );
}

type PageParams = Promise<{ closingTradeId: string }>;

export default async function TradeReviewPage({ params }: { params: PageParams }) {
  const { closingTradeId: raw } = await params;
  const closingTradeId = Number(raw);
  if (!Number.isFinite(closingTradeId) || closingTradeId <= 0) {
    notFound();
  }

  return (
    <div className="flex-1 w-full flex flex-col gap-6">
      <div>
        <Link
          href="/protected/trades"
          className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
        >
          <ChevronLeft className="h-3 w-3" />
          Trades
        </Link>
        <p className="mt-2 text-xs font-semibold uppercase tracking-widest text-amber-500">
          Post-trade review
        </p>
        <h1 className="mt-1 text-2xl font-bold tracking-tight">Trade #{closingTradeId}</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          AI review of a closed round-trip position. Reviewers grade entry, exit, risk
          management, and surface a key lesson.
        </p>
      </div>

      <Suspense
        fallback={
          <div className="text-sm text-muted-foreground animate-pulse rounded-lg border border-border p-6">
            Loading review…
          </div>
        }
      >
        <ReviewData closingTradeId={closingTradeId} />
      </Suspense>
    </div>
  );
}
