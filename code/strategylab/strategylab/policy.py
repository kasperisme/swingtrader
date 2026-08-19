"""The LLM policy — Claude as the experiment designer.

The samplers in `search.py` are good at local refinement and at exploiting a
response surface they have already sampled. What they cannot do is form a
*hypothesis*: read that winners are giving back 70% of their peak gain, connect
that to the trailing-stop parameterisation, and propose the two coordinated
edits that test it. That is the job here.

The policy is deliberately constrained:

* It proposes **patches** (a handful of `key -> value` edits against a named
  base genome), never whole genomes. Patches are auditable, they keep the
  parent link intact for credit assignment, and a partially wrong patch still
  yields a valid experiment because every value is clipped to the space.
* Each proposal must carry a **falsifiable hypothesis** and the metric it
  expects to move. A proposal that cannot be wrong teaches nothing, and the
  hypothesis is what gets stored next to the outcome in the ledger.
* It sees the **diagnostics**, not just the scores — the same findings the
  deterministic operators route on.

The stable half of the prompt (role, principles, the full space spec) is cached;
only the run state changes between calls.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

from .config import LabConfig, load_env
from .genome import Genome, space_spec
from .search import OPERATORS, Proposal

log = logging.getLogger(__name__)

MAX_PATCH_KEYS = 8


SYSTEM = """You are the research policy in a reinforcement-learning loop that \
searches for a deployable swing-trading strategy.

An outer loop repeatedly: (1) asks you for experiments, (2) backtests each one \
over a purged walk-forward on US equities with realistic costs and capacity \
limits, (3) runs a deterministic diagnostic pass, and (4) reports results back \
to you. You never see the sealed out-of-sample vault; it is opened once, at the \
end, for a single finalist.

OBJECTIVE
Maximise the reward: the MEDIAN out-of-sample fold Sharpe, minus explicit \
penalties for dispersion across folds, drawdown beyond budget, turnover beyond \
budget, active-parameter count, left-tail heaviness, and reliance on market beta.
A configuration only ships if it also clears a Deflated-Sharpe gate that is \
adjusted for how many configurations the search has already tried — so every \
experiment you spend raises the bar for the eventual winner. Spend them on \
hypotheses, not on sweeps.

HOW TO THINK ABOUT THIS SEARCH
- The response surface is noisy. A reward difference under roughly 0.15 between \
two genomes on the same folds is not evidence of anything; do not chase it.
- Prefer coordinated edits within one mechanism (all the exit knobs; the gate \
and the ranking weight that feed the same idea) over scattered single-scalar \
nudges. One coherent change per proposal makes the result attributable.
- Diversity across a batch is worth more than eight variations on the current \
best. If several of your proposals would land in the same place, replace them.
- Removing a rule is a legitimate and often superior experiment. Fewer active \
parameters is directly rewarded, and every gate you keep must earn its place.
- Structural moves (a different entry trigger, a different sizing rule, turning \
an overlay on) are yours to make. Numeric fine-tuning is already handled by a \
Parzen-estimator sampler running alongside you — do not duplicate it.

DOMAIN PRINCIPLES THAT ARE NOT NEGOTIABLE
- Exits and position sizing usually dominate entry selection for risk-adjusted \
return. If the diagnostics say the entry finds moves the exit does not bank, \
fix the exit before touching the screen.
- A strategy whose profit comes from one year, one sector, or five trades has \
not been found — it has been fitted. Treat those findings as high priority.
- High beta with a weak alpha t-stat means the equity curve is a levered index \
position. Differentiating the holdings or standing down in weak regimes is the \
fix; more leverage is not.
- Frictions are real. If cost drag is a large share of gross P&L, trading less \
and holding longer is usually worth more than any parameter change.
- A gate that removes almost every candidate is the binding constraint on the \
whole funnel; a gate that removes nothing is dead weight paying a complexity \
cost.

