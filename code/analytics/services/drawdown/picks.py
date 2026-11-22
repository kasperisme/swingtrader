"""Long/short picks from the panel-reviewed stress test: pool, dossiers, deep panel, seal, grade.

The deterministic half of the `drawdown-picks` skill. Python supplies data and
keeps the ledger; it never ranks or chooses. Choosing is done by agents: the
session (portfolio manager) picks what to research, a deep panel of specialist
subagents (narrative / earnings / news / market) reports on each candidate, a
pick-verdict agent turns the reports into a trade or a pass, the PM sizes the
book, and a skeptic attacks it.

    pool         the PANEL-REVIEWED scorecard -> every long and short candidate with
                 trend, beta and 20-day liquidity; shorts below the liquidity floor out
    dossiers     evidence bundle per chosen name (+ the trend/beta block)
    deep         research_queue.json -> deep-panel batches (one side, <= 8 names each)
    deep-check   a deep batch's four specialist reports + verdicts are complete
    seal         picks.json -> validated as a BOOK (sizes, stops, beta-neutral, caps),
                 betas stamped, full payload hashed into the append-only ledger
    grade        sealed book -> entered at the next open after the seal, stops honoured,
                 marked at the sealed horizon, sized P&L and beta-adjusted alpha

Council round 3 is why the book rules exist: an unsized, unhedged list built from
the stress test is long high-beta reversal and short low-beta leaders by
construction, and a raw-vs-SPY grade then measures the rebound, not the work.
Nothing here is a validated signal; the stress test has never been graded.
"""

from __future__ import annotations

import json
import logging
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

from . import ledger
from .market import blocks as market_blocks
from .snapshots import ET, FMP_BASE, _fmp_key, _get, market_date

log = logging.getLogger(__name__)

OUT_ROOT = Path(__file__).resolve().parents[2] / "output" / "drawdown" / "picks"
MIN_CAP_SHORT = 2e9
MIN_ADV_SHORT = 20e6        # 20-day average dollar volume, not one day's
MAX_PER_SECTOR = 3
MAX_HIGH_EXPOSURE = 3       # per side, across sector labels
PICKS_PER_SIDE = 10         # at most; the panel decides how many it backs
MIN_PICKS_PER_SIDE = 2      # a side of one is a position, not a book
MAX_SIDE_GROSS = 120        # % of NAV per side
MAX_NET_BETA = 10           # |beta-weighted long - short|, % of NAV
MAX_SHORT_SI = 15           # % of float
MAX_SHORT_DTC = 5           # days to cover
DEEP_ROLES = ("narrative", "earnings", "news", "market")
#: Index legs a book may carry as an explicit hedge (`"hedge": true`). Exempt from the
#: single-name fields (thesis research, short interest), never counted as a pick.
HEDGES = {"SPY", "QQQ", "IWM"}
HEDGE_FIELDS = ("ticker", "entry", "size_pct", "reason")
PICK_FIELDS = ("ticker", "sector", "thesis", "evidence", "catalyst", "invalidation", "risk", "conviction",
               "entry", "stop", "target", "size_pct", "earnings_date", "pre_earnings_action")


# --- the reviewed stress test --------------------------------------------
def latest_scorecard(as_of: str | None = None) -> tuple[dict, list[dict], Path]:
    from .judge import OUT_ROOT as JUDGED_ROOT

    days = sorted(p for p in JUDGED_ROOT.iterdir() if p.is_dir() and (p / "scorecard.json").exists()) \
        if JUDGED_ROOT.exists() else []
    if as_of:
        days = [p for p in days if p.name == as_of]
    if not days:
        raise RuntimeError("no panel-reviewed scorecard; run the correction-review skill first")
    sc = json.loads((days[-1] / "scorecard.json").read_text())
    return sc["meta"], sc["rows"], days[-1]


def _brief(r: dict, mk: dict) -> dict:
    j = r.get("judgement") or {}
    return {"ticker": r["ticker"], "company": r["company"], "sector": r["sector"], "group": r["group"],
            "rule_group": r.get("rule_grp"), "cushion_pt": round(r["breakeven_cut"] * 100, 1),
            "panel_cut_pt": None if r.get("correction_cut") is None else round(float(r["correction_cut"]) * 100, 1),
            "sector_pct": r.get("sector_pct"), "margin": r.get("margin_used"), "upside_to_median": r.get("upside_to_median"),
            "quality": r.get("quality"), "exposure": r["exposure"], "confidence": j.get("confidence"),
            "from_peak": r.get("drawdown_from_peak"), "trend": mk.get("trend"), "ret_3m": mk.get("ret_3m"),
            "vs_50dma": mk.get("vs_50dma"), "beta_spy_1y": mk.get("beta_spy_1y"), "atr20_pct": mk.get("atr20_pct"),
            "adv20_usd": mk.get("adv20_usd"), "thesis": r.get("thesis"), "breaks_if": r.get("breaks_if")}


