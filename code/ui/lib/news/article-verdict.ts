/**
 * The article page's stance layer: what the headline says, what the scores say,
 * and where each number sits against this week's distribution.
 *
 * Pure functions only — no I/O — so every rule here is unit-tested
 * (__tests__/article-verdict.test.ts) and the page stays a thin renderer.
 */

export type Direction = "bullish" | "bearish" | "neutral";

/** Below this magnitude a score is treated as no signal either way. Matches the
 *  page's own colour threshold family (scoreClass uses 0.03, sentimentLabel 0.05). */
export const NEUTRAL_BAND = 0.05;

export function directionOf(score: number, band = NEUTRAL_BAND): Direction {
  if (score > band) return "bullish";
  if (score < -band) return "bearish";
  return "neutral";
}

// ── Headline stance ──────────────────────────────────────────────────────────

export type HeadlineStance = {
  /**
   * call — the headline states a rating ("…, Buy", "Downgrade to Sell").
   * tone — no rating, but its verbs lean one way ("Plunges", "Beats").
   * none — takes no side, or asks a question.
   */
  kind: "call" | "tone" | "none";
  direction: Direction;
  /** "Buy", "Strong Sell", "Hold", "Downgrade"… for calls; the direction word for tone. */
  label: string;
};

const RATING_WORDS: Record<string, { direction: Direction; label: string }> = {
  "strong buy": { direction: "bullish", label: "Strong Buy" },
  buy: { direction: "bullish", label: "Buy" },
  accumulate: { direction: "bullish", label: "Accumulate" },
  outperform: { direction: "bullish", label: "Outperform" },
  overweight: { direction: "bullish", label: "Overweight" },
  bullish: { direction: "bullish", label: "Bullish" },
  "strong sell": { direction: "bearish", label: "Strong Sell" },
  sell: { direction: "bearish", label: "Sell" },
  reduce: { direction: "bearish", label: "Reduce" },
  underperform: { direction: "bearish", label: "Underperform" },
  underweight: { direction: "bearish", label: "Underweight" },
  avoid: { direction: "bearish", label: "Avoid" },
  bearish: { direction: "bearish", label: "Bearish" },
  hold: { direction: "neutral", label: "Hold" },
  neutral: { direction: "neutral", label: "Neutral" },
  "equal weight": { direction: "neutral", label: "Equal Weight" },
  "market perform": { direction: "neutral", label: "Market Perform" },
};

const RATING_ALT =
  "strong buy|strong sell|market perform|equal weight|buy|sell|hold|accumulate|reduce|outperform|underperform|overweight|underweight|avoid|bullish|bearish|neutral";

