/**
 * A/B-testable copy variants for the article early-access CTA.
 *
 * A visitor is assigned one variant (sticky, see `pickArticleCtaVariant`) and
 * that id flows into the `cta_exposed` event and the signup, so conversion can
 * be split by variant in PostHog and in the `early_access_signups.source`
 * column ("article:<id>").
 *
 * Every variant shares the same shape (heading + body + ctaLabel) so swapping
 * copy never causes layout shift. The id is the analytics key — keep it stable.
 */
export type ArticleCtaVariant = {
  id: string;
  heading: string;
  body: string;
  ctaLabel: string;
};

export const ARTICLE_CTA_VARIANTS: readonly ArticleCtaVariant[] = [
  {
    // A — Regret aversion
    id: "a_regret_aversion",
    heading: "You’re reading about it. Someone else is already positioned.",
    body: "News Impact Screener scores every headline against the stocks it moves — before the chart reacts. Join the early-access list and get alerted the moment a story hits your tickers.",
    ctaLabel: "Join early access",
  },
  {
    // B — Loss aversion
    id: "b_loss_aversion",
    heading: "By the time it’s on the chart, it’s too late.",
    body: "News Impact Screener scores every story against the stocks it moves before the price reacts. You just read one of those stories. Now you know the signal exists.",
    ctaLabel: "Join the early-access list",
  },
  {
    // C — Social proof + specificity
    id: "c_social_proof",
    heading:
      "Most traders see the move. Screener users see what caused it — three minutes earlier.",
    body: "Every headline gets scored against the tickers it moves, in real time. You’re already reading the news. Get the alert before the chart catches up.",
    ctaLabel: "Join early access",
  },
  {
    // D — Pattern interrupt
    id: "d_pattern_interrupt",
    heading: "Don’t read the news. Screen it.",
    body: "Every headline scored against the stocks it moves — before the move shows up on the chart. Get alerted the moment a story hits the tickers you care about.",
    ctaLabel: "Get early access",
  },
  {
    // E — Curiosity gap
    id: "e_curiosity_gap",
    heading: "This article just moved something. Did you catch which ticker?",
    body: "News Impact Screener tells you — automatically, in real time. Join the early-access list and stop reading news without knowing what it means for your portfolio.",
    ctaLabel: "Join the list",
  },
  {
    // F — Exclusivity + FOMO
    id: "f_exclusivity_fomo",
    heading: "The signal was in this article. Most people missed it.",
    body: "News Impact Screener scores every headline against the stocks it moves before the price reacts. Join early access — get the alert before the chart tells the story.",
    ctaLabel: "Get early access",
  },
  {
    // G — Minimal friction
    id: "g_minimal_friction",
    heading: "Early access",
    body: "You read the news. We score it against the stocks it moves — before the chart reacts. Be first to know on the tickers you follow.",
    ctaLabel: "Join the early-access list",
  },
  {
    // H — Identity reframe
    id: "h_identity_reframe",
    heading: "Reading news without screening it is just noise.",
    body: "News Impact Screener links every headline to the stocks it moves — in real time, before the price reacts. Join early access and turn your reading into an edge.",
    ctaLabel: "Join early access",
  },
  {
    // I — Hypothetical framing
    id: "i_hypothetical",
    heading: "What if you got the alert before the chart moved?",
    body: "That’s exactly what News Impact Screener does. Every headline scored against the tickers it moves — automatically. Join the early-access list to start.",
    ctaLabel: "Join early access",
  },
  {
    // J — Effort reframe
    id: "j_effort_reframe",
    heading: "You already found the news. We find the trade.",
    body: "News Impact Screener scores every headline against the stocks it moves before the chart reacts. Join the early-access list — get alerted the moment it matters.",
    ctaLabel: "Join the early-access list",
  },
] as const;

export const DEFAULT_ARTICLE_CTA_VARIANT = ARTICLE_CTA_VARIANTS[0];

export function getArticleCtaVariant(id: string | null): ArticleCtaVariant {
  return (
    ARTICLE_CTA_VARIANTS.find((v) => v.id === id) ?? DEFAULT_ARTICLE_CTA_VARIANT
  );
}

/**
 * Resolve a sticky variant for this browser. Reuses a prior assignment so the
 * reader always sees the same CTA (a clean A/B unit); otherwise picks one
 * uniformly at random and persists it. Returns the default on the server / when
 * storage is unavailable.
 */
export function pickArticleCtaVariant(): ArticleCtaVariant {
  if (typeof window === "undefined") return DEFAULT_ARTICLE_CTA_VARIANT;

  const KEY = "article_cta_variant";
  try {
    const stored = window.localStorage.getItem(KEY);
    const existing = ARTICLE_CTA_VARIANTS.find((v) => v.id === stored);
    if (existing) return existing;

    const chosen =
      ARTICLE_CTA_VARIANTS[
        Math.floor(Math.random() * ARTICLE_CTA_VARIANTS.length)
      ];
    window.localStorage.setItem(KEY, chosen.id);
    return chosen;
  } catch {
    return DEFAULT_ARTICLE_CTA_VARIANT;
  }
}
