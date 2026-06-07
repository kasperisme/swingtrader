"use client";

import { useState, useTransition } from "react";
import { Check, ChevronDown, Globe, Loader2 } from "lucide-react";
import { setPreferredLanguage } from "@/app/actions/preferences";
import {
  SUPPORTED_LANGUAGES,
  DEFAULT_LANGUAGE,
  type LanguageCode,
} from "@/lib/languages";

type Props = {
  initialValue?: LanguageCode;
  /** Notifies the parent of a successful change (e.g. to thread into other flows). */
  onChanged?: (lang: LanguageCode) => void;
  className?: string;
};

/**
 * Self-contained language picker. Persists to user_profiles.metadata on change
 * (the agent + Telegram delivery read the same key). Optimistic UI with a small
 * saved/saving indicator; reverts the visible value if the save fails.
 */
export function LanguageSelector({ initialValue = DEFAULT_LANGUAGE, onChanged, className }: Props) {
  const [value, setValue] = useState<LanguageCode>(initialValue);
  const [pending, startTransition] = useTransition();
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function handleChange(next: LanguageCode) {
    const prev = value;
    setValue(next);
    setSaved(false);
    setError(null);
    startTransition(async () => {
      const res = await setPreferredLanguage(next);
      if (res.ok) {
        setSaved(true);
        onChanged?.(next);
        setTimeout(() => setSaved(false), 2000);
      } else {
        setValue(prev);
        setError(res.error);
      }
    });
  }

  return (
    <div className={className}>
      <div className="relative">
        <Globe className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <select
          aria-label="Preferred language"
          value={value}
          onChange={(e) => handleChange(e.target.value as LanguageCode)}
          disabled={pending}
          className="w-full appearance-none rounded-md border border-input bg-background py-2 pl-9 pr-9 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-60"
        >
          {SUPPORTED_LANGUAGES.map((l) => (
            <option key={l.code} value={l.code}>
              {l.endonym} · {l.label}
            </option>
          ))}
        </select>
        <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2">
          {pending ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
          ) : saved ? (
            <Check className="h-3.5 w-3.5 text-emerald-500" />
          ) : (
            <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
          )}
        </span>
      </div>
      {error && <p className="mt-1 text-xs text-destructive">{error}</p>}
    </div>
  );
}
