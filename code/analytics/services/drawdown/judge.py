"""Agent panel review of the narrative stress test: batches, panel, commit, check, apply.

narrative.py is the RULE baseline. Every judgement a rule makes badly is made by
a panel of Claude Code subagents per batch of names (`correction-review` skill):

    narrative-analyst  is the priced-in story still credible after the drop? where
                       in its cycle is the business? how does THIS correction reach it?
    earnings-analyst   are the quality flags real or accounting artefacts? what
                       margin does the business earn through a cycle?
    news-analyst       what has happened since the narrative was written: guidance,
                       analyst actions, M&A, litigation, event risk?
    market-analyst     trend, volatility, beta, liquidity, estimate revisions,
                       economic (not co-mention) exposure to the epicenter
    verdict-analyst    reads the four reports and the inputs, commits margin, cut,
                       exposure and group BEFORE seeing the rule's answer, then the
                       arithmetic is re-run here and the verdict finalised

Python keeps the arithmetic and the audit honest around them (council round 3):

  * batches are BLIND: the rule's group, cushion and cuts are not in them, and
    `reveal` computes them only after the draft is committed (the scorecard itself
    is still on disk, so this is a procedural gate, not a cryptographic one);
  * `commit` hashes the draft into the ledger, so the first view is on record and
    every later change to margin, cut, exposure or group needs a `revision_reason`;
  * `check` enforces: every specialist covered every name; a margin >25% from
    consensus needs a cited reason; a 'high' exposure needs at least the rule's
    bust cut; on_top needs a recovery_case; override_reason is a real argument;
    overrides (incl. not_valued) are capped at 10% of a batch;
  * `apply` seals the FULL judgement payload, archives it, and logs it in the
    append-only ledger with the run manifest (model, agent ids).

    batches   valued rows -> blind sector batches + reveal files (+ news, trend)
    whatif    one name re-solved under a stated margin / cut / discount rate
    commit    hash a verdict draft into the ledger (before reveal/check)
    reveal    the rule's answer for a committed batch
    check     specialists + verdict vs the arithmetic and the rules above
    apply     all verdicts -> the reviewed scorecard (+ Supabase), rule group kept
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from . import ledger
from .market import blocks as market_blocks
from .narrative import (FLUSH_CUT, OUT_ROOT as NARRATIVE_ROOT, Row, breakeven_cut, faded_cagr, required_now,
                        write_db)
from .snapshots import ET

OUT_ROOT = Path(__file__).resolve().parents[2] / "output" / "drawdown" / "judged"
GROUPS = ("on_top", "holds", "fragile", "drowns")
ROLES = ("narrative", "earnings", "news", "market")
INPUTS = ("ticker", "margin", "margin_reason", "correction_cut", "cut_reason", "exposure", "group")
FIELDS = INPUTS + ("quality_read", "thesis", "breaks_if", "confidence", "panel")
MARGIN_DRIFT = 0.25
MAX_OVERRIDE_SHARE = 0.10
MIN_REASON = 40


def _scorecard(as_of: str | None) -> tuple[dict, list[dict], str]:
    days = sorted(p for p in NARRATIVE_ROOT.iterdir() if p.is_dir() and (p / "scorecard.json").exists())
    if as_of:
        days = [p for p in days if p.name == as_of]
    if not days:
        raise RuntimeError("no narrative scorecard; run `cli narrative --no-db` first")
    sc = json.loads((days[-1] / "scorecard.json").read_text())
    if not any((r.get("solve") or {}).get("r") for r in sc["rows"]):
        raise RuntimeError(f"{days[-1].name}'s scorecard predates per-company discount rates; rerun `cli narrative --no-db`")
    return sc["meta"], sc["rows"], days[-1].name


def _valued(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r.get("solve") and r["group"] in GROUPS]


# --- batches ----------------------------------------------------------------
def _blind(r: dict, news: dict, trend: dict) -> dict:
    """What the panel sees. No rule group, cushion or cut: those are in the reveal file."""
    s = r["solve"]
    return {
        "ticker": r["ticker"], "company": r["company"], "sector": r["sector"], "industry": s.get("industry"),
        "valuation": {"price_now": r["price"], "consensus_3y_revenue_cagr": s["g3"], "terminal_growth": s["gt"],
                      "consensus_net_margin": s["consensus_margin"], "hist_net_margin_5y": r.get("hist_net_margin"),
                      "rule_midcycle_margin_floor": r.get("midcycle_margin"), "stored_fcf_margin": s["p"]["fcf_margin"],
                      "cost_of_equity": s["r"], "loss_making_3y": r.get("loss_making")},
        "quality": {k: r.get(k) for k in ("quality", "quality_flags", "cash_conversion", "cfo_to_ni", "accruals",
                                           "sbc_to_revenue", "share_growth", "one_off_share", "cash_margin", "quality_years")},
        "market": {"from_peak": r["drawdown_from_peak"], "move_since_model": r["move_since_model"],
                   "upside_to_median_target": r["upside_to_median"], "n_targets": r["n_targets"],
                   "targets_predate_drop": r["targets_predate_drop"], "beta_reported": r["beta"], "trend": trend},
        "links": {"epicenter": r["epicenter"], "news_linked_with": r["linked_with"]},
        "narrative": {"as_of": r["model_as_of"], "position": r.get("position"), "pays_for": r.get("pays_for"),
                      "declines": r.get("declines"), "crux": r.get("crux"),
                      "note": "LLM-written priced-in reconstruction; treat as a claim to test, not evidence"},
        "news": news,
    }


#: Which parts of a blind record each specialist reads. The verdict analyst reads
#: `valuation` and `quality` plus the four reports, not the raw news or tape.
VIEWS = {
    "narrative": ("valuation", "narrative", "links"),
    "earnings": ("valuation", "quality"),
    "news": ("news", "links"),
    "market": ("market", "links"),
    "verdict": ("valuation", "quality", "links"),
}


def _view(rec: dict, role: str) -> dict:
    keep = ("ticker", "company", "sector", "industry") + VIEWS[role]
    out = {k: rec[k] for k in keep if k in rec}
    if role == "news":  # the news analyst needs the price context for what headlines mean
        out["market"] = {k: rec["market"].get(k) for k in ("from_peak", "move_since_model", "upside_to_median_target",
                                                           "n_targets", "targets_predate_drop")}
    return out


def _reveal(r: dict) -> dict:
    s = r["solve"]
    return {"group": r["group"], "margin_basis": r.get("margin_basis"), "margin_used": r["margin_used"],
            "required_cagr": r["required_cagr"], "breakeven_cut_pt": round(r["breakeven_cut"] * 100, 1),
            "breakeven_at_consensus_margin_pt": None if r.get("breakeven_consensus") is None else round(r["breakeven_consensus"] * 100, 1),
            "flush_cut_pt": FLUSH_CUT * 100, "bust_cut_pt": round(s["bust_cut"] * 100, 1), "exposure": r["exposure"],
            "rule_flags": r["flags"]}


def _news(sb, sym: str) -> dict:
    st = sb.schema("swingtrader")
    out: dict = {}
    try:
        rows = st.rpc("get_ticker_impact_news", {"p_ticker": sym, "p_days": 30, "p_limit": 8, "p_per_bucket": 3}).execute().data or []
        out["scored_30d"] = [{k: n.get(k) for k in ("published_at", "title", "sentiment", "impact_magnitude")} for n in rows]
    except Exception as exc:  # noqa: BLE001
        out["scored_30d"], out["error"] = [], str(exc)[:120]
    try:
        out["sentiment_windows"] = st.rpc("get_relationship_node_sentiment_windows", {"p_ticker": sym}).execute().data
    except Exception:  # noqa: BLE001
        out["sentiment_windows"] = None
    return out


def batches(as_of: str | None = None, size: int = 60, workers: int = 6) -> dict:
    from shared.db import get_supabase_client

    meta, rows, day = _scorecard(as_of)
    valued = _valued(rows)
    syms = [r["ticker"] for r in valued]
    sb = get_supabase_client()
    with ThreadPoolExecutor(workers) as ex:
        news = dict(zip(syms, ex.map(lambda s: _news(sb, s), syms)))
    trend = market_blocks(syms + ["SPY", "QQQ"], workers)
    # The market analyst needs the index's own drawdown to say whose drawdown a
    # name's is; without it each agent guessed a different number (round 1: -10%..-15%).
    bench = {s: {k: trend.pop(s, {}).get(k) for k in ("date", "ret_1m", "ret_3m", "vs_200dma")} for s in ("SPY", "QQQ")}
    bench["note"] = "market-explained fall ~ beta_spy_1y x SPY's move; compare with each name's from_peak"
    by_sector: dict[str, list[dict]] = defaultdict(list)
    for r in valued:
        by_sector[r["sector"] or "Unknown"].append(r)
    made, chunk = [], []
    for sector in sorted(by_sector, key=lambda s: -len(by_sector[s])):
        names = sorted(by_sector[sector], key=lambda r: r["ticker"])
        while len(names) > size:
            made.append(names[:size])
            names = names[size:]
        if len(chunk) + len(names) > size:
            made.append(chunk)
            chunk = []
        chunk += names
    if chunk:
        made.append(chunk)
    out = OUT_ROOT / day / "batches"
    out.mkdir(parents=True, exist_ok=True)
    index = []
    for i, names in enumerate(made, 1):
        stem = out / f"batch_{i:02d}"
        sectors = sorted({r["sector"] or "Unknown" for r in names})
        head = {"batch": i, "as_of": day, "estimate_snapshot": meta["estimate_snapshot"], "drop_date": meta["drop_date"],
                "rf_10y": meta.get("rf"), "sectors": sectors, "benchmark": bench}
        recs = [_blind(r, news[r["ticker"]], trend.get(r["ticker"], {})) for r in names]
        Path(f"{stem}.json").write_text(json.dumps({**head, "names": recs}, indent=1, default=str))
        for role in VIEWS:
            Path(f"{stem}.{role}.input.json").write_text(json.dumps(
                {**head, "role": role, "names": [_view(x, role) for x in recs]}, indent=1, default=str))
        index.append({"batch": i, "n": len(names), "sectors": sectors, "path": f"{stem}.json",
                      "inputs": {role: f"{stem}.{role}.input.json" for role in VIEWS},
                      "panel": {role: f"{stem}.{role}.json" for role in ROLES},
                      "draft": f"{stem}.draft.json", "out": f"{stem}.judged.json"})
    (out / "index.json").write_text(json.dumps(index, indent=1))
    return {"as_of": day, "batches": index}


# --- what-if ----------------------------------------------------------------
def _resolve(r: dict, margin: float | None = None, cut: float | None = None, r_disc: float | None = None) -> dict:
    s = r["solve"]
    m = margin if margin is not None else r["margin_used"]
    rr = r_disc if r_disc is not None else s["r"]
    mt = s.get("method")   # "equity" since council 4; older sealed solves keep their own basis
    req, _ = required_now(s["p"], s["price_now"], s["mcap_now"], s["revenue"], m, solve_r=rr, clamp=True, method=mt)
    req_lo, _ = required_now(s["p"], s["price_now"], s["mcap_now"], s["revenue"], m, solve_r=rr - 0.01, clamp=True, method=mt)
    if req is None:
        return {"ticker": r["ticker"], "error": "no solution at this margin (margin <= 0?)"}
    be = breakeven_cut(s["g3"], s["gt"], req)
    be_lo = breakeven_cut(s["g3"], s["gt"], req_lo) if req_lo is not None else be
    c = cut if cut is not None else s["bust_cut"]
    return {"ticker": r["ticker"], "margin": m, "discount_rate": rr, "required_cagr": req, "consensus_3y": s["g3"],
            "supported_cagr": faded_cagr(s["g3"], s["gt"]), "breakeven_cut": be, "breakeven_cut_1pt_lower_r": be_lo,
            "cut": c, "survives_cut_by": be - c, "clamped": req in (-0.30, 0.60) or abs(be) >= 0.5999}


def whatif(ticker: str, margin: float | None = None, cut: float | None = None, r_disc: float | None = None,
           as_of: str | None = None) -> dict:
    _, rows, _ = _scorecard(as_of)
    hit = [r for r in rows if r["ticker"] == ticker.upper() and r.get("solve")]
    if not hit:
        return {"ticker": ticker.upper(), "error": "not a valued name in this scorecard"}
    return _resolve(hit[0], margin, cut, r_disc)


def _implied_group(w: dict) -> set[str]:
    """Groups the numbers support at the agent's own margin and cut."""
    be, be_lo, c = w["breakeven_cut"], w["breakeven_cut_1pt_lower_r"], w["cut"]
    if be < 0:
        return {"drowns"} if be_lo < 0 else {"fragile"}
    if be >= c:
        return {"on_top", "holds"}
    return {"fragile", "holds"} if be >= FLUSH_CUT else {"fragile"}


