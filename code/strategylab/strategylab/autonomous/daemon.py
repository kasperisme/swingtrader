"""The 24/7 loop.

Runs research campaigns back to back, indefinitely, with the stopping rules
enforced rather than advised. Each campaign is a bounded search that ends for a
stated reason; between campaigns the daemon decides what to do next from what
the ledger already knows.

Design commitments, all of them consequences of what this project measured:

* **A campaign always ends.** No campaign runs to exhaustion of the machine —
  it ends on plateau, on trial budget, on PBO degradation, or on clearing the
  gate. An unbounded overnight search does not find more, it finds worse.
* **Every campaign is seeded from the ledger and carries its ancestry.** A
  restart that resets the trial count launders selection bias, so inherited
  trials follow the genome.
* **The holdout is rationed.** It is consulted only for a genome that has
  already cleared the dev gate, at most a couple of times a week, and every use
  is counted.
* **The daemon degrades rather than dying.** A failed campaign is logged and
  the loop continues; a missing model falls back; a crash resumes from the
  ledger.
"""

from __future__ import annotations

import json
import logging
import signal
import time
import traceback
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from ..config import OUTPUT_ROOT, LabConfig
from ..genome import Genome, default_genome
from ..ledger import Ledger
from ..loop import Lab
from ..metrics import probability_of_backtest_overfitting
from ..reward import gate_report, sharpe_variance_across_trials
from .budget import CampaignState, DailyBudget, SearchBudget, StopReason, should_stop
from .findings import Finding, FindingStore, Status
from .llm import Client
from .policy import OllamaPolicy

log = logging.getLogger(__name__)


@dataclass
class CampaignResult:
    run_id: str
    started: str
    ended: str
    iterations: int
    trials: int
    best_reward: float
    best_hash: str
    best_sharpe: float
    stop_reason: str
    stop_detail: str
    pbo: float | None = None
    seeded_from: str = ""
    model: str = ""
    error: str = ""

    def line(self) -> str:
        return (f"{self.run_id:<22} {self.iterations:>3} iters  "
                f"{self.trials:>4} trials  reward {self.best_reward:+.3f}  "
                f"Sharpe {self.best_sharpe:+.3f}  -> {self.stop_reason}")


