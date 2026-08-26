import { TrendingDown, TrendingUp, Minus } from "lucide-react";
// From the client-safe half, not `priced-in.ts`: this panel is rendered from
// the workspace's client-side tab switcher as well as from the quote page.
import type { PricedInVote } from "@/lib/quote/priced-in-vote";
import { injectPrice, STALE_AFTER_DAYS } from "@/lib/quote/priced-in-vote";

/**
 * Where the price sits among the analyst models published about a company.
 *
 * A server component: everything here is arithmetic on stored numbers, so there
 * is nothing to hydrate.
 *
 * The design decision worth recording is what is NOT shown. The analysis behind
 * this also produces per-driver "this is 25% priced in" estimates, and those are
 * unvalidated — two attempts to validate them failed. They are omitted rather
 * than caveated, because a number printed next to a real share price is read as
 * analysis no matter what the footnote says.
 *
 * What IS shown is arithmetic on other people's published targets: the spread,
 * the median, and where the market is actually paying relative to both. No model
 * judgement anywhere in it.
 */

/**
 * How much of an assumption the price already reflects, as an ORDINAL band.
 *
 * Bands rather than the raw percentage, for two reasons that happen to agree.
 * Design: a bare "15%" next to a "70%" invites a precision the reader cannot
 * act on. Honesty: the underlying figure is an unvalidated estimate — two
 * attempts to validate it failed — so a decimal asserts more than the number
 * can carry. A four-step band says what it knows and no more.
 *
 * Encoded as a SEQUENTIAL one-hue ramp (amber, dark→light), not a
 * red/green diverging scale: this is magnitude, not polarity. "Unpriced" is
 * not good and "fully priced" is not bad — the ramp marks where there is
 * something left to find, so intensity fades to a plain neutral once the price
 * already reflects it.
 *
 * The steps are validated, not eyeballed — one hue (21 deg spread), monotone
 * lightness, adjacent gaps >= 0.06 L, and the lightest step clears 2:1 against
 * the surface in both modes.
 *
 * Colour is never the only channel: every band ships its own word. WCAG 1.4.1,
 * and it is also what makes the column scannable in greyscale.
 */
type Band = { label: string; dot: string; text: string };

function band(pricedInPct: number): Band {
  if (pricedInPct <= 25)
    return {
      label: "Unpriced",
      dot: "bg-[#b45309] dark:bg-[#fbbf24]",
      text: "text-[#b45309] dark:text-[#fbbf24]",
    };
  if (pricedInPct <= 55)
    return {
      label: "Partly priced",
      dot: "bg-[#d97706] dark:bg-[#f59e0b]",
      text: "text-[#d97706] dark:text-[#f59e0b]",
    };
  if (pricedInPct <= 84)
    return {
      label: "Mostly priced",
      dot: "bg-[#f59e0b] dark:bg-[#d97706]",
      text: "text-muted-foreground",
    };
  // Fully priced sits outside the ramp on purpose: the market already reflects
  // it, so there is nothing here to draw the eye to.
  return {
    label: "Fully priced",
    dot: "bg-muted-foreground/40",
    text: "text-muted-foreground",
  };
}

function money(n: number): string {
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: n >= 100 ? 0 : 2,
  }).format(n);
}

/** Position along the low..high axis, clamped so a marker never leaves the rail. */
function pct(value: number, low: number, high: number): number {
  if (!(high > low)) return 50;
  return Math.max(2, Math.min(98, ((value - low) / (high - low)) * 100));
}