/** First match wins; order runs from least to most ambiguous. */
const CALL_PATTERNS: Array<{ re: RegExp; resolve: (m: RegExpMatchArray) => { direction: Direction; label: string } | null }> = [
  // Negations before the bare words they contain.
  { re: /\b(?:don'?t|do not|never)\s+buy\b/i, resolve: () => ({ direction: "bearish", label: "Don't buy" }) },
  { re: /\bnot\s+(?:yet\s+)?a\s+buy\b/i, resolve: () => ({ direction: "neutral", label: "Not a buy" }) },
  // Seeking Alpha's house style: the rating is the headline's last word.
  {
    re: new RegExp(`(?:[,:;]|\\s[–—-])\\s*(?:rating\\s+)?(?:reiterate\\s+|upgrade\\s+to\\s+|downgrade\\s+to\\s+)?(${RATING_ALT})(?:\\s+rating)?\\s*\\.?\\s*$`, "i"),
    resolve: (m) => RATING_WORDS[m[1].toLowerCase()] ?? null,
  },
  { re: new RegExp(`\\((?:rating\\s+)?(${RATING_ALT})\\)`, "i"), resolve: (m) => RATING_WORDS[m[1].toLowerCase()] ?? null },
  // Analyst actions only — "Microsoft upgrades Windows" is not a rating. The
  // word must sit next to "rating", carry a target ("… to Overweight"), or be
  // the passive "Downgraded at/by" of a broker note.
  {
    re: new RegExp(`\\b(upgrade|downgrade)[sd]?\\b[^.]*?\\bto\\s+(${RATING_ALT})\\b`, "i"),
    resolve: (m) => {
      const target = RATING_WORDS[m[2].toLowerCase()];
      const up = m[1].toLowerCase() === "upgrade";
      return { direction: up ? "bullish" : "bearish", label: `${up ? "Upgrade" : "Downgrade"} to ${target?.label ?? m[2]}` };
    },
  },
  {
    re: /\brating\s+(upgrade|downgrade)\b|\b(upgraded|downgraded)\s+(?:at|by)\b/i,
    resolve: (m) => {
      const up = (m[1] ?? m[2]).toLowerCase().startsWith("up");
      return { direction: up ? "bullish" : "bearish", label: up ? "Upgrade" : "Downgrade" };
    },
  },
  // "Buy The Dip", "Sell Before Earnings" after a colon or dash.
  { re: /[:–—-]\s*(buy|sell)\s+(?:the|this|now|before|while|on|it)\b/i, resolve: (m) => RATING_WORDS[m[1].toLowerCase()] ?? null },
  // Listicle calls: "3 Stocks to Buy in September", "Stock to Avoid".
  { re: /\bstocks?\s+to\s+(buy|sell|avoid)\b/i, resolve: (m) => RATING_WORDS[m[1].toLowerCase()] ?? null },
  { re: /\bworth\s+buying\b/i, resolve: () => RATING_WORDS.buy },
  // Leading imperative: "Buy This Dividend Stock Before…" (but not "Buyback…").
  { re: /^(strong\s+buy|strong\s+sell|buy|sell)\b(?![-\s]*(?:back|side|out|now,?\s+pay))/i, resolve: (m) => RATING_WORDS[m[1].toLowerCase().replace(/\s+/g, " ")] ?? null },
];

const BULL_WORDS =
  /\b(beats?|tops?|surg(?:e|es|ed|ing)|soar(?:s|ed|ing)?|jump(?:s|ed)?|rall(?:y|ies|ied)|climb(?:s|ed)?|gains?|ris(?:e|es|ing)|raises?|lifts?|boosts?|record high|wins?|approv(?:al|ed|es)|expands?|accelerat\w*|strong(?:er)?|higher|outperform\w*|breakout|rebound\w*|recover\w*|upside)\b/gi;
const BEAR_WORDS =
  /\b(miss(?:es|ed)?|plung(?:e|es|ed)|sink(?:s)?|sank|tumbl(?:e|es|ed)|falls?|fell|falling|drops?|dropped|slid(?:e|es)?|slump\w*|cuts?|lowers?|warns?|warning|lawsuit|probe|investigation|recall\w*|halt\w*|delay\w*|layoffs?|bankrupt\w*|loss(?:es)?|los(?:es|ing)|weak\w*|lower|declin\w*|downside|crash\w*|sell-?off|fraud|subpoena|slows?|slowdown|stall\w*|record low)\b/gi;

function countMatches(re: RegExp, text: string): number {
  return (text.match(re) ?? []).length;
}

export function parseHeadlineStance(title: string | null | undefined): HeadlineStance {
  const t = (title ?? "").trim();
  if (!t) return { kind: "none", direction: "neutral", label: "" };

  // A question asks; it does not assert. "Is Nvidia a Buy?" takes no side.
  const isQuestion = /\?\s*$/.test(t);
  if (!isQuestion) {
    for (const { re, resolve } of CALL_PATTERNS) {
      const m = t.match(re);
      if (!m) continue;
      const hit = resolve(m);
      if (hit) return { kind: "call", ...hit };
    }
  }
  if (isQuestion) return { kind: "none", direction: "neutral", label: "" };

  const net = countMatches(BULL_WORDS, t) - countMatches(BEAR_WORDS, t);
  if (net > 0) return { kind: "tone", direction: "bullish", label: "bullish" };
  if (net < 0) return { kind: "tone", direction: "bearish", label: "bearish" };
  return { kind: "none", direction: "neutral", label: "" };
}

// ── Verdict line ─────────────────────────────────────────────────────────────

export type Agreement =
  /** Headline and score point the same way. */
  | "confirms"
  /** Headline and score point opposite ways. */
  | "contradicts"
  /** Headline takes a side; the score is neutral. */
  | "unbacked"
  /** Headline says Hold/Neutral; the score leans one way. */
  | "diverges"
  /** Headline takes no side — the score is the only stance on the page. */
  | "no-call";

export function agreementOf(stance: HeadlineStance, net: number): Agreement {
  const scoreDir = directionOf(net);
  if (stance.kind === "none") return "no-call";
  if (stance.direction === "neutral") return scoreDir === "neutral" ? "confirms" : "diverges";
  if (scoreDir === "neutral") return "unbacked";
  return scoreDir === stance.direction ? "confirms" : "contradicts";
}

const NUMBER_WORDS = ["No", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten"];

function countWord(n: number, lower = false): string {
  const w = NUMBER_WORDS[n] ?? String(n);
  return lower ? w.toLowerCase() : w;
}

export function signed(n: number, digits = 2): string {
  // U+2212 minus: a hyphen next to tabular digits reads as a dash.
  return `${n >= 0 ? "+" : "−"}${Math.abs(n).toFixed(digits)}`;
}

export type Verdict = {
  stance: HeadlineStance;
  agreement: Agreement;
  /** "Source says Buy." / "Headline leans bearish." / "Headline takes no side." */
  headline: string;
  /** "We score DLTH −0.20 across four claims." */
  score: string;
  /** "Score contradicts the headline." */
  conclusion: string;
  net: number;
};

export function buildVerdict(args: {
  title: string | null | undefined;
  /** The primary ticker and its sentiment, when the story has one. */
  primary: { ticker: string; score: number } | null;
  claimImpacts: number[];
}): Verdict | null {
  const { primary, claimImpacts } = args;
  const n = claimImpacts.length;
  if (!primary && n === 0) return null;

  const net = primary
    ? primary.score
    : claimImpacts.reduce((a, b) => a + b, 0) / n;
  const stance = parseHeadlineStance(args.title);
  const agreement = agreementOf(stance, net);

  const headline =
    stance.kind === "call"
      ? `Source says ${stance.label}.`
      : stance.kind === "tone"
        ? `Headline leans ${stance.direction}.`
        : "Headline takes no side.";

  const across = n > 0 ? ` across ${countWord(n, true)} claim${n === 1 ? "" : "s"}` : "";
  const score = primary
    ? `We score ${primary.ticker} ${signed(net)}${across}.`
    : `${countWord(n)} claim${n === 1 ? "" : "s"} average ${signed(net)}.`;

  const scoreDir = directionOf(net);
  const conclusion = {
    confirms: "Score confirms the headline.",
    contradicts: "Score contradicts the headline.",
    unbacked: "Score is neutral — the claims don't back the headline's call.",
    diverges: `Score leans ${scoreDir}; the headline says ${stance.label}.`,
    "no-call":
      scoreDir === "neutral" ? "Our read: neutral." : `Our read: ${scoreDir}.`,
  }[agreement];

  return { stance, agreement, headline, score, conclusion, net };
}

// ── Percentile anchors ───────────────────────────────────────────────────────

export type ScoreKind = "claim" | "ticker" | "relationship";
export type ScoreHistogram = Array<{ score: number; n: number }>;
export type ScoreDistribution = Partial<Record<ScoreKind, ScoreHistogram>>;

const KIND_NOUN: Record<ScoreKind, string> = {
  claim: "claims",
  ticker: "ticker scores",
  relationship: "relationship scores",
};

/** Fewer than this many scores in the window and a percentile is noise. */
const MIN_SAMPLE = 50;

export type Anchor = {
  side: "negative" | "positive" | "neutral";
  /** 1..99 */
  pct: number;
  text: string;
};

/**
 * Where `value` sits against this week's scores of the same kind. Ties count
 * half (mid-rank): the model emits ~20 distinct values, so a strict "<" would
 * swing a score across a whole histogram bar.
 */
export function percentileAnchor(
  hist: ScoreHistogram | undefined,
  value: number,
  kind: ScoreKind,
): Anchor | null {
  if (!hist?.length || !Number.isFinite(value)) return null;
  const v = Math.round(value * 100) / 100;
  let total = 0;
  let below = 0;
  let above = 0;
  let equal = 0;
  let stronger = 0;
  for (const { score, n } of hist) {
    total += n;
    if (score < v) below += n;
    else if (score > v) above += n;
    else equal += n;
    if (Math.abs(score) > Math.abs(v)) stronger += n;
  }
  if (total < MIN_SAMPLE) return null;

  const clampPct = (x: number) => Math.min(99, Math.max(1, Math.round(x * 100)));
  const noun = KIND_NOUN[kind];
  const side = directionOf(v);
  if (side === "bearish") {
    const pct = clampPct((above + equal / 2) / total);
    return { side: "negative", pct, text: `More negative than ${pct}% of ${noun} this week` };
  }
  if (side === "bullish") {
    const pct = clampPct((below + equal / 2) / total);
    return { side: "positive", pct, text: `More positive than ${pct}% of ${noun} this week` };
  }
  const pct = clampPct(stronger / total);
  return { side: "neutral", pct, text: `Near neutral — ${pct}% of ${noun} this week are stronger` };
}

// ── Claims: split, rationale gate, novelty ───────────────────────────────────

/**
 * STORY_KEY_POINTS stores each claim as "point — rationale" (impact_scorer.py).
 * Split on the LAST separator: a point may itself contain " — ", a rationale is
 * one sentence appended after it.
 */
export function splitClaim(text: string): { claim: string; rationale: string } {
  const t = (text ?? "").trim();
  const i = t.lastIndexOf(" — ");
  if (i <= 0) return { claim: t, rationale: "" };
  return { claim: t.slice(0, i).trim(), rationale: t.slice(i + 3).trim() };
}

// Mirror of code/analytics/services/news/scoring/claim_rationale.py — the scorer
// drops a failing rationale at write time; this holds rows scored before that
// gate existed to the same rule. Change both together.

const NUMBER_RE = /\d+(?:[.,]\d+)?/g;
const HORIZON_RES: RegExp[] = [
  /\b(?:next|this|coming|following|current)\s+(?:trading\s+)?(?:session|week|month|quarter|year|fiscal\s+year|print|report|earnings|guide)s?\b/gi,
  /\bQ[1-4]\b/gi,
  /\b[1-4]Q\b/gi,
  /\bFY\s?'?\d{2,4}\b/gi,
  /\bH[12]\b/gi,
  /\b(?:19|20)\d{2}\b/g,
  /\b\d+\s*(?:-|to)?\s*\d*\s*(?:trading\s+)?(?:day|week|month|quarter|year|session)s?\b/gi,
  /\bwithin\s+(?:a|an|one|two|three|four|six|twelve)\s+(?:day|week|month|quarter|year|session)s?\b/gi,
  /\b(?:year[- ]end|holiday\s+quarter|back[- ]to[- ]school|next\s+earnings)\b/gi,
];
const CONSEQUENCE_TERMS = [
  "margin", "eps", "earnings per share", "guidance", "guide", "estimate",
  "consensus", "multiple", "p/e", "valuation", "re-rat", "rerat", "dividend",
  "buyback", "repurchase", "dilution", "dilutive", "share count", "cash burn",
  "runway", "covenant", "refinanc", "credit rating", "free cash flow", "fcf",
  "net debt", "leverage", "write-down", "writedown", "impairment", "layoff",
  "price target", "short interest", "squeeze", "delist", "bankrupt",
  "comps", "market share", "pricing power", "capex", "backlog",
  "order book", "default", "downgrade", "upgrade", "cost of capital",
  "customer acquisition",
];
const WORD_RE = /[a-z][a-z'-]+/g;
const STOP = new Set(
  "the a an and or of to in on for with by at from as is are was were be been this that these those it its their which who into over under than more less has have had will would could may might can not no but so".split(
    " ",
  ),
);

function numbersIn(text: string): Set<string> {
  return new Set((text.match(NUMBER_RE) ?? []).map((s) => s.replace(/,/g, "")));
}

function horizonsIn(text: string): Set<string> {
  const out = new Set<string>();
  for (const re of HORIZON_RES) for (const m of text.match(re) ?? []) out.add(m.toLowerCase());
  return out;
}

function consequencesIn(text: string): Set<string> {
  const lowered = text.toLowerCase();
  return new Set(CONSEQUENCE_TERMS.filter((t) => lowered.includes(t)));
}

function contentWords(text: string): Set<string> {
  return new Set((text.toLowerCase().match(WORD_RE) ?? []).filter((w) => !STOP.has(w)));
}

function hasNew(a: Set<string>, b: Set<string>): boolean {
  for (const x of a) if (!b.has(x)) return true;
  return false;
}

export function rationaleAddsInformation(point: string, rationale: string): boolean {
  const p = (point ?? "").trim();
  const r = (rationale ?? "").trim();
  if (!r) return false;
  const rw = contentWords(r);
  const pw = contentWords(p);
  if (rw.size) {
    let shared = 0;
    for (const w of rw) if (pw.has(w)) shared++;
    if (shared / rw.size >= 0.7) return false;
  }
  return (
    hasNew(numbersIn(r), numbersIn(p)) ||
    hasNew(horizonsIn(r), horizonsIn(p)) ||
    hasNew(consequencesIn(r), consequencesIn(p))
  );
}

export type Novelty = "new" | "priced_in";

export type ClaimMeta = { novelty: Novelty | null; basis: string };

/** Read one claim's entry out of news_impact_heads.meta_json. Unknown → null, never guessed. */
export function claimMetaOf(meta: unknown, id: string): ClaimMeta {
  const entry =
    meta && typeof meta === "object" ? (meta as Record<string, unknown>)[id] : undefined;
  if (!entry || typeof entry !== "object") return { novelty: null, basis: "" };
  const raw = (entry as Record<string, unknown>).novelty;
  const novelty: Novelty | null = raw === "new" || raw === "priced_in" ? raw : null;
  const basisRaw = (entry as Record<string, unknown>).novelty_basis;
  return { novelty, basis: typeof basisRaw === "string" ? basisRaw.trim() : "" };
}
