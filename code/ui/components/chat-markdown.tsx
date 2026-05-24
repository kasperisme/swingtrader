"use client";

import ReactMarkdown, {
  type Components,
  type Options,
} from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkBreaks from "remark-breaks";

/**
 * Markdown renderer shared by the AI chats and AI/content panels. Bundles GFM
 * (tables, strikethrough, task lists, autolinks) so those parse everywhere, and
 * — for the chat-style variants — soft-break handling so a single "\n" renders
 * as a line break (the assistant streams plain newlines, not double-space hard
 * breaks). The `description` variant keeps standard markdown paragraph
 * behaviour, since that content is authored prose, not streamed chat.
 *
 * Element styles are hand-rolled per variant: the chats use very specific small
 * font sizes that the typography plugin would fight, and the description surface
 * wants native list markers / prose leading.
 */

export type ChatMarkdownVariant =
  | "persona"
  | "analysis"
  | "help"
  | "description";

type VariantStyle = {
  /** Single newline → <br>. On for streamed chat, off for authored prose. */
  breaks: boolean;
  p: string;
  strong: string;
  link: string;
  ul: string;
  ol: string;
  li: string;
  /** Bullet dot colour for custom list rendering; null = native list markers. */
  bullet: string | null;
  liGap: string;
  blockquote: string;
  h1: string;
  h2: string;
  h3: string;
};

const VARIANTS: Record<ChatMarkdownVariant, VariantStyle> = {
  persona: {
    breaks: true,
    p: "text-[11px] leading-relaxed text-muted-foreground mb-1.5 last:mb-0",
    strong: "font-semibold text-foreground/90",
    link: "text-[11px] text-sky-400 underline underline-offset-2 hover:text-sky-300 break-words",
    ul: "mb-1.5 space-y-0.5",
    ol: "mb-1.5 space-y-0.5 list-decimal pl-3",
    li: "text-[11px] text-muted-foreground leading-relaxed",
    bullet: "bg-muted-foreground/40",
    liGap: "gap-2",
    blockquote: "my-2 border-l-2 border-border pl-3 italic text-muted-foreground",
    h1: "text-[12px] font-semibold text-foreground mt-3 mb-1 first:mt-0",
    h2: "text-[11px] font-semibold text-foreground/80 mt-2.5 mb-1 first:mt-0",
    h3: "text-[10px] font-medium text-foreground/50 uppercase tracking-widest mt-2 mb-0.5 first:mt-0",
  },
  analysis: {
    breaks: true,
    p: "text-[12px] leading-relaxed text-foreground/70 mb-2 last:mb-0",
    strong: "font-semibold text-foreground",
    link: "text-[12px] text-sky-400 underline underline-offset-2 hover:text-sky-300 break-words",
    ul: "mb-2 space-y-1",
    ol: "mb-2 space-y-1 list-decimal pl-4",
    li: "text-[12px] text-foreground/70 leading-relaxed",
    bullet: "bg-amber-500/60",
    liGap: "gap-2.5",
    blockquote: "my-2 border-l-2 border-border pl-3 italic text-foreground/70",
    h1: "text-[13px] font-semibold text-foreground mt-4 mb-1.5 first:mt-0",
    h2: "text-[12px] font-semibold text-foreground mt-3 mb-1 first:mt-0",
    h3: "text-[10px] font-medium text-foreground/45 uppercase tracking-widest mt-3 mb-1 first:mt-0",
  },
  help: {
    breaks: true,
    p: "text-sm leading-relaxed text-foreground/80 mb-2 last:mb-0",
    strong: "font-semibold text-foreground",
    link: "text-sm text-sky-400 underline underline-offset-2 hover:text-sky-300 break-words",
    ul: "mb-2 space-y-1",
    ol: "mb-2 space-y-1 list-decimal pl-4",
    li: "text-sm text-foreground/80 leading-relaxed",
    bullet: "bg-muted-foreground/50",
    liGap: "gap-2.5",
    blockquote: "my-2 border-l-2 border-border pl-3 italic text-foreground/80",
    h1: "text-base font-semibold text-foreground mt-4 mb-1.5 first:mt-0",
    h2: "text-sm font-semibold text-foreground mt-3 mb-1 first:mt-0",
    h3: "text-xs font-medium text-foreground/60 uppercase tracking-wide mt-3 mb-1 first:mt-0",
  },
  description: {
    breaks: false,
    p: "text-sm leading-7 text-muted-foreground mb-3 last:mb-0",
    strong: "font-semibold text-foreground",
    link: "text-primary underline-offset-2 hover:underline break-words",
    ul: "my-2 list-disc space-y-1 pl-5 text-sm leading-7 text-muted-foreground marker:text-muted-foreground/50",
    ol: "my-2 list-decimal space-y-1 pl-5 text-sm leading-7 text-muted-foreground marker:text-muted-foreground/60",
    li: "pl-1",
    bullet: null,
    liGap: "",
    blockquote: "my-2 border-l-2 border-border pl-3 italic text-muted-foreground",
    h1: "mt-4 text-sm font-semibold uppercase tracking-wide text-foreground first:mt-0",
    h2: "mt-4 text-sm font-semibold uppercase tracking-wide text-foreground first:mt-0",
    h3: "mt-3 text-sm font-semibold text-foreground first:mt-0",
  },
};

function buildComponents(v: VariantStyle): Components {
  return {
    p: ({ children }) => <p className={v.p}>{children}</p>,
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
        className={v.link}
      >
        {children}
      </a>
    ),
    ul: ({ children }) => <ul className={v.ul}>{children}</ul>,
    ol: ({ children }) => <ol className={v.ol}>{children}</ol>,
    li: ({ children }) =>
      v.bullet ? (
        <li className={`${v.li} flex ${v.liGap}`}>
          <span
            className={`mt-[5px] w-[3px] h-[3px] rounded-full ${v.bullet} flex-shrink-0`}
          />
          <span className="min-w-0 flex-1">{children}</span>
        </li>
      ) : (
        <li className={v.li}>{children}</li>
      ),
    h1: ({ children }) => <h1 className={v.h1}>{children}</h1>,
    h2: ({ children }) => <h2 className={v.h2}>{children}</h2>,
    h3: ({ children }) => <h3 className={v.h3}>{children}</h3>,
    blockquote: ({ children }) => (
      <blockquote className={v.blockquote}>{children}</blockquote>
    ),
    hr: () => <hr className="my-3 border-border" />,
    // Inline code gets a subtle chip; the [&>code] resets on <pre> below
    // neutralise that chip for fenced blocks so only the container shows a bg.
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

const COMPONENTS = Object.fromEntries(
  (Object.keys(VARIANTS) as ChatMarkdownVariant[]).map((k) => [
    k,
    buildComponents(VARIANTS[k]),
  ]),
) as Record<ChatMarkdownVariant, Components>;

const PLUGINS_WITH_BREAKS: Options["remarkPlugins"] = [remarkGfm, remarkBreaks];
const PLUGINS_NO_BREAKS: Options["remarkPlugins"] = [remarkGfm];

export function ChatMarkdown({
  content,
  variant,
}: {
  content: string;
  variant: ChatMarkdownVariant;
}) {
  return (
    <ReactMarkdown
      remarkPlugins={
        VARIANTS[variant].breaks ? PLUGINS_WITH_BREAKS : PLUGINS_NO_BREAKS
      }
      components={COMPONENTS[variant]}
    >
      {content}
    </ReactMarkdown>
  );
}
