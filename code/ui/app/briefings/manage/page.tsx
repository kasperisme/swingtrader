import type { Metadata } from "next";
import Link from "next/link";
import {
  getBriefingByEmail,
  verifyBriefingToken,
} from "@/lib/email/briefing-subscriptions";
import { ManageForm } from "./_components/manage-form";

export const metadata: Metadata = {
  title: "Manage your briefing",
  robots: { index: false, follow: false },
};

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <main className="mx-auto w-full max-w-xl px-4 py-12 lg:px-6 lg:py-16">
      <p className="font-mono text-xs uppercase tracking-[0.2em] text-amber-500">
        News Impact Screener · Briefings
      </p>
      <h1 className="mt-3 text-2xl font-bold">Manage your briefing</h1>
      <div className="mt-6">{children}</div>
    </main>
  );
}

export default async function ManageBriefingPage({
  searchParams,
}: {
  searchParams: Promise<{ token?: string }>;
}) {
  const { token } = await searchParams;
  const payload = token ? verifyBriefingToken(token) : null;

  if (!token || !payload) {
    return (
      <Shell>
        <div className="rounded-xl border border-border bg-card p-6">
          <p className="font-medium text-foreground">This link is invalid or expired.</p>
          <p className="mt-2 text-sm text-muted-foreground">
            Open the &ldquo;Edit my briefing&rdquo; link from your most recent
            briefing email, or{" "}
            <Link href="/briefings" className="text-amber-500 underline-offset-2 hover:underline">
              set up a new briefing
            </Link>
            .
          </p>
        </div>
      </Shell>
    );
  }

  const sub = await getBriefingByEmail(payload.email);

  if (!sub) {
    return (
      <Shell>
        <div className="rounded-xl border border-border bg-card p-6">
          <p className="font-medium text-foreground">No briefing found for this email.</p>
          <p className="mt-2 text-sm text-muted-foreground">
            It may have been removed.{" "}
            <Link href="/briefings" className="text-amber-500 underline-offset-2 hover:underline">
              Set up a new briefing
            </Link>
            .
          </p>
        </div>
      </Shell>
    );
  }

  return (
    <Shell>
      <ManageForm
        token={token}
        email={payload.email}
        initialTickers={sub.tickers}
        initialTags={sub.tags}
        initialStatus={sub.status}
      />
    </Shell>
  );
}
