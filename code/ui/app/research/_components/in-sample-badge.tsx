import { AlertTriangle } from "lucide-react";

/**
 * The in-sample warning.
 *
 * A backtest equity curve drawn on the window the optimiser searched over is
 * the most persuasive and least informative image in quantitative finance. It
 * always slopes up, because it was selected to. This label is what separates
 * showing the reader the research from selling them a result, so it renders
 * from `is_in_sample` on the view rather than being left to page copy.
 *
 * Amber is the site's accent and carries the warning. Emerald appears only on
 * the out-of-sample case — a semantic signal in a financial interface, not
 * decoration, and the one place a second hue earns its place.
 */

const WINDOW_LABEL: Record<string, string> = {
  holdout: "Out-of-sample · never seen by the search",
  vault: "Sealed window · opened once",
  full: "Spans both windows · read the caption",
};

export function InSampleBadge({ window }: { window: string }) {
  if (window === "n/a") return null;

  if (window === "dev") {
    return (
      <span className="inline-flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-widest text-amber-600 dark:text-amber-500">
        <AlertTriangle className="h-3 w-3 shrink-0" aria-hidden />
        In-sample · optimised on this data
      </span>
    );
  }

  return (
    <span className="inline-flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-widest text-emerald-600 dark:text-emerald-500">
      <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-500" aria-hidden />
      {WINDOW_LABEL[window] ?? window}
    </span>
  );
}

/** The rail colour a figure inherits from its data window. */
export function railFor(window: string): string {
  if (window === "dev") return "border-l-amber-500/70";
  if (window === "n/a") return "border-l-border";
  return "border-l-emerald-500/70";
}
