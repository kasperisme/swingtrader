import Link from "next/link";
import { ChevronRight } from "lucide-react";
import type {
  PricedInAnalystCase,
  PricedInDriver,
  PricedInDriverCase,
  PricedInVote,
} from "@/lib/quote/priced-in-vote";
import {
  caseVerdict,
  injectPrice,
  verdictReason,
} from "@/lib/quote/priced-in-vote";
import {
  band,
  CitedText,
  EvidenceList,
  FIELD_LABEL,
  Field,
  money,
  PartsColumn,
  SECTION_LABEL,
} from "./priced-in-ui";

/**
 * The members-only half of the priced-in panel.
 *
 * Everything after "The price pays for" lives here: what the price declines to
 * pay for, and the claim-by-claim deep dive underneath it. Split out of
 * `priced-in-panel.tsx` so the quote page can render the free half statically
 * and never ship this half to a reader who is not signed in — a wall that only
 * hides the markup is not a wall, and it would be cloaking besides.
 *
 * Nothing in here holds state, so it renders on the server for the workspace
 * and inside `PricedInMembersGate` on the quote page from the same source.
 */

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
    <li>
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

        <div className="ml-3 space-y-4 border-l-2 border-border py-3 pl-3 pr-3">
          {/* The verdict is arithmetic, so it is stated as arithmetic, first
              and before any reconstruction can colour it. */}
          <div>
            <p className={`mb-1 ${FIELD_LABEL}`}>Why this verdict</p>
            <p className="max-w-[76ch] text-pretty text-sm leading-relaxed text-foreground">
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
              <p className={`mb-1 ${SECTION_LABEL}`}>
                Headlines it drew on
              </p>
              <ul className="flex flex-col gap-1">
                {c.sources.map((s, i) => (
                  <li
                    key={i}
                    className="max-w-[76ch] truncate text-[11px] leading-relaxed text-muted-foreground"
                    title={s.title}
                  >
                    {s.slug ? (
                      <Link
                        href={`/articles/${s.slug}`}
                        className="underline decoration-border underline-offset-2 transition-colors hover:text-foreground"
                      >
                        {s.title}
                      </Link>
                    ) : (
                      s.title
                    )}
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
        <summary className="flex cursor-pointer list-none items-start gap-3 px-3 py-3 transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring motion-reduce:transition-none [&::-webkit-details-marker]:hidden">
          {row}
        </summary>
        {/* Indented to the title's own x-position rather than boxed again: the
            evidence belongs to the row above it, and a third nested card inside
            a card inside the panel is how a dense page turns into a stack of
            containers. */}
        <div className="ml-3 space-y-4 border-l-2 border-border pb-4 pl-3 pr-3 pt-1 sm:ml-[3.25rem]">
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
                <span className="ml-1.5 whitespace-nowrap font-mono text-[10px] text-muted-foreground">
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
          <p className={`mb-1 ${FIELD_LABEL}`}>What the coverage says</p>
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
          <p className="max-w-[76ch] text-pretty text-sm leading-relaxed text-foreground/90">
            <CitedText
              text={injectPrice(c.whatCoverageSays, price)}
              passages={c.passages}
            />
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
          <EvidenceList
            label="Coverage that supports it"
            items={c.evidenceFor}
            passages={c.passages}
          />
          <EvidenceList
            label="Coverage that cuts against it"
            items={c.evidenceAgainst}
            passages={c.passages}
          />
        </div>
      )}

      {c.whatTheDataShows && (
        <div>
          <p className={`mb-1 flex flex-wrap items-center gap-x-2 gap-y-1 ${FIELD_LABEL}`}>
            What the data outside the news shows
            {c.measurement?.ran && c.measurement.tool && (
              <span className="whitespace-nowrap font-mono text-[10px] font-normal text-muted-foreground">
                {c.measurement.tool.replaceAll("_", " ")}
              </span>
            )}
            {c.measurement && !c.measurement.ran && (
              <span className="whitespace-nowrap font-mono text-[10px] font-normal text-muted-foreground">
                nothing wired
              </span>
            )}
          </p>
          <p className="max-w-[76ch] text-pretty text-sm leading-relaxed text-foreground/90">
            <CitedText
              text={injectPrice(c.whatTheDataShows, price)}
              passages={c.passages}
            />
          </p>
        </div>
      )}

      {c.stillNeeded && (
        <Field label="What would still settle it">
          <CitedText
            text={injectPrice(c.stillNeeded, price)}
            passages={c.passages}
          />
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
          <p className={`mb-1 ${FIELD_LABEL}`}>Headlines it drew on</p>
          <ul className="flex flex-col gap-1">
            {c.sources.map((s, i) => (
              <li
                key={i}
                className="max-w-[76ch] truncate text-[11px] leading-relaxed text-muted-foreground"
                title={s.title}
              >
                {s.slug ? (
                  <Link
                    href={`/articles/${s.slug}`}
                    className="underline decoration-border underline-offset-2 transition-colors hover:text-foreground"
                  >
                    {s.title}
                  </Link>
                ) : (
                  s.title
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </>
  );
}

/** What the price declines to pay for — the gated half of the two-column list. */
export function PricedInDeclines({
  vote,
  price,
}: {
  vote: PricedInVote;
  price: number | null;
}) {
  return (
    <PartsColumn
      label="It declines to pay for"
      items={vote.parts?.declines ?? []}
      price={price}
    />
  );
}

/** True when there is a claim-by-claim section to render (or to lock). */
export function hasClaimByClaim(vote: PricedInVote): boolean {
  return vote.analystCases.length > 0 || vote.drivers.length > 0;
}

/**
 * The claim-by-claim deep dive: the published models (legacy rows) and the
 * assumptions the price is built on, each row opening onto its evidence.
 *
 * The most expensive thing on the panel to produce and the reason to have an
 * account, so on the quote page it is behind `PricedInMembersGate`.
 */
export function PricedInClaimByClaim({
  vote,
  price,
  priceAtAsOf,
}: {
  vote: PricedInVote;
  price: number | null;
  priceAtAsOf: number | null;
}) {
  const analystCases = vote.analystCases;
  if (!hasClaimByClaim(vote)) return null;

  return (
        <div className="mt-4 border-t border-border pt-4">
          <p className={`mb-1 ${SECTION_LABEL}`}>
            Claim by claim
          </p>
          <p className="mb-3 max-w-[78ch] text-[11px] leading-relaxed text-muted-foreground">
            {analystCases.length > 0 ? (
              <>
                Two kinds of claim sit behind this price, and they do not carry
                the same weight. Each one is labelled with the verdict on it;
                open a row for the reasoning behind that label.
              </>
            ) : (
              <>
                The assumptions the price is built on, least reflected first —
                the top of this list is where it is not paying for something.
                Open a row for what is known about that assumption: the coverage
                in circulation, what it asserts either way, and whether anything
                outside the news can measure it. The bands are estimates, not
                measurements — two attempts to validate them have failed and a
                third is unresolved until Dec 2026, so read the ordering and the
                evidence, not the shade.
              </>
            )}
          </p>

          {analystCases.length > 0 && (
            <>
              <p className={`mb-1 ${FIELD_LABEL}`}>The published models</p>
              <p className="mb-2.5 max-w-[78ch] text-[11px] leading-relaxed text-muted-foreground">
                {analystCases.length} of the {vote.nTargets}{" "}
                models, numbered on the rail above, highest target first. The
                verdict on each is arithmetic — where its target sits against
                the price, nothing more. What the analyst must believe, and the
                coverage for and against it, is a language model&rsquo;s
                reconstruction from the published note and the news.
              </p>
              <ul className="mb-5 divide-y divide-border border-y border-border">
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
              {analystCases.length > 0 && (
                <p className={`mb-1 ${FIELD_LABEL}`}>
                  The assumptions underneath them
                </p>
              )}
              {/* The percentages are estimates and have failed two validation
                  attempts; the ORDER and the "can anything measure this" flag
                  are the parts that carry weight. Said once here rather than
                  repeated per row. */}
              {analystCases.length > 0 && (
                <p className="mb-2.5 max-w-[78ch] text-[11px] leading-relaxed text-muted-foreground">
                  Decomposed from the whole spread rather than one per model, so
                  these do not pair off against the models above. How much of
                  each the price appears to reflect, least reflected first.
                  These bands are estimates, not measurements: two attempts to
                  validate them have failed and a third is unresolved until Dec
                  2026. Read the ordering and the evidence, not the shade.
                </p>
              )}
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
              <ul className="divide-y divide-border border-y border-border">
                {vote.drivers.map((d, i) => (
                  <DriverCard
                    key={`${i}-${d.driver.slice(0, 24)}`}
                    d={d}
                    price={price}
                  />
                ))}
              </ul>
            </>
          )}
        </div>
  );
}
