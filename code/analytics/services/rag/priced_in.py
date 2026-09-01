"""
Priced-in retrieval — the drivers behind a share price, and the case for each.

The priced-in programme (`code/strategylab/social/`, written up in
`research/PRICED-IN-FINDINGS.md`) reconstructs what a price already contains and
writes the result to `swingtrader.research_priced_in`. Two of its columns are the
reason this module exists, and nothing else in `services/rag` could reach them:

  * ``drivers_json`` — the decomposition. One row per assumption the price is
    resting on: what it is, which segment it sits in, how much of it the price
    already appears to pay for, what it is worth if it proves out, and the kind
    of measurement that would settle it.
  * ``cases_json``  — the investigation of each of those drivers: what the
    scored coverage says, passages for and against with their source articles,
    whatever non-news measurement is wired for the driver's observable, and what
    is still missing.

Note that `research_priced_in_public_v` — the view the quote page reads — drops
``cases_json`` entirely, so this module goes to the base table like the rest of
`services/rag` does, and keeps that view's ``published`` filter.

**Two case shapes live in this column and they are not the same object.** Under
`priced-in/3` a case is a per-DRIVER investigation carrying ``driver_index``,
which is what joins it back to the decomposition. Under `priced-in/2` a case was
a per-ANALYST reconstruction keyed to a firm, with no driver to join to — the
programme abandoned that shape precisely because it could not be joined. Most
tickers' newest published row is still `/2`, so both are surfaced, tagged with
``case_kind`` (``"driver"`` / ``"analyst"``), and only driver cases are ever
attached to a driver. A consumer that wants the current object filters on
``case_kind == "driver"``.

**The judged tier.** ``priced_in_pct`` and ``value_if_true_pct`` are the
programme's UNVALIDATED tier — two attempts to validate them failed, the second
producing three believable numbers in a row that were all measurement artefacts.
Every payload from this module carries ``CAVEAT`` on it and every tool schema
repeats it, because the consumer here is a language model that will otherwise
present the number as analysis. The grounded numbers in the same row (the target
spread, the median, where the price sits in it) are arithmetic on other people's
published targets and need no such warning.
"""

from __future__ import annotations

import json
import logging
import math
from datetime import date, datetime, timezone
from typing import Any

from shared.db import get_supabase_client, _as_json

log = logging.getLogger(__name__)

# Past this the reconstruction describes a different price than today's.
# Mirrors STALE_AFTER_DAYS in ui/lib/quote/priced-in-vote.ts — the same run
# feeds both, so the two readers should not disagree about when it went stale.
STALE_AFTER_DAYS = 45

CAVEAT = (
    "priced_in_pct and value_if_true_pct are the priced-in programme's JUDGED "
    "tier and are UNVALIDATED — two attempts to validate them failed. Report "
    "them as one model's allocation of a price, never as measured fact. The "
    "target spread (target_low/median/high, n_targets, median_gap) is the "
    "grounded tier: arithmetic over published analyst targets."
)

# Enough of the decomposition to reason about, none of the batch bookkeeping.
_ROW_COLUMNS = (
    "ticker, as_of, price, implied_revenue_cagr, discount_rate, "
    "terminal_growth, fcf_margin, n_targets, target_low, target_high, "
    "target_median, median_gap, n_rejected_bull, n_rejected_bear, n_endorsed, "
    "summary, summary_json, drivers_json, cases_json, pipeline_version, "
    "model, generation_is_pit, created_at"
)

# A case's `narrative.top` and `passages` are the evidence, but the whole list
# is far more than a tool result should spend. These are the defaults; callers
# that want the lot pass a bigger number.
_DEFAULT_TOP_CLAIMS = 4
_DEFAULT_PASSAGES = 6

# A wired measurement is a raw series — one ticker's segment history ran to 10kB
# of nested period dicts, which is most of a tool result spent on one driver's
# evidence. Bounded rather than dropped: the measurement is the only source in a
# case that speaks to whether the driver is TRUE, so losing it entirely to save
# bytes would cost the case the one thing the market has not already read.
_MEASUREMENT_CHARS = 2000


def _client():
    return get_supabase_client(), "swingtrader"


def _norm(tickers: list[str] | str | None) -> list[str]:
    if tickers is None:
        return []
    if isinstance(tickers, str):
        tickers = [tickers]
    return list(dict.fromkeys(str(t or "").upper().strip() for t in tickers if str(t or "").strip()))


def _age_days(as_of: Any) -> int | None:
    """Whole days between the reconstruction's date and today."""
    try:
        d = as_of if isinstance(as_of, date) else date.fromisoformat(str(as_of)[:10])
    except (TypeError, ValueError):
        return None
    return max(0, (datetime.now(timezone.utc).date() - d).days)