export function PricedInPanel({
  vote,
  livePrice,
}: {
  vote: PricedInVote;
  livePrice: number | null;
}) {
  const { low, high, median, priceAtAsOf } = vote;
  const anchor = priceAtAsOf ?? median;
  const stale = vote.ageDays > STALE_AFTER_DAYS;

  // Drift between the price this was computed at and the live quote. When it is
  // large the reconstruction is describing a different price than the one on
  // the page, and saying so is more useful than hiding the panel.
  const drift =
    livePrice != null && priceAtAsOf != null && priceAtAsOf > 0
      ? livePrice / priceAtAsOf - 1
      : null;

  const gap = vote.medianGap;
  const leanIcon =
    gap == null || Math.abs(gap) < 0.08 ? Minus : gap < 0 ? TrendingDown : TrendingUp;
  const LeanIcon = leanIcon;
  const leanText =
    gap == null
      ? "position among the published models is unavailable"
      : Math.abs(gap) < 0.08
        ? `within ${Math.abs(gap * 100).toFixed(0)}% of the median target — broadly agreeing with the analysts`
        : gap < 0
          ? `${Math.abs(gap * 100).toFixed(0)}% below the median target — more cautious than the analysts`
          : `${(gap * 100).toFixed(0)}% above the median target — more optimistic than the analysts`;

  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <p className="text-sm text-foreground">
          <span className="font-semibold">
            {vote.nTargets} analyst price targets
          </span>{" "}
          <span className="text-muted-foreground">
            from {money(low)} to {money(high)}
          </span>
        </p>
        <p className="font-mono text-xs text-muted-foreground">
          as of {vote.asOf}
        </p>
      </div>

      {/* Distribution rail: low ─── median ─── high, with the price marked. */}
      <div className="mt-5 mb-2">
        <div className="relative h-2 rounded-full bg-muted">
          <div
            className="absolute -top-1 h-4 w-px bg-muted-foreground/50"
            style={{ left: `${pct(median, low, high)}%` }}
            aria-hidden
          />
          <div
            className="absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-[3px] border-background bg-foreground shadow-sm"
            style={{ left: `${pct(anchor, low, high)}%` }}
            aria-hidden
          />
        </div>
        <div className="relative mt-2 h-8 text-[11px]">
          <span className="absolute left-0 text-muted-foreground">{money(low)}</span>
          <span
            className="absolute -translate-x-1/2 text-muted-foreground"
            style={{ left: `${pct(median, low, high)}%` }}
          >
            median {money(median)}
          </span>
          <span className="absolute right-0 text-muted-foreground">{money(high)}</span>
          <span
            className="absolute top-4 -translate-x-1/2 whitespace-nowrap font-medium text-foreground"
            style={{ left: `${pct(anchor, low, high)}%` }}
          >
            {money(anchor)} today
          </span>
        </div>
      </div>

      <p className="mt-4 flex items-start gap-2 text-sm text-foreground">
        <LeanIcon className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
        <span>
          The market is {leanText}.
        </span>
      </p>

      <dl className="mt-4 grid grid-cols-3 gap-px overflow-hidden rounded-lg border border-border bg-border text-center">
        {[
          {
            label: "Agree with the price",
            value: vote.nEndorsed,
            hint: "targets within 8% of it",
          },
          {
            label: "Say it's too cheap",
            value: vote.nContestedBull,
            hint: "targets 15%+ higher",
          },
          {
            label: "Say it's too dear",
            value: vote.nContestedBear,
            hint: "targets 15%+ lower",
          },
        ].map((s) => (
          <div key={s.label} className="bg-card px-2 py-3">
            <dt className="text-[11px] uppercase tracking-wide text-muted-foreground">
              {s.label}
            </dt>
            <dd className="mt-1 font-mono text-lg text-foreground">{s.value}</dd>
            <dd className="text-[11px] text-muted-foreground">{s.hint}</dd>
          </div>
        ))}
      </dl>

      {(vote.parts || vote.summary) && (
        <div className="mt-4 border-t border-border pt-4">
          <p className="mb-2 text-[11px] uppercase tracking-wide text-muted-foreground">
            The reconstruction
          </p>

          {vote.parts?.position && (
            <p className="max-w-[72ch] text-pretty text-sm leading-relaxed text-foreground">
              {injectPrice(vote.parts.position, livePrice ?? priceAtAsOf)}
            </p>
          )}

          {/* Promoted above the breakdown.
              The spread on a contested name is often ONE variable at different
              dates — every rejected Tesla target is robotaxi timing, from
              Truist's 2028-2030 at +6% to the software-P&L case at +43%. When
              that is true this line is the whole disagreement, and reading it
              after two columns of bullets buries the finding. */}
          {vote.parts?.crux && (
            <div className="mt-4 rounded-lg border border-border bg-muted/40 p-3">
              <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-foreground/70">
                What the disagreement turns on
              </p>
              <p className="max-w-[74ch] text-pretty text-[13px] leading-relaxed text-foreground">
                {injectPrice(vote.parts.crux, livePrice ?? priceAtAsOf)}
              </p>
            </div>
          )}

          {(vote.parts?.paysFor?.length || vote.parts?.declines?.length) && (
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              {[
                { label: "The price pays for", items: vote.parts?.paysFor ?? [] },
                { label: "It declines to pay for", items: vote.parts?.declines ?? [] },
              ]
                .filter((c) => c.items.length > 0)
                .map((col) => (
                  <div key={col.label}>
                    <p className="mb-1.5 text-[11px] uppercase tracking-wide text-muted-foreground">
                      {col.label}
                    </p>
                    <ul className="flex flex-col gap-1.5">
                      {col.items.map((item, i) => (
                        <li
                          key={i}
                          className="flex gap-2 text-[13px] leading-snug text-foreground/90"
                        >
                          <span
                            className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-muted-foreground/50"
                            aria-hidden
                          />
                          <span>{injectPrice(item, livePrice ?? priceAtAsOf)}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
            </div>
          )}

          {/* Older rows predate the structured summary; render the flat text. */}
          {!vote.parts && vote.summary && (
            <p className="max-w-[72ch] text-pretty text-sm leading-relaxed text-foreground/90">
              {injectPrice(vote.summary, livePrice ?? priceAtAsOf)}
            </p>
          )}

          <p className="mt-3 text-[11px] text-muted-foreground">
            Written by a language model from the published models, the reported
            segments and a reverse-DCF — not a recommendation, and not a house
            view.
          </p>
        </div>
      )}

      {vote.drivers.length > 0 && (
        <div className="mt-4 border-t border-border pt-4">
          <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">
            Assumption by assumption
          </p>

          {/* The percentages are estimates and have failed two validation
              attempts; the ORDER and the "can anything measure this" flag are
              the parts that carry weight. Said once here rather than repeated
              per row. */}
          <p className="mb-2 max-w-[78ch] text-[11px] leading-relaxed text-muted-foreground">
            How much of each assumption the price appears to reflect, least
            reflected first — the top of this list is where the price is not
            paying for something. These
            bands are estimates, not measurements — two attempts to validate
            them have failed and a third is unresolved until Dec 2026. Read the
            ordering and the evidence, not the shade.
          </p>
          <ul className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[11px] text-muted-foreground">
            {[0, 40, 70, 95].map((v) => {
              const b = band(v);
              return (
                <li key={b.label} className="flex items-center gap-1.5">
                  <span className={`h-2 w-2 rounded-full ${b.dot}`} aria-hidden />
                  {b.label}
                </li>
              );
            })}
          </ul>
          <ul className="grid gap-x-8 gap-y-4 lg:grid-cols-2">
            {vote.drivers.map((d, i) => {
              const b = band(d.pricedInPct);
              return (
                <li key={`${i}-${d.driver.slice(0, 24)}`} className="flex gap-3">
                  <span
                    className={`mt-[7px] h-2 w-2 shrink-0 rounded-full ${b.dot}`}
                    aria-hidden
                  />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm leading-snug text-foreground">
                      {d.driver}
                    </p>
                    <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px]">
                      <span className={`font-medium ${b.text}`}>{b.label}</span>
                      {d.valueIfTruePct != null && Math.abs(d.valueIfTruePct) >= 1 && (
                        <>
                          <span className="text-muted-foreground/50">·</span>
                          <span className="font-mono tabular-nums text-muted-foreground">
                            worth {d.valueIfTruePct > 0 ? "+" : ""}
                            {d.valueIfTruePct.toFixed(0)}% if it lands
                          </span>
                        </>
                      )}
                      {!d.testable && (
                        <>
                          <span className="text-muted-foreground/50">·</span>
                          <span className="text-muted-foreground">not measurable</span>
                        </>
                      )}
                    </p>
                    {d.basis && (
                      <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
                        {d.basis}
                      </p>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {(stale || (drift != null && Math.abs(drift) >= 0.05)) && (
        <p className="mt-3 border-t border-border pt-3 text-xs text-muted-foreground">
          Computed at {priceAtAsOf != null ? money(priceAtAsOf) : "an earlier price"} on{" "}
          {vote.asOf}
          {drift != null && Math.abs(drift) >= 0.05 ? (
            <>
              {" "}
              — the quote has since moved {drift > 0 ? "+" : ""}
              {(drift * 100).toFixed(0)}%, so read this as a record of what was
              priced in then, not now.
            </>
          ) : (
            <> — {vote.ageDays} days ago.</>
          )}
        </p>
      )}
    </div>
  );
}