def pool(as_of: str | None = None, workers: int = 6) -> dict:
    """Every reviewed name that could be a pick, with the tape. Unranked: choosing is the PM's call."""
    meta, rows, src = latest_scorecard(as_of)
    longs = [r for r in rows if r["group"] in ("on_top", "holds")]
    shorts = [r for r in rows if r["group"] == "drowns" or (r["group"] == "fragile" and (r.get("breakeven_cut") or 0) < 0)]
    mk = market_blocks([r["ticker"] for r in longs + shorts], workers)
    key, today = _fmp_key(), market_date()
    with ThreadPoolExecutor(workers) as ex:
        caps = dict(zip([r["ticker"] for r in shorts],
                        ex.map(lambda r: ((_fmp("quote", {"symbol": r["ticker"]}, key) or [{}])[0]).get("marketCap") or 0, shorts)))
    dropped, keep = [], []
    for r in shorts:
        adv = mk.get(r["ticker"], {}).get("adv20_usd") or 0
        if caps[r["ticker"]] < MIN_CAP_SHORT or adv < MIN_ADV_SHORT:
            dropped.append({"ticker": r["ticker"], "why": f"illiquid for a short: cap ${caps[r['ticker']] / 1e9:.1f}B, "
                                                          f"20d ADV ${adv / 1e6:.0f}M"})
        else:
            keep.append(r)
    out = OUT_ROOT / today.isoformat()
    out.mkdir(parents=True, exist_ok=True)
    order = lambda r: (r["sector"] or "", r["ticker"])  # noqa: E731  (alphabetical: no implied ranking)
    res = {"as_of": today.isoformat(), "scorecard": str(src), "scorecard_seal": meta.get("seal_sha256"),
           "reviewed_by": meta.get("reviewer"), "estimate_snapshot": meta["estimate_snapshot"],
           "long": [_brief(r, mk.get(r["ticker"], {})) for r in sorted(longs, key=order)],
           "short": [_brief(r, mk.get(r["ticker"], {})) for r in sorted(keep, key=order)],
           "dropped": dropped, "out_dir": str(out)}
    (out / "pool.json").write_text(json.dumps(res, default=str, indent=1))
    ledger.append("pick_pool", today.isoformat(), out / "pool.json", res)
    return res


# --- evidence ---------------------------------------------------------------
def _fmp(ep: str, params: dict, key: str):
    try:
        b = _get(f"{FMP_BASE}/{ep}", {**params, "apikey": key}).json()
        return b if isinstance(b, list) else [b] if isinstance(b, dict) and b else []
    except Exception as exc:  # noqa: BLE001
        log.warning("%s %s: %s", ep, params.get("symbol"), exc)
        return []


def fmp_bundle(sym: str, key: str, today: date) -> dict:
    quote = (_fmp("quote", {"symbol": sym}, key) or [{}])[0]
    grades = [g for g in _fmp("grades", {"symbol": sym, "limit": 40}, key)
              if g.get("date", "") >= (today - timedelta(days=90)).isoformat()]
    earn = _fmp("earnings", {"symbol": sym, "limit": 6}, key)
    nxt = sorted((e for e in earn if e.get("date", "") > today.isoformat()), key=lambda e: e["date"])
    last = sorted((e for e in earn if e.get("epsActual") is not None), key=lambda e: e["date"], reverse=True)
    tgt = (_fmp("price-target-summary", {"symbol": sym}, key) or [{}])[0]
    flt = (_fmp("shares-float", {"symbol": sym}, key) or [{}])[0]
    actions = {}
    for g in grades:
        actions[g.get("action", "?")] = actions.get(g.get("action", "?"), 0) + 1
    return {
        "quote": {k: quote.get(k) for k in ("price", "marketCap", "volume", "yearHigh", "yearLow", "priceAvg50", "priceAvg200")},
        "dollar_volume": (quote.get("price") or 0) * (quote.get("volume") or 0),
        "analyst_actions_90d": actions,
        "analyst_changes_90d": [g for g in grades if g.get("action") in ("upgrade", "downgrade")][:8],
        "next_earnings": nxt[0] if nxt else None,
        "last_earnings": last[0] if last else None,
        "target_trend": {k: tgt.get(k) for k in ("lastMonthCount", "lastMonthAvgPriceTarget", "lastQuarterAvgPriceTarget",
                                                  "lastYearAvgPriceTarget")},
        "free_float_pct": flt.get("freeFloat"),
    }


