/**
 * Shared visual language for every email this app sends.
 *
 * Resolved from the LIGHT tokens in app/globals.css `:root` — a warm cream
 * theme, not stark white. Kept as literals because email clients cannot read
 * CSS variables, and centralised here because the values are easy to get
 * subtly wrong: see ACCENT_TEXT below.
 */

/** --secondary: the ground behind the card. */
export const PAGE = "#f1ece4";
/** --card. */
export const CARD = "#fefdfb";
/** --muted: boxes inside the card. */
export const PANEL = "#f2eee8";
/** --foreground. */
export const TEXT = "#0f1729";
/** --muted-foreground. */
export const MUTED = "#546378";
/** --border. */
export const BORDER = "#dfd6cd";
/** --primary. Button fills only — see ACCENT_TEXT for anything set in type. */
export const ACCENT = "#f59f0a";
/**
 * Amber that actually passes contrast on cream, and the same light-mode value
 * app/quote/[symbol]/_components/priced-in-ui.tsx picks for its bands.
 * --primary at 11-15px on this background does not.
 */
export const ACCENT_TEXT = "#b45309";
/** --primary-foreground: type on an ACCENT fill. */
export const ON_ACCENT = "#0f1729";

export const MONO =
  "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace";
export const SANS =
  "'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif";

/** Body copy. */
export const P = `font-family:${SANS};font-size:15px;line-height:1.6;color:${TEXT};margin:0 0 14px 0;`;

export function esc(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
