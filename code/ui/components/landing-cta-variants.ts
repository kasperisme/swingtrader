/**
 * A/B-testable copy variants for the landing-page HERO.
 *
 * The hero headline is split into a base + an amber-highlighted phrase, mirroring
 * the existing markup (`{headline} <span class="text-amber-400">{highlight}</span>`).
 *
 * The CMS/default hero copy is injected at runtime as the `control` cell (see
 * `LandingHeroCta`), so these are the *challengers* tested against it. A visitor
 * is assigned one cell (sticky, `pickLandingHeroVariant`) and that id flows into
 * the `cta_exposed` event and the signup (`source="landing-hero:<id>"`).
 *
 * Keep ids stable — they're the analytics key. Keep headlines a similar length
 * so the post-hydration swap doesn't shift the hero.
 */
export type LandingHeroVariant = {
  id: string;
  headline: string;
  highlight: string;
  description: string;
  ctaLabel: string;
};

export const LANDING_HERO_CHALLENGERS: readonly LandingHeroVariant[] = [
  {
    // Loss aversion
    id: "loss_aversion",
    headline: "By the time it’s on the chart,",
    highlight: "it’s already too late.",
    description:
      "News Impact Screener scores every headline against the stocks it moves — before the price reacts. Catch the signal while it still matters.",
    ctaLabel: "Join early access",
  },
  {
    // Speed / edge
    id: "speed_edge",
    headline: "See what the news moves —",
    highlight: "before the chart does.",
    description:
      "Every headline scored against the tickers it touches, in real time. Be early, not late.",
    ctaLabel: "Get early access",
  },
  {
    // Identity reframe
    id: "identity_reframe",
    headline: "Reading the news isn’t research.",
    highlight: "Screening it is.",
    description:
      "News Impact Screener links every headline to the stocks it moves — so your reading becomes an edge, not noise.",
    ctaLabel: "Join early access",
  },
  {
    // Effort reframe
    id: "effort_reframe",
    headline: "You follow the news.",
    highlight: "We find the trade.",
    description:
      "News Impact Screener scores every headline against the stocks it moves before the chart reacts — and alerts you the moment it matters.",
    ctaLabel: "Join the early-access list",
  },
  {
    // Curiosity + specificity
    id: "curiosity_specificity",
    headline: "Which stock did today’s headline move?",
    highlight: "Know in seconds.",
    description:
      "News Impact Screener scores every story against the tickers it touches, automatically. Stop guessing what the news means for your portfolio.",
    ctaLabel: "Join early access",
  },
  {
    // Regret aversion
    id: "regret_aversion",
    headline: "While you read the news,",
    highlight: "someone’s already positioned.",
    description:
      "News Impact Screener scores every headline against the stocks it moves — before the chart reacts. Get alerted the moment a story hits your tickers.",
    ctaLabel: "Join early access",
  },
] as const;

const STORAGE_KEY = "landing_hero_cta_variant";

/**
 * Resolve a sticky hero variant for this browser from the provided cell list
 * (control + challengers). Reuses a prior assignment; otherwise picks one
 * uniformly at random and persists it. Returns the first cell (control) on the
 * server / when storage is unavailable.
 */
export function pickLandingHeroVariant(
  variants: readonly LandingHeroVariant[],
): LandingHeroVariant {
  const fallback = variants[0];
  if (typeof window === "undefined" || variants.length === 0) return fallback;

  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    const existing = variants.find((v) => v.id === stored);
    if (existing) return existing;

    const chosen = variants[Math.floor(Math.random() * variants.length)];
    window.localStorage.setItem(STORAGE_KEY, chosen.id);
    return chosen;
  } catch {
    return fallback;
  }
}
