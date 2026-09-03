import { Suspense } from "react";
import Link from "next/link";
import type { Metadata } from "next";
import { ArrowUpRight } from "lucide-react";
import { isSanityConfigured, sanityFetch } from "@/lib/sanity/client";
import { traderPreviewsQuery } from "@/lib/sanity/queries";
import type { TraderPreview } from "@/lib/sanity/types";
import { SITE_URL } from "@/lib/site";
import { TraderSearch } from "./_components/trader-search";

export const metadata: Metadata = {
  title: "Famous Traders",
  description:
    "A reference on the investors worth learning from — what each one actually did, the ideas that survived, and which of them the Arena's AI agents are modelled on.",
  alternates: { canonical: `${SITE_URL}/traders` },
};

function Skeleton() {
  return (
    <div className="grid gap-px bg-border sm:grid-cols-2" aria-hidden>
      {Array.from({ length: 6 }, (_, i) => (
        <div key={i} className="h-32 animate-pulse bg-background" />
      ))}
    </div>
  );
}

async function Directory() {
  const traders = isSanityConfigured
    ? await sanityFetch<TraderPreview[]>(traderPreviewsQuery)
    : [];

  if (traders.length === 0) {
    return (
      <div className="border-l-2 border-l-border py-6 pl-5">
        <p className="text-sm font-medium">No traders published yet</p>
        <p className="mt-1.5 max-w-[60ch] text-sm leading-relaxed text-muted-foreground">
          Profiles are written in the studio and appear here once published.
        </p>
      </div>
    );
  }

  return <TraderSearch traders={traders} />;
}

export default function TradersPage() {
  return (
    <main className="mx-auto max-w-5xl px-4 py-12 sm:py-16">
      <header className="max-w-[68ch]">
        <p className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
          Reference
        </p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">
          Famous Traders
        </h1>
        <p className="mt-4 text-base leading-relaxed text-muted-foreground">
          The investors worth learning from, and what each one actually did —
          not the quotes, the method. Every profile covers the approach, the
          ideas that survived contact with the market, and where the approach
          fails.
        </p>
        <p className="mt-3 text-base leading-relaxed text-muted-foreground">
          Several of them have a counterpart in{" "}
          <Link
            href="/arena"
            className="font-medium text-foreground underline decoration-amber-500/40 underline-offset-4 transition-colors hover:decoration-amber-500"
          >
            The Arena
          </Link>
          , where an AI agent runs their approach against a live $100,000 paper
          account. Those profiles link straight to the agent, so you can read
          the method and then watch it trade.
        </p>
      </header>

      <section className="mt-12">
        <Suspense fallback={<Skeleton />}>
          <Directory />
        </Suspense>
      </section>
    </main>
  );
}