def db_bundle(sb, sym: str, snapshot: str) -> dict:
    st = sb.schema("swingtrader")
    out: dict = {}
    try:
        news = st.rpc("get_ticker_impact_news", {"p_ticker": sym, "p_days": 30, "p_limit": 10, "p_per_bucket": 4}).execute().data or []
        out["news_30d"] = [{k: n.get(k) for k in ("published_at", "title", "source", "sentiment", "impact_magnitude", "url")}
                           for n in news]
    except Exception as exc:  # noqa: BLE001
        out["news_30d"], out["news_error"] = [], str(exc)
    try:
        out["sentiment_windows"] = st.rpc("get_relationship_node_sentiment_windows", {"p_ticker": sym}).execute().data
    except Exception as exc:  # noqa: BLE001
        out["sentiment_windows"] = None
        log.warning("sentiment %s: %s", sym, exc)
    # Estimate revisions: this snapshot vs the earliest complete one (only one exists until a second evening runs).
    snaps = [r["snapshot_date"] for r in st.table("drawdown_snapshot_runs").select("snapshot_date")
             .eq("status", "complete").order("snapshot_date").execute().data or []]
    cur = st.table("drawdown_estimate_snapshots").select("fiscal_date,revenue_avg,eps_avg,net_income_avg,num_analysts_revenue") \
        .eq("snapshot_date", snapshot).eq("symbol", sym).order("fiscal_date").execute().data or []
    out["estimates"] = cur
    out["revision_base"] = None
    if snaps and snaps[0] != snapshot:
        base = {r["fiscal_date"]: r for r in st.table("drawdown_estimate_snapshots").select("fiscal_date,revenue_avg,eps_avg")
                .eq("snapshot_date", snaps[0]).eq("symbol", sym).execute().data or []}
        out["revision_base"] = snaps[0]
        out["revisions"] = [{"fiscal_date": r["fiscal_date"],
                             "revenue": (r["revenue_avg"] / base[r["fiscal_date"]]["revenue_avg"] - 1)
                             if base.get(r["fiscal_date"], {}).get("revenue_avg") else None,
                             "eps": (r["eps_avg"] / base[r["fiscal_date"]]["eps_avg"] - 1)
                             if base.get(r["fiscal_date"], {}).get("eps_avg") else None} for r in cur]
    return out


def dossiers(tickers: list[str], as_of: str | None = None, workers: int = 6) -> dict:
    """The evidence bundle for each name the PM chose to research."""
    from shared.db import get_supabase_client

    meta, rows, _ = latest_scorecard(as_of)
    by = {r["ticker"]: r for r in rows}
    missing = [t for t in tickers if t not in by]
    tickers = [t for t in tickers if t in by]
    key, today, sb = _fmp_key(), market_date(), get_supabase_client()
    with ThreadPoolExecutor(workers) as ex:
        fmp = dict(zip(tickers, ex.map(lambda s: fmp_bundle(s, key, today), tickers)))
    mk = market_blocks(tickers, workers)
    out = OUT_ROOT / today.isoformat() / "dossiers"
    out.mkdir(parents=True, exist_ok=True)
    paths = {}
    for t in tickers:
        r = {k: v for k, v in by[t].items() if k != "solve"}
        d = {"stress_test": r, "tape": mk.get(t, {}), "market": fmp[t], **db_bundle(sb, t, meta["estimate_snapshot"])}
        path = out / f"{t}.json"
        path.write_text(json.dumps(d, default=str, indent=1))
        paths[t] = str(path)
    return {"written": paths, "not_in_scorecard": missing}