# --- commit + reveal + check --------------------------------------------------
def _paths(batch_path: str) -> dict:
    stem = batch_path[:-5] if batch_path.endswith(".json") else batch_path
    for suffix in (".reveal", ".draft", ".judged") + tuple(f".{r}.input" for r in VIEWS) + tuple(f".{r}" for r in ROLES):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
    return {"batch": f"{stem}.json", "reveal": f"{stem}.reveal.json", "draft": f"{stem}.draft.json",
            "out": f"{stem}.judged.json", **{role: f"{stem}.{role}.json" for role in ROLES}}


def _key(batch: dict) -> str:
    return f"{batch['as_of']}/batch_{batch['batch']:02d}"


def commit(batch_path: str) -> dict:
    """Hash the verdict agent's draft into the ledger. Only the first commit of a batch counts."""
    p = _paths(batch_path)
    if not Path(p["draft"]).exists():
        return {"ok": False, "issue": f"{p['draft']} not written"}
    draft = json.loads(Path(p["draft"]).read_text())
    batch = json.loads(Path(p["batch"]).read_text())
    missing = sorted({n["ticker"] for n in batch["names"]} - {d.get("ticker") for d in draft.get("judgements") or []})
    bad = [d.get("ticker") for d in draft.get("judgements") or [] if any(d.get(k) in (None, "") for k in INPUTS)]
    if missing or bad:
        return {"ok": False, "issue": f"draft incomplete: missing {missing[:10]}, without inputs {bad[:10]}"}
    panel = _panel_issues(p, {n["ticker"] for n in batch["names"]})
    if panel:
        return {"ok": False, "issue": "the panel is not complete: " + "; ".join(panel)}
    prior = ledger.first("verdict_draft", _key(batch))
    if prior:
        return {"ok": True, "already_committed": prior["at"], "payload_sha256": prior["payload_sha256"]}
    e = ledger.append("verdict_draft", _key(batch), Path(p["draft"]), draft)
    return {"ok": True, "committed": e["at"], "payload_sha256": e["payload_sha256"]}


