import type { PortableTextComponents } from "@portabletext/react";

/**
 * Shared Sanity Portable Text rendering — matches blog article typography
 * (readable line length, hierarchy, links, code, blockquotes, lists).
 */
export const portableTextComponents: PortableTextComponents = {
  block: {
    normal: ({ children }) => (
      <p className="leading-8 text-foreground/90">{children}</p>
    ),
    h1: ({ children }) => (
      <h1 className="mt-12 mb-4 text-3xl font-bold tracking-tight text-foreground">{children}</h1>
    ),
    h2: ({ children }) => (
      <h2 className="mt-10 mb-3 text-2xl font-semibold tracking-tight text-foreground">{children}</h2>
    ),
    h3: ({ children }) => (
      <h3 className="mt-8 mb-2 text-xl font-semibold tracking-tight text-foreground">{children}</h3>
    ),
    h4: ({ children }) => (
      <h4 className="mt-6 mb-2 text-lg font-semibold text-foreground">{children}</h4>
    ),
    blockquote: ({ children }) => (
      <blockquote className="my-6 border-l-4 border-primary/40 pl-5 italic text-muted-foreground leading-8">
        {children}
      </blockquote>
    ),
  },
  list: {
    bullet: ({ children }) => (
      <ul className="my-5 list-disc pl-6 space-y-2 text-foreground/90 leading-7">{children}</ul>
    ),
    number: ({ children }) => (
      <ol className="my-5 list-decimal pl-6 space-y-2 text-foreground/90 leading-7">{children}</ol>
    ),
  },
  listItem: {
    bullet: ({ children }) => <li>{children}</li>,
    number: ({ children }) => <li>{children}</li>,
  },
  marks: {
    strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
    em: ({ children }) => <em className="italic">{children}</em>,
    code: ({ children }) => (
      <code className="rounded bg-muted px-1.5 py-0.5 text-sm font-mono text-foreground">
        {children}
      </code>
    ),
    link: ({ value, children }) => {
      const href = value?.href ?? "#";
      const isExternal = href.startsWith("http");
      return (
        <a
          href={href}
          target={isExternal ? "_blank" : undefined}
          rel={isExternal ? "noopener noreferrer" : undefined}
          className="text-primary underline underline-offset-4 hover:text-primary/80 transition-colors"
        >
          {children}
        </a>
      );
    },
  },
  types: {
    image: ({ value }) => {
      if (!value?.asset) return null;
      return (
        <figure className="my-8">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={value.asset.url}
            alt={value.alt ?? ""}
            className="w-full rounded-lg border border-border object-cover"
          />
          {value.caption && (
            <figcaption className="mt-2 text-center text-xs text-muted-foreground">
              {value.caption}
            </figcaption>
          )}
        </figure>
      );
    },
  },
};