OUTPUT CONTRACT
Return proposals as JSON matching the provided schema. For each one:
- `base`: "best", "current", or an exact genome_hash from the state you were given.
- `patch`: at most 8 `key: value` pairs. Keys MUST come from the search space; \
values are clipped to their declared bounds, so stay inside them.
- `hypothesis`: what you claim will happen and WHY, in mechanism terms.
- `expected_metric`: the single metric you expect to move most.
- `operator_tag`: the closest label from the provided operator list.
Do not restate the state back to me. Do not propose a patch identical to a \
genome already listed as evaluated."""


# Structured outputs require fully closed schemas: no `additionalProperties:
# true`, no array min/max. That rules out a free-form `{key: value}` patch
# object, so a patch travels as a list of typed pairs with the value carried as
# a string and coerced by the dimension it targets — which every dimension type
# in `genome.py` already does safely.
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "reasoning_summary": {
            "type": "string",
            "description": "Two or three sentences on what the evidence says and the "
                           "strategy behind this batch of experiments.",
        },
        "proposals": {
            "type": "array",
            "description": "Exactly the number of experiments requested in the message.",
            "items": {
                "type": "object",
                "properties": {
                    "base": {
                        "type": "string",
                        "description": ('"best", "current", or an exact genome_hash '
                                        'from the state above.'),
                    },
                    "patch": {
                        "type": "array",
                        "description": "At most 8 edits. Every key must exist in the "
                                       "search space; values are clipped to bounds.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "key": {"type": "string"},
                                "value": {
                                    "type": "string",
                                    "description": "Number, true/false, or one of the "
                                                   "declared options — as a string.",
                                },
                            },
                            "required": ["key", "value"],
                            "additionalProperties": False,
                        },
                    },
                    "hypothesis": {"type": "string"},
                    "expected_metric": {"type": "string"},
                    "operator_tag": {"type": "string"},
                },
                "required": ["base", "patch", "hypothesis", "expected_metric", "operator_tag"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["reasoning_summary", "proposals"],
    "additionalProperties": False,
}


@dataclass
class PolicyState:
    iteration: int
    best: list[dict]            # [{hash, reward, metrics, genome, diagnostics_brief}]
    recent: list[dict]          # last N trials, including failures
    operator_table: list[dict]
    baseline: dict | None       # the incumbent NIS Momentum genome's scorecard
    n_trials: int
    notes: list[str]
    leader_tables: dict | None = None   # full diagnostic tables for the #1 genome


class LLMPolicy:
    def __init__(self, cfg: LabConfig):
        self.cfg = cfg
        load_env()
        self.model = os.environ.get("STRATEGYLAB_MODEL") or cfg.llm_model
        self._client = None
        self._space_json = json.dumps(space_spec(), separators=(",", ":"))
        self.last_reasoning = ""

    # ------------------------------------------------------------------
    @property
    def available(self) -> bool:
        load_env()
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return False
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False
        return True

    def _client_or_none(self):
        if self._client is None:
            try:
                import anthropic
                self._client = anthropic.Anthropic()
            except Exception as exc:
                log.warning("Anthropic client unavailable: %s", exc)
                return None
        return self._client

    # ------------------------------------------------------------------
    def propose(self, state: PolicyState, n: int, elites: list[Genome]) -> list[Proposal]:
        client = self._client_or_none()
        if client is None:
            return []

        system = [
            # Stable prefix — cached across the whole run.
            {"type": "text", "text": SYSTEM},
            {"type": "text",
             "text": "SEARCH SPACE (authoritative; every key and bound):\n" + self._space_json,
             "cache_control": {"type": "ephemeral"}},
        ]
        user = self._render_state(state, n)

        try:
            with client.messages.stream(
                model=self.model,
                max_tokens=32000,
                system=system,
                messages=[{"role": "user", "content": user}],
                thinking={"type": "adaptive"},
                output_config={
                    "effort": self.cfg.llm_effort,
                    "format": {"type": "json_schema", "schema": RESPONSE_SCHEMA},
                },
            ) as stream:
                message = stream.get_final_message()
        except Exception as exc:
            log.warning("LLM policy call failed: %s", exc)
            return []

        if getattr(message, "stop_reason", None) == "refusal":
            log.warning("LLM policy request was declined; continuing without it this round")
            return []

        text = next((b.text for b in message.content if b.type == "text"), None)
        if not text:
            return []
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            log.warning("LLM policy returned unparseable JSON: %s", exc)
            return []

        self.last_reasoning = payload.get("reasoning_summary", "")
        return self._to_proposals(payload.get("proposals", [])[: n * 2], state, elites)

    # ------------------------------------------------------------------
    def _to_proposals(self, raw: list[dict], state: PolicyState,
                      elites: list[Genome]) -> list[Proposal]:
        by_hash = {e.hash: e for e in elites}
        best = elites[0] if elites else Genome()
        out: list[Proposal] = []
        for item in raw:
            base_key = str(item.get("base", "best"))
            base = by_hash.get(base_key, best)
            clean = _patch_to_dict(item.get("patch"))
            if not clean:
                continue
            child = base.patched(clean)
            if child.hash == base.hash:
                continue
            tag = str(item.get("operator_tag", "llm"))
            out.append(Proposal(
                genome=child, source="llm",
                operator=tag if tag in OPERATORS else "llm_structural",
                parent_hash=base.hash,
                hypothesis=str(item.get("hypothesis", ""))[:600],
                meta={"expected_metric": str(item.get("expected_metric", ""))[:80],
                      "applied_keys": sorted(k for k in clean if k in child)},
            ))
        return out

    # ------------------------------------------------------------------
    def _render_state(self, s: PolicyState, n: int) -> str:
        lines = [
            f"ITERATION {s.iteration}. Propose exactly {n} experiments.",
            f"Distinct configurations already evaluated: {s.n_trials}. "
            f"(Each one raises the deflated-Sharpe bar the winner must clear.)",
            "",
        ]
        if s.baseline:
            lines += ["INCUMBENT BASELINE (the rules currently in production — beat this):",
                      _fmt_scorecard(s.baseline), ""]

        lines.append("BEST CONFIGURATIONS SO FAR (patch against these by hash):")
        if s.best:
            for b in s.best:
                lines.append(_fmt_scorecard(b, include_hash=True))
                if b.get("diff_from_baseline"):
                    lines.append(f"    changes vs baseline: {b['diff_from_baseline']}")
                if b.get("diagnostics_brief"):
                    lines.append("    diagnostics:")
                    lines += [f"      {ln}" for ln in b["diagnostics_brief"].splitlines()]
        else:
            lines.append("  (none yet — the search has no valid result to build on)")
        lines.append("")

        if s.leader_tables:
            lines += [
                "DIAGNOSTIC TABLES FOR THE LEADER (the raw evidence behind the findings;",
                "bucket tables are quintiles of a per-trade feature — if expectancy_r does",
                "not slope across them, that feature is not separating outcomes):",
                json.dumps(s.leader_tables, separators=(",", ":"), default=str)[:6000],
                "",
            ]

        lines.append("RECENT EXPERIMENTS (what has been tried, including failures):")
        for r in s.recent:
            status = "ok" if r.get("valid") else f"INVALID: {r.get('reason', '')}"
            lines.append(
                f"  [{r.get('source', '?')}/{r.get('operator', '?')}] {r.get('genome_hash')} "
                f"reward={_num(r.get('reward'))} sharpe={_num(r.get('sharpe'))} {status}")
            if r.get("hypothesis"):
                lines.append(f"      hypothesis was: {r['hypothesis'][:200]}")
            if r.get("diff"):
                lines.append(f"      changes: {r['diff'][:300]}")
        lines.append("")

        if s.operator_table:
            lines.append("OPERATOR PERFORMANCE (mean reward improvement over parent):")
            for row in s.operator_table[:12]:
                lines.append(f"  {row['operator']}: n={row['n']} "
                             f"mean={_num(row.get('mean_improvement'))}")
            lines.append("")

        if s.notes:
            lines.append("NOTES FROM THE LOOP:")
            lines += [f"  - {x}" for x in s.notes]
            lines.append("")

        lines.append(f"Valid operator_tag values: {', '.join(OPERATORS)}")
        return "\n".join(lines)


def _patch_to_dict(patch) -> dict:
    """Typed pairs -> a genome patch.

    Unknown keys are dropped rather than fatal: the space is the authority, and
    a partially-wrong patch is still a perfectly usable experiment. Values keep
    their string form because every dimension's `clip` coerces safely from one.
    """
    from .genome import SPACE

    out: dict = {}
    if not isinstance(patch, list):
        return out
    for pair in patch:
        if not isinstance(pair, dict):
            continue
        key = str(pair.get("key", "")).strip()
        if key not in SPACE:
            continue
        out[key] = pair.get("value")
        if len(out) >= MAX_PATCH_KEYS:
            break
    return out


def _num(v, nd: int = 3) -> str:
    try:
        return f"{float(v):.{nd}f}"
    except (TypeError, ValueError):
        return "n/a"


def _fmt_scorecard(b: dict, include_hash: bool = False) -> str:
    m = b.get("metrics", {})
    head = f"  {b.get('genome_hash', '')} " if include_hash else "  "
    folds = b.get("fold_sharpes")
    fold_str = ("  folds=[" + ", ".join(_num(x, 2) for x in folds) + "]") if folds else ""
    return (f"{head}reward={_num(b.get('reward'))}  sharpe={_num(m.get('sharpe'))}"
            f"  maxDD={_num(m.get('max_drawdown'))}  trades={m.get('n_trades')}"
            f"  expectancy={_num(m.get('expectancy_r'), 2)}R"
            f"  turnover={_num(m.get('turnover_annual'), 1)}x"
            f"  exposure={_num(m.get('avg_exposure'), 2)}"
            f"  beta={_num(m.get('beta'), 2)}  alpha_t={_num(m.get('alpha_t'), 2)}{fold_str}")