def _reveal_for(batch: dict) -> dict:
    """The rule's answer for a batch, computed from the scorecard on demand. Round 1 of the panel
    found it sitting on disk next to the batch; it is no longer written anywhere an agent lists."""
    _, rows, _ = _scorecard(batch["as_of"])
    by = {r["ticker"]: r for r in rows}
    return {n["ticker"]: _reveal(by[n["ticker"]]) for n in batch["names"]}


def reveal(batch_path: str) -> dict:
    p = _paths(batch_path)
    batch = json.loads(Path(p["batch"]).read_text())
    if not ledger.first("verdict_draft", _key(batch)):
        return {"error": "commit the draft first: the rule's answer is shown only after your own"}
    return _reveal_for(batch)


def _panel_issues(p: dict, tickers: set[str]) -> list[str]:
    issues = []
    for role in ROLES:
        path = Path(p[role])
        if not path.exists():
            issues.append(f"{role}-analyst report missing: {path.name}")
            continue
        try:
            got = {n.get("ticker") for n in json.loads(path.read_text()).get("names") or []}
        except ValueError:
            issues.append(f"{role}-analyst report is not valid JSON")
            continue
        if tickers - got:
            issues.append(f"{role}-analyst did not cover: {', '.join(sorted(tickers - got)[:12])}")
    return issues


