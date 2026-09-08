# The Priced-In Story Spine

The beat sheet, the hook matrix, the reel script and the copy rules. Read this before
writing copy; `SKILL.md` is the workflow, this is the craft.

Everything here assumes one thing about the audience: **they already own or watch the
company**. They are not looking for a stock idea. They are looking for a reading of a
company they already have an opinion about — and the reconstruction gives them one they
cannot assemble themselves.

---

## 1. The spine, written out

```
  1  THE NUMBER          $27.73. Seventeen published models. It agrees with none.
  1c WHICH SIDE          Believe growth comes back → the $43 median is +55%.
                         Believe it doesn't → the lowest model is $20, −28%.
  2  WHAT IT BELIEVES    Growth 24% → 10%. Tariffs. A 62.8% margin, not the 64.5% guided.
  3  WHAT IT REFUSES     A return to 24% — which is what the $43 median is built on.
  4  THE CRUX            Does growth re-accelerate, or is single-digit permanent?
  5  WHERE TO READ IT    On's reconstruction. Free.
```

Three properties make this work, and losing any one of them collapses it into a
finance-bro stat post:

**Beat 2 must be boring.** It is the credibility deposit. A reader who nods at "yes,
growth is slowing, that's obvious" has just agreed that the reconstruction reads the
company correctly — which is what makes beat 3 land as information rather than as a
claim. Do not make beat 2 exciting; make it *undeniable*.

**Beat 1c must be conditional.** It is the only beat that says BUY and SELL, and it
earns those words by never asserting either: the viewer brings the belief, the
published spread supplies the consequence, and a side the spread does not contain is
reported as absent rather than invented. "If you believe X, you're a buyer — the
median of 17 models is $43, +55%" is a fact about other people's research. "Buy ONON"
is not, and is not ours to say.

**Beat 3 must be priced.** "It refuses to pay for the upside" is nothing. "It refuses
to pay for a return to 24% growth — the median $43 model needs it" is the ad. The
refusal has to name what the bulls need and what it is worth in the published spread.

**Beat 4 must be watchable.** The crux is only interesting because it will resolve.
Where `crux` says the observation is testable, say so; where the reconstruction admits
nothing wired can settle it, that admission is *more* credible than a claim, not less.
The honest version of beat 4 is often the strongest line in the ad.

### The company is the protagonist

The reconstruction is about a business, so write about the business. The failure mode
is writing about the *tool*:

> ✗ "Our engine reconstructs what any price already contains, across 543 US companies."
> ✓ "On's price already believes growth is over. Here is the rest of what it believes."

The tool gets one line, at the end, as the reason this is knowable. Never the opening.

---

## 2. The hook matrix

A hook is **three components** — visual, headline, first line of primary text — and
they must not repeat each other. Fill a row per concept; a row with one column filled
is a third of a hook. Generate *across* segments and beats, not ten rewordings of one.

| Segment | Motivation | Lead beat | Visual | Headline | First line of primary text |
|---|---|---|---|---|---|
| Holds the stock | "Am I wrong, or is the market?" | 1 | `price_rail`, price chip far left | "17 analysts published a target on On. The price agrees with none of them." | "Seventeen analysts publish a target on On Holding. They range from $20 to $83." |
| Watches the brand | "I wear these — is it a business?" | 2 | `ledger`, pays half only | "On's price already believes growth is over." | "A share price is not an opinion about a company. It is a list of assumptions." |
| Distrusts analysts | "Price targets are theatre" | 1 | `price_rail` with `stale` note | "Nine analysts set a target on Oracle when it traded at $201. It's $146." | "None of them have moved. The price did." |
| Wants an edge, not a tip | "Everyone sees the same chart" | 3 | `ledger`, refusal half withheld | "Everything On's price refuses to pay for." | "The interesting half of a price is the half it declines to fund." |
| Values-driven skeptic | "Why should I believe you?" | 4 | crux typed over the rail | "One question decides On. It's measurable." | "Not a forecast. The question the arithmetic leaves open — and what would settle it." |

