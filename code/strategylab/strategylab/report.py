"""Run report — what the search did, and whether to believe it."""

from __future__ import annotations

import json
from datetime import date

import numpy as np

from .config import LabConfig
from .genome import DEFAULTS, Genome
from .ledger import Ledger


def run_report(cfg: LabConfig, ledger: Ledger, final: dict | None = None) -> str:
    s = ledger.summary()
    best = ledger.best(n=10, rung=1)
    base = Genome(DEFAULTS)

    started = ledger.conn.execute(
        "SELECT payload FROM events WHERE kind='run_started' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    universe = ""
    seed_note = ""
    if started:
        try:
            ev = json.loads(started[0])
            universe = f" · universe {ev.get('universe_loaded')} names"
            if ev.get("seed_genome"):
                seed_note = (f"\n> Continued from {ev.get('seed_origin')}, carrying "
                             f"**{ev.get('inherited_trials')}** inherited configurations "
                             "into the deflated-Sharpe trial count.\n")
        except Exception:
            pass

    lines = [
        f"# strategylab run `{cfg.run_id}`",
        "",
        f"{date.today().isoformat()} · protocol `{cfg.protocol_version}` · "
        f"dev {cfg.splits.dev_start}→{cfg.splits.dev_end} · "
        f"vault {cfg.splits.vault_start}→{cfg.splits.vault_end}{universe}",
        seed_note,
        "",
        "## Search budget",
        "",
        f"- distinct configurations: **{s['genomes_distinct']}**",
        f"- evaluations: {s['rung0']} screening (rung 0), {s['rung1']} full walk-forward (rung 1)",
        f"- vault opened: {'yes' if s['vault_opened'] else 'no'}",
        "",
        "## Leaderboard (dev)",
        "",
        "| rank | genome | reward | Sharpe | maxDD | trades | expectancy | source |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for i, row in enumerate(best, 1):
        m = json.loads(row["metrics_json"] or "{}")
        lines.append(
            f"| {i} | `{row['genome_hash']}` | {_n(row['reward'])} | {_n(m.get('sharpe'))} | "
            f"{_pct(m.get('max_drawdown'))} | {m.get('n_trades', '—')} | "
            f"{_n(m.get('expectancy_r'), 2)}R | {row['source']} |")

    if best:
        top = Genome(json.loads(best[0]["genome_json"]))
        lines += ["", "## What the winner changed", "", "```",
                  top.describe_diff(base).replace("; ", "\n") or "(nothing)", "```"]
        diag = best[0].get("diag_json")
        if diag:
            try:
                lines += ["", "## Open findings on the winner", "", "```",
                          json.loads(diag).get("brief", ""), "```"]
            except Exception:
                pass

    stats = ledger.operator_stats(rung=1)
    if stats:
        lines += ["", "## Which move types paid off", "",
                  "| operator | trials | mean reward | valid rate |", "|---|---|---|---|"]
        for op, st in sorted(stats.items(), key=lambda kv: -kv[1]["mean"]):
            lines.append(f"| {op} | {st['n']} | {_n(st['mean'])} | {_pct(st['valid_rate'])} |")

    if final:
        gate = final.get("final_gate") or final.get("dev_gate") or {}
        lines += ["", "## Verdict", "",
                  ("**Deployable.**" if final.get("deployable")
                   else f"**Not deployable** — failed: {', '.join(gate.get('failed', [])) or 'n/a'}"),
                  "",
                  f"- Deflated Sharpe: {_n(gate.get('deflated_sharpe'))} "
                  f"(against {final.get('n_trials')} configurations tried)",
                  f"- PBO: {_n(final.get('pbo'))} over {final.get('pbo_sample_size', 0)} configurations",
                  ]
        if final.get("vault_metrics"):
            vm = final["vault_metrics"]
            lines.append(f"- Vault Sharpe: {_n(vm.get('sharpe'))}, "
                         f"maxDD {_pct(vm.get('max_drawdown'))}, trades {vm.get('n_trades')}")

    return "\n".join(lines)


def _n(v, nd: int = 3) -> str:
    try:
        f = float(v)
        return f"{f:.{nd}f}" if np.isfinite(f) else "—"
    except (TypeError, ValueError):
        return "—"


def _pct(v) -> str:
    try:
        f = float(v)
        return f"{f:.1%}" if np.isfinite(f) else "—"
    except (TypeError, ValueError):
        return "—"
