/**
 * Value-proposition experiment for the article "go deeper" block (Tier 2).
 *
 * Unlike `cta-variants.ts` — which tests the *tone* of one fixed offer — this
 * tests *which platform payoff to lead with*. A visitor is assigned one variant
 * (sticky, see `pickValuePropVariant`); the id flows into the `cta_exposed`
 * event (cta = "article_deeper_value") and, on conversion, into the signup
 * (source = "article_deeper_value", variant = <id>). So performance is split by
 * value prop in BOTH PostHog (waitlist_joined breakdown by cta_variant) and
 * Supabase (early_access_signups where source = 'article_deeper_value', grouped
 * by metadata->>'cta_variant'). No backend or schema changes required.
 *
 * To add a value prop to the test: append an entry with a NEW stable id. To
 * retire one: remove it (its historical events/rows keep their id). Keep every
 * variant the same shape so swapping never shifts layout.
 */
export type PlatformFeature =
  | "live_screenings"
  | "relationship_maps"
  | "stage2_trend"
  | "full_breakdown";

export type ValuePropVariant = {
  /** Stable analytics key — never reuse or repurpose an id. */
  id: string;
  /** The platform payoff this variant leads with. */
  feature: PlatformFeature;
  /** Short eyebrow above the heading. */
  eyebrow: string;
  /** Value-prop headline — the thing we're testing. */
  heading: string;
  /** One supporting sentence. */
  body: string;
  /** The lead "in the platform" bullet (this variant's emphasis). */
  leadBullet: string;
  /** Primary action label (the "action" shown to the user). */
  ctaLabel: string;
};

export const VALUE_PROP_VARIANTS: readonly ValuePropVariant[] = [
  {
    id: "vp_live_screenings",
    feature: "live_screenings",
    eyebrow: "Go deeper",
    heading: "Get the names this kind of story moves — emailed every week.",
    body: "You just saw which tickers this one story hits. A free account turns that into a standing screen: the movers delivered on schedule, before the chart catches up.",
    leadBullet: "Live screenings emailed on schedule — the week's movers, ranked",
    ctaLabel: "Get the weekly movers →",
  },
  {
    id: "vp_relationship_maps",
    feature: "relationship_maps",
    eyebrow: "Go deeper",
    heading: "See the full web of tickers behind this story — not just the obvious one.",
    body: "Every name here sits in a network of suppliers, customers and competitors. The relationship map shows the second-order exposure most readers miss.",
    leadBullet: "Full relationship maps — supplier, customer & competitor exposure",
    ctaLabel: "Open the relationship map →",
  },
  {
    id: "vp_stage2_trend",
    feature: "stage2_trend",
    eyebrow: "Go deeper",
    heading: "Know which of these tickers are actually in an uptrend right now.",
    body: "Impact tells you what the news touches. Stage-2 analysis tells you which of those names are in a confirmed uptrend today — the difference between a headline and a trade.",
    leadBullet: "Stage-2 trend confirmation — which exposed names are tradeable now",
    ctaLabel: "Check the trend →",
  },
  {
    id: "vp_full_breakdown",
    feature: "full_breakdown",
    eyebrow: "Go deeper",
    heading: "Unlock every cluster and dimension behind the score.",
    body: "You're seeing the top of the breakdown. A free account opens the full analytical profile — every dimension that moved, and every ticker exposed to it.",
    leadBullet: "The complete impact breakdown — all clusters and dimensions",
    ctaLabel: "Unlock the full breakdown →",
  },
] as const;

export const DEFAULT_VALUE_PROP_VARIANT = VALUE_PROP_VARIANTS[0];

/** Constant "what you already get on this page, free" bullets (Tier 1). */
export const FREE_HERE_BULLETS: readonly string[] = [
  "Impact-rated claims from the story",
  "The tickers this story is exposed to",
  "How the market reaction breaks down",
] as const;

export function getValuePropVariant(id: string | null): ValuePropVariant {
  return (
    VALUE_PROP_VARIANTS.find((v) => v.id === id) ?? DEFAULT_VALUE_PROP_VARIANT
  );
}

/**
 * Resolve a sticky value-prop variant for this browser — reuse a prior
 * assignment so a reader always sees the same offer (a clean experiment unit),
 * otherwise pick uniformly at random and persist it. Returns the default on the
 * server / when storage is unavailable.
 */
export function pickValuePropVariant(): ValuePropVariant {
  if (typeof window === "undefined") return DEFAULT_VALUE_PROP_VARIANT;

  const KEY = "article_value_prop_variant";
  try {
    const stored = window.localStorage.getItem(KEY);
    const existing = VALUE_PROP_VARIANTS.find((v) => v.id === stored);
    if (existing) return existing;

    const chosen =
      VALUE_PROP_VARIANTS[
        Math.floor(Math.random() * VALUE_PROP_VARIANTS.length)
      ];
    window.localStorage.setItem(KEY, chosen.id);
    return chosen;
  } catch {
    return DEFAULT_VALUE_PROP_VARIANT;
  }
}
