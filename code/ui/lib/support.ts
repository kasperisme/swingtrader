/**
 * The one human a user can write to.
 *
 * A single constant rather than the address typed into each surface: it already
 * appeared verbatim in the profile page, and every additional literal is another
 * place a changed address would keep pointing at the old inbox.
 *
 * This is the founder's own inbox, not a shared support alias — the surfaces
 * that show it say so, because "you are writing to the person who built this"
 * is the reason someone bothers to write at all.
 */
export const SUPPORT_EMAIL = "k@newsimpactscreener.com";

/** How the inbox is signed elsewhere in the product. */
export const SUPPORT_NAME = "Kasper";

/**
 * A mailto with the subject filled in, and optionally the page the user was on.
 *
 * `context` goes in the BODY rather than the subject: it is for triage, not for
 * the reader, and a subject line carrying a URL fragment reads like an automated
 * ticket instead of a message to a person. The user sees and can delete it
 * before sending — nothing is transmitted by building this string.
 */
export function supportMailto(subject: string, context?: string | null): string {
  const params = new URLSearchParams({ subject });
  if (context) params.set("body", `\n\n---\nSent from: ${context}`);
  return `mailto:${SUPPORT_EMAIL}?${params.toString()}`;
}
