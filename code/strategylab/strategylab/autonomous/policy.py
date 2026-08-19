"""The proposal policy, backed by Ollama.

Reuses the prompt, schema and patch-validation from `strategylab.policy` — the
parts that were tuned against real runs — and swaps only the transport. What
changes for a local/hosted open model rather than a frontier one:

* the schema is rendered into the prompt as well as sent as `format`, because
  hosted Ollama models ignore the field;
* the reply is validated and repaired here, never trusted;
* the current VALUE of every mentioned key is included alongside its range.
  Without that, models read the range bounds as the current setting and propose
  moves relative to a value that does not exist.
"""

from __future__ import annotations

import logging

from ..genome import SPACE, Genome
from ..policy import RESPONSE_SCHEMA, SYSTEM, LLMPolicy, PolicyState, _patch_to_dict
from ..search import OPERATORS, Proposal
from .llm import Client

log = logging.getLogger(__name__)


class OllamaPolicy(LLMPolicy):
    """Drop-in replacement for the Anthropic-backed policy."""

    def __init__(self, cfg, client: Client | None = None):
        super().__init__(cfg)
        self.client = client or Client()
        self.last_model = ""

    @property
    def available(self) -> bool:
        return self.client.api.available()

    def _current_values(self, g: Genome, keys: list[str]) -> str:
        rows = []
        for k in keys:
            d = SPACE[k]
            if hasattr(d, "options"):
                rng = "{" + ", ".join(map(str, d.options)) + "}"
            elif hasattr(d, "lo"):
                rng = f"{d.lo}..{d.hi}"
            else:
                rng = "true/false"
            cur = g[k]
            cur = f"{cur:.4g}" if isinstance(cur, float) else str(cur)
            rows.append(f"  {k:<32} {rng:<26} now={cur}")
        return "\n".join(rows)

    def propose(self, state: PolicyState, n: int, elites: list[Genome]) -> list[Proposal]:
        if not self.available:
            return []
        base = elites[0] if elites else Genome()

        # Only the keys the diagnostics actually point at, with their current
        # values. The full 102-dimension space in every prompt buries the two
        # or three knobs that matter.
        keys: list[str] = []
        for card in state.best[:2]:
            for line in (card.get("diagnostics_brief") or "").splitlines():
                if line.strip().startswith("move:"):
                    keys += [k.strip() for k in line.split("move:", 1)[1].split(",")]
        keys = [k for k in dict.fromkeys(keys) if k in SPACE][:14]
        if len(keys) < 6:
            keys += [k for k in ("exit.stop_atr_mult", "exit.max_hold_days",
                                 "exit.target_r", "pf.max_positions", "pf.risk_pct",
                                 "pf.max_gross_exposure", "gates.rs_rank_min",
                                 "entry.type") if k not in keys]
            keys = keys[:14]

        prompt = (
            f"{self._render_state(state, n)}\n\n"
            f"KEYS IN SCOPE (range, and the CURRENT value of the base genome):\n"
            f"{self._current_values(base, keys)}\n\n"
            f"Propose exactly {n} experiments. `base` must be one of the genome "
            f"hashes listed above. Every patch key must come from the list above, "
            f"and every value must sit inside its stated range."
        )
        res = self.client.complete(prompt, RESPONSE_SCHEMA, system=SYSTEM,
                                   temperature=0.6)
        self.last_model = res.model
        if not res.ok:
            log.warning("policy call failed: %s", res.error)
            return []
        self.last_reasoning = str(res.data.get("reasoning_summary", ""))[:600]
        raw = res.data.get("proposals") or []
        return self._to_proposals(raw[: n * 2], state, elites)
