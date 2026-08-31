/**
 * The small shared vocabulary of the priced-in panel: its two label styles, its
 * money formatter, the band ramp, and the two evidence atoms.
 *
 * Split out of `priced-in-panel.tsx` when the deep dive moved behind the
 * members gate — the free panel, the gated deep dive and the client gate all
 * render the same labels, and none of the three should own them.
 */
import { injectPrice } from "@/lib/quote/priced-in-vote";

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
export type Band = { label: string; dot: string; text: string };

export function band(pricedInPct: number): Band {
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

export function money(n: number): string {
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: "USD",
    // Cents only where there are cents. A column of targets reading $55.00
    // beside $133 is ragged for no information — analysts publish round
    // numbers, and the ".00" is noise in every one of them.
    maximumFractionDigits: n >= 100 || Number.isInteger(n) ? 0 : 2,
  }).format(n);
}

/**
 * The panel has exactly two label styles and they mean different things.
 *
 * SECTION is uppercase and marks a division of the panel itself. FIELD is
 * sentence-case and marks one part of a single row's evidence. Before this
 * there were four, and a fourth tier of label on a page that is already a
 * distribution, a written summary and a list stops separating anything — every
 * heading looked equally important, so the reader had to read all of them to
 * find the structure.
 */
export const SECTION_LABEL =
  "text-[11px] uppercase tracking-wide text-muted-foreground";
export const FIELD_LABEL = "text-[11px] font-medium text-foreground/70";

/** One labelled paragraph inside a row's evidence. */
export function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <p className={`mb-1 ${FIELD_LABEL}`}>{label}</p>
      <p className="max-w-[76ch] text-pretty text-sm leading-relaxed text-foreground/90">
        {children}
      </p>
    </div>
  );
}

/** Evidence the retrieval turned up, for or against. Bulleted, never prose. */
export function EvidenceList({ label, items }: { label: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div>
      <p className={`mb-1.5 ${FIELD_LABEL}`}>{label}</p>
      <ul className="flex flex-col gap-1.5">
        {items.map((e, i) => (
          <li
            key={i}
            className="flex gap-2 text-sm leading-snug text-foreground/90"
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
 * One side of the reconstruction's two-column list — what the price pays for,
 * or what it declines to pay for.
 *
 * The two columns render from different places now: "pays for" is free and
 * server-rendered, "declines" comes back from the members gate. Same component
 * so they cannot drift apart.
 */
export function PartsColumn({
  label,
  items,
  price,
}: {
  label: string;
  items: string[];
  price: number | null;
}) {
  if (items.length === 0) return null;
  return (
    <div>
      <p className={`mb-1.5 ${SECTION_LABEL}`}>{label}</p>
      <ul className="flex flex-col gap-1.5">
        {items.map((item, i) => (
          <li
            key={i}
            className="flex gap-2 text-sm leading-snug text-foreground/90"
          >
            <span
              className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-muted-foreground/50"
              aria-hidden
            />
            <span>{injectPrice(item, price)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
