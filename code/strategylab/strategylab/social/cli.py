"""SOCIAL-ARB-1 CLI.

    python -m strategylab.social.cli entities  [--limit N]   # build the dictionary
    python -m strategylab.social.cli pageviews                # pull the attention data
    python -m strategylab.social.cli l2        [--top-k 10]   # run the pivotal link

`l2` is the gate. It cleans the entity map, builds one row per (ticker,
announcement) with a strictly pre-announcement signal, runs the test against its
placebos, and writes the result to the thesis registry — which is append-only,
so a second run is a second arm and raises the exploratory bar rather than
overwriting the first.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import OUTPUT_ROOT, load_env
from ..data.prices import PriceStore
from ..thesis.cli import DB, DISCOVER_DB
from ..thesis.registry import ThesisRegistry
from ..thesis.theses import SOCIAL_ARB_1
from . import batch, universe
from .entity import EntityStore
from .pageviews import PageviewStore
from .study import (L2Spec, add_announcement_return, build_events,
                    l2_attention_predicts_surprise, load_surprises)

log = logging.getLogger(__name__)

UNIVERSE = OUTPUT_ROOT / "cache" / "meta" / "consumer_universe.json"


def _universe() -> list[str]:
    if not UNIVERSE.exists():
        raise SystemExit(f"no universe at {UNIVERSE}; run `entities` first")
    return [r["symbol"] for r in json.loads(UNIVERSE.read_text())]


def clean_map(tickers: list[str], es: EntityStore, pv: PageviewStore,
              top_k: int = 10) -> tuple[dict, dict]:
    """Drop what cannot carry firm-specific information, then keep the biggest.

    Three filters, each closing a specific hole found in the first real run:

    * **Shared pages.** An article claimed by two tickers in the same universe
      (`Consumer_electronics`, `Truck`) measures a category. It would correlate
      with sector returns and read as signal.
    * **Unusable series.** Fewer than 730 daily observations cannot support a
      study starting in 2015, and a page averaging under 30 views a day is
      integer noise that the growth ratio amplifies rather than smooths.
    * **The long tail.** One carmaker contributed 709 articles, almost all
      discontinued models with flat traffic. Summing them buries a live brand's
      inflection under hundreds of dead pages, so only the `top_k` by median
      views are kept. `top_k` is a researcher degree of freedom and is recorded
      in the registry with the result.
    """
    owners: dict[str, int] = {}
    for t in tickers:
        for e in es.load(t):
            if e.kind == "product":
                owners[e.article] = owners.get(e.article, 0) + 1
    shared = {a for a, n in owners.items() if n > 1}

    out, stats = {}, {"shared_dropped": 0, "unusable_dropped": 0,
                      "tail_dropped": 0, "kept_products": 0, "kept_company": 0,
                      "shared_pages": len(shared)}
    for t in tickers:
        prods, comps = [], []
        for e in es.load(t):
            if e.kind == "company":
                if pv.probe(e.article).get("usable"):
                    comps.append(e)
                continue
            if e.article in shared:
                stats["shared_dropped"] += 1
                continue
            pr = pv.probe(e.article)
            if not pr.get("usable"):
                stats["unusable_dropped"] += 1
                continue
            prods.append((pr["median"], e))
        prods.sort(key=lambda x: -x[0])
        stats["tail_dropped"] += max(0, len(prods) - top_k)
        keep = [e for _, e in prods[:top_k]]
        if keep:
            out[t] = keep + comps
            stats["kept_products"] += len(keep)
            stats["kept_company"] += len(comps)
    return out, stats


def cmd_entities(args) -> int:
    load_env()
    from ..data.universe import UniverseBuilder
    from ..flow.universe import listing_metadata

    CONSUMER = {"Consumer Cyclical", "Consumer Defensive"}
    EXTRA = {"Restaurants", "Internet Retail", "Specialty Retail", "Apparel Retail",
             "Footwear & Accessories", "Leisure", "Travel Services", "Lodging",
             "Beverages - Non-Alcoholic", "Beverages - Brewers", "Packaged Foods",
             "Household & Personal Products", "Electronic Gaming & Multimedia",
             "Consumer Electronics", "Auto Manufacturers", "Resorts & Casinos"}
    meta = listing_metadata()
    rows = UniverseBuilder().membership("liquid_mid_large", include_delisted=False)
    sel = []
    for r in rows:
        m = meta.get(r["symbol"]) or {}
        if m.get("sector") in CONSUMER or m.get("industry") in EXTRA:
            sel.append({"symbol": r["symbol"], "sector": m.get("sector"),
                        "industry": m.get("industry"), "name": m.get("companyName"),
                        "dv": float(r.get("price") or 0) * float(r.get("volume") or 0)})
    sel.sort(key=lambda x: -x["dv"])
    sel = sel[:args.limit]
    UNIVERSE.parent.mkdir(parents=True, exist_ok=True)
    UNIVERSE.write_text(json.dumps(sel, indent=1))
    print(f"universe: {len(sel)} consumer-facing liquid names "
          f"(selected on SECTOR + LIQUIDITY only — never on a remembered trend)")
    print(json.dumps(EntityStore().ensure([s["symbol"] for s in sel]), indent=1))
    return 0


def cmd_pageviews(args) -> int:
    load_env()
    es, tickers = EntityStore(), _universe()
    arts = sorted({e.article for t in tickers for e in es.load(t)})
    print(f"pulling {len(arts)} articles")
    print(json.dumps(PageviewStore().ensure(arts, workers=args.workers), indent=1))
    return 0


def cmd_l2(args) -> int:
    load_env()
    tickers = _universe()
    es, pv = EntityStore(), PageviewStore()
    spec = L2Spec()

    ents, cstats = clean_map(tickers, es, pv, top_k=args.top_k)
    print("\n--- entity map after cleaning ---")
    for k, v in cstats.items():
        print(f"   {k:<20} {v}")
    print(f"   {'tickers usable':<20} {len(ents)} / {len(tickers)}")
    if not ents:
        raise SystemExit("no usable tickers — run `pageviews` first")

    sur = load_surprises(list(ents))
    print(f"\nsurprises: {len(sur)} announcements over {sur.ticker.nunique()} tickers "
          f"({sur.date.min().date()} .. {sur.date.max().date()})")

    panel = PriceStore().build_panel(sorted(ents), "2014-01-01", spec.vault_start
                                     and "2026-06-30", min_rows=200)
    ev = build_events(ents, sur, pv, spec)
    ev = add_announcement_return(ev, panel, spec)
    print(f"events with a usable pre-announcement signal: {len(ev)} "
          f"over {ev.ticker.nunique() if len(ev) else 0} tickers")

    reg = ThesisRegistry(DB)
    reg.register(SOCIAL_ARB_1)
    link = next(l for l in SOCIAL_ARB_1.links if l.id == "L2")
    arms = reg.arms_run(SOCIAL_ARB_1.id)
    res = l2_attention_predicts_surprise(link, ev, spec, arms)
    res.detail["clean_stats"] = cstats
    res.detail["top_k"] = args.top_k
    reg.record(SOCIAL_ARB_1.id, res, arm=f"top_k={args.top_k}")

    print("\n" + "=" * 74)
    print(f"L2 — {link.claim}")
    print("=" * 74)
    print(f"  verdict        {res.verdict}")
    print(f"  effect         {res.effect:+.4f}   t {res.t_stat:+.2f}   "
          f"bar |t|>{res.bar:.2f}")
    print(f"  n (dev)        {res.n_obs}  over {res.detail.get('clusters', 0)} monthly clusters")
    print(f"  company placebo t {res.placebo_t:+.2f}   (must NOT match the product page)")
    print(f"  shuffle 95th pct  {res.detail.get("shuffle_t", float("nan")):.2f}   perm p {res.detail.get("perm_p_value", float("nan")):.3f}")
    print(f"  vault          effect {res.vault_effect:+.4f}  t {res.vault_t:+.2f} "
          f"(n={res.detail.get('n_vault', 0)})")
    print(f"  announcement return t {res.detail.get("announcement_return_t", float("nan")):+.2f}  (corroboration, not a kill criterion)")
    print(f"  note           {res.note}")
    verdict, reason = SOCIAL_ARB_1.verdict(reg.results(SOCIAL_ARB_1.id))
    lab = reg.lab_trials(DISCOVER_DB)
    print(f"\n  THESIS         {verdict} — {reason}")
    print(f"  lab-wide measurements: {lab['total']}")
    print("=" * 74 + "\n")
    if len(ev):
        ev.to_csv(OUTPUT_ROOT / "social_arb_l2_events.csv", index=False)
    return 0


# The probes the saturation metric must get right before any of its scores are
# believed. Two are HARD — a claim lifted from the ticker's own coverage must
# read as priced in, and off-topic or incoherent text must not read as a gap.
# The soft ones are informative but not pass/fail.
CONTROL_PROBES = [
    ("POSITIVE  verbatim claim", None, "PRICED_IN", True),
    ("POSITIVE  reworded claim", "__REWORD__", "PRICED_IN", True),
    ("NEGATIVE  other industry",
     "Semiconductor foundry capacity constraints are limiting AI accelerator supply",
     "OFF_TOPIC", True),
    ("INCOHERENT word salad",
     "The purple velocity of quarterly umbrella synergy accelerates the lunar tessellation",
     "OFF_TOPIC", True),
    ("GENERIC on-topic",
     "{T} will benefit from international expansion and margin improvement",
     "PRICED_IN", False),
]


def _as_thesis(claim: str, ticker: str) -> str:
    """Put an extracted claim into the form a GENERATED thesis takes.

    The metric gates on whether a thesis names its subject, which Stage 2 is
    required to do. Claims lifted from articles frequently do not — "Revenue in
    Greater China declined 30%" is unmistakably about Nike inside a Nike
    article and unmistakably about nobody outside one. Scoring such a claim
    as-is tests the metric on an input shape it will never receive, and it duly
    failed for NKE and SBUX while passing for CROX and MNST purely on whether
    the extracted sentence happened to include the name.

    Prefixing the ticker aligns the probe with the contract. It is not a
    weakening of the control: the assertion, which is what saturation measures,
    is untouched.
    """
    return claim if ticker.lower() in claim.lower() else f"{ticker}: {claim}"


def _reword(claim: str) -> str:
    """Degrade a real claim into a looser restatement of the same proposition.

    A hand-written paraphrase is not a control, it is a second opinion about
    what the claim means. The first version of this probe read "{TICKER}'s
    weakest brand is struggling and management is prioritising a turnaround" —
    which never names HEYDUDE, is materially vaguer than the claim it stands in
    for, and duly failed. Deriving the probe from the claim itself removes the
    author from the loop and turns the control into a real question: how much
    rewording can this metric survive before it loses a proposition it has
    definitely seen?

    The degradation is mechanical — drop the figures and the dates, keep the
    subject and the assertion.
    """
    out = re.sub(r"\d[\d,.]*\s*(%|percent|bn|billion|million|m\b)?", "", claim)
    out = re.sub(r"\b(20\d\d|Q[1-4])\b", "", out)
    out = re.sub(r"\s{2,}", " ", out).strip(" ,.;–—-")
    return out or claim


def cmd_control(args) -> int:
    """Calibrate the saturation metric and verify it on known-answer probes.

    Run this before trusting any GAP verdict, and again after changing the
    embedding model or the corpus window. The first two versions of this metric
    each passed casual inspection and each failed here: one reported literal
    word salad as a narrative gap, the next reported a verbatim quote from the
    ticker's own coverage as off-topic.
    """
    load_env()
    from .narrative import narrative
    from .saturation import NarrativeSpace

    T = args.ticker.upper()
    n = narrative(T, lookback_days=args.lookback)
    own = [c.text for c in n.claims if c.ticker == T]
    if not own:
        print(f"{T}: no claims about the ticker itself — cannot run the positive "
              f"control. Coverage is too thin for the metric to be calibrated here.")
        return 2

    # The verbatim probe must be a claim that is actually IN the corpus being
    # searched. `own[0]` is the ticker's highest-weighted claim, but
    # `corpus(N)` is the top N across the ticker AND its peers — for a
    # well-covered name the two diverge, and SBUX's "verbatim" probe scored a
    # raw similarity of 0.60 because the claim was never in the corpus at all.
    # A positive control that is not actually positive tests nothing.
    corpus = n.corpus(args.claims)
    in_corpus = set(corpus)
    own = [c for c in own if c in in_corpus] or own
    # Entities that make a thesis unambiguously about this company.
    from .entity import EntityStore
    ents = [T, (n.network.get("owns") or [])] and [T]
    ents += [e.article.replace("_", " ") for e in EntityStore().load(T)]
    ents += list(n.network.get("owns") or [])
    space = NarrativeSpace(T, corpus, lookback_days=args.lookback, entities=ents)
    print(f"  entities gating topicality: {sorted(set(e for e in ents))[:8]}")
    cal = space.calibrate(n_null=args.null)
    print(f"\n{T} — corpus {cal['n_chunks']} chunks, {cal['n_claims']} claims "
          f"({len(own)} about {T} itself), null n={cal['n_null']}")
    print(f"  topicality bar {cal['topicality_bar']:+.4f} "
          f"(null median {cal['topicality_null_median']:+.4f})")
    print(f"  saturation bar {cal['saturation_bar']:+.4f} "
          f"(null median {cal['saturation_null_median']:+.4f})")

    print(f"\n{'probe':<28}{'topical':>9}{'satur':>9}{'raw':>7}  {'verdict':<11}expected")
    print("-" * 84)
    hard_ok = True
    for label, tmpl, expect, hard in CONTROL_PROBES:
        if tmpl is None:
            text = _as_thesis(own[0], T)
        elif tmpl == "__REWORD__":
            text = _as_thesis(_reword(own[0]), T)
        else:
            text = tmpl.format(T=T)
        r = space.score(text)
        ok = r.verdict == expect
        if hard and not ok:
            hard_ok = False
        print(f"{label:<28}{r.topicality:+9.3f}{r.saturation:+9.3f}"
              f"{r.saturation_raw:7.2f}  {r.verdict:<11}{expect}"
              f"{'' if ok else '   <-- MISS'}{'  [hard]' if hard else ''}")

    print(f"\nHARD CONTROLS {'PASS' if hard_ok else 'FAIL'}")
    if not hard_ok:
        print("Do NOT trust GAP verdicts from this configuration.")
    print(f"\ncorpus: {getattr(space, 'n_articles', 0)} articles "
          f"({len(space.chunks)} usable body chunks after boilerplate removal), "
          f"{len(own_all)} extracted claims about {T}")
    if len(space.chunks) < 120:
        print(f"NOTE: thin body corpus. PRICED_IN stays reliable, but absence from "
              f"{len(space.chunks)} chunks says very little.")
    return 0 if hard_ok else 1


# The pipeline moved to `batch.py` so the scheduled pass and the interactive
# command cannot drift. `_entities_for` went with it; imported here for
# `cmd_theses`, which is the deprecated generation path.
from .batch import _entities_for                              # noqa: E402


def cmd_theses(args) -> int:
    """The narrative pipeline end to end for one ticker.

    narrative (the null) -> business profile -> BLIND generation -> difference.

    The order matters and is enforced by the code path: the generator is handed
    `BusinessProfile.brief()` and never the narrative, so a thesis cannot be a
    paraphrase of the coverage it is about to be scored against.
    """
    load_env()
    from .business import BusinessStore
    from .entity import EntityStore
    from .generate import generate, priced_in
    from .implied import implied
    from .narrative import narrative
    from .saturation import NarrativeSpace

    T = args.ticker.upper()
    n = narrative(T, lookback_days=args.lookback)
    ents = _entities_for(T, n.network)
    brands = [e.label for e in EntityStore().load(T) if e.kind == "product"]
    bp = BusinessStore().ensure(T, brands + list(n.network.get("owns") or []))

    print("=" * 78)
    print(bp.brief())
    print("=" * 78)
    print(f"\nNULL: {n.article_count} articles on {T}, {len(n.claims)} claims "
          f"({sum(1 for c in n.claims if c.ticker == T)} about {T} itself)")
    for c in [c for c in n.claims if c.ticker == T][:5]:
        print(f"   [{c.impact:+.2f}] {c.text[:112]}")

    # THE NULL, in two layers. The press tells you what has been MENTIONED; the
    # price tells you what has been ASSUMED, and only the second is a magnitude
    # a thesis can beat. Reconstructing the price first also reframes the whole
    # exercise: Crocs' coverage reads as mildly constructive while the price
    # requires a decade of shrinkage, and a thesis has to clear the price.
    imp = implied(T)
    print("\n" + imp.brief())

    # The sell-side ARGUMENT — target dispersion and what analysts pressed
    # management on. Not the consensus number, which is inert the day it prints.
    from .analyst import build as analyst_build
    av = analyst_build(T)
    if av.targets or av.questions:
        print("\n" + av.brief())

    corpus = n.corpus(args.claims)
    own_claims = [c.text for c in sorted(n.claims, key=lambda c: -c.weight)
                  if c.ticker == T]
    pin = priced_in(bp, imp.brief(), own_claims + corpus[:25],
                    analyst_brief=(av.brief() if (av.targets or av.questions) else ""),
                    effort=args.effort)
    if pin:
        print("\n" + pin.brief())
        # The priced-in assumptions are deliberately NOT added to the corpus the
        # counterfactuals are scored against. They were, briefly, and it made the
        # check circular: a counterfactual is built to contradict a named
        # assumption, so it quotes it, so it matched — and all four came back
        # "in corpus => priced in" when what they had actually matched was the
        # target they were aimed at. The corpus check answers only "has the PRESS
        # said this", which under the governing assumption is the same as "is
        # this already in the price".
    space = NarrativeSpace(T, corpus, lookback_days=args.lookback, entities=ents,
                           own_claims=own_claims)
    cal = space.calibrate(n_null=args.null)
    print(f"\ncalibrated: saturation bar {cal['saturation_bar']:+.4f} "
          f"(null median {cal['saturation_null_median']:+.4f}), "
          f"{cal['n_chunks']} chunks, {len(own_claims)} OWN claims, "
          f"{len(space.peer_claims)} peer claims")

    print(f"\nsearching for counterfactuals the corpus does NOT already contain "
          f"(up to {args.rounds} rounds x {args.n})...")
    from .generate import iterate_until_novel
    res = iterate_until_novel(bp, ents, space, n_per_round=args.n,
                              max_rounds=args.rounds, want=args.want,
                              effort=args.effort)
    rows, priced, attempts = res["survivors"], res["rejected"], res["attempts"]
    req = imp.implied_revenue_cagr      # what the price requires; the benchmark

    print("\n" + "=" * 78)
    print("COUNTERFACTUALS")
    print("=" * 78)
    if priced:
        print(f"\n{len(priced)} REJECTED — already written up, so priced in:")
        for t_, r_ in priced:
            e = getattr(t_, "entailment", None)
            print(f"   [{t_.id}] {t_.statement[:92]}")
            if e is not None and e.quote:
                print(f"        in \"{e.source_title[:64]}\":")
                print(f"        \"{e.quote[:150]}\"")

    if not rows:
        print(f"\nNOTHING SURVIVED after {attempts} attempts over {res['rounds']} "
              f"rounds. Every angle this generator can reach on {T} is already in "
              f"the corpus. That is a real answer, not a failure: it says the "
              f"visible narrative is saturated and any edge here is not reachable "
              f"from what a language model knows about the business.")
    else:
        rows.sort(key=lambda x: -(x[0].consolidated_revenue_cagr_if_true
                                  - (req if req is not None else 0.0)))
        # Tier by how close the survivor came to matching. On a densely covered
        # name, matching NOTHING is more often a sign of vagueness than of
        # originality — the corpus is thick, so a genuinely specific claim about
        # this company should still land in its neighbourhood.
        for t_, r_ in rows:
            gap = ((t_.consolidated_revenue_cagr_if_true - req)
                   if req is not None else None)
            e = getattr(t_, "entailment", None)
            ev = e.verdict if e is not None else "?"
            tier = (f"{ev}; closest coverage {r_.saturation_raw:.2f}"
                    + ("" if r_.saturation_raw >= 0.60
                       else "  WEAK — near nothing; check it is not merely vague"))
            print(f"\n>> [{t_.id}] thesis CAGR "
                  f"{t_.consolidated_revenue_cagr_if_true:+.1%} vs price {req:+.1%}"
                  + (f" => gap {gap:+.1%}" if gap is not None else ""))
            print(f"   corpus     : {tier} (closest {r_.saturation_raw:.2f})")
            print(f"   breaks     : {t_.targets_assumption[:150]}")
            print(f"   {t_.statement}")
            print(f"   observable : {t_.observable[:150]}  [{t_.data_source}]")
            print(f"   falsifier  : {t_.falsifier[:140]}")
            if r_.nearest_claims and r_.nearest_claims[0].title:
                print(f"   closest    : \"{r_.nearest_claims[0].title[:70]}\"")

    print("\n" + "-" * 78)
    print(f"SEARCH: {len(rows)} survived of {attempts} attempts over "
          f"{res['rounds']} rounds.")
    if attempts:
        print(f"Read that ratio before reading any survivor. Generating until "
              f"something clears a filter is how false positives are made; "
              f"{len(rows)}/{attempts} is the number that says how hard this had "
              f"to be searched for.")
    print("The corpus is the BASELINE, not a source of edge. Survivors are "
          "UNPROVEN — each still needs its observable tested against data that "
          "is not news.")

    out = OUTPUT_ROOT / "social" / T
    out.mkdir(parents=True, exist_ok=True)
    (out / "theses.json").write_text(json.dumps(
        {"implied": imp.to_dict(),
         "priced_in": pin.to_dict() if pin else None,
         "search": {"attempts": attempts, "rounds": res["rounds"],
                    "survived": len(rows)},
         "rejected": [{"thesis": a.to_dict(), "score": b.to_dict()}
                      for a, b in priced],
         "theses": [{"thesis": a.to_dict(), "score": b.to_dict()}
                    for a, b in rows]},
        indent=1, default=str))
    print(f"\nwrote {out / 'theses.json'}")
    return 0


def _as_of(args):
    """Parse --as-of, and say plainly what a past date can and cannot control.

    Data becomes point-in-time; the MODEL does not. Everything the generator
    writes at a past date may already contain the outcome, which is why
    `leakage.py` gates per ticker rather than per window.
    """
    from datetime import date as _date
    if not getattr(args, "as_of", None):
        return None
    d = _date.fromisoformat(args.as_of)
    print(f"\n{'!' * 78}")
    print(f"AS OF {d} — data is point-in-time (filing dates, publishedDate, "
          f"published_at).\nGENERATION IS NOT: the model's training corpus may "
          f"contain this window's outcome.\nRun `leakage` for this ticker before "
          f"treating any generated text as a forecast.")
    print("!" * 78)
    return d


def cmd_cases(args) -> int:
    """The price-as-vote pipeline: whose model is the market declining to pay?

    Replaces LLM-invented counterfactuals with published ones. The generator
    could not be original — its priors ARE consensus, which is why 12/12 of its
    theses turned out to be already written up. Rejected analyst models do not
    have that problem: each is a real model, by someone paid to hold it, that
    the market has seen and declined.

    The pipeline itself now lives in `batch.reconstruct`, so this command and
    the scheduled pass run the same code. What stays here is the printing.
    """
    load_env()
    from .batch import reconstruct

    T = args.ticker.upper()
    payload = reconstruct(T, lookback=args.lookback, claims=args.claims,
                          top=args.top, passages=args.passages,
                          effort=args.effort, as_of=_as_of(args), emit=print)
    if not (payload.get("cases") or payload.get("decomposition")):
        return 0

    out = OUTPUT_ROOT / "social" / T
    out.mkdir(parents=True, exist_ok=True)
    (out / "cases.json").write_text(json.dumps(payload, indent=1, default=str))
    print("\nEach case is KNOWN (published) and NOT BELIEVED (the price declines "
          "it). The decomposition bounds what each unpriced driver is worth using "
          "the published model spread — it does not claim any of them will happen.")
    print(f"\nwrote {out / 'cases.json'}")
    return 0


def cmd_predict(args) -> int:
    """Register locked forward predictions from a ticker's decomposition.

    The ledger is Supabase (`swingtrader.research_predictions`), not the local
    SQLite file. A scheduled pass is not tied to the machine that started it,
    and a ledger that only exists on one desk re-registers everything the first
    time it runs anywhere else.
    """
    load_env()
    from datetime import date as _date, timedelta as _td

    from .business import BusinessStore
    from .implied import fetch_financials
    from .ledger import SupabaseLedger, resolve_due
    from .predict import predictions_from_decomposition, score

    led = SupabaseLedger()
    ok, why = led.ready()
    if not ok:
        print(f"ledger unavailable: {why}")
        return 2

    if args.action == "status":
        s = led.summary()
        print(json.dumps(s, indent=1))
        if s["tampered"]:
            print("\n!! LEDGER VOID — locks do not match content: "
                  f"{s['tampered']}")
        print("\n" + json.dumps(score(led), indent=1, default=str))
        return 1 if s["tampered"] else 0

    if args.action == "migrate":
        path = OUTPUT_ROOT / "runs" / "predictions.db"
        res = led.migrate_from_sqlite(path, dry_run=not args.go)
        print(json.dumps(res, indent=1))
        if res.get("void_skipped"):
            print("\n!! rows whose LOCAL content fails its own lock were NOT "
                  "imported. A void row does not become sound by changing "
                  "stores.")
        if not args.go:
            print("\ndry run — pass --go to write.")
        return 0

    if args.action == "resolve":
        rows = resolve_due(led)
        print(f"{len(rows)} prediction(s) due")
        for r in rows:
            print(f"  {r['ticker']:<6} {r['status']:<11} "
                  f"{(r.get('driver') or '')[:54]}")
            print(f"         {json.dumps(r['detail'], default=str)[:110]}")
        print("\n" + json.dumps(score(led), indent=1, default=str))
        return 0

    # register
    T = args.ticker.upper()
    src = OUTPUT_ROOT / "social" / T / "cases.json"
    alt = OUTPUT_ROOT / "tier2b" / f"{T}.json"
    path = src if src.exists() else alt
    if not path.exists():
        print(f"no decomposition for {T}; run `cases {T}` first")
        return 2
    dec = json.loads(path.read_text()).get("decomposition")
    if not dec:
        print(f"{T}: file has no decomposition")
        return 2
    fin = fetch_financials(T)
    if not fin.price:
        print(f"{T}: no current price")
        return 2
    on = _date.today() + _td(days=args.horizon)
    bp = BusinessStore().load(T)
    preds = predictions_from_decomposition(
        T, dec["drivers"], fin.price, on,
        business_brief=(bp.brief() if bp else ""), effort=args.effort)
    if not preds:
        print(f"{T}: no registrable predictions. This is a normal outcome — "
              f"most drivers name observables no wired resolver can settle.")
        return 0
    print(f"{T} @ ${fin.price:,.2f} — registering {len(preds)} of "
          f"{len(dec['drivers'])} drivers, resolving {on}\n")
    for p in preds:
        lock = led.register(p)
        print(f"  [{lock[:12]}] {p.resolver:<18} p={p.p_resolves:.2f}  "
              f"move T/F {p.move_if_true:+.1%}/{p.move_if_false:+.1%}  "
              f"({p.priced_in_pct:.0f}% priced)")
        print(f"      {p.driver[:88]}")
        print(f"      spec {json.dumps(p.spec)}")
    print(f"\nSealed. Editing any of these breaks its lock; `predict status` "
          f"reports it.")
    return 0


def cmd_persist(args) -> int:
    """Mirror decompositions and the sealed prediction ledger to Supabase."""
    load_env()
    import glob

    from .persist import PricedInPublisher

    pub = PricedInPublisher()
    ok, why = pub.ready()
    if not ok:
        print(f"not ready: {why}")
        return 2

    if args.action == "verify":
        print(json.dumps(pub.verify_locks(), indent=1))
        return 0

    ids = {}
    sources = sorted(glob.glob(str(OUTPUT_ROOT / "tier2b" / "*.json"))) + \
        sorted(glob.glob(str(OUTPUT_ROOT / "social" / "*" / "cases.json")))
    for f in sources:
        payload = json.loads(Path(f).read_text())
        T = (Path(f).stem if "tier2b" in f else Path(f).parent.name).upper()
        try:
            new_id = pub.publish_decomposition(payload, T, model=args.model)
        except Exception as exc:                              # noqa: BLE001
            print(f"  {T}: failed — {str(exc).splitlines()[0][:100]}")
            continue
        if new_id:
            ids[T] = new_id
            n = len((payload.get("decomposition") or {}).get("drivers") or [])
            print(f"  {T:<6} decomposition #{new_id} ({n} drivers)")

    print(json.dumps(pub.verify_locks(), indent=1))
    print("\nDecompositions are written unpublished. `batch` is what promotes "
          "one, and only when it is valid AND something it is about moved; "
          "predictions are written straight to the Supabase ledger at "
          "registration and are never promoted here.")
    return 0


def cmd_universe(args) -> int:
    """Build and inspect the NYSE + NASDAQ working universe.

    Two stages, separated because they cost different amounts: `seed` is one
    Supabase query over tables that already exist, `check` is one FMP call per
    candidate and is therefore bounded and cached.
    """
    load_env()
    from .persist import PricedInPublisher
    from . import universe as U

    pub = PricedInPublisher()
    ok, why = pub.ready()
    if not ok:
        print(f"not ready: {why}")
        return 2

    if args.action == "seed":
        print(json.dumps(U.seed(pub, min_market_cap=args.min_market_cap,
                                min_price=args.min_price,
                                min_mentions=args.min_mentions), indent=1))
        print(json.dumps(U.stats(pub), indent=1))
        return 0

    if args.action == "check":
        syms = [t.strip().upper() for t in (args.tickers or "").split(",")
                if t.strip()]
        print(json.dumps(U.check_eligibility(pub, limit=args.limit,
                                             symbols=syms or None), indent=1))
        print(json.dumps(U.stats(pub), indent=1))
        return 0

    if args.action == "queue":
        rows = U.queue(pub, limit=args.limit, due_days=args.due_days)
        print(f"{len(rows)} due\n")
        print(f"  {'sym':<7}{'prio':>7}{'tgts':>6}{'mentions':>10}"
              f"{'age':>6}  live  name")
        for q in rows:
            print(f"  {q['symbol']:<7}{q['priority']:>7.2f}"
                  f"{q['n_targets'] or 0:>6}{q['mentions_180d'] or 0:>10}"
                  f"{q['days_since_run']:>5}d  "
                  f"{'yes ' if q['last_published'] else 'no  '}  "
                  f"{(q['company_name'] or '')[:40]}")
        return 0

    print(json.dumps(U.stats(pub), indent=1))
    return 0


def cmd_batch(args) -> int:
    """One scheduled pass over the queue.

    Bounded by `--limit` and optionally `--max-seconds`, resumable because every
    completed name is marked in Supabase before the next one starts, and gated:
    a row goes live only when it is valid AND something it is about moved.
    """
    load_env()
    from .batch import run_batch
    from .persist import PricedInPublisher

    pub = PricedInPublisher()
    ok, why = pub.ready()
    if not ok:
        print(f"not ready: {why}")
        return 2

    syms = [t.strip().upper() for t in (args.tickers or "").split(",")
            if t.strip()]
    summary = run_batch(pub, limit=args.limit, due_days=args.due_days,
                        symbols=syms or None, effort=args.effort, top=args.top,
                        publish=not args.no_publish, stale_days=args.stale_days,
                        predict=args.predict, horizon=args.horizon,
                        max_seconds=args.max_seconds, dry_run=args.dry_run,
                        verbose=args.verbose)
    return 0 if summary.get("failed", 0) == 0 else 1


def cmd_investigate(args) -> int:
    """Investigate the crux the decomposition already identified."""
    load_env()
    from .business import BusinessStore
    from .investigate import run as investigate_run

    T = args.ticker.upper()
    q = args.question
    if not q:
        # Default to the stored crux — the whole point is that the question is
        # given by the analysis, not invented here.
        for f in (OUTPUT_ROOT / "social" / T / "cases.json",
                  OUTPUT_ROOT / "tier2b" / f"{T}.json"):
            if f.exists():
                dec = json.loads(f.read_text()).get("decomposition") or {}
                q = dec.get("crux") or ""
                if q:
                    print(f"crux for {T} (from the decomposition):\n  {q}\n")
                    break
    if not q:
        print(f"no crux stored for {T}; run `cases {T}` first or pass --question")
        return 2

    bp = BusinessStore().load(T)
    inv = investigate_run(T, q, business_brief=(bp.brief() if bp else ""),
                          effort=args.effort)
    if inv is None:
        print("investigation failed — check ANTHROPIC_API_KEY")
        return 1
    print(inv.brief())
    out = OUTPUT_ROOT / "social" / T
    out.mkdir(parents=True, exist_ok=True)
    (out / "investigation.json").write_text(
        json.dumps(inv.to_dict(), indent=1, default=str))
    print(f"\nwrote {out / 'investigation.json'}")
    if not inv.settled:
        print("\nNot settled is the expected outcome: the crux is by construction "
              "the thing nobody has resolved, and the decomposition usually says "
              "the deciding measurement is missing. The probability is a prior to "
              "be scored forward, not a finding.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="strategylab.social")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("entities", help="build the ticker -> brand dictionary")
    p.add_argument("--limit", type=int, default=250)
    p.set_defaults(func=cmd_entities)

    p = sub.add_parser("pageviews", help="pull Wikimedia daily pageviews")
    p.add_argument("--workers", type=int, default=8)
    p.set_defaults(func=cmd_pageviews)

    p = sub.add_parser("theses", help="narrative -> blind generation -> differencing")
    p.add_argument("ticker")
    p.add_argument("--lookback", type=int, default=180)
    p.add_argument("--claims", type=int, default=60)
    p.add_argument("--null", type=int, default=60)
    p.add_argument("-n", type=int, default=5, help="theses per round")
    p.add_argument("--rounds", type=int, default=4, help="max search rounds")
    p.add_argument("--want", type=int, default=3, help="stop once this many survive")
    p.add_argument("--effort", default="medium")
    p.set_defaults(func=cmd_theses)

    p = sub.add_parser("cases", help="price-as-vote: reconstruct rejected models")
    p.add_argument("ticker")
    p.add_argument("--lookback", type=int, default=180)
    p.add_argument("--claims", type=int, default=60)
    p.add_argument("--top", type=int, default=3, help="how many rejected models")
    p.add_argument("--passages", type=int, default=12)
    p.add_argument("--effort", default="medium")
    p.add_argument("--as-of", dest="as_of", default=None,
                   help="reconstruct at a past date (YYYY-MM-DD). Data becomes "
                        "point-in-time; the MODEL does not — gate with `leakage`.")
    p.set_defaults(func=cmd_cases)

    p = sub.add_parser("predict", help="Tier 3 — locked forward predictions")
    p.add_argument("action",
                   choices=["register", "status", "resolve", "migrate"])
    p.add_argument("--go", action="store_true",
                   help="migrate: actually write (default is a dry run)")
    p.add_argument("ticker", nargs="?", default="")
    p.add_argument("--horizon", type=int, default=120,
                   help="days until the prediction may be resolved")
    p.add_argument("--effort", default="medium")
    p.set_defaults(func=cmd_predict)

    p = sub.add_parser("persist", help="mirror the record to Supabase")
    p.add_argument("action", choices=["push", "verify"], default="push",
                   nargs="?")
    p.add_argument("--model", default="claude-opus-5")
    p.set_defaults(func=cmd_persist)

    p = sub.add_parser("universe", help="the NYSE + NASDAQ working universe")
    p.add_argument("action", nargs="?", default="stats",
                   choices=["seed", "check", "queue", "stats"])
    p.add_argument("--limit", type=int, default=250,
                   help="check: FMP calls to spend; queue: rows to show")
    p.add_argument("--due-days", dest="due_days", type=int, default=7)
    p.add_argument("--tickers", default="",
                   help="check: comma-separated symbols to check by hand")
    p.add_argument("--min-market-cap", dest="min_market_cap", type=int,
                   default=universe.MIN_MARKET_CAP)
    p.add_argument("--min-price", dest="min_price", type=float,
                   default=universe.MIN_PRICE)
    p.add_argument("--min-mentions", dest="min_mentions", type=int,
                   default=universe.MIN_MENTIONS_180D)
    p.set_defaults(func=cmd_universe)

    p = sub.add_parser("batch", help="one scheduled pass over the queue")
    p.add_argument("--limit", type=int, default=25,
                   help="how many tickers this pass may run")
    p.add_argument("--due-days", dest="due_days", type=int, default=7,
                   help="skip names run more recently than this")
    p.add_argument("--tickers", default="",
                   help="run these symbols instead of taking the queue")
    p.add_argument("--top", type=int, default=3)
    p.add_argument("--effort", default="medium")
    p.add_argument("--stale-days", dest="stale_days", type=int,
                   default=batch.STALE_DAYS,
                   help="republish on age alone after this many days")
    p.add_argument("--no-publish", dest="no_publish", action="store_true",
                   help="write rows but never promote one")
    p.add_argument("--predict", action="store_true",
                   help="also register Tier-3 forward predictions (one more "
                        "LLM call per ticker, and it changes WHICH tickers the "
                        "sealed ledger follows)")
    p.add_argument("--horizon", type=int, default=120)
    p.add_argument("--max-seconds", dest="max_seconds", type=float, default=None)
    p.add_argument("--dry-run", dest="dry_run", action="store_true",
                   help="print the queue this pass would take, and stop")
    p.add_argument("--verbose", action="store_true",
                   help="print each ticker's full reconstruction")
    p.set_defaults(func=cmd_batch)

    p = sub.add_parser("investigate", help="investigate the crux with non-news data")
    p.add_argument("ticker")
    p.add_argument("--question", default="", help="override the stored crux")
    p.add_argument("--effort", default="medium")
    p.set_defaults(func=cmd_investigate)

    p = sub.add_parser("control", help="calibrate + verify the saturation metric")
    p.add_argument("ticker")
    p.add_argument("--lookback", type=int, default=180)
    p.add_argument("--claims", type=int, default=60)
    p.add_argument("--null", type=int, default=60)
    p.set_defaults(func=cmd_control)

    p = sub.add_parser("l2", help="the pivotal link: attention -> earnings surprise")
    p.add_argument("--top-k", type=int, default=10)
    p.set_defaults(func=cmd_l2)

    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
