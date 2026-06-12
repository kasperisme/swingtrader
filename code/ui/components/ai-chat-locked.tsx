import Link from "next/link";
import { Sparkles } from "lucide-react";

/**
 * Shown in place of the AI chat for Observers (free tier). They keep full access
 * to the breakdown + data — only the AI chat / customization is gated behind a
 * paid plan (or the active trial). Used by the screenings and charts pages.
 */
export function AiChatLocked() {
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
        className="mt-1 inline-flex items-center gap-1.5 rounded-md bg-foreground px-3 py-1.5 text-xs font-medium text-background transition-opacity hover:opacity-90"
      >
        <Sparkles className="h-3.5 w-3.5" />
        Upgrade to unlock AI
      </Link>
    </div>
  );
}