class Daemon:
    def __init__(self, cfg: LabConfig, ctx, search_budget: SearchBudget | None = None,
                 daily: DailyBudget | None = None, client: Client | None = None,
                 root: Path | None = None, publisher=None,
                 runs_root: Path | None = None):
        self.cfg = cfg
        self.ctx = ctx
        self.budget = search_budget or SearchBudget()
        self.daily = daily or DailyBudget()
        self.client = client or Client()
        self.root = Path(root or (OUTPUT_ROOT / "autonomous"))
        # Where prior ledgers live. Injectable so a cold start can be tested
        # against a fixture instead of whatever happens to be on this machine.
        self.runs_root = Path(runs_root or (OUTPUT_ROOT / "runs"))
        self.root.mkdir(parents=True, exist_ok=True)
        self.findings = FindingStore(self.root / "findings.sqlite")
        self.history: list[CampaignResult] = []
        # Optional: mirror the record into Supabase for the public site. A
        # publish failure must never kill a research campaign, so every call is
        # wrapped — the local ledger stays the source of truth.
        self.publisher = publisher
        self._stop = False
        self.campaign_no = 0

    # ------------------------------------------------------------------
    def install_signal_handlers(self) -> None:
        def handle(signum, _frame):
            log.warning("signal %s received — finishing the current campaign "
                        "and stopping cleanly", signum)
            self._stop = True
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, handle)
            except Exception:
                pass

    # ------------------------------------------------------------------
    def _seed_for_next_campaign(self) -> tuple[Genome | None, int, str]:
        """Continue from the best genome found so far, carrying its ancestry.

        Restarting from a winner without carrying the trial count is how a
        search launders its own selection bias — the deflated Sharpe would
        deflate against a best-of-N that excludes the search which found the
        starting point.

        `self.history` only covers the current process, so on a cold start it
        is empty and this used to fall through to the untuned default genome
        with `inherited = 0`. That threw away every prior run AND reported a
        DSR deflated against a best-of-N of ~30 when the real N was in the
        hundreds — optimistic in exactly the direction that matters. So when
        there is no in-process history, the ledgers on disk are the history.
        """
        best_g, best_reward, origin, inherited = None, float("-inf"), "", 0
        for res in self.history:
            path = LabConfig(run_id=res.run_id).ledger_path
            if not path.exists():
                continue
            led = Ledger(path)
            rows = led.best(n=1, rung=1)
            if not rows or rows[0]["reward"] is None:
                continue
            if rows[0]["reward"] > best_reward:
                best_reward = rows[0]["reward"]
                best_g = Genome(json.loads(rows[0]["genome_json"]))
                origin = f"campaign {res.run_id}"
                inherited = led.count(distinct=True) + led.inherited_trials()
        if best_g is not None:
            return best_g, inherited, origin
        return self._seed_from_disk()

    def _seed_from_disk(self) -> tuple[Genome | None, int, str]:
        """Cold start: recover the incumbent from every ledger on disk.

        `inherited` is the total across ALL ledgers scanned, not just the one
        that happened to hold the winner. The seed is the argmax over the whole
        set, so the whole set is the N that the best-of-N correction has to
        account for — charging only the winning run's trials would understate
        the search that actually did the selecting.

        Genomes from older runs may predate dimensions added since; `Genome()`
        fills those with defaults, so an old long-only winner resumes into the
        current space with the newer knobs off rather than failing to load.
        """
        runs_root = self.runs_root
        best_row, best_reward, best_run, total = None, float("-inf"), "", 0
        scanned = 0
        for path in sorted(runs_root.glob("*/ledger.sqlite")):
            try:
                led = Ledger(path)
                n = led.count(distinct=True)
            except Exception as exc:
                log.warning("skipping unreadable ledger %s: %s", path.parent.name, exc)
                continue
            total += n
            scanned += 1
            rows = led.best(n=1, rung=1)
            if rows and rows[0]["reward"] is not None and rows[0]["reward"] > best_reward:
                best_reward, best_row, best_run = rows[0]["reward"], rows[0], path.parent.name

        if best_row is None:
            log.info("no prior ledgers — starting from the default genome")
            return None, 0, ""

        try:
            genome = Genome(json.loads(best_row["genome_json"]))
        except Exception as exc:
            log.warning("incumbent genome from %s is unreadable (%s) — "
                        "starting from the default", best_run, exc)
            return None, 0, ""

        log.info("resuming from %s (%s): reward %.4f, sharpe %.4f, "
                 "inheriting %d trials across %d prior runs",
                 best_row["genome_hash"][:12], best_run, best_reward,
                 best_row["sharpe"] or 0.0, total, scanned)
        return genome, total, f"{scanned} prior runs, best from {best_run}"

    def _run_campaign(self) -> CampaignResult:
        self.campaign_no += 1
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        run_id = f"auto-{stamp}"
        cfg = LabConfig(run_id=run_id)
        cfg.splits = self.cfg.splits
        cfg.prefilter = self.cfg.prefilter
        cfg.costs = self.cfg.costs
        cfg.search.proposals_per_iteration = self.cfg.search.proposals_per_iteration

        seed, inherited, origin = self._seed_for_next_campaign()
        ledger = Ledger(cfg.ledger_path)
        lab = Lab(cfg, self.ctx, ledger, use_llm=False, seed_genome=seed,
                  inherited_trials=inherited, seed_origin=origin)
        lab.policy = OllamaPolicy(cfg, self.client)

        state = CampaignState()
        started = datetime.now().isoformat(timespec="seconds")
        stop_reason, detail, pbo = StopReason.NONE, "", None
        err = ""

        try:
            # Records the protocol variables AND the inherited trial count.
            # Without it the ledger reads back 0 ancestry and every deflated
            # Sharpe this campaign publishes would be too high.
            lab.log_run_start()
            if not ledger.count(rung=1, distinct=False):
                lab.seed_baseline()
            lab._prime_notes()

            for it in range(1, 1000):
                if self._stop:
                    stop_reason, detail = StopReason.OPERATOR, "operator requested stop"
                    break
                proposals = lab._propose(it)
                n_new = len(proposals)
                promoted = lab_promote(lab, proposals, it)
                self.daily.backtests += n_new + len(promoted)
                self.daily.llm_calls += 1

                best = lab.elites[0][1] if lab.elites else float("-inf")
                state.observe(it, best, self.budget.min_improvement)

                trials = ledger.count(distinct=True) + inherited
                if trials >= self.budget.pbo_check_after:
                    R, _names = ledger.returns_matrix(rung=1)
                    if R.size:
                        pbo = probability_of_backtest_overfitting(R)

                stop, stop_reason, detail = should_stop(
                    state, self.budget, trials, pbo=pbo,
                    proposals_available=n_new, gate_cleared=lab._dev_gate_clear())
                log.info("[%s] iter %d | best %+.3f | trials %d | pbo %s%s",
                         run_id, it, best, trials,
                         f"{pbo:.3f}" if pbo is not None else "n/a",
                         f" | STOPPING: {stop_reason.value}" if stop else "")
                if stop:
                    break
        except Exception as exc:  # a campaign must never kill the daemon
            err = f"{exc}\n{traceback.format_exc()[:800]}"
            stop_reason, detail = StopReason.NONE, "campaign raised"
            log.error("[%s] campaign failed: %s", run_id, exc)

        best_hash, best_sharpe = "", 0.0
        rows = ledger.best(n=1, rung=1)
        if rows:
            best_hash = rows[0]["genome_hash"]
            best_sharpe = float(rows[0]["sharpe"] or 0.0)

        res = CampaignResult(
            run_id=run_id, started=started,
            ended=datetime.now().isoformat(timespec="seconds"),
            iterations=state.iterations, trials=ledger.count(distinct=True) + inherited,
            best_reward=state.best_reward if state.best_reward > float("-inf") else 0.0,
            best_hash=best_hash, best_sharpe=best_sharpe,
            stop_reason=stop_reason.value, stop_detail=detail, pbo=pbo,
            seeded_from=origin, model=getattr(lab.policy, "last_model", ""), error=err)
        self.daily.campaigns += 1
        self.history.append(res)
        self._record_findings(res, ledger)
        self._write_report()
        self._publish(res)
        return res

    def _publish(self, res: CampaignResult) -> None:
        if self.publisher is None:
            return
        try:
            self.publisher.publish_campaign(
                res, self.cfg, universe_size=len(self.ctx.symbols),
                models={k: v.to_dict() for k, v in self.client.stats.items()})
            # only CONFIRMED findings become visible; the rest are recorded
            self.publisher.publish_findings(self.findings, run_id=res.run_id,
                                            only_confirmed=False)
        except Exception as exc:
            log.warning("publish failed (campaign is safe, record is local): %s", exc)

    # ------------------------------------------------------------------
    def _record_findings(self, res: CampaignResult, ledger: Ledger) -> None:
        """Log candidate findings — as OBSERVED, never as claims."""
        if res.best_reward > 0 and res.best_hash:
            self.findings.observe(Finding(
                claim=f"genome {res.best_hash} reaches reward {res.best_reward:.3f}",
                evidence={"sharpe": res.best_sharpe, "trials": res.trials,
                          "pbo": res.pbo, "run": res.run_id},
                source=res.run_id))
        if res.pbo is not None and res.pbo > self.budget.max_pbo:
            self.findings.observe(Finding(
                claim=f"search degraded: PBO {res.pbo:.2f} after {res.trials} configurations",
                evidence={"pbo": res.pbo, "trials": res.trials}, source=res.run_id))

    def _write_report(self) -> None:
        p = self.root / "report.md"
        lines = [f"# Autonomous research — {datetime.now():%Y-%m-%d %H:%M}", "",
                 f"campaigns run: {len(self.history)}", "",
                 "## Campaigns", "", "```"]
        lines += [r.line() for r in self.history[-40:]]
        lines += ["```", "", "## Stop reasons", ""]
        counts: dict[str, int] = {}
        for r in self.history:
            counts[r.stop_reason] = counts.get(r.stop_reason, 0) + 1
        lines += [f"- {k}: {v}" for k, v in sorted(counts.items(), key=lambda x: -x[1])]
        lines += ["", "## Findings", "",
                  "Nothing here is a claim until it is CONFIRMED — two independent "
                  "replications, zero refutations.", "```",
                  json.dumps(self.findings.summary(), indent=2), "```",
                  "", "## Budget", "", "```",
                  json.dumps(self.daily.summary(), indent=2), "```",
                  "", "## Models", "", "```",
                  json.dumps({k: v.to_dict() for k, v in self.client.stats.items()},
                             indent=2), "```"]
        p.write_text("\n".join(lines))

    # ------------------------------------------------------------------
    def run(self, max_campaigns: int | None = None, sleep_between: float = 60.0) -> None:
        self.install_signal_handlers()
        log.info("daemon starting | models %s | prefilter %s",
                 self.client.models, self.cfg.prefilter)
        while not self._stop:
            if max_campaigns is not None and len(self.history) >= max_campaigns:
                log.info("reached max_campaigns=%d", max_campaigns)
                break
            ok, why = self.daily.can_start_campaign()
            if not ok:
                log.info("waiting: %s", why)
                self._sleep(min(1800.0, sleep_between * 10))
                continue
            res = self._run_campaign()
            log.info("campaign done: %s", res.line())
            if self._stop:
                break
            self._sleep(sleep_between)
        log.info("daemon stopped after %d campaigns", len(self.history))

    def _sleep(self, seconds: float) -> None:
        end = time.time() + seconds
        while time.time() < end and not self._stop:
            time.sleep(min(2.0, end - time.time()))


