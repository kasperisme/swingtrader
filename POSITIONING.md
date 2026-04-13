# Market Positioning & Value Proposition

## What This Product Is

News Impact Screener sits at the intersection of **market intelligence**, **alternative data**, and **decision-support tools**. It is not a sentiment tool. It is not a news aggregator.

The core product is an **impact intelligence layer** — a system that takes news, interprets how it ripples through the market's structural dimensions, and tells users what it means for *their* positions and *their* candidates.

---

## The Positioning Sentence

> "See what news actually matters — and whether you're early or late."

---

## The Problem We Solve

Retail investors face three compounding problems:

1. **Too much noise** — Most news is irrelevant to any given portfolio. There is no filtering layer between the firehose and the investor.
2. **No impact translation** — Raw sentiment ("positive/negative") doesn't tell you which stocks benefit, which suffer, or why. The same rate hike is a tailwind for banks and a headwind for growth tech.
3. **Always late** — By the time a narrative is widely visible, institutions have already acted. Retail ends up as exit liquidity.

These are the pain points we are directly solving. Every feature decision should trace back to one of them.

---

## Who We Are For

**Primary:** Retail swing traders who are serious enough to use systematic tools but don't have access to institutional-grade data infrastructure. They read earnings reports, follow macro themes, and trade on multi-week timeframes. They are overwhelmed by information and want a smarter filter.

**Secondary:** Self-directed investors with a portfolio they actively monitor. Not day traders. Not passive indexers. People who make 5–20 meaningful trading decisions per year and want each one to be better informed.

---

## What We Are Not

- We are not a sentiment analytics platform (sentiment is the input, not the product)
- We are not a news aggregator (news is the raw material, not the deliverable)
- We are not a Bloomberg alternative (we are simpler, more opinionated, and built for retail)
- We are not a screener (the screener is one feature, not the identity)

---

## The Competitive Edge

Most tools answer: **"What is happening?"**

Some tools answer: **"Is it positive or negative?"**

We answer: **"Does this matter to my stocks, and am I early or late?"**

That last question is where almost no tool competes well. It requires:

1. Structural understanding of how news propagates through different company types (our 9-dimension scoring system)
2. Company-level sensitivity profiles (our fundamental vectors)
3. Personalization to the user's actual portfolio (our Daily Narrative)

This stack is our moat. It is hard to replicate because it requires all three layers working together.

---

## The Five Core Features (Product Identity)

1. **News Impact Scoring** — Nine-dimensional LLM analysis per article. Not sentiment — structural impact across macro, sector, balance sheet, growth, valuation, geography, market behaviour, and ticker relationships.

2. **Company Sensitivity Vectors** — Fundamental fingerprints per company showing how structurally exposed each stock is to each dimension. When news scores high on "interest rate sensitivity" and a stock scores high on "floating rate debt", the headwind surfaces automatically.

3. **Daily Narrative** — Personalized pre-market briefing per user. Portfolio Watch (positions + sentiment), Screening Updates (candidates + catalysts), Alert Watch (levels + proximity + news context), Market Pulse (macro summary). Delivered in-app or via Telegram.

4. **Stock Screener** — Minervini Trend Template across NYSE + NASDAQ daily. Identifies stocks already in structural uptrends before they break out. Annotation layer for tracking candidates through the research process.

5. **Article Search** — Semantic search over the full article corpus using dense embeddings. Finds articles by meaning, not keywords. Each result is already scored — search leads directly to signal.

---

## Implicit Requirements (What Users Expect Without Asking)

These are table stakes. Failure on any of them breaks trust faster than any feature wins it back:

- **Speed**: Signals must arrive before or during market reaction. A late signal is no signal.
- **Consistency**: Similar events must score similarly. Users need to learn the system's logic.
- **Relevance**: Nothing irrelevant should surface. One noise item degrades trust in all items.
- **Explainability**: Every signal needs a plain-language reason. "Impact: HIGH" with no context is worse than no signal.
- **Source quality**: Users assume the data is real. Low-quality sources corrupt the output.
- **Alert discipline**: If alerts fire too often, they get ignored. High threshold = high trust.
- **Emotional calibration**: Not everything should be "you're late." Balance is essential or users feel helpless.

---

## Market Context

- Sentiment analytics market: ~$5B (2025), growing ~12% CAGR
- Driven by real-time decision making and AI adoption
- Competitive gap: everyone provides data and sentiment; almost nobody provides **impact**, **personalization**, and **timing** together
- The insight layer (interpretation + trust + decision clarity) is where value is shifting as raw sentiment becomes a commodity

---

## What Success Feels Like for the User

> "This saves me time. This makes me smarter. This protects me from being late."

That is the emotional target. Not "this shows me more data." Not "this has better charts." The user should feel like they have a smart assistant watching their portfolio 24/7 — one that only speaks up when it matters.
