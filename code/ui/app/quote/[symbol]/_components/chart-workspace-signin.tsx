import Link from "next/link";
import { LineChart } from "lucide-react";

/**
 * The logged-out counterpart to <AiChatLocked />.
 *
 * Observers are told to upgrade; anonymous readers have nothing to upgrade yet,
 * so the ask is the account. Quote pages are the site's only surfaces with
 * organic traffic and, until now, carried no ask beyond the briefing form —
 * this makes the workspace itself the reason to sign up.
 */
export function ChartWorkspaceSignedOut({ symbol }: { symbol: string }) {
  return (
    <div className="flex h-full min-h-0 flex-col items-center justify-center gap-3 px-6 py-10 text-center">
      <div className="flex h-10 w-10 items-center justify-center rounded-full border border-border bg-muted/40">
        <LineChart className="h-4 w-4 text-amber-500" aria-hidden />
      </div>
      <div className="space-y-1">
        <p className="text-sm font-medium text-foreground">
          Save your work on {symbol}
        </p>
        <p className="text-xs text-muted-foreground">
          The chart is yours to explore either way. An account keeps the levels
          and trendlines you draw, and opens the AI analyst on this ticker.
        </p>
      </div>
      <div className="mt-1 flex items-center gap-2">
        <Link
          href="/auth/sign-up"
          className="inline-flex items-center rounded-md bg-foreground px-3 py-1.5 text-xs font-medium text-background transition-opacity hover:opacity-90"
        >
          Create a free account
        </Link>
        <Link
          href="/auth/login"
          className="inline-flex items-center rounded-md border border-border px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-muted"
        >
          Sign in
        </Link>
      </div>
    </div>
  );
}