# --- deep panel -------------------------------------------------------------
def deep(queue_path: str, size: int = 8) -> dict:
    """research_queue.json -> deep-panel batches, one side each. Dossiers must exist."""
    q = json.loads(Path(queue_path).read_text())
    day = OUT_ROOT / market_date().isoformat()
    dd = day / "dossiers"
    out = day / "deep"
    out.mkdir(parents=True, exist_ok=True)
    index, n = [], 0
    for side in ("long", "short"):
        names = [x["ticker"] for x in q.get(side) or []]
        missing = [t for t in names if not (dd / f"{t}.json").exists()]
        if missing:
            raise RuntimeError(f"no dossier for {', '.join(missing)}; run `picks dossiers` first")
        for i in range(0, len(names), size):
            n += 1
            stem = out / f"deep_{n:02d}"
            chunk = names[i:i + size]
            body = {"deep": n, "side": side, "tickers": chunk, "why": {x["ticker"]: x.get("why") for x in q[side] if x["ticker"] in chunk},
                    "dossiers": {t: str(dd / f"{t}.json") for t in chunk}}
            Path(f"{stem}.json").write_text(json.dumps(body, indent=1))
            index.append({"deep": n, "side": side, "tickers": chunk, "path": f"{stem}.json",
                          "panel": {r: f"{stem}.{r}.json" for r in DEEP_ROLES}, "verdict": f"{stem}.verdict.json"})
    (out / "index.json").write_text(json.dumps(index, indent=1))
    return {"batches": index}


VERDICT_FIELDS = ("ticker", "verdict", "conviction", "thesis", "evidence", "against", "catalyst", "invalidation",
                  "stop", "entry", "target", "earnings_date", "pre_earnings_action", "panel", "risk")


def deep_check(batch_path: str) -> dict:
    b = json.loads(Path(batch_path).read_text())
    stem = batch_path[:-5]
    want, issues = set(b["tickers"]), []
    for role in DEEP_ROLES:
        p = Path(f"{stem}.{role}.json")
        if not p.exists():
            issues.append(f"{role}-analyst report missing")
            continue
        got = {x.get("ticker") for x in json.loads(p.read_text()).get("names") or []}
        if want - got:
            issues.append(f"{role}-analyst did not cover {', '.join(sorted(want - got))}")
    vp = Path(f"{stem}.verdict.json")
    if not vp.exists():
        return {"ok": False, "issues": issues + ["verdict not written yet"]}
    vs = {x.get("ticker"): x for x in json.loads(vp.read_text()).get("names") or []}
    for t in sorted(want):
        v = vs.get(t)
        if not v:
            issues.append(f"{t}: no verdict")
            continue
        miss = [f for f in VERDICT_FIELDS if v.get(f) in (None, "", [], {})]
        if v.get("verdict") == "kill":
            miss = [f for f in miss if f in ("ticker", "verdict", "thesis", "panel")]
        if miss:
            issues.append(f"{t}: missing {', '.join(miss)}")
        if v.get("verdict") not in ("pick", "watch", "kill"):
            issues.append(f"{t}: verdict must be pick, watch or kill")
        if isinstance(v.get("panel"), dict) and any(not str(v["panel"].get(r) or "").strip() for r in DEEP_ROLES):
            issues.append(f"{t}: panel must carry a takeaway from each of {', '.join(DEEP_ROLES)}")
        if v.get("verdict") == "pick" and b["side"] == "short":
            if v.get("short_interest_pct_float") is None or v.get("days_to_cover") is None:
                issues.append(f"{t}: a short pick needs short_interest_pct_float and days_to_cover from a source")
        stop = v.get("stop") if isinstance(v.get("stop"), dict) else {}
        if v.get("verdict") == "pick" and not isinstance(stop.get("price"), (int, float)):
            issues.append(f"{t}: stop must be {{price: number, basis}}")
    return {"ok": not issues, "issues": issues}