# ── Row → structured reconstruction ──────────────────────────────────────────


def _bound_result(result: Any, max_chars: int) -> tuple[Any, bool]:
    """Shrink a measurement result to a byte budget by shortening its lists.

    Trims every list in the structure to the same cap, tightening the cap until
    the whole thing serialises under budget. Lists are cut from the tail, so the
    shape and the leading periods survive; a caller that needs the untrimmed
    series reads `research_priced_in.cases_json` directly. Returns
    (result, was_truncated).
    """
    if result is None or max_chars <= 0:
        return result, False

    def _fits(obj: Any) -> bool:
        try:
            return len(json.dumps(obj, default=str)) <= max_chars
        except (TypeError, ValueError):
            return False

    if _fits(result):
        return result, False

    def _trim(obj: Any, cap: int) -> Any:
        if isinstance(obj, list):
            return [_trim(x, cap) for x in obj[:cap]]
        if isinstance(obj, dict):
            return {k: _trim(v, cap) for k, v in obj.items()}
        return obj

    for cap in (3, 2, 1):
        candidate = _trim(result, cap)
        if _fits(candidate):
            return candidate, True
    return _trim(result, 1), True


def _case_kind(case: dict) -> str:
    """Which of the two case shapes this is.

    `driver_index` is the join key a /3 case carries and a /2 case cannot have;
    `firm` is the /2 shape's own tell. Keyed on the payload rather than on
    `pipeline_version` so a row written by a future version is classified by
    what it actually contains.
    """
    if "driver_index" in case:
        return "driver"
    if "firm" in case or "analyst" in case:
        return "analyst"
    return "unknown"


def _slim_case(case: dict, top_claims: int, passages: int,
               measurement_chars: int = _MEASUREMENT_CHARS) -> dict:
    """One driver case, trimmed to the parts that carry the argument.

    Dropped: `retrieval` (the retriever's own bookkeeping — k, thresholds, timings)
    and the tail of the claim and passage lists. Kept in full: every prose field,
    because those ARE the case, and `sources`, because a citation the reader
    cannot follow is worth little.
    """
    nar = _as_json(case.get("narrative"), default={}) or {}
    meas = _as_json(case.get("measurement"), default={}) or {}
    result, result_truncated = _bound_result(meas.get("result"), measurement_chars)
    out = {
        "case_kind": "driver",
        "driver_index": case.get("driver_index"),
        "driver": case.get("driver") or "",
        "segment": case.get("segment") or "",
        "priced_in_pct": case.get("priced_in_pct"),
        "value_if_true_pct": case.get("value_if_true_pct"),
        "observable": case.get("observable") or "",
        "testable": bool(case.get("testable")),
        # The reading.
        "what_coverage_says": case.get("what_coverage_says") or "",
        "evidence_for": list(case.get("evidence_for") or []),
        "evidence_against": list(case.get("evidence_against") or []),
        "what_the_data_shows": case.get("what_the_data_shows") or "",
        "still_needed": case.get("still_needed") or "",
        "confidence": case.get("confidence") or "",
        # How loudly the scored corpus speaks to this driver. Evidence about how
        # KNOWN the driver is — by the programme's governing assumption, known is
        # already priced — never evidence that it is true.
        "coverage": {
            "n_related": nar.get("n_related", 0),
            "positive": nar.get("positive", 0),
            "negative": nar.get("negative", 0),
            "net_impact": nar.get("net_impact"),
            "n_claims_scanned": nar.get("n_claims_scanned"),
            "note": nar.get("note") or "",
            "top_claims": list(nar.get("top") or [])[:max(0, top_claims)],
        },
        # The only source here that can speak to whether the driver is TRUE,
        # because it is the only one the market has not already read. Most
        # drivers have none, and the honest output is the stated gap.
        "measurement": {
            "tool": meas.get("tool"),
            "wired": meas.get("result") is not None,
            "result": result,
            "result_truncated": result_truncated,
            "note": meas.get("note") or "",
        },
        "n_passages": case.get("n_passages", 0),
        "sources": list(case.get("sources") or []),
        # Kept IN THE ORDER THEY WERE NUMBERED FOR THE MODEL — that ordering is
        # the only thing that resolves a "(Passage 4)" citation in the prose to
        # the article it came from. `sources` is deduplicated and sorted by
        # title, so it cannot do that job and must not be used for it.
        "passages": list(case.get("passages") or [])[:max(0, passages)],
        "model": case.get("model") or "",
    }
    return out


