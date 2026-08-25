# What is priced in — reconstruction, and the counterfactuals the price rejects

**Verdict: the reconstruction works and is partly grounded; nothing built on top
of it is validated. The one thing tested against outcomes came back negative.**

This is the successor to the social-arbitrage line that `SOCIAL-ARB-1` closed out
(see the thesis registry). That thesis assumed consumer attention could be found
*before* the market had it. It failed on its pivotal link, and the reason
generalises: **anything in our news database is already priced in.** By the time
a proposition has been published, scored and indexed, the market has had it.

That assumption is not a limitation being worked around. It is the design. It
makes the corpus useless as a source of edge and valuable as a **map of the
baseline** — and you cannot say what would change a price without first saying
precisely what it already contains.

**Status, 2026-08-25.** Tier 1 negative, Tier 2 a measurement artefact, Tier 3
open with 65 sealed predictions resolving 2026-12-23. The grounded tier is live
on `/quote/<symbol>`; the judged tier is shown as ordinal bands, not decimals.
The investigation loop runs and returns "not settled" on its first real crux,
which is the honest answer.

```bash
.venv/bin/python -m strategylab.social.cli cases CROX        # the whole pipeline, one ticker
.venv/bin/python -m strategylab.social.cli universe queue    # what a scheduled pass would take
.venv/bin/python -m strategylab.social.cli batch --limit 25  # one scheduled pass
.venv/bin/python -m strategylab.social.cli investigate TSLA  # the crux, adversarially
.venv/bin/python -m strategylab.social.cli predict status    # the sealed ledger
.venv/bin/python -m strategylab.social.cli control CROX      # calibrate the corpus veto
.venv/bin/python -m strategylab.social.cli theses CROX       # generated counterfactuals (deprecated path)
```

---

## 1. The pipeline

| stage | module | what it produces |
|---|---|---|
| network | `narrative.py` | typed peers from `ticker_relationship_edges` |
| the null | `narrative.py` | circulating claims, market-wrap filtered |
| arithmetic | `implied.py` | the revenue path the price requires |
| the argument | `analyst.py` | target dispersion + earnings-call Q&A |
| the vote | `vote.py` | endorsed vs rejected published models |
| the case | `case.py` | each rejected model, checked against article bodies |
| the answer | `decompose.py` | per driver: how much is priced, what it is worth |

The unit of work is a **rejected published model**, not a generated idea. That
was the single most important change and it came from a measured failure: asked
to generate counterfactuals, the model produced twelve and **all twelve were
already written up in the corpus**. It could not be original because its priors
*are* consensus. A bank's rejected target does not have that problem — it is a
real model, held by someone paid to hold it, that the market has seen and
declined.

---

## 2. Read the output in three tiers

Keeping these apart is the difference between a tool and a story generator.

| tier | example | status |
|---|---|---|
| **grounded** | 12 models $95–$163; price at $122; `$163/$122−1 = 31%` upper bound | arithmetic on other people's models |
| **assumption-sensitive** | "the price requires −2.1% revenue CAGR" | correct arithmetic, fragile inputs |
| **judged** | "HEYDUDE stabilisation is ~25% priced in" | LLM allocation, **unvalidated** |

The middle tier deserves its own warning. Crocs' implied CAGR moved **nine
points** across three dates (−0.3%, −9.3%, −1.8%) purely on which year's FCF
margin anchored it, because free cash flow swings with working capital. It is
now normalised on a five-year median, and the reconstructions themselves have
twice called the DCF framing "a red herring" for companies mid-reinvestment —
correctly.

---

## 3. What killed what

Every one of these was a wrong answer that looked right.

| what looked like it worked | what killed it |
|---|---|
| semantic saturation as a gap-finder | word salad scored as a narrative GAP |
| absolute cosine thresholds | a **verbatim quote** from the ticker's own coverage scored OFF_TOPIC |
| max-similarity over claims | order-statistic inflation — max of N grows with N, **three separate times** |
| claim-level corpus check | 6 claims / 639 chars used; **235,342 chars of article body discarded** |
| similarity as the corpus veto | ruled a *school-dress-code* thesis covered by a *sandals* article at 0.75 |
| consensus estimates as an anchor | circular (published ⇒ priced in) **and** historically poisoned |
| the `GAP` verdict itself | asserted absence ⇒ unpriced, which is false |
| implied CAGR as a signal | 188 observations, wrong sign |

