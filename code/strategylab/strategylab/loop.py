"""The search loop — propose, evaluate, investigate, learn, repeat.

One iteration:

    1. assemble state          elites, recent failures, operator statistics
    2. propose                 LLM hypotheses + TPE exploitation + bandit-chosen
                               mutations + a random draw, deduplicated
    3. screen (rung 0)         one fold, capped universe — cheap
    4. promote (rung 1)        the survivors get the full purged walk-forward
    5. investigate             deterministic diagnostics on the promoted set
    6. learn                   credit the operator with its improvement over the
                               parent, write everything to the ledger
    7. gate                    if the leader clears every dev criterion, stop

The successive-halving step in 3-4 is what makes the budget go far: most
proposals are eliminated at a quarter of the cost, so the expensive evaluation
is spent almost entirely on candidates with a chance.

The vault is never touched here. `finalize()` opens it once, for one genome,
after the search has stopped.
"""

from __future__ import annotations

import json
import logging
import math
import random
import time
from dataclasses import dataclass, field

import numpy as np

from .config import LabConfig
from .genome import Genome, default_genome, random_genome
from .investigate import investigate
from .ledger import Ledger, Trial
from .metrics import probability_of_backtest_overfitting
from .policy import LLMPolicy, PolicyState
from .reward import compute_reward, gate_report, sharpe_variance_across_trials
from .search import (OPERATORS, OperatorBandit, Proposal, TPESampler, apply_operator,
                     dedupe, diversify_against)
from .validation import DataContext, Evaluation, evaluate, evaluate_vault

log = logging.getLogger(__name__)


@dataclass
class IterationReport:
    iteration: int
    proposed: int
    screened: int
    promoted: int
    best_reward: float
    best_hash: str
    elapsed_s: float
    sources: dict = field(default_factory=dict)
    llm_note: str = ""


