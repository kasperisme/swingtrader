"""The scheduled pass: reconstruct, persist, and decide what goes live.

Everything the hand-run pipeline did stays exactly as it was. What is added here
is the three things a hand-run pipeline gets from having a person watching it:

**Resumability.** State lives in `research_priced_in_universe`, not in the
process. A pass that is killed halfway leaves every completed name marked, and
the next pass takes the queue from where it stopped rather than from the top.
This is why the runner takes its work list from a view instead of a Python list.

**Isolation.** One ticker's failure is one ticker's failure. A name with no
transcript, a rate-limited FMP call, a model that returns prose — each is caught,
recorded against that symbol with a backoff, and the pass continues. A batch that
dies on its fortieth name has spent forty names' worth of compute and produced a
traceback.

**A publish gate.** This is the part that did not exist at all, and the one that
would have made a naive cron useless: nothing in the pipeline ever set
`published`, and the quote pages read `published = true` only. Scheduled without
a gate, the job writes a fresh unpublished row every week, reports success, and
the pages silently keep serving whatever was promoted by hand months ago.

## What the gate decides

Two questions, in order, and they are different questions.

*Is the row valid?* — does it clear the same floor the UI applies before it will
render anything (`MIN_TARGETS` published models, a real spread, drivers, both
summary parts)? An invalid row is never published. This is not a judgement call
and has no configuration.

*Has anything changed?* — the reconstruction is regenerated on a cycle, but its
judged tier is model output, and re-running it on unchanged inputs produces a
differently-worded answer with the same content. Publishing that churns the
public page and reads, to anyone watching, as new analysis. So a new row goes
live only when something it is about actually moved: a new analyst model, a
materially different median, a materially different price, or enough elapsed
time that the reader should be told the work was redone.

Held rows are still written, still `published = false`, and still the record of
what the pipeline said that day. Nothing is discarded — the previous row simply
stays live.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import date

from ..config import OUTPUT_ROOT
from .universe import MIN_TARGETS

log = logging.getLogger(__name__)

# How long a published reconstruction stands before it is refreshed purely on
# age. The UI already displays `ageDays`, so a stale row is visibly stale rather
# than silently wrong — this is about the work being redone, not about hiding it.
STALE_DAYS = 30

# What counts as the inputs having moved. Both are deliberately generous: the
# reconstruction is a statement about where a price sits among published models,
# and neither a 1% drift in the median nor a 3% move in the price changes that
# statement enough to justify rewriting the page.
MEDIAN_MOVE_PCT = 0.02
PRICE_MOVE_PCT = 0.10

# Thresholds are compared with a tolerance because they are compared against a
# RATIO of two floats. A move of exactly -10% computes to 0.09999999999999987
# and a move of exactly +10% to 0.10000000000000031, so a bare `>=` publishes
# the rally and holds the identical crash. The asymmetry is invisible in
# ordinary use and would surface as a gate that quietly favours good news.
_EPS = 1e-9


@dataclass
class TickerResult:
    ticker: str
    status: str = "ok"                # ok | failed | skipped
    error: str = ""
    priced_in_id: int | None = None
    published: bool = False
    publish_reason: str = ""
    n_drivers: int = 0
    n_targets: int = 0
    n_predictions: int = 0
    seconds: float = 0.0
    models: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


# ----------------------------------------------------------------------
def validity(payload: dict) -> tuple[bool, str]:
    """The same floor the UI applies, checked before writing rather than after.

    `code/ui/lib/quote/priced-in.ts` returns null on any of these, so a row that
    fails here can never render. Publishing it would put a ticker in the
    published set that shows nothing, which is indistinguishable from a bug.
    """
    dec = payload.get("decomposition") or {}
    vote = payload.get("vote") or {}
    if not dec:
        return False, "no decomposition"
    n = vote.get("n_targets") or 0
    if n < MIN_TARGETS:
        return False, f"{n} published models, below the {MIN_TARGETS} the UI needs"
    lo, hi, med = vote.get("low"), vote.get("high"), vote.get("median")
    if lo is None or hi is None or med is None:
        return False, "incomplete model distribution"
    if not hi > lo:
        return False, f"degenerate spread (${lo}..${hi})"
    if not (dec.get("drivers") or []):
        return False, "no drivers"
    if not (dec.get("position") or "").strip():
        return False, "no position statement"
    if not (dec.get("crux") or "").strip():
        return False, "no crux"
    if not vote.get("price"):
        return False, "no price"
    return True, ""


def materiality(payload: dict, current: dict | None, *,
                stale_days: int = STALE_DAYS,
                today: date | None = None) -> tuple[bool, str]:
    """Has anything this row is ABOUT moved since the live one was written?

    `current` is the currently-published row, or None. Returning False is the
    normal, healthy outcome on a short cycle: it means the pipeline re-ran, the
    answer did not change, and the page was left alone.
    """
    if current is None:
        return True, "first published reconstruction"
    today = today or date.today()
    vote = payload.get("vote") or {}

    as_of = current.get("as_of")
    if as_of is not None:
        age = (today - as_of).days if isinstance(as_of, date) else None
        if age is not None and age >= stale_days:
            return True, f"live row is {age}d old (>= {stale_days}d)"

    old_n, new_n = current.get("n_targets"), vote.get("n_targets")
    if old_n is not None and new_n is not None and new_n != old_n:
        return True, f"published models {old_n} -> {new_n}"

    old_med, new_med = current.get("target_median"), vote.get("median")
    if old_med and new_med and abs(new_med / old_med - 1) >= MEDIAN_MOVE_PCT - _EPS:
        return True, (f"median target ${old_med:,.0f} -> ${new_med:,.0f} "
                      f"({new_med/old_med - 1:+.1%})")

    old_px, new_px = current.get("price"), vote.get("price")
    if old_px and new_px and abs(new_px / old_px - 1) >= PRICE_MOVE_PCT - _EPS:
        return True, (f"price ${old_px:,.2f} -> ${new_px:,.2f} "
                      f"({new_px/old_px - 1:+.1%})")

    return False, ("inputs unchanged — same model count, median within "
                   f"{MEDIAN_MOVE_PCT:.0%} and price within {PRICE_MOVE_PCT:.0%}")


def publish_gate(payload: dict, current: dict | None, *,
                 stale_days: int = STALE_DAYS,
                 today: date | None = None) -> tuple[bool, str]:
    ok, why = validity(payload)
    if not ok:
        return False, f"invalid: {why}"
    ok, why = materiality(payload, current, stale_days=stale_days, today=today)
    return ok, why


def current_published(publisher, ticker: str) -> dict | None:
    schema = publisher.schema
    c = publisher._connect()
    with c.cursor() as cur:
        cur.execute(f"""
            SELECT id, as_of, price, n_targets, target_median
            FROM {schema}.research_priced_in
            WHERE ticker = %s AND published
            ORDER BY as_of DESC, created_at DESC
            LIMIT 1
        """, (ticker,))
        r = cur.fetchone()
    if not r:
        return None
    return dict(zip(["id", "as_of", "price", "n_targets", "target_median"], r))


def set_published(publisher, priced_in_id: int) -> None:
    """Promote one row. The previous one is left published but superseded.

    The UI orders published rows by `as_of` then `created_at` and takes the
    first, so promotion is enough — un-publishing the predecessor would destroy
    the record of what was shown and when, which is the more useful artefact.
    """
    schema = publisher.schema
    c = publisher._connect()
    with c.cursor() as cur:
        cur.execute(f"UPDATE {schema}.research_priced_in SET published = true "
                    f"WHERE id = %s", (priced_in_id,))
    c.commit()


# ----------------------------------------------------------------------
def reconstruct(ticker: str, *, lookback: int = 180, claims: int = 60,
                top: int = 3, passages: int = 12, effort: str = "medium",
                as_of: date | None = None, emit=None) -> dict:
    """The `cases` pipeline as a function. Returns the payload it would write.

    Lifted out of the CLI verbatim so the scheduled path and the interactive one
    cannot drift: the interactive command now calls this and prints what it
    yields, rather than keeping a second copy of the ordering rules that decide
    which models get reconstructed.
    """
    from .analyst import build as analyst_build
    from .business import BusinessStore
    from .case import build as case_build
    from .decompose import build as decompose_build
    from .entity import EntityStore
    from .implied import fetch_financials, implied
    from .narrative import narrative
    from .saturation import NarrativeSpace
    from .tools import coverage_report
    from .vote import build as vote_build

    say = emit or (lambda *_a, **_k: None)
    T = ticker.upper()

    n = narrative(T, lookback_days=lookback)
    ents = _entities_for(T, n.network)
    brands = [e.label for e in EntityStore().load(T) if e.kind == "product"]
    bp = BusinessStore().ensure(T, brands + list(n.network.get("owns") or []))
    imp = implied(T, as_of=as_of)
    if as_of:
        from .pit import market_cap_as_of
        _, px = market_cap_as_of(T, as_of)

        class _F:
            price = px
        fin = _F()
    else:
        fin = fetch_financials(T)

    say("=" * 78)
    say(bp.brief())
    say("=" * 78)
    say("\n" + imp.brief())

    av = analyst_build(T, as_of=as_of)
    vote = vote_build(av, fin.price)
    say("\n" + vote.brief())
    if not vote.rejected:
        say("\nNo rejected models to investigate.")
        return {"implied": imp.to_dict(), "vote": vote.to_dict(), "cases": [],
                "decomposition": None, "tool_coverage": {}}

    own_all = [c.text for c in sorted(n.claims, key=lambda c: -c.weight)
               if c.ticker == T]
    space = NarrativeSpace(T, n.corpus(claims), lookback_days=lookback,
                           entities=ents, own_claims=own_all)
    say(f"\ncorpus: {getattr(space, 'n_articles', 0)} articles, "
        f"{len(space.chunks)} usable body chunks")

    # Pick across STANCES, not just by size of move. Ranking Crocs' rejected set
    # by |implied move| returned two bulls making substantially the same
    # re-rating argument and skipped the bear entirely. The bear is not a weaker
    # version of the same idea; it is the mirror trade, and where the bull and
    # bear disagree is the crux worth testing.
    bulls = sorted([p for p in vote.rejected if p.stance == "rejected_bull"],
                   key=lambda p: -p.implied_move)
    bears = sorted([p for p in vote.rejected if p.stance == "rejected_bear"],
                   key=lambda p: p.implied_move)
    picks, seen = [], set()
    for grp in (bulls[:1], bears[:1]):
        for p_ in grp:
            picks.append(p_)
            seen.add((p_.firm, p_.target))
    for p_ in sorted(vote.rejected, key=lambda x: -abs(x.implied_move)):
        if len(picks) >= top:
            break
        if (p_.firm, p_.target) not in seen:
            picks.append(p_)
            seen.add((p_.firm, p_.target))
    picks = picks[:top]
    # The CONSENSUS model leads: the rejected ones say what the price is NOT
    # paying for; the endorsed one says what it IS.
    cons = vote.consensus_position
    if cons is not None:
        picks = [cons] + picks
    n_b = sum(1 for p_ in picks if p_.stance == "rejected_bull")
    n_e = sum(1 for p_ in picks if p_.stance in ("endorsed", "neutral"))
    say(f"\npicked {n_e} consensus / {n_b} bull / {len(picks)-n_b-n_e} bear  "
        f"(from {len(vote.endorsed)} endorsed, {len(bulls)} rejected bull, "
        f"{len(bears)} rejected bear)")
    say(f"\nreconstructing the {len(picks)} most-rejected model(s) against the "
        f"corpus...\n")

    cases = []
    for pos in picks:
        c = case_build(pos, space, bp, imp.brief(), k=passages, effort=effort)
        cases.append(c)
        say("=" * 78)
        say(c.brief())
        if c.sources:
            say(f"   sources        {', '.join(s[:46] for s in c.sources[:3])}")
        say("")

    kinds = sorted({c.data_source for c in cases if c.data_source})
    cov = {k: coverage_report(k) for k in kinds} or {
        "consumer_attention": coverage_report("consumer_attention")}
    dec = decompose_build(bp, imp.brief(), vote, cases, cov, effort=effort)
    if dec:
        say("=" * 78)
        say(dec.brief())
        say("=" * 78)

    return {"implied": imp.to_dict(), "vote": vote.to_dict(),
            "cases": [c.to_dict() for c in cases],
            "decomposition": dec.to_dict() if dec else None,
            "tool_coverage": cov,
            "as_of": (as_of or date.today()).isoformat()}


def _entities_for(ticker: str, net: dict) -> list[str]:
    """Names that make a thesis unambiguously about this company.

    Three sources because none is complete on its own: the ticker, the Wikidata
    brand dictionary, and the relationship graph's ownership edges — the graph
    is what knows CROX owns HEYDUDE, and Wikidata is what knows Monster owns
    Reign and NOS.
    """
    from .business import BusinessStore
    from .entity import EntityStore
    ents = {ticker}
    for e in EntityStore().load(ticker):
        ents.add(e.label)
        ents.add(e.article.replace("_", " "))
    ents.update(net.get("owns") or [])
    bp = BusinessStore().load(ticker)
    if bp and bp.company:
        ents.add(bp.company)
        # "Crocs, Inc." also licenses the bare "Crocs".
        ents.add(bp.company.split(",")[0].strip())
    return sorted(e for e in ents if e and len(e) > 2)


# ----------------------------------------------------------------------
def run_ticker(publisher, ticker: str, *, effort: str = "medium",
               top: int = 3, lookback: int = 180, passages: int = 12,
               publish: bool = True, stale_days: int = STALE_DAYS,
               predict: bool = False, horizon: int = 120,
               ledger=None, write_disk: bool = True,
               verbose: bool = False) -> TickerResult:
    """One ticker, end to end, and it does not raise.

    Every failure mode here is expected at scale — a missing transcript, an FMP
    timeout, a model that will not produce JSON — so each is recorded against
    the symbol and the pass continues. Raising would make one bad name cost the
    rest of the queue.
    """
    from .universe import record_run

    T = ticker.upper()
    t0 = time.time()
    r = TickerResult(ticker=T)
    try:
        payload = reconstruct(T, lookback=lookback, top=top, passages=passages,
                              effort=effort,
                              emit=print if verbose else None)
    except Exception as exc:                                  # noqa: BLE001
        r.status, r.error = "failed", f"{type(exc).__name__}: {exc}"[:400]
        r.seconds = time.time() - t0
        log.warning("%s: %s", T, r.error)
        record_run(publisher, T, "failed", r.error)
        return r

    dec = payload.get("decomposition") or {}
    vote = payload.get("vote") or {}
    r.n_drivers = len(dec.get("drivers") or [])
    r.n_targets = vote.get("n_targets") or 0
    r.models = sorted({c.get("model") for c in (payload.get("cases") or [])
                       if c.get("model")} | ({dec.get("model")} if dec.get("model")
                                             else set()))

    if not dec:
        # Not an error: a name with no rejected models, or a decomposition the
        # LLM declined, is a legitimate outcome. It is recorded as skipped so it
        # earns a cooldown rather than being retried every pass.
        r.status = "skipped"
        r.error = "no decomposition produced"
        r.seconds = time.time() - t0
        record_run(publisher, T, "skipped", r.error)
        return r

    if write_disk:
        out = OUTPUT_ROOT / "social" / T
        out.mkdir(parents=True, exist_ok=True)
        (out / "cases.json").write_text(json.dumps(payload, indent=1, default=str))

    try:
        r.priced_in_id = publisher.publish_decomposition(
            payload, T, model=",".join(r.models))
    except Exception as exc:                                  # noqa: BLE001
        r.status, r.error = "failed", f"persist failed: {exc}"[:400]
        r.seconds = time.time() - t0
        record_run(publisher, T, "failed", r.error)
        return r

    if publish and r.priced_in_id:
        go, why = publish_gate(payload, current_published(publisher, T),
                               stale_days=stale_days)
        r.publish_reason = why
        if go:
            set_published(publisher, r.priced_in_id)
            r.published = True

    if predict and r.priced_in_id and ledger is not None:
        r.n_predictions = _register_predictions(
            ledger, T, dec, vote.get("price"), horizon=horizon,
            effort=effort, priced_in_id=r.priced_in_id)

    r.seconds = time.time() - t0
    record_run(publisher, T, "ok")
    return r


def _register_predictions(ledger, ticker: str, dec: dict, price, *,
                          horizon: int, effort: str,
                          priced_in_id: int | None) -> int:
    from datetime import timedelta

    from .business import BusinessStore
    from .predict import predictions_from_decomposition

    if not price:
        return 0
    try:
        bp = BusinessStore().load(ticker)
        preds = predictions_from_decomposition(
            ticker, dec.get("drivers") or [], price,
            date.today() + timedelta(days=horizon),
            business_brief=(bp.brief() if bp else ""), effort=effort)
    except Exception as exc:                                  # noqa: BLE001
        log.warning("%s: prediction registration failed — %s", ticker, exc)
        return 0
    n = 0
    for p in preds:
        try:
            ledger.register(p, priced_in_id=priced_in_id)
            n += 1
        except ValueError as exc:
            log.info("%s: prediction refused — %s", ticker, exc)
    return n


# ----------------------------------------------------------------------
def run_batch(publisher, *, limit: int = 25, due_days: int = 7,
              symbols: list[str] | None = None, effort: str = "medium",
              top: int = 3, publish: bool = True, stale_days: int = STALE_DAYS,
              predict: bool = False, horizon: int = 120,
              max_seconds: float | None = None, dry_run: bool = False,
              verbose: bool = False, emit=print) -> dict:
    """One pass over the queue. Bounded, resumable, and it records what it did."""
    from .llm import resolve
    from .universe import queue as build_queue

    say = emit or (lambda *_a, **_k: None)
    backend, chain = resolve()
    work = build_queue(publisher, limit=limit, due_days=due_days, symbols=symbols)
    say(f"backend {backend}, chain {', '.join(chain)}")
    say(f"{len(work)} ticker(s) due "
        f"(limit {limit}, not run in the last {due_days}d)\n")
    if dry_run:
        for q in work:
            say(f"  {q['symbol']:<6} prio {q['priority']:>7.2f}  "
                f"{q['n_targets'] or 0:>3} targets  "
                f"{q['days_since_run']:>5}d since run  "
                f"live={'yes' if q['last_published'] else 'no'}")
        return {"dry_run": True, "queued": len(work),
                "symbols": [q["symbol"] for q in work]}

    ledger = None
    if predict:
        from .ledger import SupabaseLedger
        ledger = SupabaseLedger(publisher.schema, publisher=publisher)

    run_id = _start_run(publisher, backend, chain)
    started = time.time()
    results, stop_reason = [], "queue exhausted"
    for i, q in enumerate(work, 1):
        if max_seconds and time.time() - started > max_seconds:
            stop_reason = f"time budget of {max_seconds:.0f}s reached at {i-1}/{len(work)}"
            say(f"\n{stop_reason}")
            break
        T = q["symbol"]
        say(f"[{i}/{len(work)}] {T:<6} ", )
        r = run_ticker(publisher, T, effort=effort, top=top, publish=publish,
                       stale_days=stale_days, predict=predict, horizon=horizon,
                       ledger=ledger, verbose=verbose)
        results.append(r)
        flag = ("LIVE" if r.published else
                "held" if r.status == "ok" else r.status.upper())
        say(f"    {r.status:<8} {r.n_drivers:>2} drivers  {r.seconds:>5.0f}s  "
            f"{flag:<6} {(r.publish_reason or r.error)[:70]}")

    summary = _finish_run(publisher, run_id, results, stop_reason)
    say("\n" + json.dumps(summary, indent=1))
    return summary


def _start_run(publisher, backend: str, chain: list[str]) -> int:
    from .persist import PIPELINE_VERSION
    schema = publisher.schema
    c = publisher._connect()
    with c.cursor() as cur:
        cur.execute(f"""
            INSERT INTO {schema}.research_priced_in_runs
              (backend, models, pipeline_version) VALUES (%s,%s,%s)
            RETURNING id
        """, (backend, ",".join(chain), PIPELINE_VERSION))
        rid = cur.fetchone()[0]
    c.commit()
    return int(rid)


def _by_model(results: list) -> dict:
    """Tickers and wall-clock per model.

    The chain exists so a degraded model is survivable, which means a run
    summary that does not say which model answered hides the degradation it was
    designed to absorb. A pass that silently fell through to the second model in
    the chain looks identical to a healthy one without this.
    """
    out: dict = {}
    for r in results:
        for m in (r.models or ["(none)"]):
            slot = out.setdefault(m, {"tickers": 0, "seconds": 0.0, "failed": 0})
            slot["tickers"] += 1
            slot["seconds"] += r.seconds
            if r.status == "failed":
                slot["failed"] += 1
    for slot in out.values():
        slot["seconds"] = round(slot["seconds"], 1)
    return out


def _finish_run(publisher, run_id: int, results: list, stop_reason: str) -> dict:
    ok = [r for r in results if r.status == "ok"]
    summary = {
        "run_id": run_id,
        "attempted": len(results),
        "succeeded": len(ok),
        "failed": sum(1 for r in results if r.status == "failed"),
        "skipped": sum(1 for r in results if r.status == "skipped"),
        "published": sum(1 for r in ok if r.published),
        "held": sum(1 for r in ok if not r.published),
        "predictions_registered": sum(r.n_predictions for r in results),
        "seconds": round(sum(r.seconds for r in results), 1),
        "median_seconds_per_ticker": round(
            sorted(r.seconds for r in results)[len(results) // 2], 1)
        if results else 0.0,
        "by_model": _by_model(results),
        "stop_reason": stop_reason,
    }
    schema = publisher.schema
    c = publisher._connect()
    with c.cursor() as cur:
        cur.execute(f"""
            UPDATE {schema}.research_priced_in_runs
            SET ended_at=now(), attempted=%s, succeeded=%s, failed=%s,
                published=%s, held=%s, predictions_registered=%s,
                usage_json=%s::jsonb, stop_reason=%s,
                detail=%s
            WHERE id=%s
        """, (summary["attempted"], summary["succeeded"], summary["failed"],
              summary["published"], summary["held"],
              summary["predictions_registered"],
              json.dumps({"by_model": summary["by_model"],
                          "per_ticker": [r.to_dict() for r in results]},
                         default=str),
              stop_reason,
              ", ".join(f"{r.ticker}:{r.status}" for r in results)[:2000],
              run_id))
    c.commit()
    return summary