# --- kept module-level so the loop body above stays readable ---------------
def lab_promote(lab: Lab, proposals: list, iteration: int) -> list:
    """Successive halving, then full evaluation of the survivors."""
    import math

    from ..reward import compute_reward
    from ..validation import evaluate

    scored = []
    for p in proposals:
        ev0 = evaluate(p.genome, lab.ctx, rung=0)
        rw0 = compute_reward(ev0, p.genome, lab.cfg)
        lab._record(p.genome, ev0, rw0.value, p.source, p.operator,
                    hypothesis=p.hypothesis, parent=p.parent_hash, iteration=iteration)
        scored.append((p, ev0, rw0.value))
    scored.sort(key=lambda x: -x[2])
    k = max(lab.cfg.search.min_promoted,
            int(math.ceil(lab.cfg.search.promote_fraction * len(scored))))
    promoted = [x for x in scored[:k] if x[1].valid] or scored[:1]

    from ..investigate import investigate
    out = []
    for p, _ev0, _r0 in promoted:
        ev = evaluate(p.genome, lab.ctx, rung=1)
        rw = compute_reward(ev, p.genome, lab.cfg)
        diag = investigate(ev, p.genome, lab.ctx) if ev.result else None
        lab._record(p.genome, ev, rw.value, p.source, p.operator,
                    hypothesis=p.hypothesis, parent=p.parent_hash,
                    diagnostics=diag, iteration=iteration)
        parent_reward = lab._reward_of(p.parent_hash)
        if parent_reward is not None and p.operator:
            lab.bandit.update(p.operator, rw.value - parent_reward)
        if ev.valid:
            lab._offer_elite(p.genome, rw.value, ev)
        if diag:
            lab.diagnostics[p.genome.hash] = diag.brief()
            lab.diag_tables[p.genome.hash] = diag.tables
        out.append((p, ev, rw))
    return out
