import { isSanityConfigured, sanityFetch } from "@/lib/sanity/client";

/**
 * Resolve an arena agent to the trader profile it is modelled on.
 *
 * The join lives on the Sanity side (`trader.arenaAgentSlug`) rather than on the
 * agent row, because the editorial content is what changes — a trader can be
 * added, retitled or unpublished without a migration, and an agent whose profile
 * has not been written yet simply gets no link instead of a dead one.
 */
export type TraderLink = {
  slug: string;
  name: string;
  knownFor?: string;
  style?: string;
  summary?: string;
};

const byAgentQuery = `
  *[_type == "trader" && arenaAgentSlug == $agentSlug && defined(slug.current)][0] {
    "slug": slug.current,
    name,
    knownFor,
    style,
    summary
  }
`;

export async function getTraderForAgent(
  agentSlug: string,
): Promise<TraderLink | null> {
  if (!isSanityConfigured) return null;
  try {
    return await sanityFetch<TraderLink | null>(byAgentQuery, {
      agentSlug,
    });
  } catch (e) {
    console.warn("getTraderForAgent", e);
    return null;
  }
}
