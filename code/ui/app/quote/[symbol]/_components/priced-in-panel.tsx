import { ChevronRight, TrendingDown, TrendingUp, Minus } from "lucide-react";
// From the client-safe half, not `priced-in.ts`: this panel is rendered from
// the workspace's client-side tab switcher as well as from the quote page.
import type {
  PricedInAnalystCase,
  PricedInDriver,
  PricedInDriverCase,
  PricedInVote,
} from "@/lib/quote/priced-in-vote";
import {
  caseVerdict,
  injectPrice,
  STALE_AFTER_DAYS,
  verdictReason,
} from "@/lib/quote/priced-in-vote";

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
    // Cents only where there are cents. A column of targets reading $55.00
    // beside $133 is ragged for no information — analysts publish round
    // numbers, and the ".00" is noise in every one of them.
    maximumFractionDigits: n >= 100 || Number.isInteger(n) ? 0 : 2,
  }).format(n);
}

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

/** One labelled paragraph inside a case's deep dive. */
function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <p className="max-w-[76ch] text-pretty text-[13px] leading-relaxed text-foreground/90">
        {children}
      </p>
    </div>
  );
}

/** Evidence the retrieval turned up, for or against. Bulleted, never prose. */
function EvidenceList({ label, items }: { label: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div>
      <p className="mb-1.5 text-[11px] uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <ul className="flex flex-col gap-1.5">
        {items.map((e, i) => (
          <li
            key={i}
            className="flex gap-2 text-[13px] leading-snug text-foreground/90"
          >
            <span
              className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-muted-foreground/50"
              aria-hidden
            />
            <span className="max-w-[70ch]">{e}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * LEGACY (`priced-in/2` rows): one published model, and its reconstruction.
 *
 * Kept only so the rows published before the pipeline was inverted keep
 * rendering until the batch regenerates them. New rows carry the evidence on
 * the driver instead — see `DriverCard`.
 *
 * The two tiers are separated by the disclosure, not by a footnote. Closed, the
 * card shows only arithmetic — a firm, a target, and where the price sits
 * against it. Open, it shows a language model's reconstruction of the argument,
 * and the reader is told so before they read a word of it.
 *
 * `<details>` rather than state: the panel is server-rendered on the quote page
 * and shipped to the client only by the workspace tab, so a disclosure that
 * costs no JavaScript and works before hydration is the right one. It is also
 * findable by the browser's own in-page search, which a hidden div is not.
 */
function AnalystCaseCard({
  c,
  index,
  priceAtAsOf,
}: {
  c: PricedInAnalystCase;
  index: number;
  priceAtAsOf: number | null;
}) {
  const v = caseVerdict(c.stance);
  const rejected =
    c.stance === "rejected_bull" || c.stance === "rejected_bear";
  const move =
    c.impliedMove == null
      ? null
      : `${c.impliedMove > 0 ? "+" : ""}${(c.impliedMove * 100).toFixed(0)}%`;

  return (
    <li className="overflow-hidden rounded-lg border border-border">
      <div className="flex items-start gap-3 p-3">
        <span
          className="mt-px flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-full border border-border bg-muted font-mono text-[10px] tabular-nums text-muted-foreground"
          aria-hidden
        >
          {index}
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm leading-snug text-foreground">
            <span className="font-medium">{c.firm}</span>
            {c.analyst && (
              <span className="text-muted-foreground"> · {c.analyst}</span>
            )}
          </p>
          {/* Stacked narrow, one line wide: the gloss wraps to two lines on a
              phone, which leaves the separator dangling at the end of the
              verdict. */}
          <p className="mt-1 flex flex-col gap-y-0.5 text-[11px] sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-2">
            <span className="flex items-center gap-1.5">
              <span className={`h-2 w-2 rounded-full ${v.dot}`} aria-hidden />
              <span className={`font-medium ${v.text}`}>{v.label}</span>
            </span>
            <span className="hidden text-muted-foreground/50 sm:inline">·</span>
            <span className="text-muted-foreground">{v.gloss}</span>
          </p>
        </div>
        <p className="shrink-0 text-right">
          <span className="font-mono text-sm tabular-nums text-foreground">
            {money(c.target)}
          </span>
          {move && (
            <span className="block font-mono text-[11px] tabular-nums text-muted-foreground">
              {move} from the price
            </span>
          )}
        </p>
      </div>

      <details className="group border-t border-border">
        <summary className="flex cursor-pointer list-none items-center gap-1.5 px-3 py-2 text-[11px] font-medium text-muted-foreground transition-colors hover:text-foreground [&::-webkit-details-marker]:hidden">
          <ChevronRight
            className="h-3 w-3 shrink-0 transition-transform group-open:rotate-90"
            aria-hidden
          />
          Deep dive — why this verdict, and what the model claims
        </summary>

        <div className="space-y-4 border-t border-border bg-muted/20 px-3 py-3">
          {/* The verdict is arithmetic, so it is stated as arithmetic, first
              and before any reconstruction can colour it. */}
          <div className="rounded-md border border-border/70 bg-card p-2.5">
            <p className="mb-1 text-[11px] uppercase tracking-wide text-foreground/70">
              Why this verdict
            </p>
            <p className="max-w-[76ch] text-pretty text-[13px] leading-relaxed text-foreground">
              {verdictReason(c, priceAtAsOf)}
            </p>
          </div>

          {c.thesis && <Field label="What this analyst must believe">{c.thesis}</Field>}
          {c.loadBearing && (
            <Field label="The assumption it turns on">{c.loadBearing}</Field>
          )}
          {c.objection && (
            <Field
              label={
                rejected
                  ? "Why the market declines it"
                  : "What this consensus takes for granted"
              }
            >
              {c.objection}
            </Field>
          )}

          {(c.evidenceFor.length > 0 || c.evidenceAgainst.length > 0) && (
            <div className="grid gap-4 sm:grid-cols-2">
              <EvidenceList label="Coverage that supports it" items={c.evidenceFor} />
              <EvidenceList
                label="Coverage that cuts against it"
                items={c.evidenceAgainst}
              />
            </div>
          )}

          {c.observable && (
            <Field label="What would settle it">
              {c.observable}
              {c.dataSource && (
                <span className="ml-1.5 whitespace-nowrap rounded border border-border bg-card px-1.5 py-px font-mono text-[10px] text-muted-foreground">
                  {c.dataSource.replaceAll("_", " ")}
                </span>
              )}
            </Field>
          )}

          {/* Provenance. The retrieval warning is the load-bearing part: a
              reconstruction drawn from most of a thin corpus is evidence about
              the company in general, not about this case. */}
          <p className="border-t border-border/70 pt-2.5 text-[11px] leading-relaxed text-muted-foreground">
            Reconstructed from {c.nPassages} passage
            {c.nPassages === 1 ? "" : "s"} of news coverage
            {c.confidence && <> · {c.confidence} confidence in the reconstruction</>}
            {c.model && <> · {c.model}</>}
            {!c.selective && (
              <>
                {" "}
                — the corpus held only{" "}
                {c.distinctArticles != null
                  ? `${c.distinctArticles} articles`
                  : "a handful of articles"}
                , so this is most of what has been written about the company
                rather than a targeted pull on this argument.
              </>
            )}
          </p>

          {c.sources.length > 0 && (
            <div>
              <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">
                Headlines it drew on
              </p>
              <ul className="flex flex-col gap-1">
                {c.sources.map((t, i) => (
                  <li
                    key={i}
                    className="max-w-[76ch] truncate text-[11px] leading-relaxed text-muted-foreground"
                    title={t}
                  >
                    {t}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </details>
    </li>
  );
}

/**
 * One assumption, in the same card grammar as a published model.
 *
 * The two are NOT paired. It is tempting to read the models and the assumptions
 * as one list each way round — four of each is the most common shape — but the
 * decomposition is drawn from the whole spread, not one driver per model: the
 * counts disagree in roughly half of the published rows, and nothing in the data
 * keys a driver to a firm. Pairing them would invent a correspondence, so they
 * are two kinds of claim in one section rather than two halves of one table.
 *
 * The other difference the UI has to carry is weight. A model's verdict is
 * arithmetic; an assumption's band is an unvalidated estimate. Same card, and
 * the label above each group says which is which.
 */
function DriverCard({
  d,
  price,
}: {
  d: PricedInDriver;
  price: number | null;
}) {
  const b = band(d.pricedInPct);
  const worth =
    d.valueIfTruePct != null && Math.abs(d.valueIfTruePct) >= 1
      ? `${d.valueIfTruePct > 0 ? "+" : ""}${d.valueIfTruePct.toFixed(0)}%`
      : null;
  const n = d.case?.narrative;
  const expandable = Boolean(d.basis || d.observable || d.case);

  // The row itself, used both as the disclosure trigger and — when there is
  // nothing to open — as a plain row. A `<summary>` that wraps only its own
  // label gives a ~28px tap target on a phone; the whole row clears 44px, which
  // is the floor, and it removes a line of "Deep dive" chrome per assumption.
  const row = (
    <>
      <ChevronRight
        className={`mt-[3px] h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform motion-reduce:transition-none group-open:rotate-90 ${
          expandable ? "" : "invisible"
        }`}
        aria-hidden
      />
      <span className={`mt-[7px] h-2 w-2 shrink-0 rounded-full ${b.dot}`} aria-hidden />
      <span className="min-w-0 flex-1">
        <span className="block text-sm leading-snug text-foreground">
          {d.driver}
        </span>
        <span className="mt-1 flex flex-col gap-y-0.5 text-[11px] sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-2">
          <span className={`font-medium ${b.text}`}>{b.label}</span>
          {d.segment && (
            <>
              <span className="hidden text-muted-foreground/50 sm:inline">·</span>
              <span className="text-muted-foreground">{d.segment}</span>
            </>
          )}
          {/* The measured coverage read, surfaced closed. It is the one piece of
              evidence here that is counted rather than judged, and burying it
              behind a click made the list scannable only on the estimate. No
              colour: the band already owns the panel's single accent, and a
              second scale for tone would compete with it. */}
          {n && n.related > 0 && (
            <>
              <span className="hidden text-muted-foreground/50 sm:inline">·</span>
              <span className="font-mono tabular-nums text-muted-foreground">
                {n.related} claim{n.related === 1 ? "" : "s"}, tone{" "}
                {n.netImpact > 0 ? "+" : ""}
                {n.netImpact.toFixed(2)}
              </span>
            </>
          )}
          {!d.testable && (
            <>
              <span className="hidden text-muted-foreground/50 sm:inline">·</span>
              <span className="text-muted-foreground">
                nothing wired can measure it
              </span>
            </>
          )}
        </span>
      </span>
      {worth && (
        <span className="shrink-0 text-right">
          <span className="block font-mono text-sm tabular-nums text-foreground">
            {worth}
          </span>
          {/* Not mono: it is a phrase, and monospacing prose to match the figure
              above it is the tell of a table that stopped being a table. */}
          <span className="block text-[11px] text-muted-foreground">
            if it lands
          </span>
        </span>
      )}
    </>
  );

  if (!expandable) {
    return (
      <li className="flex items-start gap-3 px-3 py-3">{row}</li>
    );
  }

  return (
    <li>
      <details className="group">
        {/* Open, the row takes the same ground as its evidence, so the two read
            as one block rather than a header floating above a tinted panel. */}
        <summary className="flex cursor-pointer list-none items-start gap-3 px-3 py-3 transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring motion-reduce:transition-none group-open:bg-muted/20 [&::-webkit-details-marker]:hidden">
          {row}
        </summary>
        {/* Indented to the title's own x-position rather than boxed again: the
            evidence belongs to the row above it, and a third nested card inside
            a card inside the panel is how a dense page turns into a stack of
            containers. */}
        <div className="space-y-4 bg-muted/20 px-3 pb-4 pt-1 sm:pl-[3.25rem]">
          {d.basis && (
            <Field label="Why this band">{injectPrice(d.basis, price)}</Field>
          )}
          {worth && (
            <Field label="What it is worth if it proves out">
              {worth} of the current price — bounded by the published models,
              not a point estimate: it is what the target resting on this
              assumption implies, and no more.
            </Field>
          )}

          {d.case ? (
            <CaseBody c={d.case} price={price} />
          ) : (
            <Field label="What would settle it">
              {d.testable
                ? "Measurable with the data already wired"
                : "Nothing wired can measure this one, so it stays an argument"}
              {d.observable && (
                <span className="ml-1.5 whitespace-nowrap rounded border border-border bg-card px-1.5 py-px font-mono text-[10px] text-muted-foreground">
                  {d.observable.replaceAll("_", " ")}
                </span>
              )}
            </Field>
          )}
        </div>
      </details>
    </li>
  );
}

/**
 * The evidence behind one driver: what is known, and what could be measured.
 *
 * Ordered so the reader meets the three sources in the order of what they can
 * bear. The coverage read comes first and is explicitly framed as evidence of
 * being PRICED — a driver the press is loud about is one the market has heard,
 * which is the case for the band above, not a case that the driver is true.
 * The passages follow, because they are what the coverage actually says. The
 * measurement comes last and is the only line that speaks to truth, which is
 * why it says plainly when there is nothing to say.
 */
function CaseBody({
  c,
  price,
}: {
  c: PricedInDriverCase;
  price: number | null;
}) {
  const n = c.narrative;
  return (
    <>
      {c.whatCoverageSays && (
        <div>
          <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">
            What the coverage says
          </p>
          {n && n.scanned > 0 && (
            <p className="mb-1.5 font-mono text-[11px] tabular-nums text-muted-foreground">
              {n.related} of {n.scanned}{" "}
              circulating claims speak to this
              {n.related > 0 && (
                <>
                  {" · "}mean impact {n.netImpact > 0 ? "+" : ""}
                  {n.netImpact.toFixed(2)}
                  {" · "}
                  {n.positive} positive / {n.negative} negative
                </>
              )}
            </p>
          )}
          <p className="max-w-[76ch] text-pretty text-[13px] leading-relaxed text-foreground/90">
            {injectPrice(c.whatCoverageSays, price)}
          </p>
          {/* The load-bearing caveat of this whole panel, said where the number
              is rather than in a footnote nobody reaches. */}
          <p className="mt-1.5 max-w-[76ch] text-[11px] leading-relaxed text-muted-foreground">
            Coverage measures how well known this is, not whether it is true —
            and what is known is what the price has already heard.
          </p>
        </div>
      )}

      {(c.evidenceFor.length > 0 || c.evidenceAgainst.length > 0) && (
        <div className="grid gap-4 sm:grid-cols-2">
          <EvidenceList label="Coverage that supports it" items={c.evidenceFor} />
          <EvidenceList
            label="Coverage that cuts against it"
            items={c.evidenceAgainst}
          />
        </div>
      )}

      {c.whatTheDataShows && (
        <div>
          <p className="mb-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] uppercase tracking-wide text-muted-foreground">
            What the data outside the news shows
            {c.measurement?.ran && c.measurement.tool && (
              <span className="whitespace-nowrap rounded border border-border bg-card px-1.5 py-px font-mono text-[10px] normal-case tracking-normal text-muted-foreground">
                {c.measurement.tool.replaceAll("_", " ")}
              </span>
            )}
            {c.measurement && !c.measurement.ran && (
              <span className="whitespace-nowrap rounded border border-border bg-card px-1.5 py-px font-mono text-[10px] normal-case tracking-normal text-muted-foreground">
                nothing wired
              </span>
            )}
          </p>
          <p className="max-w-[76ch] text-pretty text-[13px] leading-relaxed text-foreground/90">
            {injectPrice(c.whatTheDataShows, price)}
          </p>
        </div>
      )}

      {c.stillNeeded && (
        <Field label="What would still settle it">
          {injectPrice(c.stillNeeded, price)}
        </Field>
      )}

      <p className="border-t border-border/70 pt-2.5 text-[11px] leading-relaxed text-muted-foreground">
        Read from {c.nPassages} passage{c.nPassages === 1 ? "" : "s"} of news
        coverage
        {c.confidence && <> · {c.confidence} confidence</>}
        {c.model && <> · {c.model}</>}
        {!c.selective && (
          <>
            {" "}
            — the corpus held only{" "}
            {c.distinctArticles != null
              ? `${c.distinctArticles} articles`
              : "a handful of articles"}
            , so this is most of what has been written about the company rather
            than a targeted pull on this assumption.
          </>
        )}
      </p>

      {c.sources.length > 0 && (
        <div>
          <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">
            Headlines it drew on
          </p>
          <ul className="flex flex-col gap-1">
            {c.sources.map((t, i) => (
              <li
                key={i}
                className="max-w-[76ch] truncate text-[11px] leading-relaxed text-muted-foreground"
                title={t}
              >
                {t}
              </li>
            ))}
          </ul>
        </div>
      )}
    </>
  );
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

      {(analystCases.length > 0 || vote.drivers.length > 0) && (
        <div className="mt-4 border-t border-border pt-4">
          <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">
            Claim by claim
          </p>
          <p className="mb-4 max-w-[78ch] text-[11px] leading-relaxed text-muted-foreground">
            {analystCases.length > 0 ? (
              <>
                Two kinds of claim sit behind this price, and they do not carry
                the same weight. Each one is labelled with the verdict on it;
                open a deep dive for the reasoning behind that label.
              </>
            ) : (
              <>
                What the price pays for, broken into the assumptions underneath
                it. Each is labelled with how much of it the price appears to
                reflect; the deep dive is what is actually known about it — the
                coverage in circulation, what that coverage asserts either way,
                and whether anything outside the news can measure it.
              </>
            )}
          </p>

          {analystCases.length > 0 && (
            <>
              <p className="mb-1 text-[11px] font-medium text-foreground/70">
                The published models
              </p>
              <p className="mb-2.5 max-w-[78ch] text-[11px] leading-relaxed text-muted-foreground">
                {analystCases.length} of the {vote.nTargets}{" "}
                models, numbered on the rail above, highest target first. The
                verdict on each is arithmetic — where its target sits against
                the price, nothing more. What the analyst must believe, and the
                coverage for and against it, is a language model&rsquo;s
                reconstruction from the published note and the news.
              </p>
              <ul className="mb-5 flex flex-col gap-2">
                {analystCases.map((c, i) => (
                  <AnalystCaseCard
                    key={`${c.firm}-${c.target}-${i}`}
                    c={c}
                    index={i + 1}
                    priceAtAsOf={priceAtAsOf}
                  />
                ))}
              </ul>
            </>
          )}

          {vote.drivers.length > 0 && (
            <>
              <p className="mb-1 text-[11px] font-medium text-foreground/70">
                {analystCases.length > 0
                  ? "The assumptions underneath them"
                  : "The assumptions"}
              </p>
              {/* The percentages are estimates and have failed two validation
                  attempts; the ORDER and the "can anything measure this" flag
                  are the parts that carry weight. Said once here rather than
                  repeated per row. */}
              <p className="mb-2.5 max-w-[78ch] text-[11px] leading-relaxed text-muted-foreground">
                {analystCases.length > 0 && (
                  <>
                    Decomposed from the whole spread rather than one per model,
                    so these do not pair off against the cards above.{" "}
                  </>
                )}
                How much of each the price appears to reflect, least reflected
                first — the top of this list is where the price is not paying
                for something. These bands are estimates, not measurements: two
                attempts to validate them have failed and a third is unresolved
                until Dec 2026. Read the ordering and the evidence, not the
                shade.
              </p>
              <ul className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[11px] text-muted-foreground">
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
              <ul className="divide-y divide-border overflow-hidden rounded-lg border border-border">
                {vote.drivers.map((d, i) => (
                  <DriverCard
                    key={`${i}-${d.driver.slice(0, 24)}`}
                    d={d}
                    price={livePrice ?? priceAtAsOf}
                  />
                ))}
              </ul>
            </>
          )}
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
