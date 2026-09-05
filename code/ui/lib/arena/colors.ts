/**
 * Colour index per agent, fixed at roster order and shared by every surface
 * that draws the arena.
 *
 * Hue follows the ENTITY, never its rank — a leader change must not repaint
 * the board — and the two deterministic controls get no hue at all, because
 * they are the baseline rather than a competing series. Resolve to a CSS
 * colour with `hsl(var(--arena-N))`; the tokens live in `app/globals.css`.
 */
export const ARENA_COLOR_INDEX: Record<string, number> = {
  "jim-clamor": 1,
  "michael-beary": 2,
  "mark-minervine": 3,
  "barren-wuffett": 4,
  "philip-fissure": 5,
  "jim-sigmons": 6,
  "chris-cameo": 7,
};

/** The CSS colour for an agent, or `null` for the controls (no hue). */
export function arenaColor(slug: string): string | null {
  const i = ARENA_COLOR_INDEX[slug];
  return i == null ? null : `hsl(var(--arena-${i}))`;
}
