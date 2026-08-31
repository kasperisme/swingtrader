"use client";

import { useEffect, useId, useState, type ReactNode } from "react";

export type QuoteTab = {
  id: string;
  label: string;
  panel: ReactNode;
  /**
   * Let the panel bleed out to the page's padding. The chart workspace and the
   * relationship graph are canvases — every pixel of width is a pixel of price
   * history or another node that fits — so they get the full container the way
   * they did on their own pages, while prose-width panels stay readable.
   */
  wide?: boolean;
};

/**
 * Tabbed sections for a quote page.
 *
 * The one rule this has to respect: **every panel stays in the DOM.** These
 * pages are the site's only surfaces with organic search traffic, and they are
 * statically prerendered — unmounting the inactive panels would strip the key
 * statistics, the catalyst list and the company profile out of the crawled
 * HTML in exchange for nothing. Inactive panels are hidden, not removed.
 *
 * That also does the lazy-mount work for free. The chart workspace and the
 * relationship graph mount themselves on an IntersectionObserver, and a hidden
 * panel has no box to intersect — so they stay unmounted until their tab is
 * opened, then mount on the same code path as a scroll.
 */
export function QuoteTabs({ tabs }: { tabs: QuoteTab[] }) {
  const uid = useId();
  const [active, setActive] = useState(tabs[0]?.id ?? "");

  // Deep links: /quote/NVDA#chart opens on the chart. Read after mount rather
  // than during render so the prerendered HTML is identical for every visitor
  // and the page stays static.
  useEffect(() => {
    const fromHash = () => {
      const id = window.location.hash.replace(/^#/, "");
      if (id && tabs.some((t) => t.id === id)) setActive(id);
    };
    fromHash();
    window.addEventListener("hashchange", fromHash);
    return () => window.removeEventListener("hashchange", fromHash);
  }, [tabs]);

  const select = (id: string) => {
    setActive(id);
    // replaceState, not a hash assignment: setting location.hash would scroll
    // the panel under the sticky header.
    if (typeof window !== "undefined") {
      window.history.replaceState(null, "", `#${id}`);
    }
  };

  // Roving arrow keys, which a tablist is expected to have and a row of plain
  // buttons does not.
  const onKeyDown = (e: React.KeyboardEvent) => {
    const i = tabs.findIndex((t) => t.id === active);
    if (i < 0) return;
    const next =
      e.key === "ArrowRight"
        ? (i + 1) % tabs.length
        : e.key === "ArrowLeft"
          ? (i - 1 + tabs.length) % tabs.length
          : e.key === "Home"
            ? 0
            : e.key === "End"
              ? tabs.length - 1
              : -1;
    if (next < 0) return;
    e.preventDefault();
    select(tabs[next].id);
    document.getElementById(`${uid}-tab-${tabs[next].id}`)?.focus();
  };

  return (
    <div className="flex flex-col gap-6">
      <div
        role="tablist"
        aria-label="Quote sections"
        onKeyDown={onKeyDown}
        className="-mx-1 flex gap-1 overflow-x-auto border-b border-border/60 px-1"
      >
        {tabs.map((tab) => {
          const selected = tab.id === active;
          return (
            <button
              key={tab.id}
              id={`${uid}-tab-${tab.id}`}
              type="button"
              role="tab"
              aria-selected={selected}
              aria-controls={`${uid}-panel-${tab.id}`}
              tabIndex={selected ? 0 : -1}
              onClick={() => select(tab.id)}
              className={`-mb-px shrink-0 cursor-pointer whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring ${
                selected
                  ? "border-amber-500 text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              {tab.label}
            </button>
          );
        })}
      </div>

      {tabs.map((tab) => (
        <div
          key={tab.id}
          id={`${uid}-panel-${tab.id}`}
          role="tabpanel"
          aria-labelledby={`${uid}-tab-${tab.id}`}
          hidden={tab.id !== active}
          // The `hidden` attribute alone is not enough: Tailwind's preflight
          // sets `[hidden]{display:none}` in the base layer, and `.flex` in the
          // utilities layer overrides it at equal specificity — the panel would
          // stay visible. The class decides display; the attribute is what
          // assistive tech and in-page search read.
          className={
            tab.id !== active
              ? "hidden"
              : tab.wide
                ? "flex w-[calc(100%+2rem)] flex-col gap-8 -mx-4 sm:-mx-6 sm:w-[calc(100%+3rem)] lg:-mx-8 lg:w-[calc(100%+4rem)]"
                : "flex flex-col gap-8"
          }
        >
          {tab.panel}
        </div>
      ))}
    </div>
  );
}