def check(batch_path: str) -> dict:
    p = _paths(batch_path)
    batch = json.loads(Path(p["batch"]).read_text())
    tickers = {n["ticker"] for n in batch["names"]}
    issues = _panel_issues(p, tickers)
    committed = ledger.first("verdict_draft", _key(batch))
    if not committed:
        return {"ok": False, "issues": issues + ["draft not committed: write the draft, then `judge commit`"]}
    if not Path(p["out"]).exists():
        return {"ok": False, "issues": issues + [f"{Path(p['out']).name} not written yet"]}
    draft_body = json.loads(Path(p["draft"]).read_text())
    if ledger.payload_sha(draft_body) != committed["payload_sha256"]:
        issues.append("draft file changed after commit; the committed version is the one in the ledger")
    draft = {d["ticker"]: d for d in draft_body.get("judgements") or []}
    items = {j.get("ticker"): j for j in json.loads(Path(p["out"]).read_text()).get("judgements") or []}
    rev = _reveal_for(batch)
    _, rows, _ = _scorecard(batch["as_of"])
    by = {r["ticker"]: r for r in rows}
    numbers, overrides = [], 0
    for t in sorted(tickers):
        j = items.get(t)
        if not j:
            issues.append(f"{t}: no final judgement")
            continue
        miss = [f for f in FIELDS if j.get(f) in (None, "", {}, [])]
        if miss:
            issues.append(f"{t}: missing {', '.join(miss)}")
            continue
        panel = j["panel"] if isinstance(j["panel"], dict) else {}
        if any(not str(panel.get(role) or "").strip() for role in ROLES):
            issues.append(f"{t}: panel must carry a one-line takeaway from each of {', '.join(ROLES)}")
        qr = j["quality_read"] if isinstance(j["quality_read"], dict) else {}
        if not qr.get("verdict") or not qr.get("note"):
            issues.append(f"{t}: quality_read must be {{verdict: confirm|override, note}}")
        if j["group"] not in GROUPS + ("not_valued",):
            issues.append(f"{t}: group {j['group']!r} not one of {GROUPS + ('not_valued',)}")
            continue
        if j["exposure"] not in ("low", "medium", "high") or j["confidence"] not in (1, 2, 3):
            issues.append(f"{t}: exposure low/medium/high and confidence 1-3")
        reason = str(j.get("override_reason") or "")
        if reason and len(reason) < MIN_REASON:
            issues.append(f"{t}: override_reason must be a real argument (>= {MIN_REASON} chars)")
        d = draft.get(t, {})
        changed = [k for k in ("group", "margin", "correction_cut", "exposure") if str(d.get(k)) != str(j.get(k))]
        if changed and len(str(j.get("revision_reason") or "")) < MIN_REASON:
            issues.append(f"{t}: changed {', '.join(changed)} since the committed draft; give revision_reason")
        if j["group"] == "not_valued":
            overrides += 1
            if len(reason) < MIN_REASON:
                issues.append(f"{t}: not_valued needs override_reason (why a cash-flow DCF does not apply)")
            continue
        try:
            m, c = float(j["margin"]), float(j["correction_cut"])
        except (TypeError, ValueError):
            issues.append(f"{t}: margin and correction_cut must be numbers (fractions)")
            continue
        if not (0 < m < 0.9) or not (0 <= c <= 0.6):
            issues.append(f"{t}: margin in (0, 0.9) and correction_cut in [0, 0.6], as fractions")
            continue
        cons = by[t]["solve"]["consensus_margin"] or by[t]["margin_used"]
        if cons and abs(m / cons - 1) > MARGIN_DRIFT and len(str(j["margin_reason"])) < MIN_REASON:
            issues.append(f"{t}: margin {m:.0%} is >25% from consensus {cons:.0%}; margin_reason must cite the evidence")
        if j["exposure"] == "high" and c < rev[t]["bust_cut_pt"] / 100 - 1e-9 and len(reason) < MIN_REASON:
            issues.append(f"{t}: 'high' exposure with a {c * 100:.0f}pt cut, below the bust cut "
                          f"{rev[t]['bust_cut_pt']}pt; raise the cut or give override_reason")
        if j["group"] == "on_top" and len(str(j.get("recovery_case") or "")) < MIN_REASON:
            issues.append(f"{t}: on_top needs a recovery_case beyond the cushion")
        w = _resolve(by[t], m, c)
        if "error" in w:
            issues.append(f"{t}: {w['error']}")
            continue
        ok = _implied_group(w)
        if j["group"] not in ok:
            overrides += 1
            if len(reason) < MIN_REASON:
                issues.append(f"{t}: group {j['group']} but at margin {m:.0%} and a {c * 100:.0f}pt cut the cushion is "
                              f"{w['breakeven_cut'] * 100:+.1f}pt (1pt lower r: {w['breakeven_cut_1pt_lower_r'] * 100:+.1f}pt), "
                              f"which supports {sorted(ok)}; change it or give override_reason")
        numbers.append(f"{t:<6} {j['group']:<8} (rule {rev[t]['group']:<8}) margin {m:.0%}  cut {c * 100:4.1f}pt  "
                       f"cushion {w['breakeven_cut'] * 100:+6.1f}pt  clears cut by {w['survives_cut_by'] * 100:+6.1f}pt")
    cap = max(1, math.floor(MAX_OVERRIDE_SHARE * len(tickers)))
    if overrides > cap:
        issues.append(f"{overrides} overrides (incl. not_valued) in a batch of {len(tickers)}; at most {cap}")
    extra = sorted(set(items) - tickers)
    if extra:
        issues.append(f"not in this batch: {', '.join(extra)}")
    return {"ok": not issues, "issues": issues, "overrides": overrides, "judged": len(numbers), "of": len(tickers),
            "numbers": numbers}


