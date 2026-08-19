"""Backfill Supabase from the ledgers already on disk.

The lab ran for a long time before it had anywhere to publish to. This walks
`output/runs/*/ledger.sqlite` and writes each run as a campaign plus its top
strategies, so the public record starts complete rather than from today.

One judgement call is baked in: `--top` defaults to 5 per run, not all of them.
Publishing all 743 trials would be publishing the *search*, not the *results* —
and a leaderboard of 743 rows sorted by in-sample reward is precisely the
artefact that makes overfitting look like discovery. The trial COUNT still
travels with every published row, which is the number that matters for
interpreting the Sharpe beside it.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from ..config import OUTPUT_ROOT, LabConfig
from ..genome import Genome
from ..ledger import Ledger
from .publish import ResearchPublisher

log = logging.getLogger(__name__)


def _metrics(row: dict) -> dict:
    try:
        return json.loads(row.get("metrics_json") or "{}")
    except Exception:
        return {}


def backfill_run(pub: ResearchPublisher, ledger_path: Path, cfg: LabConfig,
                 universe_size: int, top: int = 5) -> tuple[str, int]:
    """Publish one run directory. Returns (run_id, strategies written)."""
    run_id = ledger_path.parent.name
    led = Ledger(ledger_path)
    trials = led.count(distinct=True)
    best = led.best(n=top, rung=1)
    if not best:
        return run_id, 0

    ts = [r["ts"] for r in led.rows(limit=100000, order="id ASC")] or [0]
    started = datetime.fromtimestamp(min(ts)).isoformat(timespec="seconds")
    ended = datetime.fromtimestamp(max(ts)).isoformat(timespec="seconds")

    class _Campaign:  # duck-types CampaignResult for the publisher
        pass
    c = _Campaign()
    c.run_id, c.started, c.ended = run_id, started, ended
    c.iterations = max((r.get("iteration") or 0) for r in best)
    c.trials = trials
    c.best_hash = best[0]["genome_hash"]
    c.best_reward = float(best[0]["reward"] or 0.0)
    c.best_sharpe = float(best[0]["sharpe"] or 0.0)
    c.pbo = None
    c.stop_reason = "BACKFILLED"
    c.stop_detail = f"imported from {ledger_path}"
    pub.publish_campaign(c, cfg, universe_size=universe_size, models={})

    n = 0
    for row in best:
        try:
            g = Genome(json.loads(row["genome_json"]))
        except Exception as exc:
            log.warning("%s: unreadable genome %s (%s)", run_id, row["genome_hash"], exc)
            continue
        m = _metrics(row)
        try:
            folds = json.loads(row.get("folds_json") or "[]")
        except Exception:
            folds = []
        pub.publish_strategy(
            g, run_id, dev_metrics=m or {"sharpe": row["sharpe"], "reward": row["reward"]},
            fold_metrics=folds, trials_considered=trials,
            # No stored DSR on these older rows. Publishing 0.0 would read as
            # "measured and worthless"; -1 is out of the metric's range, so the
            # site can render it as "not computed" and never as a pass.
            deflated_sharpe=float(m.get("deflated_sharpe", -1.0)),
            pbo=m.get("pbo"), gate_passed=False,
            gate_failures=["backfilled: gate never evaluated"],
            changes=row.get("reason") or "")
        n += 1
    return run_id, n


def backfill_all(pub: ResearchPublisher, cfg: LabConfig, universe_size: int,
                 root: Path | None = None, top: int = 5) -> dict:
    runs_root = Path(root or (OUTPUT_ROOT / "runs"))
    out: dict[str, int] = {}
    for led in sorted(runs_root.glob("*/ledger.sqlite")):
        try:
            run_id, n = backfill_run(pub, led, cfg, universe_size, top=top)
            out[run_id] = n
        except Exception as exc:
            log.warning("skipped %s: %s", led.parent.name, exc)
            out[led.parent.name] = 0
    return out
