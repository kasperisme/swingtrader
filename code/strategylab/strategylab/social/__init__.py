"""Social-arbitrage research: the priced-in baseline and counterfactuals against it.

**Governing assumption of this package: if it is in our news database, it is
priced in.**

That is not a limitation being worked around, it is the design. By the time a
proposition has been published, scored and indexed, the market has had it. No
amount of searching the corpus produces edge, and the first version of this
package — which ranked theses by embedding distance from journalism and called
the far ones "gaps" — was wrong in a way that produced confident, plausible,
useless output.

What the corpus IS good for is establishing the **baseline**: the set of
propositions the current price already reflects. That matters because you cannot
say what would change a price without first saying precisely what it contains.
The pipeline therefore runs in that order:

    narrative.py   what is being said                      (the corpus)
    implied.py     what the price REQUIRES                 (reverse DCF)
    generate.py    priced_in()  -> the reconstructed baseline
                   generate()   -> COUNTERFACTUALS against named assumptions
    saturation.py  has the press already said this?        (one-way check)

The counterfactual is the unit of work: pick one assumption embedded in the
price, say what would have to be fundamentally different for it to be wrong, and
name an observable — **outside the news** — that would move first if it were
already breaking. News-confirmable theses are unfalsifiable in advance under the
governing assumption, so the observable is the whole point.

Two asymmetries carried throughout, because getting either backwards invents
edge that is not there:

* ``PRICED_IN`` from `saturation.py` is a conclusion. ``NOT_FOUND`` is a
  non-answer — the corpus is a sample of the press, so absence proves nothing.
* The ranking is arithmetic, not semantic. A counterfactual states the
  consolidated revenue CAGR it implies and that is compared against what the
  price requires. When the embedding score and the arithmetic disagreed, the
  arithmetic was right.

Nothing here is validated. This package generates well-formed, quantified,
falsifiable counterfactuals; it does not provide evidence that any of them are
true. That is what the observables and forward scoring are for.
"""
from .business import BusinessProfile, BusinessStore
from .entity import Entity, EntityStore
from .implied import ImpliedExpectations, implied
from .narrative import Narrative, narrative, network
from .pageviews import PageviewStore, attention_growth
from .saturation import NarrativeSpace, SaturationScore

__all__ = ["Entity", "EntityStore", "PageviewStore", "attention_growth",
           "BusinessProfile", "BusinessStore", "ImpliedExpectations", "implied",
           "Narrative", "narrative", "network", "NarrativeSpace", "SaturationScore"]
