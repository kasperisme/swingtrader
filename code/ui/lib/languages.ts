// Supported UI / delivery languages for the platform.
//
// Phase 1 covers the "Core European" set. The agent's LLM output and the
// Telegram message templates both respect a user's choice (stored in
// user_profiles.metadata.preferred_language). Keep this list in sync with the
// Python mirror at code/analytics/shared/i18n.py.

export const SUPPORTED_LANGUAGES = [
  { code: "en", label: "English", endonym: "English" },
  { code: "es", label: "Spanish", endonym: "Español" },
  { code: "de", label: "German", endonym: "Deutsch" },
  { code: "fr", label: "French", endonym: "Français" },
  { code: "pt", label: "Portuguese", endonym: "Português" },
  { code: "it", label: "Italian", endonym: "Italiano" },
  { code: "da", label: "Danish", endonym: "Dansk" },
] as const;

export type LanguageCode = (typeof SUPPORTED_LANGUAGES)[number]["code"];

export const DEFAULT_LANGUAGE: LanguageCode = "en";

const CODES = new Set(SUPPORTED_LANGUAGES.map((l) => l.code));

export function isSupportedLanguage(value: unknown): value is LanguageCode {
  return typeof value === "string" && CODES.has(value as LanguageCode);
}

/** Coerce any stored value to a supported code, falling back to the default. */
export function normalizeLanguage(value: unknown): LanguageCode {
  return isSupportedLanguage(value) ? value : DEFAULT_LANGUAGE;
}

/** Native-name label for a code (e.g. "es" → "Español"). */
export function languageEndonym(code: LanguageCode): string {
  return SUPPORTED_LANGUAGES.find((l) => l.code === code)?.endonym ?? code;
}