def _slim_analyst_case(case: dict) -> dict:
    """A legacy `priced-in/2` per-analyst case. No driver to join it to."""
    return {
        "case_kind": "analyst",
        "firm": case.get("firm") or "",
        "analyst": case.get("analyst") or "",
        "stance": case.get("stance") or "",
        "target": case.get("target"),
        "implied_move": case.get("implied_move"),
        "case": case.get("case") or "",
        "load_bearing": case.get("load_bearing") or "",
        "market_objection": case.get("market_objection") or "",
        "evidence_for": list(case.get("evidence_for") or []),
        "evidence_against": list(case.get("evidence_against") or []),
        "observable": case.get("observable") or "",
        "data_source": case.get("data_source") or "",
        "confidence": case.get("confidence") or "",
        "n_passages": case.get("n_passages", 0),
        "sources": list(case.get("sources") or []),
        "model": case.get("model") or "",
    }


def _split_cases(raw: Any, top_claims: int, passages: int) -> tuple[list[dict], list[dict]]:
    """(driver cases, analyst cases) out of one `cases_json`."""
    driver_cases: list[dict] = []
    analyst_cases: list[dict] = []
    for case in _as_json(raw, default=[]) or []:
        if not isinstance(case, dict):
            continue
        kind = _case_kind(case)
        if kind == "driver":
            driver_cases.append(_slim_case(case, top_claims, passages))
        elif kind == "analyst":
            analyst_cases.append(_slim_analyst_case(case))
    return driver_cases, analyst_cases


def _attach_cases(drivers: list[dict], cases: list[dict]) -> list[dict]:
    """Join each driver to its case on `driver_index`.

    `driver_index` is positional into `drivers_json` and is the join the UI
    makes too. The driver text is compared as a guard: if the two disagree the
    case is still attached (the index is the contract) but `case_matches_driver`
    goes false, so a reader can see the pairing is suspect rather than quietly
    reading one driver's evidence under another driver's name.
    """
    by_index: dict[int, dict] = {}
    for case in cases:
        idx = case.get("driver_index")
        if isinstance(idx, int):
            by_index.setdefault(idx, case)

    out: list[dict] = []
    for i, drv in enumerate(drivers):
        if not isinstance(drv, dict):
            continue
        row = {
            "driver_index": i,
            "driver": drv.get("driver") or "",
            "segment": drv.get("segment") or "",
            "basis": drv.get("basis") or "",
            "priced_in_pct": drv.get("priced_in_pct"),
            "value_if_true_pct": drv.get("value_if_true_pct"),
            "observable": drv.get("observable") or "",
            "testable": bool(drv.get("testable")),
        }
        case = by_index.get(i)
        if case is not None:
            row["case"] = case
            row["case_matches_driver"] = (
                (case.get("driver") or "").strip().lower()
                == (row["driver"] or "").strip().lower()
            )
        else:
            row["case"] = None
            row["case_matches_driver"] = None
        out.append(row)
    return out


def _shape_row(row: dict, include_cases: bool, top_claims: int, passages: int,
               include_analyst_cases: bool = False) -> dict:
    drivers = _as_json(row.get("drivers_json"), default=[]) or []
    driver_cases, analyst_cases = (
        _split_cases(row.get("cases_json"), top_claims, passages)
        if include_cases else ([], [])
    )
    # The legacy per-analyst case is long prose and averages more bytes than the
    # entire rest of the record. It is also the shape the programme abandoned.
    # So it is counted by default and returned only on request — a consumer that
    # wants it knows it is there, and one that does not is not charged for it.
    n_analyst = len(analyst_cases)
    if not include_analyst_cases:
        analyst_cases = []
    age = _age_days(row.get("as_of"))
    summary_json = _as_json(row.get("summary_json"), default={}) or {}

    return {
        "ticker": row.get("ticker"),
        "as_of": str(row.get("as_of") or "")[:10],
        "age_days": age,
        "stale": (age is not None and age > STALE_AFTER_DAYS),
        "price": row.get("price"),
        "pipeline_version": row.get("pipeline_version"),
        "model": row.get("model"),
        "generation_is_pit": row.get("generation_is_pit"),
        # ── Grounded: arithmetic over other people's published targets. ──
        "vote": {
            "n_targets": row.get("n_targets"),
            "target_low": row.get("target_low"),
            "target_median": row.get("target_median"),
            "target_high": row.get("target_high"),
            "median_gap": row.get("median_gap"),
            "n_rejected_bull": row.get("n_rejected_bull"),
            "n_rejected_bear": row.get("n_rejected_bear"),
            "n_endorsed": row.get("n_endorsed"),
        },
        # ── Assumption-sensitive: correct arithmetic, fragile inputs. ──
        "implied": {
            "implied_revenue_cagr": row.get("implied_revenue_cagr"),
            "discount_rate": row.get("discount_rate"),
            "terminal_growth": row.get("terminal_growth"),
            "fcf_margin": row.get("fcf_margin"),
        },
        "summary": row.get("summary") or "",
        "position": summary_json.get("position") or "",
        "pays_for": list(summary_json.get("pays_for") or []),
        "declines": list(summary_json.get("declines") or []),
        "crux": summary_json.get("crux") or "",
        # ── Judged: the decomposition. See CAVEAT. ──
        "drivers": _attach_cases(drivers, driver_cases),
        "analyst_cases": analyst_cases,
        "analyst_cases_available": n_analyst,
        "caveat": CAVEAT,
    }


