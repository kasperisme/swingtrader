"use client";

import { useLayoutEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
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
        <Markdown source={source} />
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

function Markdown({ source }: { source: string }) {
  return (
    <ReactMarkdown
      components={{
        h1: ({ children }) => (
          <h3 className="mt-4 text-sm font-semibold uppercase tracking-wide text-foreground first:mt-0">
            {children}
          </h3>
        ),
        h2: ({ children }) => (
          <h4 className="mt-4 text-sm font-semibold uppercase tracking-wide text-foreground first:mt-0">
            {children}
          </h4>
        ),
        h3: ({ children }) => (
          <h5 className="mt-3 text-sm font-semibold text-foreground first:mt-0">
            {children}
          </h5>
        ),
        p: ({ children }) => (
          <p className="text-sm leading-7 text-muted-foreground">{children}</p>
        ),
        ul: ({ children }) => (
          <ul className="my-2 list-disc space-y-1 pl-5 text-sm leading-7 text-muted-foreground marker:text-muted-foreground/50">
            {children}
          </ul>
        ),
        ol: ({ children }) => (
          <ol className="my-2 list-decimal space-y-1 pl-5 text-sm leading-7 text-muted-foreground marker:text-muted-foreground/60">
            {children}
          </ol>
        ),
        li: ({ children }) => <li className="pl-1">{children}</li>,
        strong: ({ children }) => (
          <strong className="font-semibold text-foreground">{children}</strong>
        ),
        em: ({ children }) => <em className="italic">{children}</em>,
        code: ({ children }) => (
          <code className="rounded bg-muted px-1 py-0.5 font-mono text-[12px] text-foreground">
            {children}
          </code>
        ),
        a: ({ children, href }) => (
          <a
            href={href}
            className="text-primary underline-offset-2 hover:underline"
            target={href?.startsWith("http") ? "_blank" : undefined}
            rel={href?.startsWith("http") ? "noopener noreferrer" : undefined}
          >
            {children}
          </a>
        ),
        hr: () => <hr className="my-4 border-border/60" />,
      }}
    >
      {source}
    </ReactMarkdown>
  );
}