class Lab:
    def __init__(self, cfg: LabConfig, ctx: DataContext, ledger: Ledger | None = None,
                 use_llm: bool = True, seed_genome: Genome | None = None,
                 inherited_trials: int = 0, seed_origin: str = ""):
        self.cfg = cfg
        # Seeding from a previous run's winner is legitimate, but that winner is
        # already the survivor of however many configurations produced it. If the
        # new run reports its own trial count, the deflated Sharpe is computed
        # against a best-of-N that excludes the search which found the starting
        # point — laundering the selection bias by restarting. So the ancestry
        # is carried and added back at finalisation.
        self.seed_genome = seed_genome
        self.inherited_trials = int(inherited_trials)
        self.seed_origin = seed_origin
        self.ctx = ctx
        self.ledger = ledger or Ledger(cfg.ledger_path)
        self.rng = random.Random(cfg.seed)
        self.bandit = OperatorBandit(c=cfg.search.ucb_c)
        self.bandit.load(self.ledger.operator_stats(rung=1))
        self.tpe = TPESampler(gamma=cfg.search.tpe_gamma,
                              n_candidates=cfg.search.tpe_candidates)
        self.policy = LLMPolicy(cfg) if use_llm else None
        self.seen: set[str] = set()
        self.elites: list[tuple[Genome, float, Evaluation | None]] = []
        self.diagnostics: dict[str, str] = {}
        self.diag_tables: dict[str, dict] = {}
        self.baseline_card: dict | None = None
        self.notes: list[str] = []
        self._restore()

    # ------------------------------------------------------------------
    def _restore(self) -> None:
        """Resume from an existing ledger so a run can be stopped and continued."""
        for row in self.ledger.rows(rung=None, limit=100_000, order="id ASC"):
            self.seen.add(row["genome_hash"])
        for row in self.ledger.best(n=12, rung=1):
            g = Genome(json.loads(row["genome_json"]))
            # Rehydrate the metrics too. Without them a resumed run hands the
            # policy elites with empty scorecards — it would be reasoning about
            # its own best configurations with the evidence stripped out.
            ev = Evaluation(row["genome_hash"], 1, True)
            try:
                ev.metrics = json.loads(row["metrics_json"] or "{}")
                ev.fold_metrics = json.loads(row["folds_json"] or "[]")
            except Exception:
                pass
            # Restore the recorded return series too. Without it `finalize`
            # re-runs the backtest against today's price cache, which is not
            # necessarily the universe the search actually used.
            ev.daily_returns = self.ledger.returns_for(row["genome_hash"], 1)
            self.elites.append((g, float(row["reward"] or -9e9), ev))
            if row.get("diag_json"):
                try:
                    d = json.loads(row["diag_json"])
                    self.diagnostics[g.hash] = d.get("brief", "")
                    self.diag_tables[g.hash] = d.get("tables", {})
                except Exception:
                    pass
        if self.elites:
            log.info("resumed with %d known genomes, best reward %.3f",
                     len(self.seen), self.elites[0][1])

    # ------------------------------------------------------------------
    def n_trials(self) -> int:
        """Configurations this result was selected from, ancestry included.

        Every best-of-N correction has to charge the *whole* search, not just
        the current process's slice of it. Two call sites used to pass the
        bare `count(distinct=True)`, which made the deflated Sharpe higher than
        it should be and the deploy gate correspondingly easier to clear —
        biased in the one direction that flatters the strategy.
        """
        return self.ledger.count(distinct=True) + self.ledger.inherited_trials()

    def seed_baseline(self) -> Evaluation:
        """Evaluate the starting genome first.

        Everything afterwards is measured against this. A search with no
        baseline can report a Sharpe of 1.2 and never notice that the rules it
        started from already scored 1.3.
        """
        g = self.seed_genome or default_genome()
        ev = evaluate(g, self.ctx, rung=1)
        rw = compute_reward(ev, g, self.cfg)
        diag = investigate(ev, g, self.ctx) if ev.result else None
        origin = (f"Seeded from {self.seed_origin} — already the survivor of "
                  f"{self.inherited_trials} configurations."
                  if self.seed_genome is not None else
                  "Incumbent NIS Momentum rules, traded with an ATR stop.")
        self._record(g, ev, rw.value, "seed", "baseline",
                     hypothesis=origin, diagnostics=diag, iteration=0)
        if ev.valid:
            self._offer_elite(g, rw.value, ev)
        self.baseline_card = self._scorecard(g, rw.value, ev)
        log.info("baseline: reward %.3f sharpe %.2f (%s)", rw.value,
                 ev.metrics.get("sharpe", 0.0), ev.reason or "valid")
        return ev

    # ------------------------------------------------------------------
    def run(self, iterations: int, on_iteration=None) -> list[IterationReport]:
        reports: list[IterationReport] = []
        # The loaded universe is a protocol variable the genome cannot see, and
        # results are materially sensitive to it — the incumbent scores Sharpe
        # 0.25 on the 600 most liquid US names and roughly 0 on the top 800.
        # Recording it is what makes two runs comparable at all.
        self.ledger.log_event("run_started", {
            "universe_loaded": len(self.ctx.panel.symbols),
            "sessions": int(len(self.ctx.dates)),
            "dev": [self.cfg.splits.dev_start, self.cfg.splits.dev_end],
            "vault": [self.cfg.splits.vault_start, self.cfg.splits.vault_end],
            "protocol_version": self.cfg.protocol_version,
            "benchmark": self.cfg.benchmark,
            "llm": bool(self.policy and self.policy.available),
            "seed_genome": self.seed_genome.hash if self.seed_genome else None,
            "seed_origin": self.seed_origin,
            "inherited_trials": self.inherited_trials,
        })
        if not self.ledger.count(rung=1, distinct=False):
            self.seed_baseline()
        self._prime_notes()

        for it in range(1, iterations + 1):
            t0 = time.time()
            proposals = self._propose(it)
            if not proposals:
                log.warning("iteration %d produced no new proposals — space may be "
                            "exhausted around the current elites", it)
                break

            # ---- rung 0: cheap screen -----------------------------------
            screened: list[tuple[Proposal, Evaluation, float]] = []
            for p in proposals:
                ev0 = evaluate(p.genome, self.ctx, rung=0)
                rw0 = compute_reward(ev0, p.genome, self.cfg)
                self._record(p.genome, ev0, rw0.value, p.source, p.operator,
                             hypothesis=p.hypothesis, parent=p.parent_hash, iteration=it)
                screened.append((p, ev0, rw0.value))

            # ---- successive halving -------------------------------------
            screened.sort(key=lambda x: -x[2])
            k = max(self.cfg.search.min_promoted,
                    int(math.ceil(self.cfg.search.promote_fraction * len(screened))))
            promoted = [x for x in screened[:k] if x[1].valid] or screened[:1]

            # ---- rung 1: the real evaluation ----------------------------
            for p, _ev0, _r0 in promoted:
                ev = evaluate(p.genome, self.ctx, rung=1)
                rw = compute_reward(ev, p.genome, self.cfg)
                diag = investigate(ev, p.genome, self.ctx) if ev.result else None
                self._record(p.genome, ev, rw.value, p.source, p.operator,
                             hypothesis=p.hypothesis, parent=p.parent_hash,
                             diagnostics=diag, iteration=it)

                parent_reward = self._reward_of(p.parent_hash)
                if parent_reward is not None and p.operator:
                    self.bandit.update(p.operator, rw.value - parent_reward)
                if ev.valid:
                    self._offer_elite(p.genome, rw.value, ev)
                if diag:
                    self.diagnostics[p.genome.hash] = diag.brief()
                    self.diag_tables[p.genome.hash] = diag.tables

            best_g, best_r = (self.elites[0][0], self.elites[0][1]) if self.elites else (None, float("nan"))
            rep = IterationReport(
                iteration=it, proposed=len(proposals), screened=len(screened),
                promoted=len(promoted), best_reward=best_r,
                best_hash=best_g.hash if best_g else "",
                elapsed_s=time.time() - t0,
                sources=_count(p.source for p in proposals),
                llm_note=(self.policy.last_reasoning if self.policy else ""),
            )
            reports.append(rep)
            log.info("iter %d: %d proposed -> %d promoted | best reward %.3f (%s) | %.1fs",
                     it, rep.proposed, rep.promoted, rep.best_reward, rep.best_hash,
                     rep.elapsed_s)
            if on_iteration:
                on_iteration(rep)

            if self._dev_gate_clear():
                log.info("dev acceptance gate cleared at iteration %d — stopping search", it)
                break

        return reports

    # ------------------------------------------------------------------
    def _propose(self, iteration: int) -> list[Proposal]:
        cfg = self.cfg.search
        n = cfg.proposals_per_iteration
        elites = [g for g, _, _ in self.elites] or [default_genome()]
        pool: list[Proposal] = []

        n_llm = int(round(n * cfg.mix_llm))
        n_tpe = int(round(n * cfg.mix_surrogate))
        n_mut = int(round(n * cfg.mix_mutation))
        n_rand = max(1, n - n_llm - n_tpe - n_mut)

        # ---- LLM: hypothesis-driven, structural ------------------------
        if self.policy and self.policy.available and n_llm > 0:
            state = PolicyState(
                iteration=iteration,
                best=[self._scorecard(g, r, ev, brief=True)
                      for g, r, ev in self.elites[:cfg.llm_context_elites]],
                recent=self._recent_for_policy(cfg.llm_context_recent),
                operator_table=self.bandit.table(),
                baseline=self.baseline_card,
                n_trials=self.n_trials(),
                notes=self.notes,
                leader_tables=self.diag_tables.get(self.elites[0][0].hash) if self.elites else None,
            )
            try:
                pool += self.policy.propose(state, n_llm, elites)
            except Exception as exc:
                log.warning("LLM policy failed this iteration: %s", exc)

        # ---- TPE: exploit the observed response surface ----------------
        if n_tpe > 0:
            obs = self._observations()
            for g in self.tpe.propose(obs, self.rng, n_tpe):
                pool.append(Proposal(genome=g, source="tpe", operator="tpe_surrogate",
                                     parent_hash=None,
                                     hypothesis="Parzen-estimator draw maximising the "
                                                "good/bad density ratio."))

        # ---- Mutation: bandit-selected local moves ----------------------
        for _ in range(n_mut):
            parent, _r, _ev = self.rng.choice(self.elites) if self.elites else (default_genome(), 0.0, None)
            op = self.bandit.select(self.rng)
            ctx = {"direction_keys": self._direction_keys(parent.hash)}
            # Anneal the step: coarse early, fine once the surface is mapped.
            strength = 0.28 if iteration <= 3 else max(0.08, 0.28 * (0.92 ** iteration))
            child = apply_operator(parent, op, self.rng, strength, ctx, elites)
            pool.append(Proposal(genome=child, source="mutate", operator=op,
                                 parent_hash=parent.hash,
                                 hypothesis=f"Bandit-selected `{op}` on {parent.hash}."))

        # ---- Random restarts: keep the search from collapsing -----------
        # A uniform draw over 73 dimensions is almost surely not a strategy —
        # it trades twice or never, fails the validity checks, and buys no
        # information. So a "random" proposal is a WIDE perturbation from a
        # random elite (a random restart in the classical sense), with an
        # occasional true uniform draw to keep the space from closing over.
        for _ in range(n_rand):
            if self.elites and self.rng.random() < 0.8:
                parent = self.rng.choice(self.elites)[0]
                child = parent
                for _ in range(3):
                    child = apply_operator(child, self.rng.choice(OPERATORS), self.rng,
                                           strength=0.55, pool=elites)
                pool.append(Proposal(genome=child, source="random", operator="restart",
                                     parent_hash=parent.hash,
                                     hypothesis="Wide random restart from an elite — "
                                                "coverage against premature convergence."))
            else:
                pool.append(Proposal(genome=random_genome(self.rng), source="random",
                                     operator="uniform", parent_hash=None,
                                     hypothesis="Uniform draw over the whole space."))

        pool = dedupe(pool, self.seen)
        pool = diversify_against(pool, elites)
        return pool[: n * 2]

    # ------------------------------------------------------------------
    def _record(self, g: Genome, ev: Evaluation, reward: float, source: str,
                operator: str, hypothesis: str = "", parent: str | None = None,
                diagnostics=None, iteration: int = 0) -> None:
        diag_payload = None
        if diagnostics is not None:
            diag_payload = diagnostics.to_dict()
            diag_payload["brief"] = diagnostics.brief()
        self.ledger.record(Trial(
            genome=g, rung=ev.rung, valid=ev.valid, reward=reward,
            sharpe=float(ev.metrics.get("sharpe", 0.0)), metrics=ev.metrics,
            folds=ev.fold_metrics, diagnostics=diag_payload, reason=ev.reason,
            parent_hash=parent, operator=operator, source=source,
            hypothesis=hypothesis, iteration=iteration,
            returns=ev.daily_returns if ev.rung == 1 else None,
            dates=ev.dates if ev.rung == 1 else None,
        ))
        self.seen.add(g.hash)

    def _offer_elite(self, g: Genome, reward: float, ev: Evaluation) -> None:
        self.elites = [e for e in self.elites if e[0].hash != g.hash]
        self.elites.append((g, reward, ev))
        self.elites.sort(key=lambda e: -e[1])
        self.elites = self.elites[:12]

    def _reward_of(self, genome_hash: str | None) -> float | None:
        if not genome_hash:
            return None
        for row in self.ledger.conn.execute(
                "SELECT reward FROM trials WHERE genome_hash=? AND rung=1 "
                "ORDER BY reward DESC LIMIT 1", (genome_hash,)).fetchall():
            return float(row[0]) if row[0] is not None else None
        return None

    def _observations(self) -> list[tuple[Genome, float]]:
        out = []
        for row in self.ledger.rows(rung=1, valid_only=True, order="reward DESC", limit=400):
            try:
                out.append((Genome(json.loads(row["genome_json"])), float(row["reward"])))
            except Exception:
                continue
        return out

    def _direction_keys(self, genome_hash: str) -> list[str]:
        """Genome keys the diagnostics pointed at for this genome."""
        row = self.ledger.conn.execute(
            "SELECT diag_json FROM trials WHERE genome_hash=? AND diag_json IS NOT NULL "
            "ORDER BY id DESC LIMIT 1", (genome_hash,)).fetchone()
        if not row or not row[0]:
            return []
        try:
            d = json.loads(row[0])
        except Exception:
            return []
        keys: list[str] = []
        for f in d.get("findings", []):
            if f.get("severity") in {"high", "medium"}:
                keys.extend(f.get("direction", []))
        return list(dict.fromkeys(keys))

    def _recent_for_policy(self, n: int) -> list[dict]:
        base = default_genome()
        out = []
        for row in self.ledger.recent(n, rung=1):
            try:
                g = Genome(json.loads(row["genome_json"]))
                diff = g.describe_diff(base)
            except Exception:
                diff = ""
            out.append({
                "genome_hash": row["genome_hash"], "reward": row["reward"],
                "sharpe": row["sharpe"], "valid": bool(row["valid"]),
                "reason": row["reason"], "source": row["source"],
                "operator": row["operator"], "hypothesis": row["hypothesis"],
                "diff": diff,
            })
        return out

    def _scorecard(self, g: Genome, reward: float, ev: Evaluation | None,
                   brief: bool = False) -> dict:
        card = {"genome_hash": g.hash, "reward": reward,
                "metrics": ev.metrics if ev else {},
                "fold_sharpes": [f["sharpe"] for f in ev.fold_metrics] if ev else []}
        if brief:
            card["diff_from_baseline"] = g.describe_diff(default_genome())[:700]
            card["diagnostics_brief"] = self.diagnostics.get(g.hash, "")
        return card

    def _prime_notes(self) -> None:
        self.notes = [
            (f"You are CONTINUING from {self.seed_origin}, a genome that is already the "
             f"best of {self.inherited_trials} configurations. Incremental tweaking of it "
             "is unlikely to pay — the local neighbourhood has been searched. Spend "
             "proposals on mechanisms it has NOT tried."
             if self.seed_genome is not None else
             "You are starting from the incumbent production rules."),
            f"Dev window {self.cfg.splits.dev_start}..{self.cfg.splits.dev_end}; the vault "
            f"({self.cfg.splits.vault_start}..{self.cfg.splits.vault_end}) is sealed and you "
            "will not see it.",
            f"Costs charged per side: {self.cfg.costs.slippage_bps + self.cfg.costs.spread_bps:.0f}bps "
            f"slippage+spread, {self.cfg.costs.commission_bps:.0f}bps commission, plus market "
            f"impact; fills are capped at {self.cfg.costs.max_adv_participation:.0%} of 20d ADV.",
            f"Reward budgets: drawdown {self.cfg.reward.dd_budget:.0%}, turnover "
            f"{self.cfg.reward.turnover_budget:.0f}x/yr. Exceeding them is penalised, staying "
            "inside them is free.",
            f"The loaded universe is the {len(self.ctx.panel.symbols)} most liquid US "
            "names; `universe.max_names` and the liquidity floor select from within it. "
            "Results are sensitive to this — a wider universe admits less liquid names "
            "where momentum survives costs less well.",
            "A SHORT SLEEVE is available (`short.*`). It is off in the incumbent and "
            "costs roughly 15 active parameters of complexity when switched on, so it "
            "must earn that back. The case for it: two of the five dev folds are bear "
            "regimes where a long-only book can only stand aside, and standing aside "
            "earns nothing. The case against: borrow is charged daily (floored at 25bps "
            "annual), losses are unbounded, and covering into a rally is where short "
            "books give back a year in a fortnight — `short.cover_on_regime` exists for "
            "exactly that.",
            "Overlay availability is enforced: a genome that switches on the fundamentals "
            "or news gate when that data is absent (or empty for the evaluation window) is "
            "returned INVALID, not silently evaluated with the gate doing nothing. The news "
            "overlay only has scored data from 2025 onward, so it cannot be used on the dev "
            "window at all — do not spend proposals on it.",
        ]

    # ------------------------------------------------------------------
    def _dev_gate_clear(self) -> bool:
        if not self.elites:
            return False
        g, _r, ev = self.elites[0]
        if ev is None or ev.daily_returns is None:
            return False
        rep = gate_report(ev, self.cfg, n_trials=self.n_trials(),
                          sr_variance=sharpe_variance_across_trials(self.ledger.sharpes(1)))
        return bool(rep["pass"])

    # ------------------------------------------------------------------
    def finalize(self, open_vault: bool = True) -> dict:
        """Score the leader honestly, then open the vault once.

        Everything selection-bias related is computed here rather than during
        the search, because it depends on the FINAL trial count — the number of
        configurations the winner had to beat.
        """
        if not self.elites:
            return {"error": "no valid genome to finalise"}
        g, reward, ev = self.elites[0]
        recomputed = False
        if ev is None or ev.daily_returns is None:
            # Only when the ledger has no stored series — and say so, because a
            # recomputed evaluation is not comparable to the search's own.
            log.warning("no stored return series for %s — re-evaluating against the "
                        "CURRENT price cache; numbers may differ from the search", g.hash)
            ev = evaluate(g, self.ctx, rung=1)
            recomputed = True

        # Own trials PLUS the ancestry that produced the starting point.
        own_trials = self.ledger.count(distinct=True)
        inherited = self.ledger.inherited_trials()
        n_trials = self.n_trials()
        sr_var = sharpe_variance_across_trials(self.ledger.sharpes(1))

        R, names = self.ledger.returns_matrix(rung=1)
        pbo = probability_of_backtest_overfitting(R) if R.size else float("nan")

        dev_gate = gate_report(ev, self.cfg, n_trials, sr_var, pbo=pbo)

        out = {
            "genome_hash": g.hash,
            "metrics_recomputed": recomputed,
            "genome": dict(g),
            "reward": reward,
            "dev_metrics": ev.metrics,
            "fold_metrics": ev.fold_metrics,
            "n_trials": n_trials,
            "own_trials": own_trials,
            "inherited_trials": inherited,
            "sharpe_variance_across_trials": sr_var,
            "pbo": pbo,
            "pbo_sample_size": int(R.shape[1]) if R.size else 0,
            "dev_gate": dev_gate,
            "diagnostics": self.diagnostics.get(g.hash, ""),
            "operator_table": self.bandit.table(),
            "ledger": self.ledger.summary(),
        }

        if open_vault and dev_gate["pass"]:
            self.ledger.log_event("vault_opened", {"genome_hash": g.hash, "n_trials": n_trials})
            vev = evaluate_vault(g, self.ctx)
            self._record(g, vev, reward, "final", "vault", hypothesis="sealed out-of-sample test")
            out["vault_metrics"] = vev.metrics
            out["vault_valid"] = vev.valid
            out["final_gate"] = gate_report(ev, self.cfg, n_trials, sr_var, pbo=pbo, vault=vev)
            out["deployable"] = bool(out["final_gate"]["pass"])
        else:
            out["deployable"] = False
            out["vault_status"] = ("not opened — dev gate not cleared"
                                   if not dev_gate["pass"] else "not opened by request")
        return out


def _count(items) -> dict:
    out: dict[str, int] = {}
    for x in items:
        out[x] = out.get(x, 0) + 1
    return out
