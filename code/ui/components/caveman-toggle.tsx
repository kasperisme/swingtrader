"use client";

import { useCavemanMode } from "@/lib/caveman-mode";
import { cn } from "@/lib/utils";

// ─── SVG characters ──────────────────────────────────────────────────────────

function BusinessmanIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 20 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden
      className={className}
    >
      {/* Neat hair parting */}
      <path
        d="M7 4 Q10 2.5 13 4"
        stroke="currentColor"
        strokeWidth="1.1"
        strokeLinecap="round"
        opacity="0.45"
      />
      {/* Head */}
      <circle cx="10" cy="7" r="5" fill="currentColor" />
      {/* Suit body */}
      <path
        d="M2 15 C2 13 5 12 10 12 C15 12 18 13 18 15 L17 23 H3 Z"
        fill="currentColor"
        fillOpacity="0.72"
      />
      {/* Lapels */}
      <path
        d="M2 15 L6 12.5 L10 15.5 L14 12.5 L18 15"
        stroke="currentColor"
        strokeWidth="1.2"
        fill="none"
        strokeLinejoin="round"
      />
      {/* Tie */}
      <path d="M10 12.5 L9 17 L10 18.5 L11 17 Z" fill="currentColor" />
      {/* Briefcase */}
      <rect x="13" y="17" width="5" height="4" rx="0.8" fill="currentColor" fillOpacity="0.6" />
      <path
        d="M14.5 17 L14.5 15.8 Q14.5 15 15.5 15 Q16.5 15 16.5 15.8 L16.5 17"
        stroke="currentColor"
        strokeWidth="1"
        fill="none"
        strokeLinecap="round"
      />
    </svg>
  );
}

function CavemanIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden
      className={className}
    >
      {/* Wild spiky hair */}
      <path
        d="M5 7 L2.5 3 M7 6 L6 1.5 M10 5.5 L10 1 M13 6 L14 1.5 M15 7 L17.5 3"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
      {/* Head */}
      <circle cx="10" cy="9" r="5" fill="currentColor" />
      {/* Animal-skin body */}
      <path
        d="M2 17 C2 15 5 14 10 14 C15 14 18 15 18 17 L17 23 H3 Z"
        fill="currentColor"
        fillOpacity="0.72"
      />
      {/* Fur spots */}
      <circle cx="7.5" cy="19" r="1.3" fill="currentColor" fillOpacity="0.42" />
      <circle cx="12" cy="21" r="1.1" fill="currentColor" fillOpacity="0.42" />
      {/* Arm holding club */}
      <path
        d="M17 16 L21 10"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
      {/* Club head (bulgy end at top) */}
      <ellipse
        cx="22"
        cy="8.5"
        rx="2.5"
        ry="3.5"
        fill="currentColor"
      />
      {/* Club texture lines */}
      <path
        d="M20.5 7 L23 8 M20.5 9 L23 10"
        stroke="currentColor"
        strokeWidth="0.8"
        strokeLinecap="round"
        opacity="0.4"
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
        <BusinessmanIcon className="h-5 w-5 shrink-0" />
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
        <CavemanIcon className="h-5 w-5 shrink-0" />
        {showLabels && <span>Caveman</span>}
      </span>
    </button>
  );
}
