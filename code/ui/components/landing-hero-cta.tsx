"use client";

import { useEffect, useRef, useState } from "react";

import { EarlyAccessSignupForm } from "@/components/early-access-signup-form";
import { track } from "@/lib/analytics/events";
import {
  LANDING_HERO_CHALLENGERS,
  pickLandingHeroVariant,
  type LandingHeroVariant,
} from "@/components/landing-cta-variants";

/**
 * Landing-hero copy (headline + description + signup) with an A/B-testable
 * variant. The `control` cell carries the CMS/default hero copy, so SSR renders
 * real, indexable hero text (good for LCP/SEO); the assigned challenger swaps in
 * on mount. A `cta_exposed` event fires once when the hero is seen, and the
 * variant id is forwarded to /api/early-access via the signup form.
 */
export function LandingHeroCta({ control }: { control: LandingHeroVariant }) {
  const variants: LandingHeroVariant[] = [control, ...LANDING_HERO_CHALLENGERS];
  const [variant, setVariant] = useState<LandingHeroVariant>(control);
  const headlineRef = useRef<HTMLHeadingElement | null>(null);
  const exposed = useRef(false);

  // Resolve the sticky variant once on the client.
  useEffect(() => {
    setVariant(pickLandingHeroVariant(variants));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Fire the exposure event the first time the hero is actually seen.
  useEffect(() => {
    const el = headlineRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !exposed.current) {
          exposed.current = true;
          track("cta_exposed", { cta: "landing_hero", variant: variant.id });
          obs.disconnect();
        }
      },
      { threshold: 0.4 },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [variant.id]);

  return (
    <>
      <h1
        ref={headlineRef}
        data-cta-variant={variant.id}
        className="mt-6 text-4xl font-bold tracking-tight sm:text-5xl lg:text-[3.25rem] lg:leading-[1.1]"
      >
        {variant.headline}{" "}
        <span className="text-amber-400">{variant.highlight}</span>
      </h1>

      <p className="mt-5 max-w-lg text-base leading-7 text-muted-foreground sm:text-lg">
        {variant.description}
      </p>

      <EarlyAccessSignupForm
        align="start"
        idSuffix="hero"
        source="landing-hero"
        variant={variant.id}
        ctaText={{
          headline: variant.headline,
          highlight: variant.highlight,
          description: variant.description,
          ctaLabel: variant.ctaLabel,
        }}
        ctaLabel={variant.ctaLabel}
      />
    </>
  );
}
