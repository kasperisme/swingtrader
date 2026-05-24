"use client";

import { useLayoutEffect, useRef, useState } from "react";
import { ChatMarkdown } from "@/components/chat-markdown";
import { ChevronDown, ChevronUp } from "lucide-react";
import { cn } from "@/lib/utils";

type Props = {
  source: string;
  /** Pixel height to clamp to when collapsed. Default ~5 lines of body copy. */
  collapsedHeight?: number;
  className?: string;
};

export function ScreeningDescription({
  source,
  collapsedHeight = 120,
  className,
}: Props) {
  const [expanded, setExpanded] = useState(false);
  const [needsClamp, setNeedsClamp] = useState(false);
  const contentRef = useRef<HTMLDivElement | null>(null);

  // Decide whether the toggle is necessary based on actual rendered height,
  // not on string length — that way short markdown bodies don't show a
  // misleading "Show more" link.
  useLayoutEffect(() => {
    const el = contentRef.current;
    if (!el) return;
    setNeedsClamp(el.scrollHeight > collapsedHeight + 4);
  }, [source, collapsedHeight]);

  const showToggle = needsClamp;
  const clamped = showToggle && !expanded;

  return (
    <div className={cn("max-w-[62ch]", className)}>
      <div
        ref={contentRef}
        className={cn(
          "relative overflow-hidden transition-[max-height] duration-300 ease-out",
        )}
        style={{
          maxHeight: clamped ? `${collapsedHeight}px` : "none",
        }}
      >
        <ChatMarkdown content={source} variant="description" />
        {clamped && (
          <div
            aria-hidden
            className="pointer-events-none absolute inset-x-0 bottom-0 h-12 bg-gradient-to-t from-background to-transparent"
          />
        )}
      </div>

      {showToggle && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
        >
          {expanded ? (
            <>
              Show less <ChevronUp className="h-3 w-3" />
            </>
          ) : (
            <>
              Show more <ChevronDown className="h-3 w-3" />
            </>
          )}
        </button>
      )}
    </div>
  );
}
