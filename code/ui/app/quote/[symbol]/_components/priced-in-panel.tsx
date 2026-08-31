import { TrendingDown, TrendingUp, Minus } from "lucide-react";
// From the client-safe half, not `priced-in.ts`: this panel is rendered from
// the workspace's client-side tab switcher as well as from the quote page.
import type { PricedInVote } from "@/lib/quote/priced-in-vote";
import { injectPrice, STALE_AFTER_DAYS } from "@/lib/quote/priced-in-vote";
import {
  hasClaimByClaim,
  PricedInClaimByClaim,
  PricedInDeclines,
} from "./priced-in-deep-dive";
import {
  MembersClaimByClaimSlot,
  MembersDeclinesSlot,
  PricedInMembersProvider,
} from "./priced-in-members";
import { FIELD_LABEL, money, PartsColumn, SECTION_LABEL } from "./priced-in-ui";

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
 *
 * On the public quote page (`membersOnly`) the panel stops after "The price pays
 * for": what the price declines to pay for and the claim-by-claim evidence
 * underneath it are fetched by `PricedInMembersProvider` for a signed-in reader
 * and never rendered here, so the markup does not ship to anyone else. Inside
 * the workspace, where the reader is already signed in, the same components
 * render inline.
 */

/** Position along the low..high axis, clamped so a marker never leaves the rail. */
function pct(value: number, low: number, high: number): number {
  if (!(high > low)) return 50;
  return Math.max(2, Math.min(98, ((value - low) / (high - low)) * 100));
}

/**
 * Nudge overlapping label positions apart, keeping their order.
 *
 * Two reconstructed models often publish targets a couple of dollars apart, and
 * two numbered chips stacked on the same pixel read as one. The chips move; the
 * hairline ticks ON the rail stay at the true position, so the exact figure is
 * never distorted — only its label is.
 */
function spreadOut(positions: number[], gap = 7): number[] {
  const order = positions
    .map((x, i) => ({ x, i }))
    .sort((a, b) => a.x - b.x);
  for (let k = 1; k < order.length; k++) {
    if (order[k].x - order[k - 1].x < gap) order[k].x = order[k - 1].x + gap;
  }
  // The forward pass can push the last chip off the rail; walk back from the
  // right edge so the crowding is absorbed on the side with room.
  for (let k = order.length - 1; k >= 0; k--) {
    order[k].x = Math.min(98, order[k].x);
    if (k > 0 && order[k].x - order[k - 1].x < gap) {
      order[k - 1].x = Math.max(2, order[k].x - gap);
    }
  }
  const out = positions.slice();
  for (const o of order) out[o.i] = o.x;
  return out;
}

export function PricedInPanel({
  vote,
  livePrice,
  membersOnly = false,
}: {
  vote: PricedInVote;
  livePrice: number | null;
  /**
   * Put everything after "The price pays for" behind the account wall. Set on
   * the public quote page; left off inside the signed-in workspace.
   */
  membersOnly?: boolean;
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

  // LEGACY rows only. Where each reconstructed analyst model sits on the rail:
  // the tick is exact, and the numbered chip above it may be nudged aside but
  // carries the number that matches its card below. `priced-in/3` rows have no
  // analyst cases, so the rail is just the distribution again.
  const analystCases = vote.analystCases;
  const caseTicks = analystCases.map((c) => pct(c.target, low, high));
  const caseChips = spreadOut(caseTicks);

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

  const body = (
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

      {/* Distribution rail: low ─── median ─── high, with the price marked,
          and the reconstructed models numbered against it. */}
      <div className="mt-5 mb-2">
        {analystCases.length > 0 && (
          <div className="relative mb-1.5 h-[18px]">
            {caseChips.map((x, i) => (
              <span
                key={i}
                className="absolute top-0 flex h-[18px] w-[18px] -translate-x-1/2 items-center justify-center rounded-full border border-border bg-card font-mono text-[10px] tabular-nums text-muted-foreground"
                style={{ left: `${x}%` }}
                aria-hidden
              >
                {i + 1}
              </span>
            ))}
          </div>
        )}
        <div className="relative h-2 rounded-full bg-muted">
          {caseTicks.map((x, i) => (
            <div
              key={i}
              className="absolute top-0 h-2 w-px bg-foreground/40"
              style={{ left: `${x}%` }}
              aria-hidden
            />
          ))}
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
          <p className={`mb-2 ${SECTION_LABEL}`}>
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
            <div className="mt-4 border-l-2 border-border pl-3">
              <p className={`mb-1 ${FIELD_LABEL}`}>
                What the disagreement turns on
              </p>
              <p className="max-w-[74ch] text-pretty text-sm leading-relaxed text-foreground">
                {injectPrice(vote.parts.crux, livePrice ?? priceAtAsOf)}
              </p>
            </div>
          )}

          {/* The wall starts inside this grid: what the price pays for is free,
              the column beside it is not. The presence of each column is known
              from the row itself, so the layout is decided here even when the
              text on the right is fetched later. */}
          {(vote.parts?.paysFor?.length || vote.parts?.declines?.length) && (
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <PartsColumn
                label="The price pays for"
                items={vote.parts?.paysFor ?? []}
                price={livePrice ?? priceAtAsOf}
              />
              {(vote.parts?.declines?.length ?? 0) > 0 &&
                (membersOnly ? (
                  <MembersDeclinesSlot price={livePrice ?? priceAtAsOf} />
                ) : (
                  <PricedInDeclines
                    vote={vote}
                    price={livePrice ?? priceAtAsOf}
                  />
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

      {hasClaimByClaim(vote) &&
        (membersOnly ? (
          <MembersClaimByClaimSlot
            symbol={vote.ticker}
            price={livePrice ?? priceAtAsOf}
            priceAtAsOf={priceAtAsOf}
          />
        ) : (
          <PricedInClaimByClaim
            vote={vote}
            price={livePrice ?? priceAtAsOf}
            priceAtAsOf={priceAtAsOf}
          />
        ))}

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

  // One provider around the whole panel, not one per slot: the wall has two
  // openings in different places and they should cost a single round trip.
  return membersOnly ? (
    <PricedInMembersProvider symbol={vote.ticker}>{body}</PricedInMembersProvider>
  ) : (
    body
  );
}
