---
name: nis-priced-in-story
description: >-
  Turn the priced-in reconstruction of ONE company into a narrated vertical REEL for
  Instagram and TikTok — the company's narrative told as a story: what its share price
  already believes, every assumption it refuses to pay for, and the single question
  that settles it. Nothing is withheld; a long ledger becomes more scenes, not a
  teaser. Picks the company on how well it will TELL (disagreement × refusal ×
  recognisability), refuses names whose target spread is corrupted by a stock split,
  animates the distribution rail and the pays-for/refuses ledger at 1080×1920, voices
  it with ElevenLabs and hands off to social_publishing. Also renders the paid
  single-image variants via nis-ad-image when an ad is what's wanted. Use when the user
  wants a reel or post about "priced in", "what the price already assumes", "the
  analyst spread", or "a deep angle people can't find themselves". NOT a weekly news
  trend (nis-trend-radar), NOT a swing setup (nis-stock-breakdown).
---

# Priced-In Story

The product's deepest asset is also its least advertisable: a nightly reconstruction,
for 500+ US companies, of **what a share price already contains**. It is deep, it is
genuinely hard to find anywhere else, and it is exactly the kind of thing that dies in
a feed if you put a chart of it on screen and hope.

This skill exists to stop that. It turns one reconstruction into a **story about a
company** — because that is what the data actually is. Every row is a narrative with
a protagonist (the company), a settled belief (what the price pays for), a refusal
(what it declines to pay for), and an unresolved question (the crux). That is a story
spine, not a stat.

**The one sentence the whole creative sells:**

> A share price is not an opinion about a company. It is a **list of assumptions**,
> and the list can be written down.

Nobody scrolling has ever seen their own holding written down that way. That is the
novelty, and it is real rather than claimed — which is why the ad can afford to show
the mechanism instead of bragging about it.

---

## The five-beat spine

Every creative this skill makes — static, reel, or caption — runs the same five
beats, in this order. The order is the argument: the reconstruction earns belief with
the dull half *before* it spends it on the surprising half.

| # | Beat | What it does | Source field |
|---|---|---|---|
| 1 | **The number** | A price, and the count of published models it disagrees with. Concrete, checkable, no interpretation yet. | `spread.n_targets`, `price_at_as_of`, `spread.n_endorsed` |
| 1c | **Which side are you on** | The decision, up front: believe X and the published models put you on the buy side at +N%; believe Y and the lowest model puts you on the sell side at −M%. Conditional and attributed — see the honesty rule below. | `spread.low/median/high` + `declines[0]` / the bear-case line |
| 2 | **What it already believes** | The consensus the price has *already bought* — deceleration, the margin, the impairment. Deliberately unexciting; this is the credibility beat. | `pays_for` |
| 3 | **What it refuses** | The turn. What every bull model needs and the price will not pay a cent for. | `declines` |
| 4 | **The crux** | The single question that settles it — and whether anything measurable can. This is the open loop. | `crux` |
| 5 | **Where to read it** | The reconstruction, on the company's own page. | `destination` |

Beat 3 is the ad. Beats 1–2 are what make beat 3 land, and beat 4 is what makes the
click feel like resolution rather than obedience.

**Organic and paid split at beat 3, and only there.**

- **A reel gives everything away.** Every assumption, both halves, the crux, in full.
  The reel is not trying to buy a click; it is trying to be worth following. Someone
  who watches ninety seconds of their own holding being taken apart, for free, has
  learned what the product does better than any teaser could tell them.
- **A paid ad may withhold beat 3**, because on the quote page everything after *"the
  price pays for"* sits behind a free account — so the ad withholds exactly what the
  landing page withholds, and the tease pays off one signup later. Never tease
  something that is not there when they arrive.

Same story, different ending. Do not import the ad's partial reveal into a reel.

Full beat sheet, hook matrix, reel script and caption templates:
**`references/story-spine.md`**. Read it before writing a single line of copy.

---

## Step 0 — What past ads already taught us

```bash
cd code/analytics
.venv/bin/python -m services.meta_ads.cli design --leaderboard --min-impr 200
```

Two things to carry in, and both are about *rates*, not totals:

- Delivered ads so far run **CTR ~3.0–3.4%** at a **CPM of $195–360** and about
  **$106–111 per real lead**. The CPM is the number to attack: it is very high, and
  high CPM on Meta is usually a creative-format problem before it is an audience one.
  Video/reel placements are the standard lever, which is one reason this skill renders
  a reel from the same spec rather than treating it as optional.
- `hook_type: contradiction` and `hook_type: question` are both proven here at small
  n. Neither has earned a verdict — so vary **one** lever per launch and bump
  `design.variant`, rather than rewriting everything at once.

There is also prior art: `output/ads/2026-09-01-priced-in/` ran three priced-in angles
(price-direct, proof-page, warm-retarget) off the **implied-growth** number. Read them
for voice. This skill deliberately builds on the *grounded* tier instead — see Honesty
rules — and sends people to the page that shows the same numbers back.

---

## Step 1 — Pick the company

```bash
cd code/analytics
.venv/bin/python ../../.claude/skills/nis-priced-in-story/scripts/priced_in_story.py --shortlist
.venv/bin/python ../../.claude/skills/nis-priced-in-story/scripts/priced_in_story.py --shortlist --direction above
```

The shortlist ranks every published reconstruction on how well it will **tell**:
disagreement (`|median_gap|`), refusal (share of published models the price declines),
spread width, news attention, size, and a rarity bonus for the scarcer configuration
(a price *above* every model — about 15% of the universe — is the more surprising ad).
It caps two names per theme, because ten names that all turn on "can they convert the
AI backlog" are one ad idea, not ten.

**Then you choose, on legibility.** The score cannot judge whether a viewer recognises
the company in half a second, or whether the crux is sayable in one breath. On Holding,
Crocs, Etsy, e.l.f., Monster, Oracle, Nvidia — a viewer knows what those companies
*do*, so "what the price believes about it" has somewhere to land. APLD, CRDO and AMKR
score well and mean nothing to a cold audience. Prefer:

- a company whose product the viewer has touched, or whose name they have heard;
- a crux with a **noun in it** ("HEYDUDE", "Rhode", "the Neutron rocket") — segment
  names are the proof that this is real work rather than a screen;
- `basis: ok` or `basis: stale` (see below).

### The refusal you must not override

The shortlist runs a **price-basis check** against the corporate-action feed and drops
names whose spread is not measured in the same share as the price:

```
refused — the spread is not measured against today's share:
  ✗ MNST   2-for-1 split on 2026-08-11, inside the 120-day target window
  ✗ KLAC   10-for-1 split on 2026-06-12, inside the 120-day target window
```

Monster's row reads *"the market has largely dismissed the bullish consensus"* — a 54%
gap that is entirely a share count: eleven targets of $90–105 posted when the stock
traded at ~$92, against a post-split $44.99. Two of the top fourteen candidates were
this. **These are the exact rows a ranking on disagreement floats to the top**, so the
check is not optional and `--force` is not for launching.