# --- book validation + seal + grade ------------------------------------------
def validate(picks: dict) -> list[str]:
    errs = []
    for side in ("long", "short"):
        allx = picks.get(side) or []
        for h in (x for x in allx if x.get("hedge")):
            if h.get("ticker") not in HEDGES:
                errs.append(f"{side} {h.get('ticker')}: a hedge leg must be one of {sorted(HEDGES)}")
            miss = [k for k in HEDGE_FIELDS if h.get(k) in (None, "", {}, [])]
            if miss:
                errs.append(f"{side} hedge {h.get('ticker')}: missing {', '.join(miss)}")
        xs = [x for x in allx if not x.get("hedge")]
        if not MIN_PICKS_PER_SIDE <= len(xs) <= PICKS_PER_SIDE:
            errs.append(f"{side}: {len(xs)} picks, need {MIN_PICKS_PER_SIDE}-{PICKS_PER_SIDE} "
                        f"(only names the deep panel backed; do not pad)")
        seen, sectors, high = set(), {}, 0
        for p in xs:
            t = p.get("ticker")
            miss = [k for k in PICK_FIELDS if p.get(k) in (None, "", [], {})]
            if miss:
                errs.append(f"{side} {t}: missing {', '.join(miss)}")
            if t in seen:
                errs.append(f"{side}: {t} twice")
            seen.add(t)
            if p.get("conviction") not in (1, 2, 3):
                errs.append(f"{side} {t}: conviction must be 1, 2 or 3")
            stop = p.get("stop") if isinstance(p.get("stop"), dict) else {}
            if not isinstance(stop.get("price"), (int, float)):
                errs.append(f"{side} {t}: stop must be {{price: number, basis}}")
            if not isinstance(p.get("size_pct"), (int, float)) or not 0 < p["size_pct"] <= 20:
                errs.append(f"{side} {t}: size_pct must be a number in (0, 20] (% of NAV)")
            if p.get("pre_earnings_action") not in ("hold", "halve", "wait", None):
                errs.append(f"{side} {t}: pre_earnings_action must be hold, halve or wait")
            if p.get("exposure") == "high" or p.get("epicenter_linked"):
                high += 1
            if side == "short":
                si, dtc = p.get("short_interest_pct_float"), p.get("days_to_cover")
                if si is None or dtc is None:
                    errs.append(f"short {t}: short_interest_pct_float and days_to_cover are required")
                elif si > MAX_SHORT_SI or dtc > MAX_SHORT_DTC:
                    errs.append(f"short {t}: squeeze risk (SI {si}% of float, {dtc} days to cover)")
            s = p.get("sector") or "?"
            sectors[s] = sectors.get(s, 0) + 1
        errs += [f"{side}: {c} picks in {s} (max {MAX_PER_SECTOR})" for s, c in sectors.items() if c > MAX_PER_SECTOR]
        if high > MAX_HIGH_EXPOSURE:
            errs.append(f"{side}: {high} high-exposure / epicenter-linked picks (max {MAX_HIGH_EXPOSURE})")
        gross = sum(p.get("size_pct") or 0 for p in allx)
        if gross > MAX_SIDE_GROSS:
            errs.append(f"{side}: gross {gross:.0f}% of NAV, max {MAX_SIDE_GROSS}%")
    if all(isinstance(p.get("beta"), (int, float)) for s in ("long", "short") for p in picks.get(s) or []):
        net = sum(p["size_pct"] * p["beta"] for p in picks.get("long") or []) - \
            sum(p["size_pct"] * p["beta"] for p in picks.get("short") or [])
        if abs(net) > MAX_NET_BETA:
            errs.append(f"book: beta-weighted net {net:+.1f}% of NAV (max +/-{MAX_NET_BETA}); resize or swap names")
    else:
        errs.append("book: every pick needs a beta (seal stamps it from the tape)")
    both = {p.get("ticker") for p in picks.get("long", [])} & {p.get("ticker") for p in picks.get("short", [])}
    if both:
        errs.append(f"on both sides: {', '.join(sorted(both))}")
    return errs


def _closes(sym: str, since: date, key: str) -> list[dict]:
    from .market import _bars

    return _bars(sym, key, since)


def stamp_betas(picks: dict) -> dict:
    """Betas from the tape (1y daily vs SPY), so the book check uses one source for every name."""
    names = [p["ticker"] for s in ("long", "short") for p in picks.get(s) or []]
    mk = market_blocks(names)
    for s in ("long", "short"):
        for p in picks.get(s) or []:
            b = mk.get(p["ticker"], {}).get("beta_spy_1y")
            p["beta"] = round(b, 3) if isinstance(b, (int, float)) else p.get("beta")
            p["atr20_pct"] = mk.get(p["ticker"], {}).get("atr20_pct")
    return picks


