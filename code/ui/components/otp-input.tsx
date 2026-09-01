"use client";

import { useEffect, useRef } from "react";

/**
 * Six-box one-time-code entry.
 *
 * The boxes are presentation; the VALUE is a single string owned by the parent.
 * Keeping one source of truth is what makes paste and platform autofill work —
 * six independently-stateful inputs are the usual reason a pasted code lands
 * entirely in the first box, or an SMS/email autofill silently does nothing.
 *
 * Specifically handled, because each one is a real way this breaks:
 *   - Paste / autofill of the whole code into any box spreads across all six.
 *     `onChange` receives the full string, not one character, so it is sliced
 *     rather than truncated.
 *   - `autoComplete="one-time-code"` on the FIRST box only. iOS offers the
 *     keyboard suggestion from that field; repeating the attribute on all six
 *     makes Safari offer it six times and fill one character.
 *   - Backspace in an empty box steps back and clears the previous one, which
 *     is what every native code field does and what fingers expect.
 *   - Arrow keys move the caret between boxes.
 *   - `inputMode="numeric"` brings up the digit pad without `type="number"`,
 *     which would add spinners and accept "e" and "-".
 */
export function OtpInput({
  value,
  onChange,
  onComplete,
  length = 6,
  disabled = false,
  ariaLabel = "One-time code",
}: {
  value: string;
  onChange: (next: string) => void;
  /** Fired once the last digit lands — lets the parent submit without a click. */
  onComplete?: (code: string) => void;
  length?: number;
  disabled?: boolean;
  ariaLabel?: string;
}) {
  const refs = useRef<(HTMLInputElement | null)[]>([]);
  const digits = value.padEnd(length, " ").slice(0, length).split("");

  // Autofocus the first empty box on mount so the code can be typed immediately.
  useEffect(() => {
    const first = Math.min(value.length, length - 1);
    refs.current[first]?.focus();
    // Intentionally mount-only: refocusing on every keystroke would fight the
    // per-box focus moves below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function setAt(index: number, raw: string) {
    const clean = raw.replace(/\D/g, "");
    if (!clean) {
      // A deletion: clear this box, keep the rest.
      const next = value.split("");
      next[index] = "";
      onChange(next.join("").slice(0, length));
      return;
    }

    // One character typed, or a whole code pasted/autofilled into this box.
    const merged = (
      value.slice(0, index) + clean + value.slice(index + clean.length)
    ).slice(0, length);
    onChange(merged);

    const nextFocus = Math.min(index + clean.length, length - 1);
    refs.current[nextFocus]?.focus();
    if (merged.length === length) onComplete?.(merged);
  }

  function onKeyDown(index: number, e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Backspace" && !value[index] && index > 0) {
      e.preventDefault();
      const next = value.split("");
      next[index - 1] = "";
      onChange(next.join(""));
      refs.current[index - 1]?.focus();
      return;
    }
    if (e.key === "ArrowLeft" && index > 0) {
      e.preventDefault();
      refs.current[index - 1]?.focus();
    }
    if (e.key === "ArrowRight" && index < length - 1) {
      e.preventDefault();
      refs.current[index + 1]?.focus();
    }
  }

  return (
    <div
      role="group"
      aria-label={ariaLabel}
      className="flex items-center justify-between gap-2"
    >
      {digits.map((d, i) => (
        <input
          key={i}
          ref={(el) => {
            refs.current[i] = el;
          }}
          // Not type="number": spinners, and it accepts "e", "+" and "-".
          type="text"
          inputMode="numeric"
          // Only the first box advertises the code, or Safari offers it six times.
          autoComplete={i === 0 ? "one-time-code" : "off"}
          // maxLength is 1 for typing, but a paste still arrives whole and is
          // handled in setAt — the browser does not clamp programmatic fills.
          maxLength={1}
          disabled={disabled}
          value={d.trim()}
          aria-label={`Digit ${i + 1} of ${length}`}
          onChange={(e) => setAt(i, e.target.value)}
          onKeyDown={(e) => onKeyDown(i, e)}
          onFocus={(e) => e.currentTarget.select()}
          className="h-12 w-full min-w-0 rounded-md border border-input bg-background text-center font-mono text-lg tabular-nums shadow-sm transition-colors focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-500/40 disabled:opacity-60"
        />
      ))}
    </div>
  );
}
