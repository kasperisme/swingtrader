"use client";

import { useEffect, useMemo, useState } from "react";
import { X } from "lucide-react";

type Suggestions = { tickers: string[]; tags: string[] };

function cleanTicker(raw: string): string {
  return raw.trim().toUpperCase().replace(/[^A-Z0-9.\-]/g, "").slice(0, 12);
}
function cleanTag(raw: string): string {
  return raw
    .trim()
    .toLowerCase()
    .replace(/\s+/g, "-")
    .replace(/[^a-z0-9-]/g, "")
    .slice(0, 40);
}

function Chip({ label, prefix, onRemove }: { label: string; prefix: string; onRemove: () => void }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-border/70 bg-muted/50 py-1 pl-2.5 pr-1.5 text-sm">
      <span className="font-medium text-foreground">
        <span className="text-muted-foreground">{prefix}</span>
        {label}
      </span>
      <button
        type="button"
        onClick={onRemove}
        aria-label={`Remove ${label}`}
        className="rounded-full p-0.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </span>
  );
}

function Field({
  legend,
  prefix,
  placeholder,
  values,
  clean,
  suggestions,
  onChange,
}: {
  legend: string;
  prefix: string;
  placeholder: string;
  values: string[];
  clean: (s: string) => string;
  suggestions: string[];
  onChange: (next: string[]) => void;
}) {
  const [draft, setDraft] = useState("");

  const add = (raw: string) => {
    const v = clean(raw);
    if (v && !values.includes(v)) onChange([...values, v].slice(0, 25));
    setDraft("");
  };
  const remove = (v: string) => onChange(values.filter((x) => x !== v));

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      add(draft);
    } else if (e.key === "Backspace" && !draft && values.length) {
      remove(values[values.length - 1]);
    }
  };

  const unused = useMemo(
    () => suggestions.filter((s) => !values.includes(s)).slice(0, 12),
    [suggestions, values],
  );

  return (
    <fieldset className="space-y-2">
      <legend className="text-sm font-medium text-foreground">{legend}</legend>
      <div className="flex flex-wrap items-center gap-2 rounded-md border border-border/70 bg-background p-2">
        {values.map((v) => (
          <Chip key={v} label={v} prefix={prefix} onRemove={() => remove(v)} />
        ))}
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          onBlur={() => draft && add(draft)}
          placeholder={values.length ? "" : placeholder}
          className="min-w-[8rem] flex-1 bg-transparent px-1 py-1 text-sm outline-none placeholder:text-muted-foreground"
          aria-label={legend}
          autoCapitalize="characters"
          autoCorrect="off"
          spellCheck={false}
        />
      </div>
      {unused.length > 0 && (
        <div className="flex flex-wrap gap-1.5 pt-0.5">
          {unused.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => add(s)}
              className="rounded-full border border-dashed border-border/70 px-2.5 py-0.5 text-xs text-muted-foreground transition-colors hover:border-primary/60 hover:text-foreground"
            >
              {prefix}
              {s}
            </button>
          ))}
        </div>
      )}
    </fieldset>
  );
}

export function WatchlistPicker({
  tickers,
  tags,
  onChange,
}: {
  tickers: string[];
  tags: string[];
  onChange: (next: { tickers: string[]; tags: string[] }) => void;
}) {
  const [sugg, setSugg] = useState<Suggestions>({ tickers: [], tags: [] });

  useEffect(() => {
    let alive = true;
    fetch("/api/briefings/suggestions")
      .then((r) => r.json())
      .then((d: Suggestions) => {
        if (alive) setSugg({ tickers: d.tickers ?? [], tags: d.tags ?? [] });
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  return (
    <div className="space-y-5">
      <Field
        legend="Tickers"
        prefix="$"
        placeholder="AAPL, NVDA, TSLA…"
        values={tickers}
        clean={cleanTicker}
        suggestions={sugg.tickers}
        onChange={(next) => onChange({ tickers: next, tags })}
      />
      <Field
        legend="Tags & themes"
        prefix="#"
        placeholder="ai, earnings, energy…"
        values={tags}
        clean={cleanTag}
        suggestions={sugg.tags}
        onChange={(next) => onChange({ tickers, tags: next })}
      />
    </div>
  );
}