def seal(path: str) -> dict:
    src = Path(path)
    picks = stamp_betas(json.loads(src.read_text()))
    errs = validate(picks)
    if errs:
        raise ValueError("picks.json is not a valid book:\n  " + "\n  ".join(errs))
    today = market_date()
    out = OUT_ROOT / today.isoformat()
    sealed_path = out / "picks_sealed.json"
    if sealed_path.exists() or ledger.first("picks_sealed", today.isoformat()):
        raise FileExistsError(f"{today} is already sealed; a sealed day is never rewritten (see the ledger)")
    key = _fmp_key()
    ref = {}
    for t in [p["ticker"] for s in ("long", "short") for p in picks[s]] + ["SPY"]:
        bars = _closes(t, today - timedelta(days=10), key)
        ref[t] = (bars[-1]["date"], float(bars[-1]["close"])) if bars else (None, None)
    for s in ("long", "short"):
        for p in picks[s]:
            p["reference_date"], p["reference_close"] = ref[p["ticker"]]
    sealed_at = datetime.now(ET)
    body = {"as_of": today.isoformat(), "sealed_at": sealed_at.isoformat(),
            "entry_rule": "each pick's own entry {type, level, expires}, never before the next session after sealed_at; "
                          "next_open = that open, limit/breakout = first touch of the level; unfilled by expiry = no trade. "
                          "reference_close is context only",
            "horizon_days": int(picks.get("horizon_days", 63)), "benchmark": "SPY", "spy_reference": ref["SPY"],
            "scorecard_seal": picks.get("scorecard_seal"), "long": picks["long"], "short": picks["short"],
            "notes": picks.get("notes"), "skeptic": picks.get("skeptic_summary")}
    body["seal_sha256"] = ledger.payload_sha(body)
    out.mkdir(parents=True, exist_ok=True)
    sealed_path.write_text(json.dumps(body, indent=1, default=str))
    body["ledger"] = ledger.append("picks_sealed", today.isoformat(), sealed_path, body, seal_sha256=body["seal_sha256"])
    return body


# --- the counterfactual (council 4, decision scientist) -------------------------
CONTROL_N = 10


def _stratified(rows: list[dict], n: int, rng) -> list[dict]:
    """n names drawn across sectors in proportion to the pool (largest remainder)."""
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(r.get("sector") or "?", []).append(r)
    quota = {k: n * len(v) / len(rows) for k, v in by.items()}
    take = {k: int(q) for k, q in quota.items()}
    for k in sorted(quota, key=lambda k: (-(quota[k] - take[k]), k))[: n - sum(take.values())]:
        take[k] += 1
    out = []
    for k in sorted(by):
        out += rng.sample(sorted(by[k], key=lambda r: r["ticker"]), min(take[k], len(by[k])))
    return sorted(out, key=lambda r: r["ticker"])


def control(as_of: str, n: int = CONTROL_N) -> dict:
    """Seal what the book must beat, before the next open: a sector-stratified random draw
    from the same pool, plus the research queue and the pool itself as cohorts.

    Without it a graded book cannot say whether the panel, the PM's selection or the trade
    management added anything over the rule (council 4). The draw is seeded from the
    scorecard seal, so it is fixed by data committed before any agent chose a name. The
    raw specialist reports are hashed into the same ledger entry so the panel's inputs
    can be graded against its verdicts."""
    import random

    day = OUT_ROOT / as_of
    path = day / "control.json"
    if path.exists() or ledger.first("control_sealed", as_of):
        raise FileExistsError(f"{as_of} control already sealed")
    pool_b = json.loads((day / "pool.json").read_text())
    queue = json.loads((day / "research_queue.json").read_text()) if (day / "research_queue.json").exists() else {}
    seal_ = pool_b.get("scorecard_seal") or as_of
    ctrl = {}
    for side in ("long", "short"):
        rng = random.Random(f"{seal_}:{side}")
        ctrl[side] = [{"ticker": r["ticker"], "sector": r.get("sector"), "beta": r.get("beta_spy_1y"), "group": r.get("group")}
                      for r in _stratified(pool_b[side], n, rng)]
    files = sorted([*day.glob("deep/deep_*.json"), *(day.parent.parent / "judged" / as_of / "batches").glob("batch_*.json")])
    sealed_at = datetime.now(ET)
    body = {"as_of": as_of, "sealed_at": sealed_at.isoformat(), "seed": f"{seal_}:<side>", "n": n,
            "entry_rule": "every cohort name enters at the next session's open after sealed_at, equal weight, "
                          "no stop, exits at the book's horizon",
            "control": ctrl,
            "queue": {s: [{"ticker": q["ticker"]} for q in queue.get(s, [])] for s in ("long", "short")},
            "pool": {s: [{"ticker": r["ticker"], "beta": r.get("beta_spy_1y"), "group": r.get("group")} for r in pool_b[s]]
                     for s in ("long", "short")},
            "panel_files": {str(f.relative_to(day.parent.parent)): ledger.payload_sha(json.loads(f.read_text()))
                            for f in files}}
    body["seal_sha256"] = ledger.payload_sha(body)
    path.write_text(json.dumps(body, indent=1, default=str))
    body["ledger"] = ledger.append("control_sealed", as_of, path, body, seal_sha256=body["seal_sha256"])
    return body