# ── Queries ──────────────────────────────────────────────────────────────────


def _latest_published_rows(tickers: list[str]) -> list[dict]:
    """The newest published reconstruction per ticker.

    A ticker can hold several published rows — a point-in-time run beside a live
    one, or two pipeline versions at the same `as_of`. Ordering on `as_of` alone
    leaves same-day rows in arbitrary order, which is how a superseded row wins
    over the one that replaced it; `created_at` breaks the tie toward whatever
    was written last. Same ordering the quote page uses, deliberately.
    """
    client, schema = _client()
    q = (
        client.schema(schema)
        .table("research_priced_in")
        .select(_ROW_COLUMNS)
        .eq("published", True)
        .order("as_of", desc=True)
        .order("created_at", desc=True)
    )
    if tickers:
        q = q.in_("ticker", tickers)
    else:
        # Whole-universe reads are for the search paths, which only need the
        # newest slice; a hard cap keeps a runaway scan out of a tool result.
        q = q.limit(2000)
    try:
        res = q.execute()
    except Exception as exc:                                   # noqa: BLE001
        log.warning("priced-in query failed: %s", exc)
        return []

    latest: dict[str, dict] = {}
    for row in res.data or []:
        latest.setdefault(str(row.get("ticker") or "").upper(), row)
    return list(latest.values())


def get_priced_in(
    tickers: list[str] | str,
    include_cases: bool = True,
    include_analyst_cases: bool = False,
    top_claims: int = _DEFAULT_TOP_CLAIMS,
    passages: int = _DEFAULT_PASSAGES,
) -> list[dict[str, Any]]:
    """Latest published priced-in reconstruction for each ticker.

    Returns one dict per ticker that has one: the grounded target spread, the
    reverse-DCF inputs, the prose summary, and `drivers` — each driver with its
    investigation attached under `case` where one exists. Tickers with no
    published row are simply absent; the programme runs the universe on a
    schedule, so a miss means "not reached yet", not "no such stock".

    `analyst_cases_available` counts the legacy `priced-in/2` per-analyst cases
    on the row; pass `include_analyst_cases=True` to get their bodies too.
    """
    syms = _norm(tickers)
    if not syms:
        return []
    rows = _latest_published_rows(syms)
    order = {t: i for i, t in enumerate(syms)}
    shaped = [_shape_row(r, include_cases, top_claims, passages, include_analyst_cases)
              for r in rows]
    shaped.sort(key=lambda r: order.get(str(r.get("ticker") or "").upper(), 10**6))
    return shaped


def get_priced_in_drivers(
    tickers: list[str] | str,
    max_priced_in_pct: float | None = None,
    testable_only: bool = False,
) -> list[dict[str, Any]]:
    """The decomposition alone — every driver for these tickers, no case bodies.

    The cheap read: what the price is resting on and how much of each piece it
    already pays for, without pulling the evidence. `max_priced_in_pct` keeps
    only the drivers the price has NOT already absorbed (the interesting end);
    `testable_only` keeps the ones with an observable something could settle.
    """
    out: list[dict[str, Any]] = []
    for rec in get_priced_in(tickers, include_cases=False):
        for drv in rec["drivers"]:
            pct = drv.get("priced_in_pct")
            if max_priced_in_pct is not None and (pct is None or pct > max_priced_in_pct):
                continue
            if testable_only and not drv.get("testable"):
                continue
            out.append({
                "ticker": rec["ticker"],
                "as_of": rec["as_of"],
                "price": rec["price"],
                "stale": rec["stale"],
                **{k: v for k, v in drv.items() if k not in ("case", "case_matches_driver")},
                "caveat": CAVEAT,
            })
    out.sort(key=lambda d: (d.get("priced_in_pct") is None, d.get("priced_in_pct") or 0))
    return out


