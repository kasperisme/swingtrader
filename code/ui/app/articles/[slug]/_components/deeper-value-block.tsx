"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ArrowUpRight, Check } from "lucide-react";

import { EarlyAccessSignupForm } from "@/components/early-access-signup-form";
import { track } from "@/lib/analytics/events";
import { bumpSessionArticleView } from "@/lib/analytics/engagement";
import {
  DEFAULT_VALUE_PROP_VARIANT,
  FREE_HERE_BULLETS,
  pickValuePropVariant,
  type PlatformFeature,
  type ValuePropVariant,
} from "./value-prop-variants";

/**
 * Tier-2 "go deeper" block — the single primary conversion unit on an article
 * page. It makes the value ladder explicit: a "free here" column (what the page
 * already gave you) beside an "in the platform" column led by an experiment-
 * assigned value proposition (see value-prop-variants.ts).
 *
 * - A sticky variant is assigned per browser, so the same reader always sees the
 *   same offer (a clean experiment unit).
 * - `cta_exposed` fires once when the block scrolls into view, tagged
 *   cta="article_deeper_value" + the variant id → split exposure by value prop.
 * - Conversions route through the early-access form with
 *   source="article_deeper_value" + variant=<id>, so PostHog (waitlist_joined)
 *   and Supabase (early_access_signups.metadata) both attribute the signup to
 *   the value prop that won.
 *
 * Carries id="early-access" so the on-page gate anchors and the FloatingCTA
 * (which focuses the email input inside #early-access) keep working.
 */

/** The full platform menu — reordered so the assigned variant leads. */
const PLATFORM_FEATURES: Record<
  PlatformFeature,
  { label: string; href: string }
> = {
  live_screenings: {
    label: "Live screenings emailed on schedule",
    href: "/marketscreenings",
  },
  relationship_maps: {
    label: "Full supplier / customer / competitor maps",
    href: "/protected/relations",
  },
  stage2_trend: {
    label: "Stage-2 trend confirmation on every name",
    href: "/marketscreenings",
  },
  full_breakdown: {
    label: "Every cluster and dimension unlocked",
    href: "/protected",
  },
};

const FEATURE_ORDER: PlatformFeature[] = [
  "live_screenings",
  "relationship_maps",
  "stage2_trend",
  "full_breakdown",
];

export function DeeperValueBlock({
  tickers,
  article,
  impactedCount = 0,
  authenticated = false,
}: {
  tickers: string[];
  article: { slug: string; id: number; title: string };
  /** How many tickers this story moves (winners + losers) — used in the copy. */
  impactedCount?: number;
  /** Members skip the email capture and get direct links into the platform. */
  authenticated?: boolean;
}) {
  const tracked = tickers.slice(0, 4);
  const [variant, setVariant] = useState<ValuePropVariant>(
    DEFAULT_VALUE_PROP_VARIANT,
  );
  const sectionRef = useRef<HTMLElement | null>(null);
  const exposed = useRef(false);

  // Resolve the sticky variant on the client, and count this article view.
  useEffect(() => {
    setVariant(pickValuePropVariant());
    bumpSessionArticleView();
  }, []);

  // Fire the exposure event the first time the block is actually seen.
  useEffect(() => {
    const el = sectionRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !exposed.current) {
          exposed.current = true;
          track("cta_exposed", {
            cta: "article_deeper_value",
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

  // Platform menu with the assigned feature pulled to the front.
  const orderedFeatures = [
    variant.feature,
    ...FEATURE_ORDER.filter((f) => f !== variant.feature),
  ];

  const lead = PLATFORM_FEATURES[variant.feature];

  return (
    <section
      ref={sectionRef}
      id="early-access"
      data-value-prop={variant.id}
      className="scroll-mt-24 overflow-hidden rounded-2xl border border-amber-500/25 bg-gradient-to-br from-amber-500/[0.08] via-card/40 to-card/20 p-6 sm:p-8"
    >
      <p className="inline-flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.2em] text-amber-500/90">
        <span className="h-px w-6 bg-amber-500/60" />
        {variant.eyebrow}
      </p>

      <h2 className="mt-4 max-w-2xl text-2xl font-bold leading-tight tracking-tight md:text-3xl">
        {variant.heading}
      </h2>
      <p className="mt-3 max-w-2xl text-sm leading-relaxed text-muted-foreground">
        {variant.body}
      </p>

      {/* The value ladder, made explicit: what you already have vs. what's next. */}
      <div className="mt-6 grid gap-6 sm:grid-cols-2">
        <div className="rounded-xl border border-border/50 bg-background/30 p-4">
          <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-emerald-500/80">
            On this page · free
          </p>
          <ul className="mt-3 space-y-2">
            {FREE_HERE_BULLETS.map((b) => (
              <li
                key={b}
                className="flex items-start gap-2 text-[13px] leading-snug text-foreground/85"
              >
                <Check
                  size={14}
                  className="mt-0.5 shrink-0 text-emerald-500"
                />
                {b}
              </li>
            ))}
          </ul>
        </div>

        <div className="rounded-xl border border-amber-500/25 bg-amber-500/[0.04] p-4">
          <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-amber-500/90">
            In the platform
          </p>
          <ul className="mt-3 space-y-2">
            {orderedFeatures.map((f, i) => {
              const feat = PLATFORM_FEATURES[f];
              const isLead = i === 0;
              return (
                <li
                  key={f}
                  className={`flex items-start gap-2 text-[13px] leading-snug ${
                    isLead
                      ? "font-medium text-amber-200"
                      : "text-muted-foreground"
                  }`}
                >
                  <ArrowUpRight
                    size={14}
                    className={`mt-0.5 shrink-0 ${
                      isLead ? "text-amber-400" : "text-amber-500/50"
                    }`}
                  />
                  {isLead ? variant.leadBullet : feat.label}
                </li>
              );
            })}
          </ul>
        </div>
      </div>

      {tracked.length > 0 ? (
        <ul
          className="mt-6 flex flex-wrap gap-2"
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

      {authenticated ? (
        // Members don't need the capture — send them straight to the payoff.
        <Link
          href={lead.href}
          className="mt-6 inline-flex h-12 items-center justify-center gap-2 rounded-xl bg-violet-600 px-6 text-sm font-semibold text-white shadow-lg shadow-violet-500/20 transition-colors hover:bg-violet-500"
        >
          {variant.ctaLabel}
          <ArrowUpRight size={16} />
        </Link>
      ) : (
        <>
          <EarlyAccessSignupForm
            align="start"
            idSuffix="deeper-value"
            source="article_deeper_value"
            variant={variant.id}
            ctaText={{
              eyebrow: variant.eyebrow,
              heading: variant.heading,
              body: variant.body,
              ctaLabel: variant.ctaLabel,
              feature: variant.feature,
            }}
            article={{
              slug: article.slug,
              id: article.id,
              title: article.title,
              tickers: tracked,
            }}
            ctaLabel={variant.ctaLabel}
          />
          <p className="mt-3 text-xs text-muted-foreground/70">
            Free account, 30 seconds. No credit card.
            {impactedCount > 0
              ? ` Covers all ${impactedCount} tickers this story moves.`
              : ""}
          </p>
        </>
      )}
    </section>
  );
}
