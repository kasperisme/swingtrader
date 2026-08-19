"""The investigation setup — a deterministic critic that dissects a backtest.

A scalar reward tells the search *that* a genome was worse. It does not say
why, and a policy that only sees scalars has to rediscover structure by brute
force. This module extracts the structure: where the P&L came from, which rule
is actually binding, whether the exits are leaving money on the table, whether
the ranking has any information in it, and whether the result rests on five
lucky trades.

Every finding carries evidence (a number that can be checked) and a *direction*
(which genome keys to move and which way). That is what turns the LLM from a
narrator into a policy: it proposes edits against measured deficiencies rather
than against a number.

Nothing here is generative. If the LLM is unavailable, the same findings still
drive the mutation operators.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd
from scipy import stats

from .genome import Genome
from .validation import Evaluation


@dataclass
class Finding:
    area: str            # exits | entries | ranking | sizing | universe | regime | costs | robustness
    severity: str        # high | medium | low
    finding: str
    evidence: dict
    direction: list[str] = field(default_factory=list)   # genome keys worth moving
    hint: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Diagnostics:
    genome_hash: str
    findings: list[Finding] = field(default_factory=list)
    tables: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"genome_hash": self.genome_hash,
                "findings": [f.to_dict() for f in self.findings],
                "tables": self.tables}

    def brief(self, limit: int = 12) -> str:
        """Findings as a policy reads them — statistic, IMPLICATION, then keys.

        The hint is not decoration. Given only "the stop exit gives back 47% of
        gross profit", every model tested proposed a TIGHTER stop — the opposite
        of what the statistic implies. Given the same finding plus "the stop is
        inside the instrument's ordinary noise", all three were 100%
        directionally correct. The implication is the load-bearing part.
        """
        order = {"high": 0, "medium": 1, "low": 2}
        rows = sorted(self.findings, key=lambda f: order.get(f.severity, 3))[:limit]
        out = []
        for f in rows:
            line = f"[{f.severity.upper()}/{f.area}] {f.finding}"
            if f.hint:
                line += f"\n    means: {f.hint}"
            if f.direction:
                line += f"\n    move: {', '.join(f.direction)}"
            out.append(line)
        return "\n".join(out) or "(no findings)"


def _safe(x, default=0.0) -> float:
    try:
        v = float(x)
        return v if np.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def _bucket_stats(tf: pd.DataFrame, col: str, bins: int = 5) -> list[dict]:
    """Expectancy by quantile bucket of a per-trade column.

    This is the workhorse diagnostic: if expectancy does not increase with a
    feature the strategy is selecting on, that feature is decoration.
    """
    s = pd.to_numeric(tf[col], errors="coerce")
    ok = s.notna()
    if ok.sum() < bins * 6:
        return []
    try:
        q = pd.qcut(s[ok], bins, labels=False, duplicates="drop")
    except ValueError:
        return []
    out = []
    sub = tf.loc[ok].assign(_b=q)
    for b, grp in sub.groupby("_b"):
        out.append({
            "bucket": int(b),
            "range": [round(_safe(s[ok][q == b].min()), 3), round(_safe(s[ok][q == b].max()), 3)],
            "n": int(len(grp)),
            "expectancy_r": round(_safe(grp["r_multiple"].mean()), 3),
            "hit_rate": round(_safe((grp["pnl"] > 0).mean()), 3),
            "total_pnl": round(_safe(grp["pnl"].sum()), 0),
        })
    return out


def _monotonicity(buckets: list[dict], key: str = "expectancy_r") -> float:
    """Spearman correlation between bucket index and outcome, in [-1, 1]."""
    return _monotonicity_p(buckets, key)[0]


def _monotonicity_p(buckets: list[dict], key: str = "expectancy_r") -> tuple[float, float]:
    """Spearman AND its p-value.

    The p-value is not decoration. With five buckets a Spearman of -0.40 has
    p = 0.50 — a coin flip. An earlier version of this module emitted
    "the ranking is INVERTED" as a HIGH-severity finding at exactly that value,
    the LLM policy dutifully spent three proposals attacking it, and when the
    "defect" was finally corrected (rank IC -0.40 -> +0.10) the strategy's
    Sharpe FELL from 0.512 to 0.263. The finding was noise, and acting on it
    cost real search budget.

    At five buckets only |rho| >= 0.9 reaches p < 0.05. Directional claims are
    now gated on the p-value rather than on the correlation alone.
    """
    if len(buckets) < 3:
        return 0.0, 1.0
    x = np.arange(len(buckets), dtype=float)
    y = np.array([b[key] for b in buckets], dtype=float)
    if np.std(y) < 1e-12:
        return 0.0, 1.0
    r = stats.spearmanr(x, y)
    p_val = float(r.pvalue) if np.isfinite(r.pvalue) else 1.0
    return float(r.statistic), p_val


# Directional claims about a bucket table need this much evidence. Anything
# weaker is reported as a table, not as a finding.
MONO_ALPHA = 0.10


# ----------------------------------------------------------------------
def investigate(ev: Evaluation, g: Genome, ctx=None) -> Diagnostics:
    d = Diagnostics(genome_hash=ev.genome_hash)
    if not ev.result:
        d.findings.append(Finding("robustness", "high", "No backtest result to analyse.",
                                  {"reason": ev.reason}))
        return d

    res = ev.result
    tf = res.trades_frame()
    m = ev.metrics

    if tf.empty:
        d.findings.append(Finding(
            "entries", "high",
            "The rule set never fires — no trades at all.",
            {"gate_pass_counts": res.gate_pass_counts, "rejected": res.rejected},
            ["gates.rs_rank_min", "gates.max_pct_below_52w_high", "entry.vol_confirm_ratio",
             "entry.max_extension_pct"],
            "Loosen the most binding gate; see tables.gate_funnel."))
        d.tables["gate_funnel"] = res.gate_pass_counts
        return d

    # ------------------------------------------------------ gate funnel --
    funnel = res.gate_pass_counts
    d.tables["gate_funnel"] = funnel
    if funnel:
        items = list(funnel.items())
        worst_name, worst_drop, prev = None, 0, None
        for name, remaining in items:
            if prev is not None and prev > 0:
                drop = 1.0 - remaining / prev
                if drop > worst_drop:
                    worst_drop, worst_name = drop, name
            prev = remaining
        if worst_name and worst_drop > 0.7:
            d.findings.append(Finding(
                "entries", "medium",
                f"`{worst_name}` alone removes {worst_drop:.0%} of the surviving candidates — "
                f"it is the binding constraint on the whole funnel.",
                {"gate": worst_name, "drop": round(worst_drop, 3), "funnel": funnel},
                [_gate_to_key(worst_name)],
                "If the strategy is trade-starved, this is the gate to relax first."))

    # ------------------------------------------------- exit efficiency ---
    winners = tf[tf["r_multiple"] > 0]
    losers = tf[tf["r_multiple"] <= 0]
    if len(winners) >= 10:
        captured = (winners["r_multiple"] / winners["mfe_r"].replace(0, np.nan)).dropna()
        capture = _safe(captured.median(), 1.0)
        d.tables["exit_capture_median"] = round(capture, 3)
        if capture < 0.55:
            d.findings.append(Finding(
                "exits", "high",
                f"Winners give back most of their peak: the median trade keeps only "
                f"{capture:.0%} of its best unrealised gain.",
                {"median_capture": round(capture, 3),
                 "median_mfe_r": round(_safe(winners['mfe_r'].median()), 2),
                 "median_realised_r": round(_safe(winners['r_multiple'].median()), 2)},
                ["exit.trail_atr_mult", "exit.trail_after_r", "exit.target_r",
                 "exit.breakeven_after_r"],
                "Tighten the trail or add a fixed target — the entry is finding moves "
                "the exit is not banking."))
        elif capture > 0.92 and _safe(winners["mfe_r"].median()) < 1.5:
            d.findings.append(Finding(
                "exits", "medium",
                "Winners are exiting at their highs but the highs are small — the exit is "
                "cutting trends short rather than capturing them.",
                {"median_mfe_r": round(_safe(winners["mfe_r"].median()), 2),
                 "median_hold": round(_safe(winners["hold_days"].median()), 1)},
                ["exit.target_r", "exit.max_hold_days", "exit.trail_atr_mult"],
                "Widen the target or the trail and lengthen max_hold_days."))

    # ------------------------------------------------- stop calibration --
    if len(winners) >= 10:
        mae = winners["mae_r"]
        rarely_tested = _safe((mae > -0.45).mean())
        d.tables["winner_mae_p10"] = round(_safe(mae.quantile(0.10)), 2)
        if rarely_tested > 0.80:
            d.findings.append(Finding(
                "exits", "medium",
                f"{rarely_tested:.0%} of winners never came within half the stop distance. "
                "The stop is wider than the trades actually need, so each unit of risk buys "
                "less position than it could.",
                {"share_never_below_0.45R": round(rarely_tested, 3),
                 "winner_mae_10th_pct_r": round(_safe(mae.quantile(0.10)), 2)},
                ["exit.stop_atr_mult", "exit.stop_pct", "pf.risk_pct"],
                "Tighten the initial stop; the same risk budget then funds a larger position."))

    stopped = tf[tf["exit_reason"].isin(["stop", "stop_gap"])]
    if len(stopped) >= 10:
        quick = _safe((stopped["hold_days"] <= 3).mean())
        d.tables["stop_share"] = round(_safe(len(stopped) / len(tf)), 3)
        d.tables["quick_stop_share"] = round(quick, 3)
        if quick > 0.45:
            d.findings.append(Finding(
                "exits", "high",
                f"{quick:.0%} of stop-outs happen within three sessions — the stop sits "
                "inside the instrument's ordinary noise.",
                {"quick_stop_share": round(quick, 3),
                 "median_entry_adr": round(_safe(tf["entry_adr"].median()), 2),
                 "stop_atr_mult": g["exit.stop_atr_mult"]},
                ["exit.stop_atr_mult", "gates.adr_max", "entry.max_extension_pct"],
                "Either widen the stop relative to ATR, or stop entering names whose ADR "
                "is large relative to the stop."))

    # ------------------------------------------------ exit attribution ---
    by_reason = (tf.groupby("exit_reason")
                   .agg(n=("pnl", "size"), pnl=("pnl", "sum"),
                        avg_r=("r_multiple", "mean"), avg_hold=("hold_days", "mean"))
                   .sort_values("pnl"))
    d.tables["by_exit_reason"] = by_reason.round(3).reset_index().to_dict("records")
    total_pnl = _safe(tf["pnl"].sum())
    # Every "share of profit" below is measured against GROSS profit. Using net
    # P&L as the denominator produces nonsense like "383% of profit" whenever
    # the strategy is close to breakeven — which is most of the search space.
    # P&L-positive, not R-positive: costs can flip a marginally R-positive
    # trade into a money-losing one, and this denominator is about money.
    gross_profit = _safe(tf.loc[tf["pnl"] > 0, "pnl"].sum())
    d.tables["gross_profit"] = round(gross_profit, 0)
    d.tables["net_pnl"] = round(total_pnl, 0)

    for reason, row in by_reason.iterrows():
        if row["n"] >= 8 and gross_profit > 0 and row["pnl"] < -0.25 * gross_profit:
            d.findings.append(Finding(
                "exits", "medium",
                f"The `{reason}` exit gives back {abs(row['pnl'] / gross_profit):.0%} of "
                f"gross profit across {int(row['n'])} trades.",
                {"reason": reason, "pnl": round(_safe(row["pnl"]), 0),
                 "avg_r": round(_safe(row["avg_r"]), 2)},
                _reason_to_keys(str(reason)),
                "This exit is net-negative — reconsider whether it should exist."))

    # ----------------------------------------------------- hold horizon --
    hold_buckets = _bucket_stats(tf, "hold_days", 5)
    d.tables["by_hold_days"] = hold_buckets
    # NOTE: realised holding period is OUTCOME-CONDITIONED. Losers are stopped
    # out early by construction, so the long-hold bucket is close to a
    # definition of "the trades that worked". "Expectancy rises with holding
    # period" is therefore almost tautological, and the causal reading of it
    # ("you are exiting winners early") does not follow. Only the DECREASING
    # direction is informative: if even the survivors decay, the edge is
    # genuinely short-lived.
    if hold_buckets:
        mono, mono_p = _monotonicity_p(hold_buckets)
        d.tables["hold_vs_expectancy_spearman"] = round(mono, 3)
        d.tables["hold_vs_expectancy_note"] = (
            "outcome-conditioned: losers stop out early, so long holds are "
            "winners by construction")
        if mono < -0.7 and mono_p < MONO_ALPHA:
            d.findings.append(Finding(
                "exits", "medium",
                f"Expectancy falls with holding period even though early exits are mostly "
                f"stopped-out losers (rank corr {mono:+.2f}, p={mono_p:.3f}) — the edge "
                "really is short-lived.",
                {"spearman_hold_vs_expectancy": round(mono, 2), "p": round(mono_p, 3),
                 "buckets": hold_buckets},
                ["exit.max_hold_days", "exit.time_stop_days", "exit.target_r"],
                "Shorten max_hold_days and/or add a time stop."))

    # -------------------------------------------------- ranking quality --
    rank_buckets = _bucket_stats(tf, "entry_score", 5)
    d.tables["by_entry_score"] = rank_buckets
    if rank_buckets:
        mono, mono_p = _monotonicity_p(rank_buckets)
        d.tables["rank_information_spearman"] = round(mono, 3)
        d.tables["rank_information_p"] = round(mono_p, 3)
        # Score dispersion matters as much as the correlation: if the gate and
        # the ranking key off the same variable, every survivor scores nearly
        # the same and there is no ordering to be right or wrong about.
        spread = (rank_buckets[-1]["range"][1] - rank_buckets[0]["range"][0]
                  if rank_buckets else 0.0)
        d.tables["rank_score_spread"] = round(float(spread), 3)

        if mono < -0.5 and mono_p < MONO_ALPHA:
            d.findings.append(Finding(
                "ranking", "high",
                f"The ranking is INVERTED — the candidates it likes least perform best "
                f"(rank corr {mono:+.2f}, p={mono_p:.3f}).",
                {"spearman": round(mono, 2), "p": round(mono_p, 3), "buckets": rank_buckets},
                ["rank.w_rs", "rank.w_low_vol", "rank.w_tightness"],
                "Shift weight toward the factors whose own buckets slope the right way."))
        elif abs(mono) < 0.3 and spread < 0.25:
            # The informative case is not "flat correlation" — with five buckets
            # that is unfalsifiable — but flat correlation TOGETHER WITH a
            # compressed score range, which says the ranking is redundant with
            # the gate rather than merely weak.
            d.findings.append(Finding(
                "ranking", "medium",
                f"The ranking barely separates candidates: scores span only "
                f"{spread:.2f} and expectancy is flat across quintiles "
                f"(rank corr {mono:+.2f}, p={mono_p:.2f}). This usually means the "
                "ranking keys off the same variable the gates already filtered on.",
                {"spearman": round(mono, 2), "p": round(mono_p, 3),
                 "score_spread": round(float(spread), 3), "buckets": rank_buckets},
                ["rank.w_momo_12m_1m", "rank.w_residual_momo", "rank.w_tightness",
                 "rank.w_continuity", "gates.rs_rank_min"],
                "Rank on something ORTHOGONAL to the binding gate, or loosen that gate so "
                "the ranking has range to work with."))

    for feat, area, keys in (
        ("entry_rs_rank", "entries", ["gates.rs_rank_min", "rank.w_rs"]),
        ("entry_adr", "entries", ["gates.adr_min", "gates.adr_max"]),
        ("entry_weight", "sizing", ["pf.max_weight", "pf.risk_pct", "pf.sizing"]),
    ):
        if feat in tf.columns:
            b = _bucket_stats(tf, feat, 4)
            if b:
                d.tables[f"by_{feat}"] = b
                mono, mono_p = _monotonicity_p(b)
                if abs(mono) >= 0.8 and mono_p < MONO_ALPHA:
                    lo, hi = b[0], b[-1]
                    d.findings.append(Finding(
                        area, "medium",
                        f"`{feat}` separates outcomes cleanly (rank corr {mono:+.2f}, "
                        f"p={mono_p:.3f}): bottom bucket {lo['expectancy_r']:+.2f}R vs "
                        f"top {hi['expectancy_r']:+.2f}R.",
                        {"spearman": round(mono, 2), "p": round(mono_p, 3), "buckets": b},
                        keys,
                        "Move the gate toward the profitable end of this range."))

    # ----------------------------------------------- regime attribution --
    tf = tf.copy()
    tf["entry_year"] = pd.to_datetime(tf["entry_date"]).dt.year
    by_year = (tf.groupby("entry_year")
                 .agg(n=("pnl", "size"), pnl=("pnl", "sum"), avg_r=("r_multiple", "mean")))
    d.tables["by_year"] = by_year.round(3).reset_index().to_dict("records")
    if len(by_year) >= 3 and gross_profit > 0:
        top_year_share = _safe(by_year["pnl"].max() / gross_profit)
        d.tables["top_year_pnl_share"] = round(top_year_share, 3)
        if top_year_share > 0.6:
            d.findings.append(Finding(
                "robustness", "high",
                f"{top_year_share:.0%} of gross profit comes from a single calendar year "
                f"({int(by_year['pnl'].idxmax())}). This is one regime, not an edge.",
                {"share": round(top_year_share, 3),
                 "by_year": by_year["pnl"].round(0).to_dict()},
                ["regime.enabled", "regime.ma_len", "universe.source", "entry.type"],
                "Look for a variant that is flatter across years even at a lower peak."))

    if ev.fold_metrics:
        neg = [f for f in ev.fold_metrics if f["sharpe"] <= 0]
        d.tables["fold_sharpes"] = {f["fold"]: round(f["sharpe"], 2) for f in ev.fold_metrics}
        if neg:
            d.findings.append(Finding(
                "robustness", "high" if len(neg) > 1 else "medium",
                f"{len(neg)} of {len(ev.fold_metrics)} folds have a non-positive Sharpe "
                f"({', '.join(f['fold'] + ' ' + f['start'][:4] for f in neg)}).",
                {"folds": d.tables["fold_sharpes"]},
                ["regime.enabled", "regime.breadth_enabled", "exit.regime_exit",
                 "pf.max_gross_exposure"],
                "A regime filter that stands down in the bad folds is usually cheaper than "
                "re-tuning the entry."))

    # ------------------------------------------------- concentration -----
    if gross_profit > 0:
        top5 = _safe(tf.nlargest(5, "pnl")["pnl"].sum() / gross_profit)
        d.tables["top5_trade_pnl_share"] = round(top5, 3)
        if top5 > 0.8:
            d.findings.append(Finding(
                "robustness", "high",
                f"Five trades produce {top5:.0%} of gross profit. Remove them and the "
                "strategy is flat — the result is not repeatable.",
                {"share": round(top5, 3), "n_trades": int(len(tf))},
                ["pf.max_positions", "pf.max_weight", "exit.target_r", "gates.rs_rank_min"],
                "More positions and/or a tighter position cap spreads the dependence."))

        by_sector = tf.groupby("sector")["pnl"].sum().sort_values(ascending=False)
        d.tables["by_sector"] = by_sector.round(0).to_dict()
        if len(by_sector) > 1:
            share = _safe(by_sector.iloc[0] / gross_profit)
            if share > 0.65:
                d.findings.append(Finding(
                    "robustness", "medium",
                    f"{share:.0%} of gross profit comes from one sector ({by_sector.index[0]}).",
                    {"share": round(share, 3), "sector": str(by_sector.index[0])},
                    ["pf.max_sector_positions", "universe.exclude_sectors"],
                    "Cap sector positions, or verify the concentration is intentional."))

    # ------------------------------------------------- short sleeve ------
    if "side" in tf.columns and (tf["side"] == -1).any():
        shorts = tf[tf["side"] == -1]
        longs = tf[tf["side"] == 1]
        s_pnl = _safe(shorts["pnl"].sum())
        borrow = _safe(shorts["borrow_cost"].sum()) if "borrow_cost" in shorts else 0.0
        d.tables["short_sleeve"] = {
            "n_shorts": int(len(shorts)), "n_longs": int(len(longs)),
            "short_pnl": round(s_pnl, 0), "long_pnl": round(_safe(longs["pnl"].sum()), 0),
            "short_expectancy_r": round(_safe(shorts["r_multiple"].mean()), 3),
            "short_hit_rate": round(_safe((shorts["pnl"] > 0).mean()), 3),
            "borrow_paid": round(borrow, 0),
        }
        if s_pnl < 0:
            d.findings.append(Finding(
                "sizing", "high",
                f"The short sleeve LOSES money: {int(len(shorts))} shorts for "
                f"{s_pnl:,.0f}, of which {borrow:,.0f} is borrow. It is paying for the "
                "privilege of reducing exposure.",
                d.tables["short_sleeve"],
                ["short.enabled", "short.rs_rank_max", "short.cover_on_regime",
                 "short.max_gross", "short.stop_atr_mult"],
                "Either the short gates admit the wrong names, or the sleeve should be "
                "switched off — turning it off also refunds ~15 parameters of complexity."))
        elif s_pnl > 0 and borrow > 0.5 * s_pnl:
            d.findings.append(Finding(
                "costs", "medium",
                f"Borrow consumes {borrow / s_pnl:.0%} of the short sleeve's gross profit.",
                d.tables["short_sleeve"],
                ["short.max_hold_days", "short.min_dollar_vol", "short.borrow_bps_annual"],
                "Shorter holds, or restrict to names that are cheap to borrow."))

    # ------------------------------------------------------- frictions ---
    cost_drag = _safe(m.get("cost_drag_pct_of_pnl", 0.0))
    d.tables["cost_drag_pct_of_pnl"] = round(cost_drag, 3)
    if cost_drag > 0.35:
        d.findings.append(Finding(
            "costs", "high",
            f"Frictions consume {cost_drag:.0%} of gross P&L — the strategy is trading "
            "away its own edge. At this rate small parameter gains are illusory.",
            {"cost_drag": round(cost_drag, 3),
             "turnover_annual": round(_safe(m.get("turnover_annual")), 1),
             "avg_hold_days": round(_safe(m.get("avg_hold_days")), 1)},
            ["exit.max_hold_days", "pf.max_new_per_day", "entry.vol_confirm_ratio",
             "universe.min_dollar_vol_20d"],
            "Trade less often, hold longer, or move to more liquid names."))

    trunc = _safe(m.get("capacity_truncated_pct", 0.0))
    if trunc > 0.15:
        d.findings.append(Finding(
            "universe", "medium",
            f"{trunc:.0%} of fills were capacity-truncated — the strategy wants more size "
            "than these names can absorb.",
            {"truncated_share": round(trunc, 3)},
            ["universe.min_dollar_vol_20d", "pf.max_weight", "pf.max_positions"],
            "Raise the liquidity floor, or accept smaller positions across more names."))

    # ------------------------------------------------------- plumbing ----
    rej = res.rejected
    d.tables["rejected_orders"] = rej
    total_rej = sum(rej.values())
    if total_rej > 0:
        dominant = max(rej.items(), key=lambda kv: kv[1])
        if dominant[1] > max(60, 0.5 * total_rej) and dominant[1] > len(tf):
            d.findings.append(Finding(
                "sizing" if dominant[0] in {"no_cash", "slots"} else "entries", "medium",
                f"More orders are rejected for `{dominant[0]}` ({dominant[1]}) than are "
                f"actually filled ({len(tf)}) — the strategy is bottlenecked, not selective.",
                {"rejected": rej, "filled": int(len(tf))},
                _rejection_to_keys(dominant[0]),
                "Relieve the bottleneck before tuning anything upstream of it."))

    # ------------------------------------------------------ deployment ---
    if _safe(m.get("avg_exposure")) < 0.35:
        d.findings.append(Finding(
            "sizing", "medium",
            f"Average exposure is only {_safe(m.get('avg_exposure')):.0%}; most of the "
            "capital sits idle, which caps return regardless of how good the signal is.",
            {"avg_exposure": round(_safe(m.get("avg_exposure")), 3),
             "max_positions_used": m.get("max_positions_used")},
            ["pf.max_positions", "pf.risk_pct", "pf.max_weight", "pf.max_new_per_day",
             "gates.rs_rank_min"],
            "Either take more positions, or size the ones you take larger."))

    beta = _safe(m.get("beta"))
    if beta > 0.85 and _safe(m.get("alpha_t")) < 1.0:
        d.findings.append(Finding(
            "robustness", "high",
            f"Beta {beta:.2f} with an alpha t-stat of only {_safe(m.get('alpha_t')):.1f} — "
            "this is a long-market position wearing a strategy's clothes.",
            {"beta": round(beta, 2), "alpha_t": round(_safe(m.get("alpha_t")), 2),
             "correlation": round(_safe(m.get("correlation")), 2)},
            ["regime.enabled", "gates.rs_rank_min", "rank.w_low_vol", "exit.regime_exit"],
            "Something must differentiate holdings from the index, or reduce exposure when "
            "the index is weak."))

    return d


def _gate_to_key(gate_name: str) -> str:
    return {
        "price>sma200": "gates.price_over_sma200",
        "price>sma150": "gates.price_over_sma150",
        "price>sma50": "gates.price_over_sma50",
        "sma_stack": "gates.sma_stack",
        "sma200_rising": "gates.sma200_slope_days",
        "above_52w_low": "gates.min_pct_above_52w_low",
        "near_52w_high": "gates.max_pct_below_52w_high",
        "rs_rank": "gates.rs_rank_min",
        "adr_band": "gates.adr_max",
        "accumulation": "gates.min_up_down_vol",
        "rs_line_high": "gates.rs_line_new_high",
        "not_extended": "gates.max_dist_from_sma50",
        "tightness": "gates.min_base_tightness",
        "eps_growth": "gates.fund_min_eps_yoy",
        "rev_growth": "gates.fund_min_rev_yoy",
        "eps_beats": "gates.fund_min_beats",
        "news_sentiment": "gates.news_min_sentiment",
        "news_coverage": "gates.news_min_articles",
    }.get(gate_name, "gates.rs_rank_min")


def _reason_to_keys(reason: str) -> list[str]:
    return {
        "stop": ["exit.stop_atr_mult", "exit.stop_type"],
        "stop_gap": ["exit.stop_atr_mult", "gates.adr_max", "universe.min_dollar_vol_20d"],
        "target": ["exit.target_r"],
        "max_hold": ["exit.max_hold_days"],
        "time_stop": ["exit.time_stop_days", "exit.time_stop_min_r"],
        "sma_break": ["exit.exit_on_sma_break", "exit.exit_sma_len"],
        "regime": ["exit.regime_exit", "regime.ma_len"],
    }.get(reason, ["exit.stop_atr_mult"])


def _rejection_to_keys(reason: str) -> list[str]:
    return {
        "gap": ["entry.max_gap_pct"],
        "no_cash": ["pf.risk_pct", "pf.max_weight", "pf.max_positions"],
        "capacity": ["universe.min_dollar_vol_20d", "pf.max_weight"],
        "slots": ["pf.max_positions", "pf.max_new_per_day"],
        "sector_cap": ["pf.max_sector_positions", "universe.exclude_sectors"],
        "bad_stop": ["exit.stop_type", "exit.stop_atr_mult"],
        "no_price": ["universe.min_dollar_vol_20d"],
    }.get(reason, ["pf.max_positions"])
