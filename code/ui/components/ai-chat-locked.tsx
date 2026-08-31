"use client";

import { useEffect } from "react";
import Link from "next/link";
import { Sparkles } from "lucide-react";

import { track } from "@/lib/analytics/events";

/**
 * Shown in place of the AI chat for Observers (free tier). They keep full access
 * to the breakdown + data — only the AI chat / customization is gated behind a
 * paid plan (or the active trial). Used by the screenings and charts pages.
 *
 * This is the product's PRIMARY paywall — four mount points, and the only wall
 * most Observers will ever meet. It shipped without analytics: `paywall_viewed`
 * and `upgrade_clicked` were declared in the event map but emitted only by
 * `UpgradePrompt`, which nothing renders. So the wall could be shown a thousand
 * times and the funnel would show nothing at all. It is instrumented here rather
 * than at each call site so a new mount point cannot forget.
 *
 * A client component for the `useEffect` alone — every caller is already one.
 */
export function AiChatLocked({
  surface = "unknown",
}: {
  /**
   * Where this wall is standing, for the funnel: which surface converts is the
   * whole question, and four mounts reporting "unknown" cannot answer it.
   */
  surface?:
    | "quote_chart"
    | "quote_chart_mobile"
    | "workspace_screenings"
    | "trade_review"
    | "unknown";
}) {
  useEffect(() => {
    // `user_plan` is "observer" by construction: this component only renders on
    // the false branch of an `aiEnabled` check, and every paid tier passes it.
    track("paywall_viewed", {
      surface,
      user_plan: "observer",
      required_plan: "investor",
    });
  }, [surface]);

  return (
    <div className="flex h-full min-h-0 flex-col items-center justify-center gap-3 px-6 py-10 text-center">
      <div className="flex h-10 w-10 items-center justify-center rounded-full border border-border bg-muted/40">
        <Sparkles className="h-4 w-4 text-amber-500" aria-hidden />
      </div>
      <div className="space-y-1">
        <p className="text-sm font-medium text-foreground">AI chat is a paid feature</p>
        <p className="text-xs text-muted-foreground">
          Explore the full breakdown and data on the free plan. Upgrade to chat
          with the AI, customize the analysis, and annotate charts.
        </p>
      </div>
      <Link
        href="/protected/profile"
        onClick={() =>
          track("upgrade_clicked", {
            from_plan: "observer",
            to_plan: "investor",
            surface,
          })
        }
        className="mt-1 inline-flex items-center gap-1.5 rounded-md bg-foreground px-3 py-1.5 text-xs font-medium text-background transition-opacity hover:opacity-90"
      >
        <Sparkles className="h-3.5 w-3.5" />
        Upgrade to unlock AI
      </Link>
    </div>
  );
}
