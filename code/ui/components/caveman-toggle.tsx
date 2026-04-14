"use client";

import { useCavemanMode } from "@/lib/caveman-mode";
import { cn } from "@/lib/utils";

// ─── Icons (temaki icon set, viewBox 0 0 15 15) ───────────────────────────────

function BriefcaseIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 15 15"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden
      className={className}
    >
      <path
        fill="currentColor"
        d="M5 4h5V3H5zM4 4V3c0-.55.45-1 1-1h5c.55 0 1 .45 1 1v1h2c.55 0 1 .45 1 1v7c0 .55-.45 1-1 1H2c-.55 0-1-.45-1-1V5c0-.55.45-1 1-1z"
      />
    </svg>
  );
}

function BoulderIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 15 15"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden
      className={className}
    >
      <path
        fill="currentColor"
        d="M6 14c-.67 0-5-.22-5-2c0-2.64 1.96-4.46 2.5-5c1.04-1.04.93-2.37 1.5-3.5C5.77 1.96 7.79 1 8.5 1c.57 0 2.25 1.3 3.5 3c.56.75 2 4.37 2 5.5c0 3.58-1.66 4.5-3 4.5z"
      />
    </svg>
  );
}

// ─── Toggle pill ──────────────────────────────────────────────────────────────

type Props = {
  /** Show text labels next to the icons. Default: false */
  showLabels?: boolean;
  className?: string;
};

export function CavemanToggle({ showLabels = false, className }: Props) {
  const { isCaveman, toggle } = useCavemanMode();

  return (
    <button
      type="button"
      onClick={toggle}
      title={isCaveman ? "Back to normal (businessman mode)" : "Go prehistoric (caveman mode)"}
      aria-label={isCaveman ? "Disable caveman mode" : "Enable caveman mode"}
      className={cn(
        "group relative inline-flex items-center rounded-full border border-border bg-muted/40 p-1 transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
        className,
      )}
    >
      {/* Sliding highlight */}
      <span
        className={cn(
          "absolute top-1 bottom-1 w-[calc(50%-4px)] rounded-full transition-all duration-200 ease-in-out",
          isCaveman
            ? "left-[calc(50%+3px)] bg-amber-500/20 dark:bg-amber-500/25"
            : "left-1 bg-background shadow-sm",
        )}
        aria-hidden
      />

      {/* Businessman (left) */}
      <span
        className={cn(
          "relative z-10 flex items-center gap-1.5 px-2 py-0.5 text-xs font-medium transition-colors",
          !isCaveman ? "text-foreground" : "text-muted-foreground",
        )}
      >
        <BriefcaseIcon className="h-4 w-4 shrink-0" />
        {showLabels && <span>Normal</span>}
      </span>

      {/* Caveman (right) */}
      <span
        className={cn(
          "relative z-10 flex items-center gap-1.5 px-2 py-0.5 text-xs font-medium transition-colors",
          isCaveman
            ? "text-amber-600 dark:text-amber-400"
            : "text-muted-foreground",
        )}
      >
        <BoulderIcon className="h-4 w-4 shrink-0" />
        {showLabels && <span>Caveman</span>}
      </span>
    </button>
  );
}