A `stale` basis is different and is not a defect: it means the models were published
when the stock was 25%+ away from where the reconstruction prices it. That is usually
the *sharper* ad ("nine analysts set targets on Oracle when it traded at $201; it is
$146 and none of them have moved") — as long as the copy says so.

## Step 2 — Pull the story material

```bash
.venv/bin/python ../../.claude/skills/nis-priced-in-story/scripts/priced_in_story.py --ticker ONON
→ output/ads/<today>-priced-in-<ticker>/story.json
```

`story.json` is the campaign-level fact sheet every variant renders from — so an A/B
between two folders is an A/B of the **creative**, not of two different sets of facts.
It carries:

| Field | Use it for |
|---|---|
| `spread` | every headline number: `n_targets`, `low/median/high`, `median_gap_pct`, `n_endorsed`, `refused` |
| `pays_for` / `declines` / `crux` | beats 2, 3, 4 — the reconstruction's own prose |
| `position` | the one-sentence summary, when you want it in the primary text |
| `segments` | driver + segment NAMES (never their percentages) — the specificity that proves depth |
| `price_basis` | `ok` / `stale` / `split` / `unchecked`, plus when the models were written |
| `coverage_published_now` | the live count of covered companies. **Never hardcode a coverage number** — the last campaign said 284, it is 543 today, and a stale claim about the product is the easiest false claim to make |
| `checks` | age, drift vs the live quote, basis. Any `false` is a stop |

Read the whole file before writing. The reconstruction usually contains a better
sentence than anything you would invent.

## Step 3 — The reel (the default output)

An organic Instagram/TikTok reel is what this skill makes unless someone asks for
an ad. Two commands:

```bash
cd code/analytics
.venv/bin/python ../../.claude/skills/nis-priced-in-story/scripts/animate_priced_in.py --ticker ONON
.venv/bin/python ../../.claude/skills/nis-priced-in-story/scripts/build_priced_in_reel.py --ticker ONON --tempo 1.06
```

→ `output/setups/priced-in/<TICKER>/reel.mp4` (+ `reel_poster.png`, `vo_script.txt`),
which is exactly what `social_publishing` posts.

**Nothing is held back.** Every assumption the price pays for and every one it
refuses goes on screen — the reel gets longer rather than shorter, splitting a
long ledger across scenes with a `1/2` counter. This is the opposite of the paid
creative's partial reveal and it is deliberate: a post that withholds the
interesting half to sell a click gets scrolled past; a post that hands over the
entire reading gets saved and sent to someone. The signup pitch is one line at the
end, after the value is already delivered.

Structure (the same five beats, sized to the reconstruction):

| Scene | Beat | Notes |
|---|---|---|
| `number` | 1 | the price counts up; "N published targets · it agrees with none" |
| `stakes` | 1c | two cards — BUY / SELL, each with the belief that puts you there and the published target behind it |
| `rail` | 1b | the distribution draws, the price marker travels in and settles |
| `believes1..n` | 2 | every `pays_for` row, ✓, chunked to fit the safe band |
| `refuses1..n` | 3 | every `declines` row, ✕ |
| `crux` | 4 | the whole question, type stepped down to fit — never cut |
| `outro` | 5 | "Every price is a list of assumptions" + where to read it |
| `disclaimer` | — | added by the voicing step; the card is in the video, not just the caption |

Craft rules baked into the renderer, so don't undo them by hand:

- **1080×1920, safe band 220px top / 500px bottom.** Nothing load-bearing outside it.
- **Static captions**, white with a black stroke and no pill — animated captions
  read as "made by a brand". Each caption says something the narration does not.
- **Scene length comes from its own narration**, and each scene is stretched to its
  own line. One clip stretched to one long voiceover drifts, and the beat where the
  price stops believing something has to land on the words that say so.
- **The narrator is `VCgLBmBjldJmfphyB8sZ`** (override with `--voice-id` or
  `NIS_PRICED_IN_VOICE_ID`). Keep it constant across the series — one voice is most
  of what makes a catalogue feel like one show.
- **No baked music.** Attach a trending sound in-app; the platform rewards native
  audio and an attached sound is discoverable by other people.

Then write `output/setups/priced-in/<TICKER>/caption.txt` — the caption repeats the
full ledger as compressed text (people screenshot captions), names the crux, states
the as-of date and the disclaimer, and puts the link last. **Keep it to 1,100–1,400
characters**: IG and TikTok both hard-cap at 2,200 and show only ~125 before "more",
so the first sentence must stand alone. Drop qualifiers, never points. The publisher
refuses an over-length caption at the dry run. Add `social/linkedin.txt` for a
LinkedIn voice if posting there.

```bash
.venv/bin/python -m services.social_publishing.cli publish --ticker priced-in/ONON --dry-run
.venv/bin/python -m services.social_publishing.cli publish --ticker priced-in/ONON --platforms instagram
```

## Step 3b — Paid formats (only when the ask is an ad)

Ranked for *this* product, from the creative-format tiering in the marketing skills
(`ad-creative/references/meta-creative-formats.md`) and what the data here supports:

| Format | Verdict | Why |
|---|---|---|
| **Reel from the same spec** (9:16, blocks flying in on the beat order) | **make it every time** | The spine is educational and education-gated formats (VSL-shaped) are the ones that scale cold. Also the CPM lever. |
| **The reconstruction card** (static 4:5 — `price_rail`) | **hero static** | The distribution *is* the novel object. It is a miniature of the panel they land on. |
| **The ledger** (static 4:5/9:16 — `ledger`, partial reveal) | **hero static** | An "educational infographic" in the tier list's sense — it teaches, so it earns attention hard-sell formats don't. Under-used generally. |
| **Challenging-your-beliefs** headline over either block | good variant | "You think it's expensive. The price disagrees with all 17 analysts." |
| **David & Goliath** framing (you vs. published-target theatre) | good variant | There is a real villain: a $43 median nobody has revisited since May. |
| Notes-app / fake-native, press-logo walls, testimonial statics, listicles | **do not build** | F/E tier: they do not convert, and the fake-native ones actively confuse delivery. |

One hero block per frame. A `price_rail` **and** a `ledger` together only fit in 9:16 —
the renderer warns rather than overflowing silently, and that warning is a stop.

## Step 4 — Author the spec

One `ad.json` per variant, in its own subfolder under the campaign
(`output/ads/<date>-priced-in-<ticker>/<variant>/ad.json`) so `nis-ad-launch` treats
each as an ad set with an isolated budget. Everything in `nis-ad-image`'s spec applies;
this skill adds two blocks:

```json
"price_rail": {
  "title": "17 published models · On Holding",
  "ticker": "ONON", "price": 27.73,
  "low": 20, "median": 43, "high": 83, "n_targets": 17,
  "caption": "Reconstructed 2 Sep 2026 · targets published May–Aug 2026"
},
"ledger": {
  "pays":    ["Growth slowing from 24% to the ~10% a year the price requires",
              "Tariffs, FX and a 62.8% gross margin instead of the 64.5% guided"],
  "refuses": ["A return to 24% growth — the median $43 model needs it",
              "Margin recovery to 64.5%+",
              "Any credit for the bear case being wrong"],
  "reveal": "partial", "shown_refuses": 1, "more_label": "read them free →"
}
```

Both draw only what `story.json` carries. The rail marks the three positions that are
actually *known* — low, median, high — and puts the count in the title; it never draws
N evenly spaced ticks, because the stored row has the count, not the individual
targets, and evenly spaced ticks would invent a distribution.

Copy rules (the rest are in `references/story-spine.md`):

- **The hook is three components that must not repeat each other** — the visual (the
  rail, the ledger), the headline, and the primary text's first line. If the headline
  captions the image, one of three slots is wasted.
- **Headline numbers come from the numeric columns**, never from the prose. The
  reconstruction's `position` sentence may be *quoted* in the primary text; it may not
  be the source of a number on the image.
- **Name the company's own nouns.** "HEYDUDE", "Rhode", "the $638bn backlog". Generic
  copy about "the market" is what every other finance ad says.
- **The destination is the same company's page**, deep-linked to the panel:
  `https://www.newsimpactscreener.com/quote/<T>?utm_…#priced-in`. An ad about On that
  lands on a pricing page breaks the promise the ad just made.

## Step 5 — Render

```bash
.venv/bin/python ../../.claude/skills/nis-ad-image/scripts/build_ad_image.py \
    --spec output/ads/<date>-priced-in-<ticker>/<variant>/ad.json
```

Writes `4x5/ 9x16/ 1x1/ ad.png`, `ad_copy.txt`, `design.json`, and (when `launch_as`
allows) the fly-in `9x16/ad_reel.mp4`. **Look at every PNG before moving on.** A block
that overflows prints a warning; a chip that collides with a label does not.

`design.json` now records `has_price_rail`, `has_ledger`, `ledger_reveal` and
`ledger_refuses_shown/total`, so the reveal depth becomes a testable lever in
`meta_ads design` alongside `hook_type` and `accent`.

## Step 6 — Launch

```bash
.venv/bin/python -m services.meta_ads.cli preflight
.venv/bin/python -m services.meta_ads.cli draft --campaign <date>-priced-in-<ticker> --go
```

Everything is created **PAUSED**. Before flipping anything Active:

1. re-run `--ticker` and confirm `checks.drift_ok` is still true — a price that has
   moved 8% makes the creative's own number wrong;
2. click the rendered destination and confirm the `#priced-in` fragment survives the
   UTM tags Meta appends;
3. confirm the numbers on the image match the numbers on the page.

**Measurement gap, stated plainly.** `meta_ads reconcile` counts real leads from the
two email-subscription tables. A quote-page ad converts into a **free account**, which
is not in either table — so cost-per-real-lead will read as infinite for these ads even
when they work. Either accept CTR + `signup_completed` as the read for now, or add
`utm_content` to the signup attribution first (`components/sign-up-form.tsx` tracks
`signup_completed` with no UTM properties today). Say which one you did.

---

## Honesty rules (non-negotiable)

- **Grounded tier only.** `drivers_json.priced_in_pct` and `value_if_true_pct` are the
  programme's JUDGED tier and are **unvalidated** — two attempts to validate them
  failed, the second producing three believable numbers that were all measurement
  artefacts. They are not on the public quote page, so an ad using them would be both
  dishonest and incongruent with its own landing page. `story.json` never emits them.
  Driver and segment *names* are fine.
- **A split in the target window is a refusal**, not a caveat. See Step 1.
- **Say when the models were written** whenever `price_basis.verdict` is `stale`.
- **Attribute the prose.** `pays_for` / `declines` / `crux` are written by a language
  model from the arithmetic. The page attributes them; the ad must not upgrade them to
  house view or to fact.
- **Never a recommendation — and the `stakes` beat is the sharp edge of this rule.**
  It puts the words BUY and SELL on screen, so it has to earn them three ways, all
  enforced in `build_stakes()`:
  1. **Conditional.** Never "buy", always "*if you believe X*, you're a buyer". The
     viewer supplies the belief; we supply what follows from it.
  2. **Attributed and arithmetic.** The number beside each label is a published
     third-party target (`median of 17 models · $43`), never our estimate. The
     conditions are overridable for phrasing (`--bull-if` / `--bear-if`); the numbers
     are not overridable at all.
  3. **Honest about an absent side.** Where the spread contains no published target
     above (or below) the price, the card says "no published model above $X" rather
     than manufacturing a side.
  Everywhere else: "the price refuses to pay for X" is a reconstruction; "X is
  undervalued" is advice, is not what the data says, and is not what we sell. The
  disclaimer card runs in the video, not only the caption.
- **Freshness.** `age_days ≤ 21` to launch; the row is refused past 45 (the same
  staleness line the panel itself draws). Re-check drift before going Active.
- **Coverage counts come from `coverage_published_now`**, every time.

## What separates a good one from a generic one

- The viewer recognises the company, and the beat-2 list makes them think *"…that's
  true, actually"* before beat 3 surprises them.
- The refusal is specific and priced ("a return to 24% growth — the median $43 model
  needs it"), not vague ("the upside case").
- The crux is a question they could not have googled and can actually watch.
- The numbers on the creative are the numbers on the page they land on.
- It reads as a company story, not a screener output. If the ad would work with the
  ticker swapped out, it is not this skill's ad.

## Related surfaces (keep them consistent)

- `code/ui/app/quote/[symbol]/_components/priced-in-panel.tsx` — the page the ad lands
  on. It shows the rail, the position, the crux and *what the price pays for*; the
  refusal half and the claim-by-claim evidence are behind a free account. The ad's
  reveal depth should never exceed the page's.
- `code/ui/scripts/broadcast-priced-in.ts` — the "Priced In is free with an account"
  email, same offer and same wall. It ranks its hero ticker by `n_targets` with claim
  gates, and it has **no price-basis check** — so a split-corrupted row can carry it.
  If you touch one of these, consider the other.
- `code/strategylab/social/analyst.py` — where the target spread is built. The split
  problem is upstream of every consumer here.

## Not built yet (don't imply otherwise)

- **A short cut.** The reel runs as long as the reconstruction does — ONON came out
  at ~95s with 4 + 3 assumptions. Instagram carries it, but there is no 30s edit and
  no automatic "best three points" selection. If a short version is wanted, cap it
  deliberately with `--max-rows` and say in the caption that it is an excerpt.
- **Music.** Left silent on purpose; attach a trending sound in-app.
- **A carousel.** `social_publishing` can post `slides/slide-*.png`, and the scene
  frames would make a decent one, but nothing generates that set today.
- **Scheduling.** Posting is a deliberate command per ticker. There is no queue.