**Opening moves that suit this material** (from the hook system in `ad-creative`):
curiosity gap (withhold the refusal, pay it off on the page), contradiction (the price
against every published model), challenging-a-belief ("you think it's cheap; the price
is telling you what it will not fund"), proof-first (the rail itself). Avoid
confession and POV — there is no persona here to inhabit, and faking one costs the
credibility the data earns for free.

**The on-ramp rule.** Whatever the hook promises, seconds 3–15 (or the second and third
lines of the primary text) must *continue that premise*, not pivot to the product. If
the hook is "17 analysts, zero agreement", the next beat starts listing what the price
believes — not what the subscription costs.

---

## 3. The reel, beat by beat

The reel is the default output and it **holds nothing back** — every assumption on
both sides of the ledger, the whole crux, in the order the spine runs. A long
reconstruction becomes more scenes, never a shorter list. `animate_priced_in.py`
builds it; `build_priced_in_reel.py` voices it.

```
number        the price counts up · "N published targets · it agrees with none"
stakes        BUY / SELL cards — the belief that puts you on each side, and the
              published target behind it. Deliberately second: the viewer who
              leaves at fifteen seconds should still have got the decision.
rail          the distribution draws; the price marker travels in and settles
believes 1..n every pays_for row, green ✓, chunked to fit the safe band
refuses  1..n every declines row, amber ✕, with a 1/2 counter when it splits
crux          the whole question, type stepped down to fit — never cut
outro         "Every price is a list of assumptions" + where to read it
disclaimer    a reconstruction, not advice — in the video, not only the caption
```

**Each scene is cut to its own narration and stretched to its own line.** One clip
stretched to one long voiceover drifts by seconds before the end, and the beat
where the price stops believing something has to land on the words that say so.

**Length follows the story.** ONON — four assumptions paid for, three refused —
came out at ~95 seconds. That is a feature: the viewer who stays for ninety
seconds is the viewer worth having, and the ones who leave at fifteen were never
going to read a reconstruction anyway. Cap it with `--max-rows` only when a short
cut is explicitly wanted, and say in the caption that it is an excerpt.

**Narration rules** (enforced in `_speakable`, so don't undo them by hand): "$32
target" reads as "32 dollar target", "64.5%+" as "64.5 percent or better", and a
list item after a lead-in loses its capital so the model does not restart the
sentence mid-breath. Acronyms keep theirs.

**Voice:** `VCgLBmBjldJmfphyB8sZ`, constant across the series. Takes are cached by
(voice, text) under `.vo_cache/`, so iterating on the visuals costs nothing.

**Craft constraints** (from the vertical spec): 1080×1920; nothing load-bearing
outside the 720×1200 safe band (top 220px, bottom 500px, sides 180px); captions
static, white with a black stroke, no pill, and never a transcript of the
voiceover; no baked music — attach a trending sound in-app so the platform
rewards native audio.

## 4. Copy rules

**Say**

- "the price pays for", "the price declines to pay for", "the price already assumes"
- "17 published models", "the median model", "the models were published in May"
- "reconstructed", "what a price already contains", "the question that would settle it"
- the company's own nouns: segments, brands, products, contracts

**Never say**

- "undervalued", "overvalued", "cheap", "expensive", "buy", "sell", "opportunity"
- "X% priced in" for a driver — the judged tier is unvalidated and is not on the page
- "our model predicts", "we forecast", "AI-powered" — nothing here forecasts anything
- "unlock", "secret", "hidden gem", "what Wall Street doesn't want you to know"
- a coverage number from memory — read `coverage_published_now`
- "guaranteed", "risk-free", or any implication of a return

**Numbers**

- Headline numbers come from `spread`. Prose numbers may come from `pays_for` /
  `declines`, quoted as the reconstruction's words.
- Round the way the page rounds: prices to cents, targets to whole dollars,
  percentages to whole numbers.
- The price on the creative is `price_at_as_of` — the price the reconstruction was
  computed at — and the caption says the date. Never label it "today".

---

## 5a. The reel caption (Instagram / TikTok)

The caption repeats the WHOLE ledger as text. People screenshot captions, the
sound-off viewer reads it instead of watching, and a caption that summarises what
the video already said wastes the one surface that survives a re-share. Same
beats, no withholding, link last.

```
[hook]  {N} analysts publish a price target on {Company} (${TICKER}). The share
        price agrees with {none / N} of them.
[gap]   They range from ${low} to ${high}. The median is ${median}. The stock is
        ${price} — {gap}% below it.

WHAT THE PRICE ALREADY PAYS FOR
✓ every pays_for row, verbatim-ish

WHAT IT REFUSES TO PAY FOR
✕ every declines row, each with what it is worth in the published spread

THE ONE QUESTION
{crux}, and what would settle it.

That's the whole reading. Nothing held back, nothing behind a signup.
{coverage} US companies, rebuilt nightly — {Company}'s is at
newsimpactscreener.com/quote/{TICKER} (link in bio).

Reconstructed {as_of} from {N} published analyst models. Not financial advice —
a reading of what the price contains is not a forecast of where it goes.
#{TICKER} #stockmarket #investing #valuation …
```

**Length is a hard constraint, not a preference.** Instagram and TikTok both cut
off at **2,200 characters**, and only the first ~125 show before "more" — so the
first sentence has to carry the hook on its own. Aim for **1,100–1,400 characters**:
the reel carries the detail, the caption carries the decision and a compressed
ledger. `social_publishing` now refuses to post an over-length caption rather than
letting the network truncate it, so a long one fails at the dry run instead of
appearing mangled in the feed.

Compress by dropping qualifiers, not points: "Revenue growth decelerating from
24.2% to roughly the 9.7% the reverse-DCF requires over the next decade" becomes
"Growth decelerating from 24.2% to roughly 9.7% a year". Every point still appears.

Hashtags: the ticker, the company's retail name if it has one, and 6–8 broad
finance tags. LinkedIn gets its own file (`social/linkedin.txt`) — lead with the
method, drop the hashtags to three.

## 5b. Primary text template (paid ad, Meta, front-loaded)

The first 125 characters are all most people read; the rest is for the ones the hook
caught. Five beats, one paragraph each, product last.

```
[1] {N} analysts publish a price target on {Company}. They range from ${low} to
    ${high}, and the median is ${median}.

[2] The shares are ${price} — {position phrase}. The market has taken a position, and
    the position is legible: it pays for {pays 1}, {pays 2}, and {pays 3}.

[3] What it declines to pay for is the interesting half: {declines 1} — which is what
    the ${median} median is built on.

[4] One question decides it, and it is {observable / not yet measurable}: {crux}.

[5] {coverage} US companies, reconstructed nightly. {Company}'s is free to read.
```

TikTok caps ad text at ~80–100 characters, so write a separate one-liner rather than
truncating: lead with beat 1 or beat 3 and let the video carry the rest.

---

## 6. Self-check before rendering

- [ ] `story.json` `checks` all true; `price_basis.verdict` is `ok`, or `stale` **and
      the copy says when the models were written**
- [ ] Every number on the image traces to `spread` or to a quoted line
- [ ] No `priced_in_pct` / `value_if_true_pct` anywhere, in any wording
- [ ] Visual, headline and first line say three different things
- [ ] Beat 2 is boring and true; beat 3 is specific and priced
- [ ] REEL: every pays_for and every declines row is on screen — nothing capped
- [ ] AD ONLY: the withheld tail exists on the landing page, behind the free account
- [ ] Link is `/quote/<TICKER>#priced-in` (UTMs on the ad; bio link on the reel)
- [ ] Coverage count read from `coverage_published_now`
- [ ] Disclaimer present; nothing reads as advice
- [ ] You have watched the reel end to end, or looked at every rendered PNG
- [ ] The narration was read back for numbers that speak wrong ($32 target, 64.5%+)