def _cohort(names: list[dict], side: str, sealed_at: datetime, horizon: int, since: date, key: str,
            spy_by: dict) -> dict:
    """Equal-weight, next-open, no-stop result for a list of names (the unmanaged trade)."""
    sign = 1 if side == "long" else -1
    rows = []
    for c in names:
        h = _hold(_closes(c["ticker"], since, key), sealed_at, side, None, horizon)
        if h["status"] == "not_entered":
            rows.append({"ticker": c["ticker"], "status": "no_price"})
            continue
        ret = h["exit"] / h["entry"] - 1
        s0, s1 = spy_by.get(h["entry_date"]), spy_by.get(h["exit_date"])
        spy_ret = (float(s1["close"]) / float(s0.get("open") or s0["close"]) - 1) if s0 and s1 else None
        b = c.get("beta")
        rows.append({"ticker": c["ticker"], "pnl": sign * ret,
                     "alpha": None if spy_ret is None or b is None else sign * (ret - b * spy_ret)})
    got = [r for r in rows if "pnl" in r]
    al = [r["alpha"] for r in got if r.get("alpha") is not None]
    return {"n": len(names), "priced": len(got), "mean_pnl": sum(r["pnl"] for r in got) / len(got) if got else None,
            "mean_alpha": sum(al) / len(al) if al else None,
            "hit_rate": sum(r["pnl"] > 0 for r in got) / len(got) if got else None}


def _fill(bars: list[dict], side: str, entry: dict | None) -> tuple[int, float] | None:
    """Index and price of the fill under the sealed entry rule, or None if it never filled.

    next_open  the first open after the seal
    limit      long: first bar trading at/below the level; short: at/above. Filled at the
               level (or the open, if it gapped through)
    breakout   long: first bar trading at/above the level; short: at/below
    A limit/breakout with an `expires` date that passes unfilled is never entered."""
    e = entry or {}
    kind, level, exp = e.get("type", "next_open"), e.get("level"), e.get("expires")
    if kind == "next_open" or not isinstance(level, (int, float)):
        return (0, float(bars[0].get("open") or bars[0]["close"])) if bars else None
    buy_low = (kind == "limit") == (side == "long")      # long limit / short breakout trigger on the way down
    for i, b in enumerate(bars):
        if exp and b["date"] > str(exp):
            return None
        o = float(b.get("open") or b["close"])
        hi, lo = float(b.get("high") or b["close"]), float(b.get("low") or b["close"])
        if buy_low and lo <= level:
            return i, (o if o < level else level)
        if not buy_low and hi >= level:
            return i, (o if o > level else level)
    return None


def _hold(bars: list[dict], sealed_at: datetime, side: str, stop: float | None, horizon: int,
          entry: dict | None = None) -> dict:
    """Fill under the sealed entry rule (never before the next session), then exit at the stop
    (first close through it) or at the sealed horizon, counted in sessions from the fill."""
    after = [b for b in bars if b["date"] > sealed_at.date().isoformat()
             or (b["date"] == sealed_at.date().isoformat() and sealed_at.hour < 9)]
    if not after:
        return {"status": "not_entered"}
    f = _fill(after, side, entry)
    if f is None:
        return {"status": "not_filled"}
    i0, px = f
    held = after[i0: i0 + horizon]
    for b in held:
        c = float(b["close"])
        if stop is not None and ((side == "long" and c <= stop) or (side == "short" and c >= stop)):
            return {"status": "stopped", "entry_date": held[0]["date"], "entry": px, "exit_date": b["date"], "exit": c}
    last = held[-1]
    return {"status": "horizon" if len(held) >= horizon else "open", "entry_date": held[0]["date"], "entry": px,
            "exit_date": last["date"], "exit": float(last["close"])}


