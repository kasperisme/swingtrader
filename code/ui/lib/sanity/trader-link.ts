import { isSanityConfigured, sanityFetch } from "@/lib/sanity/client";

/**
 * Resolve an arena agent to the trader profile(s) it is modelled on.
 *
 * The join lives on the Sanity side (`trader.arenaAgentSlug`) rather than on the
 * agent row, because the editorial content is what changes — a trader can be
 * added, retitled or unpublished without a migration, and an agent whose profile
 * has not been written yet simply gets no link instead of a dead one.
 *
 * It is MANY-to-one and always was: several trader documents can carry the same
 * `arenaAgentSlug`, and the query simply took `[0]`. An agent's method is often
 * not one person's — the second-order chain agent owes as much to O'Neil as to
 * Fisher — so the plural is the honest shape. Add another trader by setting the
 * same agent slug on it; nothing else needs changing.
 *
 * Ordered by the trader's own `order` so the primary influence leads and the
 * sequence is editorial rather than incidental.
 */
export type TraderLink = {
  slug: string;
  name: string;
  knownFor?: string;
  style?: string;
  summary?: string;
  imageUrl?: string;
  imageAlt?: string;
};

const byAgentQuery = `
  *[_type == "trader" && arenaAgentSlug == $agentSlug && defined(slug.current)]
    | order(order asc, name asc) {
    "slug": slug.current,
    name,
    knownFor,
    style,
    summary,
    "imageUrl": image.asset->url,
    "imageAlt": image.alt
  }
`;

export async function getTradersForAgent(
  agentSlug: string,
): Promise<TraderLink[]> {
  if (!isSanityConfigured) return [];
  try {
    return (await sanityFetch<TraderLink[]>(byAgentQuery, { agentSlug })) ?? [];
  } catch (e) {
    console.warn("getTradersForAgent", e);
    return [];
  }
}

/** The primary influence, for callers that can only name one. */
export async function getTraderForAgent(
  agentSlug: string,
): Promise<TraderLink | null> {
  return (await getTradersForAgent(agentSlug))[0] ?? null;
}