### 3.1 The order-statistic bias, three times

`max` and `top-k` over N draws grow with N regardless of meaning. It appeared in
the claim pool, the background chunk pool (3,000 against 600), and the chunk
comparison. Every comparison in `saturation.py` is now size-matched, and
`test_mean_top_is_biased_by_pool_size` pins it — because it is a property of the
statistic, not of the data, and will reappear in any new comparison.

### 3.2 Similarity cannot do entailment

Cosine sees *subject*, not *proposition*. The veto is now: **embeddings retrieve,
a model reads, and a claim of coverage must carry a verbatim quote.** A `COVERED`
whose quote cannot be found is auto-downgraded — without that rule the model
hand-waves "broadly covered" for anything on-topic, which is cosine with extra
steps. Controls pass 6/6 (`entail.py`).

### 3.3 Many-to-many, at three levels

Article facts attach to *articles*; tickers attach many-to-many. Unfiltered:

- a market wrap naming 15 tickers contributes 105 pairwise co-occurrences → every
  peer list collapsed to mega-caps (Crocs' "network" was NVDA, AAPL, MU);
- an article tagged with eight names donates all its claims to all eight → Crocs'
  "narrative" contained the Iran deal and WTI crude;
- an article that merely *mentions* Crocs became evidence about its price drivers
  → a **Columbia Sportswear** strategy piece.

Fixes: `HAVING COUNT(*) <= 4` for claims, `BETWEEN 2 AND 5` for co-occurrence,
and company-in-**title** for case retrieval — with a fallback, because the title
test collapsed Nike from 48 articles to 2.

### 3.4 Do not roll your own graph

The peer finder was written from scratch and iterated through four failed designs
(raw co-occurrence → lift → Poisson excess → share threshold), the best of which
still returned NVDA and AAPL as Crocs' peers. `ticker_relationship_edges` already
held **38,493 typed, directional, evidence-backed edges** and answered it in one
query. This is why `.claude/skills/supabase-schema` and the generated catalog
exist.

---

## 4. Point-in-time traps

Timestamps discipline the data. Three specific traps:

- **Filing lag.** FY2025 describes Dec-2025 and was filed **2026-02-12**. Use
  `fillingDate`, never `date`.
- **Article timestamps.** `published_at` only. `COALESCE(published_at, created_at)`
  lets a backfilled article leak into a past window.
- **Poisoned consensus.** FMP's analyst-estimate rows for *closed* fiscal years
  are converged actuals, not forecasts — measured on CROX at 0.0%, 0.2%, 0.7%,
  1.0% error against reported revenue, where a real year-ahead consensus misses
  by several percent. `consensus()` refuses them.

Also fixed twice: **unadjusted stock splits** in the target feed. Monster's $97.45
target against a $47.79 price is 2.04x — within 2% of exactly 2.0. The test is
proximity to an integer split factor, not an extreme-ratio threshold, and at
distribution level a set that is *entirely* on one side with **zero endorsed** is
refused outright.

---

## 5. Model leakage is heterogeneous — measure it, do not assume it

Timestamps do nothing about a model whose training corpus contains the outcome.
Rather than assume, `leakage.py` asks. Aug-2025 → Aug-2026 window, no data
supplied:

```
CROX  0/5 known   "that fiscal year closed after my reliable knowledge cutoff"
MNST  0/2 known
SBUX  2/3 known   FY2025 revenue ~$37.2bn (correct); the Boyu China JV (correct)
NVDA  2/2 claimed - and WRONG: $65bn guidance / $500bn Blackwell+Rubin
                    against $91bn / $1tn in our corpus
```

Three consequences: admissibility is **per-ticker, not per-window**; **prices leak
far less than fundamentals** (all four disclaimed the stock path), which is
convenient since the outcome variable is what matters; and **confident wrongness
is its own hazard**, so a name that *claims* knowledge is excluded whether or not
the claim is right.

---

## 6. The one negative result

Walk-forward on the arithmetic — 188 observations, 65 tickers, 3 dates, 365-day
horizon, all point-in-time:

```
forward return by implied-CAGR bucket (1 = price requires the MOST decline)

  bucket 1   implied -28.4%..+5.9%    n=47   mean +12.5%   median  -2.3%
  bucket 2   implied  +6.2%..+10.7%   n=47   mean  +9.8%   median  +5.5%
  bucket 3   implied +10.8%..+16.0%   n=47   mean  +7.5%   median  +7.6%
  bucket 4   implied +16.3%..+51.8%   n=47   mean +22.9%   median +11.7%

  most-pessimistic minus least: -10.5%   t = -1.09   rank IC +0.146
```

The hypothesis was that extreme implied pessimism precedes better-than-implied
outcomes. **The medians run monotonically the other way.** Note the trap in
bucket 1: mean +12.5% against a **median of −2.3%**, i.e. a few tail winners —
and CROX (+41%) was one of them. A single striking observation from the losing
bucket was briefly mistaken for the pattern.

Caveats cut both ways: overlapping windows, shared market beta, three dates, one
sector. At t = −1.09 nothing here is distinguishable from noise either.

**What this kills:** implied CAGR as a standalone signal.
**What it does not touch:** the reconstruction as a *description*, which is what
the counterfactuals are measured against.

### 6.1 Tier 2 — the test that bears on the judged layer, and why it failed

Tier 1 tested the vote quantities as signals; they are not, and that was never
the claim. The claim is descriptive, so the test has to be of **accuracy**:

> If a driver is fully priced, news resolving it should move the stock little.
> If it is unpriced, such news should move it a lot. So `priced_in_pct` should
> be NEGATIVELY related to the size of the reaction.

Measured with article timestamps and prices, **no model in the outcome**, each
driver's reaction normalised by that ticker's average reaction across all its
forward articles — company news clusters around earnings, so raw reaction size
otherwise measures "was this near a print".

**Verdict: there is no effect. The result is a parameter artefact.**

```
sensitivity of the clustered correlation (13 tickers, as_of 2026-02-24, 180d fwd)

  n_events  floor_pct  car_days    n   clustered r   negative
      8        75         2        76     -0.015       7/13
      8        75         1        76     -0.114       6/13
      8        75         5        76     +0.070       4/13   <- sign flip
      5        75         2        76     -0.093       7/13
     12        75         2        76     +0.060       5/13   <- sign flip
      8        60         2        80     -0.061       7/13
      8        85         2        64     -0.064       8/13
```

The sign is decided by knobs nobody has a reason to prefer: a one-day event
window gives -0.114, a five-day window +0.070. Independently, the shuffled
placebo (2,000 permutations of `priced_in_pct` within ticker) puts the observed
value at **p = 0.16** — inside the null. And the consensus-inclusive
decomposition variant (n = 92) gives **+0.109**, the opposite sign, on the same
tickers and the same event machinery.

Three results were reported to the user during this work before the bugs were
found, and **all three were artefacts**. That is the finding worth carrying.

### 6.2 The three bugs, each of which produced a believable number

**Driver-to-article matching was matching other companies.** Nike's "gross margin
mean-reversion" driver selected *Is Progress Software (PRGS) Stock Undervalued
Right Now?*, *Cava Group (CAVA) Surpasses Market Returns* and *Why American
Express (AXP) Dipped More Than Broader Market* — zero Nike articles. These are
Zacks-syndicated templates that name the ticker in a list; being generic
valuation prose, they sit close to ANY margin or multiple driver in embedding
space. Price reactions were being computed on **Cava Group's** publication
dates. Fixed with a company-in-title filter plus a template blocklist — and the
fix destroyed the monotone bucket pattern that had made the result look real.

**`car_days` was hard-coded while a sweep appeared to vary it.** The
event-window sensitivity check returned three identical rows and was read as
robustness. It was testing nothing.

**The row limit was on chunks, not articles.** Mega-cap articles are long, so
400 rows was ~27 distinct articles; every driver's selection was the same
handful and each driver's mean |CAR| equalled the baseline exactly. AAPL, AMZN
and TSLA returned **1.000x for every driver** — 20 of 81 observations carrying
no information while still counting toward n.

**Two knobs were doing one job.** A per-driver similarity percentile plus an
event cap: the cap always bound first, so `top_pct` 80 and 88 gave identical
answers and the "relative selection" was inert. Replaced by a fixed event count
by rank above a floor taken from the ticker's whole driver x article similarity
matrix — which adapts to the corpus and lets a driver nothing resembles receive
zero events rather than being force-matched to eight.

### 6.3 Do not scale this

The obvious next move was 40-50 tickers for power. It is the wrong move: it
would multiply a measurement that is sign-unstable under its own parameters,
sits inside its placebo null, and reverses between decomposition variants. Four
hours of generation would produce a more confident-looking version of nothing.

What the exercise bought was not a null result — it never had the power for one
— but working infrastructure and the three bugs above, every one of which would
have silently corrupted the larger run.

**`priced_in_pct` remains unvalidated, now with a failed attempt on the record
rather than an untested claim.** That is a better position than before.

### 6.4 One query shape, three outages

`WHERE <tag/ticker filter> OR EXISTS(...)` joined directly against
`news_article_embeddings` (1.8M rows) timed out in the narrative space, in the
event-test fetch, and in the mega-cap article pull. The fix is the same every
time: resolve ids against `news_articles` (218k rows, indexed on both paths),
then look up chunks by id. Three occurrences make it a pattern rather than an
incident, and it belongs in the schema skill.

---

### 6.5 Tier 3 — forward predictions, locked (open, resolving 2026-12-23)

Tiers 1 and 2 both failed **retrospectively**: the measurement was designed after
the data existed, so every degree of freedom in it could be turned until
something appeared. Tier 3 fixes the claim first, which leaves nothing to tune
and moves the engineering problem from statistics to record-keeping.

Two properties do the work:

* **Locked.** Each prediction is hashed over its full content at creation.
  Editing the probability, the expected move or the date breaks the lock, and
  `predict status` reports the ledger void rather than merely suspect. Pinned by
  a parametrised test that edits each field in turn.
* **Mechanically resolvable or not registrable.** A prediction must name a
  wired resolver (`earnings_beat`, `segment_growth`, `attention_growth`) with a
  complete spec, checked when it is written rather than months later when it
  comes due. This is restrictive on purpose: resolution by post-hoc judgement is
  Tier 2's failure in a new costume. The observables the cases actually want —
  weekly markdown depth, store-level foot traffic — have **no resolver, so those
  predictions cannot be registered at all.** A test we cannot run must not be
  recorded as one we might.

Also enforced: a resolved prediction is never re-resolved (re-running a resolver
until it agrees is the same failure), and `UNRESOLVED` is never scored as a miss.

**Registered 2026-08-25: 65 predictions over 13 tickers, resolving 2026-12-23.**

```
priced_in_pct   5..100, mean 60   cells: 18 unpriced (<=30%) / 32 priced (>=70%)
p_resolves      0.16..0.80, mean 0.53, only 3 at exactly 0.50 (no herding)
resolvers       segment_growth 37, earnings_beat 17, attention_growth 11

KEY CHECK  corr(priced_in_pct, |move_if_true|) = -0.641
```

That last number is what makes the test non-vacuous. The model is genuinely
using the priced-in figure to set expected magnitudes — an unpriced driver is
predicted to move the price substantially more. Had it come back near zero, the
predictions would have been independent of the quantity under test and there
would have been nothing to validate.

**Power, stated before any outcome exists: 100 resolutions, >=30 per cell.**
`score()` returns `UNDERPOWERED` until then and refuses to compute anything below
eight. At 65 registered with 18 in the unpriced cell, this run alone is **not
enough** — it needs roughly one more quarter of registrations, weighted toward
low-priced drivers. Writing the number down now is the point: this programme has
produced four believable numbers that were all artefacts, and a harness
reporting a result at n=20 would be believed.

**What is being scored:**

```
p_resolves       -> Brier, against the base-rate benchmark   tests the investigation
move_if_true     -> correlation with the realised move        tests priced_in_pct
```

Never in absolute. A 75% "beat" call on a 75% base rate scores as no skill, and
there is a test asserting exactly that.

One bug caught on the first registration: the driver was looked up by TEXT, the
model paraphrases the driver when restating it, so the lookup missed silently and
every prediction registered with `priced_in_pct = 0` — the exact quantity the
tier exists to test, zeroed on every row. Now keyed on an explicit index.

---

## 7. What the pipeline now says, and what it cannot

Crocs, decomposed (`decompose.py`):

```
  driver                                  priced   worth   testable
  Multiple re-rating from 10.6x P/E          0%     25%      NO
  Revenue decline is wholesale-to-DTC mix   15%     25%      yes
  Sandals scale $450m through $500m+        20%     10%      yes
  HEYDUDE has troughed                      25%     12%      yes
  Core clog NA demand maturing (BEAR)       30%    -23%      yes
  $100m 2026 cost savings                   80%      8%      NO
  ~10% international carries the group      90%      5%      NO
  HEYDUDE continues to decline             100%      0%      yes
```

The bottom of that table is as much the answer as the top: the price already pays
**in full** for HEYDUDE's decline and **90%** for international merely offsetting
North America. Nothing to find there.

**The binding constraint is not reasoning, it is measurement.** Two companies,
investigated independently, converged on needing the same *kind* of data we do
not have:

- **CROX** → weekly markdown depth and promoted-SKU share on the DTC sites and US
  wholesale doors
- **SBUX** → per-store foot traffic by remodel cohort versus matched control

`tools.py` reports `NOT MEASURABLE` rather than substituting a proxy. A
decomposition that quietly downgraded the test would read as more complete and be
worth less.

And note how the ask has changed. We began wanting alternative data to **discover
trends** — which is what `SOCIAL-ARB-1` died on. We now want it to **settle a
specific, pre-specified, falsifiable question about what is priced in.** That is a
far cheaper and better-targeted purchase.

---

## 7.1 The crux — and the investigation loop that acts on it

The decomposition's most useful field turned out not to be the per-driver
percentages but the **crux**: the single question the published disagreement
reduces to. Tesla is the clean case. Every rejected target is the same variable
at a different date:

| target | robotaxi assumption | worth |
|---|---|---|
| Truist $370 | autonomy revenue lands 2028-2030 | +6% |
| consensus $442-450 | FSD v15 late-2026, wide rollout 2027 | +27-29% |
| UBS/Stifel | autonomy as a software P&L on the fleet | +41-43% |

The whole $370-$500 spread is one-dimensional, and the vote says so from the
other side: **13 targets call it too cheap, 1 agrees, 0 call it too dear.** The
market is below every published target but one — not disagreeing about the
destination, only the date.

That gives the investigation loop (`investigate.py`) something no earlier stage
had: **a question it did not invent.** Every previous attempt asked the model for
an idea and it could not produce one — asked for counterfactuals it returned
twelve, all twelve already written up, because its priors *are* consensus. Here
the question is handed over and the only job is to find out whether the answer
is observable yet.

Four rules, each from a failure recorded above:

- **News is not evidence.** The tool registry excludes it deliberately; coverage
  answers "has someone said it", which `entail.py` already settles.
- **Checks are pre-registered.** Each names its supports-if and undercuts-if
  *before* the tool runs.
- **Refutation is a separate pass with its own context.** It sees the
  measurements and the claim, never the reasoning behind it, and is told not to
  be even-handed.
- **"Cannot settle it" is a first-class verdict**, and the expected one.

### 7.1a It caught the failure mode this whole programme kept hitting

Run on Tesla, the refutation pass moved the probability **0.35 -> 0.17** and
landed this:

> The operator pre-registered that decelerating Services And Other would
> undercut; the data show monotonic deceleration (64.9% -> 60.2% -> 36.6% ->
> 26.6% -> 18.9%), and instead of taking the registered undercut the claim
> declares the check non-diagnostic post hoc. **You do not get to write the
> falsifier, watch it fire, and then relabel the instrument as a proxy.**

That is the exact error behind the Tier-2 artefact — reinterpreting a
measurement after seeing it. The evidence pass committed it; the adversarial
pass caught it. It also supplied a reference class the first pass ignored:
Waymo, with a decade's head start and permits in hand, has reached a handful of
metros, so the same thing inside 24 months is a tail outcome rather than a 35%
one.

Verdict: **not settled by the available data**, P ~ 0.17 at low confidence. The
attention proxies that did move (`Tesla_Cybercab` +47% against its own baseline)
were correctly deflated — "+113 views/day globally" is noise at this scale.

**The number is a prior, not a finding, and is worth nothing unless scored.** It
cannot yet become a Tier-3 prediction: the wired resolvers (`earnings_beat`,
`segment_growth`, `attention_growth`) cannot express "monitor-free paid service
across three metros", and forcing it into `segment_growth` would be the very
substitution the refuter just called out. A dated regulatory-permit or
per-metro-launch resolver is the missing piece.

## 7.2 Published to the quote page — and what was deliberately withheld

The grounded tier now renders on `/quote/<symbol>` (`lib/quote/priced-in.ts`,
`_components/priced-in-panel.tsx`), reading `research_priced_in` where
`published = true`.

**What is shown:** the analyst-target distribution, where the price sits in it,
the endorsed/contested counts, the reconstruction, the crux, and the
assumption-by-assumption breakdown.

**How the judged tier is presented.** The per-driver percentages were initially
withheld — they are unvalidated, and a number printed beside a real share price
reads as analysis regardless of the footnote. On an explicit second request they
were included, but as **ordinal colour bands** (`Unpriced` / `Partly priced` /
`Mostly priced` / `Fully priced`) rather than decimals. Design and honesty
happened to agree: a bare "15%" beside a "70%" invites a precision the reader
cannot act on, and the underlying figure has failed validation twice. The
caveat is on the surface — *"two attempts to validate them have failed and a
third is unresolved until Dec 2026. Read the ordering and the evidence, not the
shade."*

The bands are a **sequential one-hue ramp**, not a red/green diverging scale:
this is magnitude, not polarity — "unpriced" is not good and "fully priced" is
not bad. Steps were validated rather than eyeballed; the first pick failed on
light-end contrast (1.40:1 against a 2:1 floor) and hue spread (43 degrees, not
one hue). Colour is never the only channel — every band carries its word.

### Two bugs the UI work surfaced

**`median_gap` was 0.0 on every row.** It was set only on the split-refusal
early-return path, never on the main one, while the `lean` prose built from the
same quantity read correctly ("12% BELOW the median"). A silently-zero field
next to correct text is worse than an obviously missing one — the panel would
have said "within 0% of the median" for every ticker. Fixed and backfilled.

**Row selection was non-deterministic.** A ticker can hold several published
rows (a point-in-time run and a live one, or two pipeline versions at the same
`as_of`), and ordering on `as_of` alone left same-day rows in arbitrary order —
a stale row could win over the regenerated one. Now tie-broken on `created_at`.

### Generation had to change for a lay audience

The prose was written for a sell-side desk — *"multiple compression to 28-30x"*,
*"de-rate risk"*, *"bounded below the +29% bull ceiling"*. No layout fixes that,
so the fix went into the prompt: the desk shorthand is banned outright, terms are
expanded on first use, and **every number is kept** — it is the vocabulary around
them that changes, not them. The summary is also generated as four structured
parts (`position`, `pays_for`, `declines`, `crux`) rather than one paragraph,
because the model already knows which sentence does which job, and asking beats
parsing.

The share price is written as a `{price}` token and substituted at render time.
A price baked into prose is wrong the day after it is written, and it is the one
figure already displayed accurately elsewhere on the page.

---

## 8. Running it on a schedule, across the whole universe

Everything above was produced by hand on fifteen chosen tickers. Scheduling it
across NYSE + NASDAQ needed four things, and only one of them was pipeline work.

### 8.1 The publish gate, which did not exist

**Nothing in the pipeline ever set `published`.** The fifteen live tickers were
promoted by hand, and the quote pages read `published = true` only. A cron job
dropped on top of the existing code would have written a fresh unpublished row
every week, reported success, and left the pages serving months-old analysis —
a failure with no error and no symptom.

So promotion is now a decision the runner makes, in two parts that fail in
opposite directions:

| question | rule | if it fails |
|---|---|---|
| can it render? | the same floor `lib/quote/priced-in.ts` applies — ≥5 published models, a real spread, drivers, `position` and `crux` | never published |
| did anything move? | a new analyst model, median ≥2%, price ≥10%, or the live row ≥30 days old | held; the previous row stays live |

The second rule is the less obvious one and it matters more. The judged tier is
model output: re-running it on unchanged inputs produces a differently-worded
answer with the same content, and publishing that churns a public page with what
reads as new analysis. **Held rows are still written** — the record of what the
pipeline said that day is kept, it just does not go live.

A boundary bug fell out of testing this: `abs(new/old - 1) >= 0.10` is true for
a +10% move (0.10000000000000031) and false for the identical −10% move
(0.09999999999999987), so the gate published rallies and held crashes. Float
ratios compared against an exact threshold need a tolerance.

### 8.2 The ledger moved to Supabase

`predictions.db` was a local SQLite file declared as the source of truth. That is
fine for one desk and untenable for a scheduled job: the first run on another
machine opens an empty ledger and re-registers predictions that already exist
under a new `made_on` — a retrospective edit wearing a new hash, which is
precisely what Tier 3 exists to prevent.

The move made the record **stricter**, not merely more durable: `research_predictions`
carries a trigger that refuses any change to a sealed field and refuses a second
resolution, where SQLite enforced neither and `predict.py` checked both in
Python. Because the lock is a content hash, the migration was a no-op — all 65
rows re-derived to the same primary key and every one verified against the
remote content.

### 8.3 The universe, and what it costs

The analysis cannot be run on anything you point it at. It needs a spread of
published analyst models — the grounded tier — and news coverage for the corpus
to retrieve against. Eligibility is therefore a real gate, applied in two stages
because they cost different amounts:

| stage | cost | 5,810 -> |
|---|---|---|
| size, price and news coverage, from Supabase | one query | 1,038 candidates |
| ≥5 published targets in 120 days, from FMP | one call each, cached 90 days | **725 eligible** |

**The coverage floor was calibrated wrong first, and the way it failed is the
lesson.** Set at 20 mentions/180 days it excluded CROX — 19 mentions, and the
single ticker every stage of this pipeline was built and debugged against. A
floor that rejects its own development set is measuring the wrong thing. It now
sits at 12.

Lowering it exposed a second bug in the same place: a name marked ineligible by
stage 1 kept that verdict forever, so the 411 newly-admitted names were never
sent for a stage-2 check. The reseed changed nothing, silently. A cached verdict
has to record *which* stage produced it, or a recalibration cannot take effect.

### 8.4 What it costs to run

Routing case reconstruction, decomposition and prediction generation through
Ollama (`glm-5.1:cloud`) rather than a frontier API is what makes full coverage
affordable — four calls per ticker times 725 names is a bill that scales with
exactly the thing scheduling is for.

Measured, not estimated: **~110s per ticker**, so a 7-day refresh cycle is ~105
names a night, about three hours. The prompts, schemas and validation rules are
unchanged; only the transport moved.

On quality — the reconstruction is comparable. Asked the same CROX question,
`glm-5.1:cloud` independently identified the same crux the Opus run did (whether
HEYDUDE's decline is a fixable channel problem or a permanent impairment),
bounded each driver by the published model spread as instructed, and cited the
arithmetic. It adheres slightly less well to the prompt's banned-vocabulary
rules — two violations against Opus's one on the same ticker, so this is a
difference of degree in a gap that was already there, not a new failure.

**What did not move:** `investigate` runs a tool-use loop, Ollama's
`/api/generate` has no tool protocol, and that path stays on Anthropic.

### 8.5 The schedule

`scripts/run_priced_in.sh` wraps three jobs on three cadences, matching the
Mac Mini crontab convention the rest of the project uses:

| job | cadence | cost | what it does |
|---|---|---|---|
| `resolve` | daily | free | settle due predictions; no LLM, and the DB refuses a second resolution |
| `batch` | nightly | ~3h | one bounded, resumable pass over the queue |
| `universe` | weekly | minutes | refresh size/coverage, re-check stale eligibility verdicts |

State lives in `research_priced_in_universe`, not in the process, so a pass
killed at 3am costs the ticker in flight and nothing else.

---

## 9. What to carry into any similar work

- **Presence is a conclusion; absence is a non-answer.** `PRICED_IN` is strong —
  it was published, therefore digested. `NOT_FOUND` proves nothing, because the
  corpus is a sample. Encoding that asymmetry removed a whole class of invented
  edge.
- **A search that runs until something survives a filter will always find
  something.** The counterfactual loop reports `N survived of M attempts` and
  caps its rounds, for the same reason the discovery loop raises its bar with the
  trial count.
- **A question you did not invent is worth more than one you did.** Every attempt
  to make the model produce an original thesis failed, because its priors are
  consensus. The crux — handed over by the arithmetic and the published spread —
  is what finally gave the investigation something to do.
- **Put the adversary in its own context.** A model asked to investigate a claim
  finds support for it. A second pass that sees the measurements and the claim
  but not the reasoning behind it, and is told not to be even-handed, moved
  Tesla from 0.35 to 0.17 and caught a post-hoc reinterpretation the first pass
  had committed.
- **Retrieval that is not selective is reading, not searching.** Crocs' bull and
  bear cases shared 60% of their sources because a top-12 pull over 23 articles
  returns most of the corpus. The apparent driver-matching was happening in the
  reader. It is now reported (`NOT SELECTIVE`) rather than implied by a confident
  source list.
