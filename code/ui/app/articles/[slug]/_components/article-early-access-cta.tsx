"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ArrowUpRight, LineChart } from "lucide-react";

import { EarlyAccessSignupForm } from "@/components/early-access-signup-form";
import { track } from "@/lib/analytics/events";
import { bumpSessionArticleView } from "@/lib/analytics/engagement";
import {
  DEFAULT_ARTICLE_CTA_VARIANT,
  pickArticleCtaVariant,
  type ArticleCtaVariant,
} from "./cta-variants";

/**
 * Article early-access CTA with an A/B-testable copy variant.
 *
 * - A sticky variant is assigned per browser (localStorage) so the same reader
 *   always sees the same CTA.
 * - A `cta_exposed` event fires once when the CTA scrolls into view, so we can
 *   measure exposure → conversion per variant.
 * - The variant id is passed to the signup form, which forwards it to
 *   /api/early-access — so the resulting `waitlist_joined` event and the stored
 *   signup row both record which CTA the user was exposed to.
 *
 * First paint renders the default variant (keeps SSR/hydration stable); the
 * assigned variant resolves on mount. All variants share the same layout, so
 * the copy swap never shifts the page.
 */
export function ArticleEarlyAccessCTA({
  tickers,
  article,
  impactedCount = 0,
}: {
  tickers: string[];
  article: { slug: string; id: number; title: string };
  /**
   * How many tickers this story moves (winners + losers). Drives the
   * value-explicit unlock headline; falls back to generic copy when 0.
   */
  impactedCount?: number;
}) {
  const tracked = tickers.slice(0, 4);
  // Value-explicit unlock copy. [N] = impacted tickers, else the tracked count.
  const unlockN = impactedCount || tracked.length;
  const unlockHeading = unlockN
    ? `See which ${unlockN} tickers this story hits hardest`
    : "See which tickers this story hits hardest";
  const unlockBody =
    "Unlock the full impact breakdown — and whether these names are in a Stage 2 uptrend right now. Free account, 30 seconds.";
  const [variant, setVariant] = useState<ArticleCtaVariant>(
    DEFAULT_ARTICLE_CTA_VARIANT,
  );
  const sectionRef = useRef<HTMLElement | null>(null);
  const exposed = useRef(false);

  // Resolve the sticky variant once on the client, and count this article view.
  useEffect(() => {
    setVariant(pickArticleCtaVariant());
    bumpSessionArticleView();
  }, []);

  // Fire the exposure event the first time the CTA is actually seen.
  useEffect(() => {
    const el = sectionRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !exposed.current) {
          exposed.current = true;
          track("cta_exposed", {
            cta: "article_early_access",
            variant: variant.id,
          });
          obs.disconnect();
        }
      },
      { threshold: 0.4 },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [variant.id]);

  return (
    <section
      ref={sectionRef}
      id="early-access"
      data-cta-variant={variant.id}
      className="scroll-mt-24 overflow-hidden rounded-2xl border border-amber-500/25 bg-gradient-to-br from-amber-500/[0.08] via-card/40 to-card/20 p-6 sm:p-8"
    >
      {variant.heading.trim().toLowerCase() !== "early access" ? (
        <p className="inline-flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.2em] text-amber-500/90">
          <span className="h-px w-6 bg-amber-500/60" />
          Early access
        </p>
      ) : null}
      <h2 className="mt-4 max-w-2xl text-2xl font-bold leading-tight tracking-tight md:text-3xl">
        {unlockHeading}
      </h2>
      <p className="mt-3 max-w-2xl text-sm leading-relaxed text-muted-foreground">
        {unlockBody}
      </p>

      {tracked.length > 0 ? (
        <ul
          className="mt-5 flex flex-wrap gap-2"
          aria-label="Tickers in this story"
        >
          {tracked.map((t) => (
            <li
              key={t}
              className="inline-flex items-center rounded-md border border-amber-500/30 bg-amber-500/10 px-2.5 py-1 font-mono text-xs font-semibold tracking-tight text-amber-300"
            >
              {t}
            </li>
          ))}
        </ul>
      ) : null}

      <EarlyAccessSignupForm
        align="start"
        idSuffix="article"
        source="article"
        variant={variant.id}
        ctaText={{
          eyebrow: "Early access",
          heading: unlockHeading,
          body: unlockBody,
          ctaLabel: "Unlock free →",
        }}
        article={{
          slug: article.slug,
          id: article.id,
          title: article.title,
          tickers: tracked,
        }}
        ctaLabel="Unlock free →"
      />

      <p className="mt-3 text-xs text-muted-foreground/70">
        No credit card. Cancel anytime.
      </p>

      <Link
        href="/marketscreenings"
        className="group mt-6 inline-flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground transition-colors hover:text-amber-400"
      >
        <LineChart size={13} />
        Browse live screenings
        <ArrowUpRight
          size={12}
          className="transition-transform duration-200 group-hover:-translate-y-px group-hover:translate-x-px"
        />
      </Link>
    </section>
  );
}
