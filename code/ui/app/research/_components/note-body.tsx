import type { ComponentPropsWithoutRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * Renderer for a research write-up.
 *
 * These documents are unusually table-heavy — a falsification battery is mostly
 * a grid of test statistics — and the default prose styles collapse those into
 * unreadable runs of text. So tables get real cell structure and their own
 * horizontal scroll container, and headings get a visible step in scale, since
 * the structure of the argument (claim, evidence, verdict) is what makes a
 * negative result readable at all.
 */

function Table({ children }: ComponentPropsWithoutRef<"table">) {
  return (
    // The wrapper scrolls, not the page: a wide statistics table must never
    // make the whole document scroll sideways on a phone.
    <div className="my-6 -mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0">
      <table className="w-full border-collapse text-left text-[13px]">{children}</table>
    </div>
  );
}

const components: React.ComponentProps<typeof ReactMarkdown>["components"] = {
  table: Table,
  thead: (p) => <thead className="border-b" {...p} />,
  tr: (p) => <tr className="border-b border-border/50 last:border-0" {...p} />,
  th: (p) => (
    <th
      className="whitespace-nowrap px-3 py-2 font-mono text-[11px] font-normal uppercase tracking-widest text-muted-foreground first:pl-0"
      {...p}
    />
  ),
  td: (p) => (
    <td
      className="px-3 py-2 align-top leading-relaxed tabular-nums text-muted-foreground first:pl-0 first:text-foreground"
      {...p}
    />
  ),
  h1: (p) => (
    <h2 className="mt-12 scroll-mt-20 text-2xl font-bold tracking-tight" {...p} />
  ),
  h2: (p) => (
    <h2
      className="mt-12 scroll-mt-20 border-t pt-6 text-xl font-semibold tracking-tight"
      {...p}
    />
  ),
  h3: (p) => (
    <h3 className="mt-8 scroll-mt-20 text-base font-semibold tracking-tight" {...p} />
  ),
  h4: (p) => (
    <h4
      className="mt-6 font-mono text-[11px] uppercase tracking-widest text-amber-600 dark:text-amber-500"
      {...p}
    />
  ),
  p: (p) => <p className="my-4 leading-relaxed text-muted-foreground" {...p} />,
  ul: (p) => <ul className="my-4 list-disc space-y-1.5 pl-5 marker:text-border" {...p} />,
  ol: (p) => <ol className="my-4 list-decimal space-y-1.5 pl-5 marker:text-border" {...p} />,
  li: (p) => <li className="leading-relaxed text-muted-foreground" {...p} />,
  strong: (p) => <strong className="font-semibold text-foreground" {...p} />,
  em: (p) => <em className="italic" {...p} />,
  hr: () => <hr className="my-10 border-border" />,
  blockquote: (p) => (
    <blockquote
      className="my-6 border-l-2 border-l-amber-500 py-1 pl-5 text-muted-foreground [&>p]:my-0"
      {...p}
    />
  ),
  a: (p) => (
    <a
      className="text-foreground underline decoration-amber-500/50 underline-offset-2 transition-colors hover:decoration-amber-500"
      {...p}
    />
  ),
  code: (p) => (
    <code
      className="rounded bg-muted px-1 py-0.5 font-mono text-[0.85em] text-foreground"
      {...p}
    />
  ),
  pre: (p) => (
    <pre
      className="my-6 -mx-4 overflow-x-auto bg-muted/60 p-4 font-mono text-xs leading-relaxed sm:mx-0 sm:rounded-sm [&>code]:bg-transparent [&>code]:p-0"
      {...p}
    />
  ),
};

export function NoteBody({ markdown }: { markdown: string }) {
  return (
    <div className="text-[15px]">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {markdown}
      </ReactMarkdown>
    </div>
  );
}
