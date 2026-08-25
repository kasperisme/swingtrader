"""SOCIAL-ARB-1 — consumer attention leads fundamentals leads price.

The practitioner claim (Camillo, TickerTags) and the academic claim (Da,
Engelberg & Gao, *In Search of Earnings Predictability*) are the same mechanism
described at different levels of rigour, and this thesis tests the version that
has a published effect size attached to it.

The chain, in causal order:

    consumer attention to a PRODUCT rises
        └─▶ the firm's revenue/EPS beats consensus            (L2, the gate)
              └─▶ analysts and the press had not priced it     (L3)
                    └─▶ the stock earns abnormal return        (L4)

L1 sits before all of it and is the cheapest sanity check in the whole
programme: if consumer attention does not *lead* our own news coverage, then the
news pipeline is not downstream of the trend and there is no gap to arbitrage.

Two design decisions are worth stating because they are where this thesis is
most likely to fool us:

* **The product page, not the company page.** Wikipedia pageviews for
  `Apple_Inc.` measure investor and journalist attention — the same crowd the
  price already reflects. Pageviews for a *product* measure consumers. The
  company page is therefore not a second signal, it is L2's placebo: if the
  company page predicts SUE just as well as the product page, we are measuring
  financial-market attention with extra steps and the mechanism is not what the
  thesis says it is.

* **Coverage is the denominator, not the numerator.** Measured on the live
  database, `labubu` appears in exactly one article across 217,709; `crocs` in
  twelve. That is not a gap in the news pipeline, it is a measurement of the lag
  this thesis trades. So the news pipeline enters as L3's *saturation* term —
  the condition under which the effect should be strong — and never as the
  detector.
"""

from __future__ import annotations

from ..thesis import Link, Thesis

SOCIAL_ARB_1 = Thesis(
    id="SOCIAL-ARB-1",
    title="Consumer product attention leads earnings surprise leads price",
    source=(
        "Da, Engelberg & Gao, 'In Search of Earnings Predictability' (product "
        "SVI predicts revenue surprises, SUE and the announcement return); "
        "Camillo / TickerTags social arbitrage; TickerTrends 'Investor "
        "Saturation Score'. Counter-evidence: Cookson et al. (2024) — investor "
        "sentiment effects vanish after one trading day."
    ),
    mechanism=(
        "A consumer trend inflects before it reaches financial statements. "
        "People search, read and talk about a product; they buy it; the firm's "
        "next print beats consensus; the stock reprices. Between the inflection "
        "and the print there is a window in which the change is knowable by "
        "observation but absent from analyst estimates and press coverage. The "
        "thesis is that this window is (a) real, (b) measurable from free public "
        "attention data, and (c) wide enough to pay for trading costs."
    ),
    notes=(
        "Only 16.5 months of news history exists (2025-04-10 onward), so L3 is "
        "power-limited by construction and is expected to return INCONCLUSIVE "
        "rather than HOLDS on the first pass. That is a data problem, not a "
        "result, and the verdict machinery distinguishes them."
    ),
    links=(
        Link(
            id="L1",
            claim=("Consumer attention to a product leads this project's own news "
                   "coverage of the associated ticker."),
            null=("Attention and coverage move together or coverage leads, i.e. the "
                  "press is not downstream of the consumer trend."),
            outcome=("Cross-correlation of daily product pageviews against daily "
                     "ticker article counts, at lags -30..+30 sessions; the lag "
                     "maximising correlation."),
            control=("The same cross-correlation computed on date-shuffled coverage, "
                     "and on the COMPANY page rather than the product page."),
            kill=("Peak cross-correlation occurs at lag <= 0 (coverage leads or is "
                  "contemporaneous), or the peak is indistinguishable from the "
                  "shuffled control."),
            data=("wikipedia_pageviews", "news_article_tickers", "entity_map"),
            cost="free",
            direction=1,
            anchor="Camillo: the press is the exit, not the entry.",
        ),
        Link(
            id="L2",
            claim=("Acceleration in product attention over a quarter predicts that "
                   "quarter's earnings surprise."),
            null=("Product attention carries no information about the surprise; the "
                  "coefficient on attention growth is zero once size, momentum and "
                  "the firm's own surprise history are controlled for."),
            outcome=("Cross-sectional regression / rank IC of pre-announcement "
                     "attention growth on SUE and on the 3-day announcement return."),
            control=("The COMPANY Wikipedia page as placebo (investor attention, not "
                     "consumer demand); attention shuffled within announcement date; "
                     "controls for size, 12-1 momentum and lagged SUE."),
            kill=("|t| below the pre-registered bar on dev (2015-2023), OR the "
                  "company-page placebo fires as strongly as the product page, OR "
                  "the sign flips on the 2024-2026 vault."),
            data=("wikipedia_pageviews", "earnings_surprises", "prices", "entity_map"),
            cost="free",
            direction=1,
            pivotal=True,
            anchor=("Da/Engelberg/Gao: product SVI predicts revenue surprises and SUE, "
                    "and the market does not fully incorporate it."),
        ),
        Link(
            id="L3",
            claim=("The effect is concentrated where investor saturation is low — "
                   "names this project's news pipeline barely covers."),
            null=("The effect is flat in coverage, or stronger in heavily covered "
                  "names, which would mean it is not an information gap."),
            outcome=("L2's effect estimated separately by tercile of trailing "
                     "90-day article count per ticker; the low-minus-high spread."),
            control=("Terciles of market cap rather than coverage — coverage and size "
                     "are heavily confounded and the claim is about coverage."),
            kill=("The low-minus-high coverage spread is zero or negative, i.e. the "
                  "effect does not live in the under-covered names."),
            data=("news_article_tickers", "wikipedia_pageviews", "earnings_surprises"),
            cost="free",
            direction=1,
            anchor="Da/Engelberg: search effects strongest in obscure firms.",
        ),
        Link(
            id="L4",
            claim=("A portfolio formed on product-attention acceleration earns "
                   "abnormal return net of modelled costs over a 21-63 session hold."),
            null=("Gross return is inside the cost band, or the return is explained "
                  "by momentum exposure."),
            outcome=("Purged walk-forward long-short decile spread, costs at the lab's "
                     "standard 13bp per side, alpha t-stat against SPY and a momentum "
                     "control."),
            control=("The same portfolio formed on the company page; and a matched "
                     "random-attention book with identical turnover."),
            kill=("Net Sharpe below the lab gate, OR alpha t-stat < 1.5 against the "
                  "momentum control, OR the effect is inside the cost band."),
            data=("wikipedia_pageviews", "prices", "entity_map"),
            cost="free",
            direction=1,
        ),
        Link(
            id="L5",
            claim=("Requiring two or more INDEPENDENT attention sources to agree "
                   "improves the signal over any single source."),
            null=("Convergence adds nothing — the sources are one factor measured "
                  "several ways, and their correlation is high enough that agreement "
                  "is mechanical."),
            outcome=("L2's effect for single-source vs 2-of-3 agreement signals; and "
                     "the pairwise correlation of the source panels themselves."),
            control=("Two random halves of the SAME source, which must not show the "
                     "convergence benefit if the benefit is real."),
            kill=("The 2-of-3 signal does not beat the best single source, or the "
                  "same-source split shows an equal 'benefit' (mechanical, not real)."),
            data=("wikipedia_pageviews", "google_trends", "reddit_mentions", "entity_map"),
            cost="cheap",
            direction=0,
            anchor="TickerTrends 'data convergence' requirement — untested as stated.",
        ),
    ),
)