# --- apply ------------------------------------------------------------------
def apply(as_of: str | None = None, db: bool = False, manifest: str | None = None) -> dict:
    meta, rows, day = _scorecard(as_of)
    bdir = OUT_ROOT / day / "batches"
    index = json.loads((bdir / "index.json").read_text())
    problems, judged, panels = {}, {}, defaultdict(dict)
    for b in index:
        res = check(b["path"])
        if not res["ok"]:
            problems[b["batch"]] = res["issues"][:10]
            continue
        for j in json.loads(Path(b["out"]).read_text()).get("judgements") or []:
            judged[j["ticker"]] = j
        for role in ROLES:
            for n in json.loads(Path(b["panel"][role]).read_text()).get("names") or []:
                panels[n["ticker"]][role] = n
    if problems:
        return {"ok": False, "problems": problems}
    man = json.loads(Path(manifest).read_text()) if manifest else {}
    reviewer = man.get("reviewer", "claude-code panel: narrative/earnings/news/market -> verdict")
    out_rows = []
    for r in rows:
        j = judged.get(r["ticker"])
        r = dict(r)
        r["rule_grp"] = r["group"]
        if j:
            if j["group"] == "not_valued":
                r.update(group="not_cash_flow", reason=f"analyst: {j['override_reason']}")
            else:
                w = _resolve(r, float(j["margin"]), float(j["correction_cut"]))
                r.update(group=j["group"], margin_used=w["margin"], required_cagr=w["required_cagr"],
                         breakeven_cut=w["breakeven_cut"], thesis=j["thesis"], breaks_if=j["breaks_if"],
                         exposure=j["exposure"],
                         reason=f"panel: {w['margin']:.0%} margin ({j['margin_reason']}); "
                                f"{w['cut'] * 100:.0f}pt correction cut ({j['cut_reason']}); "
                                f"cushion {w['breakeven_cut'] * 100:+.1f}pt")
            r["judgement"] = {**{k: j.get(k) for k in FIELDS + ("override_reason", "revision_reason", "recovery_case", "sources")},
                              "reviewer": reviewer, "specialists": panels.get(r["ticker"], {})}
            r["correction_cut"] = j.get("correction_cut")
        out_rows.append(r)
    order = {g: i for i, g in enumerate(("on_top", "holds", "fragile", "drowns", "not_cash_flow", "refused"))}

    def key(r):
        cut = r.get("correction_cut") or 0
        be = r.get("breakeven_cut") or 0
        return (order[r["group"]], (be if r["group"] == "drowns" else -(be - cut)), r["ticker"])
    out_rows.sort(key=key)
    counters: dict[str, int] = defaultdict(int)
    for r in out_rows:
        counters[r["group"]] += 1
        r["rank"] = counters[r["group"]]
    sealed_part = [{k: r.get(k) for k in ("ticker", "group", "rank", "rule_grp", "margin_used", "correction_cut",
                                          "breakeven_cut", "exposure", "thesis", "breaks_if", "judgement")} for r in out_rows]
    seal = hashlib.sha256(json.dumps(sealed_part, sort_keys=True, default=str).encode()).hexdigest()
    jmeta = {**meta, "reviewed": True, "reviewer": reviewer, "manifest": man, "reviewed_at": datetime.now(ET).isoformat(),
             "rule_seal_sha256": meta["seal_sha256"], "seal_sha256": seal, "judged": len(judged),
             "groups": {g: sum(r["group"] == g for r in out_rows) for g in order}, "rule_groups": meta["groups"],
             "moved": sum(r["group"] != r["rule_grp"] for r in out_rows),
             "overrides": sum(bool((r.get("judgement") or {}).get("override_reason")) for r in out_rows)}
    body = {"meta": jmeta, "rows": out_rows}
    archived = ledger.archive(OUT_ROOT / day, "scorecard.json", body)
    jmeta["ledger"] = ledger.append("reviewed_scorecard", day, archived, body, seal_sha256=seal)
    status = "skipped"
    if db:
        from shared.db import get_supabase_client

        known = set(Row.__dataclass_fields__)
        objs = []
        for r in out_rows:
            o = Row(**{k: v for k, v in r.items() if k in known})
            o.rule_grp, o.judgement, o.correction_cut = r.get("rule_grp"), r.get("judgement"), r.get("correction_cut")
            objs.append(o)
        try:
            write_db(get_supabase_client(), jmeta, objs)
            status = "written"
        except Exception as exc:  # noqa: BLE001
            status = f"failed: {exc}"
    jmeta["db"] = status
    if status == "written":
        # The day is now public on /correction: mail the update list (idempotent per day).
        try:
            from . import notify

            jmeta["notify"] = notify.send(day)
        except Exception as exc:  # noqa: BLE001 - a mail failure never undoes the publish
            jmeta["notify"] = {"ok": False, "error": str(exc)}
    return {"ok": True, "meta": jmeta, "out": str(OUT_ROOT / day / "scorecard.json")}