def grade(as_of: str) -> dict:
    sealed = json.loads((OUT_ROOT / as_of / "picks_sealed.json").read_text())
    key = _fmp_key()
    since = date.fromisoformat(as_of) - timedelta(days=3)
    sealed_at = datetime.fromisoformat(sealed["sealed_at"])
    horizon = sealed["horizon_days"]
    spy_bars = _closes("SPY", since, key)
    spy_by = {b["date"]: b for b in spy_bars}
    res = {"as_of": as_of, "horizon_days": horizon, "long": [], "short": []}
    for side, sign in (("long", 1), ("short", -1)):
        for p in sealed[side]:
            stop = (p.get("stop") or {}).get("price")
            h = _hold(_closes(p["ticker"], since, key), sealed_at, side, stop, horizon, p.get("entry"))
            row = {"ticker": p["ticker"], "size_pct": p["size_pct"], "beta": p.get("beta"), "conviction": p.get("conviction"), "hedge": bool(p.get("hedge")), **h}
            if h["status"] == "not_filled":
                # The planned entry never came: no position, no P&L. Reported, never dropped.
                row.update(**{"return": None, "pnl": None, "alpha": None, "contribution_pct_nav": 0.0})
                res[side].append(row)
                continue
            if h["status"] == "not_entered":
                # No price after the seal: delisted, halted or acquired. Count the stop as hit
                # (for a short, a takeover is the worst case), never drop the name silently.
                ref = p.get("reference_close")
                row.update(status="no_price_assumed_stopped", entry=ref, exit=stop)
                h = {"entry": ref, "exit": stop, "entry_date": None, "exit_date": None}
            ret = (h["exit"] / h["entry"] - 1) if h.get("entry") and h.get("exit") else None
            s0, s1 = spy_by.get(h.get("entry_date")), spy_by.get(h.get("exit_date"))
            spy_ret = (float(s1["close"]) / float(s0.get("open") or s0["close"]) - 1) if s0 and s1 else None
            row["return"] = ret
            row["pnl"] = None if ret is None else sign * ret
            row["alpha"] = None if ret is None or spy_ret is None or p.get("beta") is None else sign * (ret - p["beta"] * spy_ret)
            row["contribution_pct_nav"] = None if row["pnl"] is None else row["pnl"] * p["size_pct"]
            res[side].append(row)
        got = [x for x in res[side] if x["pnl"] is not None]
        w = sum(x["size_pct"] for x in got) or 1
        res[f"{side}_sized_pnl"] = sum(x["pnl"] * x["size_pct"] for x in got) / w if got else None
        res[f"{side}_sized_alpha"] = (sum(x["alpha"] * x["size_pct"] for x in got if x["alpha"] is not None) / w) if got else None
        res[f"{side}_hit_rate"] = sum(x["pnl"] > 0 for x in got) / len(got) if got else None
        res[f"{side}_stopped"] = sum(x["status"].startswith(("stopped", "no_price")) for x in res[side])
        res[f"{side}_not_filled"] = sum(x["status"] == "not_filled" for x in res[side])
    res["book_pnl_pct_nav"] = sum(x["contribution_pct_nav"] or 0 for s in ("long", "short") for x in res[s])
    res["book_alpha"] = None if res["long_sized_alpha"] is None or res["short_sized_alpha"] is None else \
        (res["long_sized_alpha"] + res["short_sized_alpha"]) / 2
    # The counterfactuals: same horizon, equal weight, next open, no stops. "picks_unmanaged"
    # isolates selection from trade management; control/queue/pool isolate the panel and
    # the PM's selection from the rule. Pool cohorts are large; they cost one price fetch each.
    cpath = OUT_ROOT / as_of / "control.json"
    if cpath.exists():
        ctl = json.loads(cpath.read_text())
        c_at = datetime.fromisoformat(ctl["sealed_at"])
        beta_of = {r["ticker"]: r.get("beta") for s in ("long", "short") for r in ctl["pool"][s]}
        res["cohorts"] = {}
        for side in ("long", "short"):
            picks_ = [{"ticker": p["ticker"], "beta": p.get("beta")} for p in sealed[side] if not p.get("hedge")]
            for name, xs in (("picks_unmanaged", picks_), ("control", ctl["control"][side]),
                             ("queue", [{**q, "beta": beta_of.get(q["ticker"])} for q in ctl["queue"][side]]),
                             ("pool", ctl["pool"][side])):
                res["cohorts"][f"{side}_{name}"] = _cohort(xs, side, min(c_at, sealed_at), horizon, since, key, spy_by)
    res["graded_on"] = max((x.get("exit_date") or "" for s in ("long", "short") for x in res[s]), default=None)
    path = OUT_ROOT / as_of / f"grade_{res['graded_on']}.json"
    path.write_text(json.dumps(res, indent=1, default=str))
    ledger.append("picks_graded", as_of, path, res)
    return res
