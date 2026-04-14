"use client";

import { useMemo, useState } from "react";

type Props = {
  value: string;
  onChange: (value: string) => void;
  onSubmit?: () => void;
  options: string[];
  placeholder?: string;
  className?: string;
};

export function TickerSearchCombobox({
  value,
  onChange,
  onSubmit,
  options,
  placeholder = "Search ticker or alias…",
  className = "",
}: Props) {
  const [open, setOpen] = useState(false);

  const suggestions = useMemo(() => {
    const q = value.trim().toUpperCase();
    const unique = Array.from(new Set(options.map((o) => o.trim().toUpperCase()).filter(Boolean))).sort((a, b) =>
      a.localeCompare(b),
    );
    if (!q) return unique.slice(0, 20);
    const starts = unique.filter((s) => s.startsWith(q));
    const contains = unique.filter((s) => !s.startsWith(q) && s.includes(q));
    return [...starts, ...contains].slice(0, 20);
  }, [options, value]);

  return (
    <div className={`relative ${className}`}>
      <input
        value={value}
        onChange={(e) => {
          onChange(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => {
          setTimeout(() => setOpen(false), 120);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            onSubmit?.();
            setOpen(false);
          }
        }}
        placeholder={placeholder}
        className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
      />
      {open && suggestions.length > 0 && (
        <div className="absolute z-20 mt-1 max-h-56 w-full overflow-auto rounded-md border border-border bg-popover p-1 shadow-lg">
          {suggestions.map((s) => (
            <button
              key={s}
              type="button"
              onMouseDown={(e) => {
                e.preventDefault();
                onChange(s);
                setOpen(false);
              }}
              className="block w-full rounded px-2 py-1.5 text-left text-xs font-mono hover:bg-muted"
            >
              {s}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
