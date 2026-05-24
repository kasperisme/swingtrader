"use client";

import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkBreaks from "remark-breaks";

/**
 * Markdown renderer shared by the AI chats. Bundles GFM (tables, strikethrough,
 * task lists, autolinks) and soft-break handling so a single "\n" renders as a
 * line break — the assistant streams plain newlines, not double-space hard
 * breaks. Element styles are hand-rolled per variant because the chats use very
 * specific small font sizes that the typography plugin would fight.
 */

export type ChatMarkdownVariant = "persona" | "analysis" | "help";

type VariantStyle = {
  text: string;
  body: string;
  strong: string;
  bullet: string;
  pMb: string;
  listMb: string;
  liGap: string;
  olPad: string;
  h1: string;
  h2: string;
  h3: string;
};

const VARIANTS: Record<ChatMarkdownVariant, VariantStyle> = {
  persona: {
    text: "text-[11px]",
    body: "text-muted-foreground",
    strong: "font-semibold text-foreground/90",
    bullet: "bg-muted-foreground/40",
    pMb: "mb-1.5",
    listMb: "mb-1.5 space-y-0.5",
    liGap: "gap-2",
    olPad: "pl-3",
    h1: "text-[12px] font-semibold text-foreground mt-3 mb-1 first:mt-0",
    h2: "text-[11px] font-semibold text-foreground/80 mt-2.5 mb-1 first:mt-0",
    h3: "text-[10px] font-medium text-foreground/50 uppercase tracking-widest mt-2 mb-0.5 first:mt-0",
  },
  analysis: {
    text: "text-[12px]",
    body: "text-foreground/70",
    strong: "font-semibold text-foreground",
    bullet: "bg-amber-500/60",
    pMb: "mb-2",
    listMb: "mb-2 space-y-1",
    liGap: "gap-2.5",
    olPad: "pl-4",
    h1: "text-[13px] font-semibold text-foreground mt-4 mb-1.5 first:mt-0",
    h2: "text-[12px] font-semibold text-foreground mt-3 mb-1 first:mt-0",
    h3: "text-[10px] font-medium text-foreground/45 uppercase tracking-widest mt-3 mb-1 first:mt-0",
  },
  help: {
    text: "text-sm",
    body: "text-foreground/80",
    strong: "font-semibold text-foreground",
    bullet: "bg-muted-foreground/50",
    pMb: "mb-2",
    listMb: "mb-2 space-y-1",
    liGap: "gap-2.5",
    olPad: "pl-4",
    h1: "text-base font-semibold text-foreground mt-4 mb-1.5 first:mt-0",
    h2: "text-sm font-semibold text-foreground mt-3 mb-1 first:mt-0",
    h3: "text-xs font-medium text-foreground/60 uppercase tracking-wide mt-3 mb-1 first:mt-0",
  },
};

function buildComponents(v: VariantStyle): Components {
  return {
    p: ({ children }) => (
      <p className={`${v.text} leading-relaxed ${v.body} ${v.pMb} last:mb-0`}>
        {children}
      </p>
    ),
    strong: ({ children }) => <strong className={v.strong}>{children}</strong>,
    em: ({ children }) => <em className="italic">{children}</em>,
    del: ({ children }) => (
      <del className="line-through opacity-70">{children}</del>
    ),
    a: ({ href, children }) => (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className={`${v.text} text-sky-400 underline underline-offset-2 hover:text-sky-300 break-words`}
      >
        {children}
      </a>
    ),
    ul: ({ children }) => <ul className={v.listMb}>{children}</ul>,
    ol: ({ children }) => (
      <ol className={`${v.listMb} list-decimal ${v.olPad}`}>{children}</ol>
    ),
    li: ({ children }) => (
      <li className={`${v.text} ${v.body} flex ${v.liGap} leading-relaxed`}>
        <span
          className={`mt-[5px] w-[3px] h-[3px] rounded-full ${v.bullet} flex-shrink-0`}
        />
        <span className="min-w-0 flex-1">{children}</span>
      </li>
    ),
    h1: ({ children }) => <h1 className={v.h1}>{children}</h1>,
    h2: ({ children }) => <h2 className={v.h2}>{children}</h2>,
    h3: ({ children }) => <h3 className={v.h3}>{children}</h3>,
    blockquote: ({ children }) => (
      <blockquote
        className={`my-2 border-l-2 border-border pl-3 italic ${v.body}`}
      >
        {children}
      </blockquote>
    ),
    hr: () => <hr className="my-3 border-border" />,
    // Inline code gets a subtle chip; the [&>code] resets below neutralise that
    // chip for fenced blocks so only the <pre> container shows its background.
    code: ({ children }) => (
      <code className="rounded bg-foreground/10 px-1 py-0.5 font-mono text-[0.85em] text-foreground/90">
        {children}
      </code>
    ),
    pre: ({ children }) => (
      <pre className="my-2 overflow-x-auto rounded-lg border border-border bg-muted/50 p-2.5 font-mono text-[11px] leading-relaxed [&>code]:bg-transparent [&>code]:p-0 [&>code]:text-foreground/80">
        {children}
      </pre>
    ),
    table: ({ children }) => (
      <div className="my-2 overflow-x-auto">
        <table className="w-full border-collapse text-[11px]">{children}</table>
      </div>
    ),
    thead: ({ children }) => (
      <thead className="border-b border-border">{children}</thead>
    ),
    th: ({ children }) => (
      <th className="px-2 py-1 text-left font-semibold text-foreground/80">
        {children}
      </th>
    ),
    td: ({ children }) => (
      <td className="border-b border-border/50 px-2 py-1 align-top text-foreground/70">
        {children}
      </td>
    ),
  };
}

const COMPONENTS: Record<ChatMarkdownVariant, Components> = {
  persona: buildComponents(VARIANTS.persona),
  analysis: buildComponents(VARIANTS.analysis),
  help: buildComponents(VARIANTS.help),
};

const REMARK_PLUGINS = [remarkGfm, remarkBreaks];

export function ChatMarkdown({
  content,
  variant,
}: {
  content: string;
  variant: ChatMarkdownVariant;
}) {
  return (
    <ReactMarkdown remarkPlugins={REMARK_PLUGINS} components={COMPONENTS[variant]}>
      {content}
    </ReactMarkdown>
  );
}
