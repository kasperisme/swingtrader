"use client";

/**
 * Company mark for a directory row.
 *
 * Uses FMP's static logo endpoint, which needs no API key and no request from
 * our server — the browser fetches each one lazily and in parallel. That matters
 * at 50 rows a page: the keyed /stable/profile endpoint would be 50 calls per
 * render, and it rejects comma-batched symbols on this plan.
 *
 * Coverage is partial (it 404s for plenty of small caps), so the monogram sits
 * underneath as the real ground and the image paints over it. On error the image
 * removes itself and the monogram is simply what's left — no state, no layout
 * shift, and a row that never renders a broken-image glyph.
 */

const FMP_LOGO_BASE = "https://financialmodelingprep.com/image-stock";

// Decorative only: every row already carries the ticker and company name as
// text, so the mark is hidden from assistive tech rather than repeating them.
export function TickerLogo({
  symbol,
  className = "",
}: {
  symbol: string;
  className?: string;
}) {
  return (
    <span
      aria-hidden
      className={`relative grid h-9 w-9 shrink-0 place-items-center overflow-hidden rounded-md border border-border/70 bg-muted/60 ${className}`}
    >
      <span className="font-mono text-[11px] font-semibold tracking-tight text-muted-foreground">
        {symbol.slice(0, 2)}
      </span>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={`${FMP_LOGO_BASE}/${encodeURIComponent(symbol)}.png`}
        alt=""
        width={36}
        height={36}
        loading="lazy"
        decoding="async"
        className="absolute inset-0 h-full w-full bg-white object-contain p-0.5"
        onError={(e) => {
          e.currentTarget.remove();
        }}
      />
    </span>
  );
}