def get_priced_in_case(
    ticker: str,
    driver_index: int | None = None,
    top_claims: int = _DEFAULT_TOP_CLAIMS,
    passages: int = _DEFAULT_PASSAGES,
) -> list[dict[str, Any]]:
    """The investigation behind one ticker's drivers.

    With `driver_index`, just that driver's case; without, every driver that has
    one. Each carries what the coverage says, the passages for and against with
    their source articles, and either the wired measurement or the stated gap
    where none exists. Empty when the ticker's newest published row predates
    per-driver cases (`priced-in/2` and earlier) — those rows' per-analyst cases
    come back from `get_priced_in` under `analyst_cases` instead.
    """
    recs = get_priced_in(ticker, include_cases=True, top_claims=top_claims, passages=passages)
    if not recs:
        return []
    rec = recs[0]
    out = []
    for drv in rec["drivers"]:
        if driver_index is not None and drv["driver_index"] != driver_index:
            continue
        if not drv.get("case"):
            continue
        out.append({
            "ticker": rec["ticker"],
            "as_of": rec["as_of"],
            "price": rec["price"],
            "stale": rec["stale"],
            "pipeline_version": rec["pipeline_version"],
            "basis": drv.get("basis") or "",
            "case_matches_driver": drv.get("case_matches_driver"),
            **drv["case"],
            "caveat": CAVEAT,
        })
    return out


def search_priced_in_drivers(
    query: str,
    limit: int = 20,
    max_priced_in_pct: float | None = None,
    tickers: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Find drivers across the published universe by what they say.

    Answers "which names is the market not yet paying for datacenter power" —
    the cross-ticker question the per-quote page cannot ask. Matching is literal
    substring over the driver text, its segment, its observable and its basis;
    it is not semantic, because the drivers are not embedded anywhere. For
    meaning-level retrieval over the news corpus use `search_news`, then bring
    the tickers it returns back here.

    Terms are weighted by how rare they are among the drivers actually searched,
    because an unweighted count ranks the wrong things: "obesity drug demand"
    otherwise puts a gold-ETF driver that merely contains "demand" above the one
    that contains "obesity", both scoring a single hit. `score` is the summed
    weight, `match_terms` the plain count, and `matched` names which terms hit —
    so a caller can see the match was on the common word and discount it.
    """
    terms = [t for t in dict.fromkeys(str(query or "").lower().split()) if len(t) > 2]
    if not terms:
        return []
    syms = _norm(tickers)

    # (record, driver, haystack) once — the corpus is scanned twice, first to
    # count how common each term is and then to score against those counts.
    scanned: list[tuple[dict, dict, str]] = []
    for rec in [
        _shape_row(r, include_cases=False, top_claims=0, passages=0)
        for r in _latest_published_rows(syms)
    ]:
        for drv in rec["drivers"]:
            hay = " ".join([
                drv.get("driver") or "", drv.get("segment") or "",
                drv.get("observable") or "", drv.get("basis") or "",
            ]).lower()
            scanned.append((rec, drv, hay))
    if not scanned:
        return []

    total = len(scanned)
    weight: dict[str, float] = {}
    for term in terms:
        df = sum(1 for _, _, hay in scanned if term in hay)
        # Standard smoothed IDF. A term in every driver contributes ~0; one in a
        # handful carries the ranking, which is the intent of naming it.
        weight[term] = math.log((total + 1) / (df + 1)) + 1e-6

    scored: list[tuple[float, int, dict]] = []
    for rec, drv, hay in scanned:
        hits = [t for t in terms if t in hay]
        if not hits:
            continue
        pct = drv.get("priced_in_pct")
        if max_priced_in_pct is not None and (pct is None or pct > max_priced_in_pct):
            continue
        score = sum(weight[t] for t in hits)
        scored.append((score, len(hits), {
            "ticker": rec["ticker"],
            "as_of": rec["as_of"],
            "price": rec["price"],
            "stale": rec["stale"],
            "score": round(score, 3),
            "match_terms": len(hits),
            "matched": hits,
            **{k: v for k, v in drv.items() if k not in ("case", "case_matches_driver")},
            "caveat": CAVEAT,
        }))

    # Best-matching first; within an equal match, the least-priced-in driver,
    # which is the end of the distribution the question is usually about.
    scored.sort(key=lambda p: (-p[0], -p[1], p[2].get("priced_in_pct") is None,
                               p[2].get("priced_in_pct") or 0))
    return [d for _, _, d in scored[:max(1, limit)]]
