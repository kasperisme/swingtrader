"""
The LLM half of a trading day.

One agent, one session: assemble the registry its spec allows, hand it its own
book, run the tool loop, and let it place order intents. The agent's final
message becomes the published narrative.

Two things this module deliberately does NOT do:

  - It does not parse trades out of the model's prose. Orders arrive only
    through the ``place_order`` tool, where they are validated the moment they
    are made. An agent that describes a trade in its summary but never called
    the tool has not traded, and the record will show that honestly.
  - It does not force JSON output. The screening agent uses ``request_format
    ="json"`` because it needs a machine-readable verdict; here the structured
    output already happened (in the tool calls), and forcing JSON on the summary
    would only degrade the writing that gets published.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx

from services.agent_core import (
    ToolRegistry,
    build_market_registry,
    run_tool_loop,
    simple_chat,
)

from . import provenance, store
from .broker import Broker
from .roster import AgentSpec, get_spec
from .tools import AccountTools, build_account_registry, build_strategy_registry
from .types import PortfolioSnapshot

log = logging.getLogger(__name__)

_OLLAMA_URL_ENV = "OLLAMA_BASE_URL"

#: Model resolution order. ARENA_MODEL lets the whole competition be moved to a
#: different model in one place — which matters, because changing the model
#: mid-competition invalidates the comparison and should be a deliberate act.
_MODEL_ENVS = ("ARENA_MODEL", "OLLAMA_NARRATIVE_MODEL", "OLLAMA_BLOG_MODEL")
_MODEL_DEFAULT = "glm-5.1:cloud"


def resolve_model(agent: dict[str, Any]) -> str:
    if agent.get("llm_model"):
        return str(agent["llm_model"])
    for env in _MODEL_ENVS:
        value = os.environ.get(env)
        if value:
            return value
    return _MODEL_DEFAULT


def build_registry(spec: AgentSpec, account: AccountTools) -> ToolRegistry:
    """Assemble exactly the tools this agent is allowed to see.

    The shared market registry is built and then FILTERED down to the spec's
    allowlist rather than being extended from empty: that way a tool added to
    ``services/rag/tools.py`` does not silently leak into every arena agent and
    quietly destroy the isolation the experiment depends on.
    """
    registry = ToolRegistry()

    shared = build_market_registry()
    for name in spec.tools:
        tool = shared.get(name)
        if tool is not None:
            registry.add(tool)

    registry.extend(build_strategy_registry(spec.tools))
    registry.extend(build_account_registry(account))

    if spec.include_fmp and os.environ.get("FMP_API_KEY"):
        try:
            from services.agent.fmp_tools import call_fmp_tool, get_fmp_tool_schemas

            schemas = get_fmp_tool_schemas()
            if schemas:
                registry.add_schemas(schemas, call_fmp_tool)
        except Exception as exc:  # a dead MCP must not take the whole run down
            log.warning("arena: FMP tools unavailable for %s: %s", spec.slug, exc)

    missing = [
        t for t in spec.tools if not registry.has(t) and t not in ("fetch_url",)
    ]
    if missing:
        log.warning(
            "arena: %s requests tools that do not exist: %s", spec.slug, missing
        )
    return registry


def _user_prompt(
    agent: dict[str, Any],
    portfolio: PortfolioSnapshot,
    session: date,
    intended_for: date,
    max_rounds: int,
) -> str:
    nav = portfolio.nav
    starting = float(agent.get("starting_cash") or 100_000)
    since = agent.get("funded_on")
    held = (
        ", ".join(
            f"{p.ticker} {'-' if p.is_short else ''}{abs(p.quantity):g}"
            for p in sorted(portfolio.positions, key=lambda x: abs(x.market_value), reverse=True)
        )
        or "nothing — you are all cash"
    )
    order_by = max(4, int(max_rounds * 0.4))
    return f"""
Trading session: {session.isoformat()} has closed. You are deciding for
{intended_for.isoformat()}, where any order you place will fill at the open.

Your account right now:
  NAV        ${nav:,.0f}   (started at ${starting:,.0f}{f", funded {since}" if since else ""})
  Return     {(nav / starting - 1) * 100:+.2f}%
  Cash       ${portfolio.cash:,.0f} ({portfolio.cash / nav * 100 if nav else 0:.0f}% of NAV)
  Positions  {held}

You have {max_rounds} tool-calling rounds this session — one tool call each. Aim
to place your first order by round {order_by} at the latest. Agents that research
until the budget runs out end the day having traded nothing, which is a worse
outcome than a smaller position taken on adequate evidence.

Do your research, decide, place any orders you want filled tomorrow, then write
your summary. Remember that no trade is a valid outcome — but it has to be a
decision you reached, not one the clock made for you.
""".strip()


async def run_decision(
    agent: dict[str, Any],
    *,
    session: date,
    intended_for: date,
    broker: Broker,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run one LLM agent's decision for one session.

    ``session`` is the last closed session (the information the agent has);
    ``intended_for`` is the session its orders fill in. Returns a summary dict
    for the CLI. Failures are recorded on the decision row and returned rather
    than raised — one broken agent must not stop the rest of the roster.
    """
    spec = get_spec(agent.get("strategy_key") or agent["slug"])
    if spec is None:
        raise ValueError(
            f"agent {agent['slug']!r} has strategy_key "
            f"{agent.get('strategy_key')!r} with no matching spec in roster.py"
        )

    model = resolve_model(agent)
    decision = store.open_decision(agent["id"], intended_for, model)
    started = datetime.now(timezone.utc)

    # A re-run supersedes the previous attempt's un-filled orders rather than
    # stacking on top of them.
    if not dry_run:
        voided = store.cancel_pending_for(agent["id"], intended_for)
        if voided:
            log.info("arena: %s — voided %d orders from a prior attempt", agent["slug"], voided)

    portfolio = store.load_portfolio(agent, as_of=session)

    # Warm the price cache for what the agent already holds, so the sizing
    # checks on a closing order never fail for a cache miss.
    held = [p.ticker for p in portfolio.positions]
    if held:
        broker.prices.load(held, session - timedelta(days=30), session)
    reference_prices = {
        t: price
        for t in held
        if (price := broker.prices.last_close_on_or_before(t, session)[0])
    }

    account = AccountTools(
        agent,
        broker=broker,
        portfolio=portfolio,
        decision_id=decision.get("id"),
        intended_for=intended_for,
        reference_prices=reference_prices,
        as_of=session,
    )
    registry = build_registry(spec, account)

    # Every tool call is recorded so the decision can say WHICH screening board,
    # WHICH quote page and WHICH articles it actually read — and link them.
    tool_calls: list[dict[str, Any]] = []
    registry = provenance.wrap_registry(registry, tool_calls)

    nav_at_decision = portfolio.nav
    cash_at_decision = portfolio.cash

    if dry_run:
        return {
            "slug": agent["slug"],
            "dry_run": True,
            "model": model,
            "tools": sorted(registry.names()),
            "nav": round(nav_at_decision, 2),
            "prompt": _user_prompt(
                agent, portfolio, session, intended_for, spec.max_tool_rounds
            ),
        }

    base_url = os.environ.get(_OLLAMA_URL_ENV, "http://localhost:11434").rstrip("/")
    max_rounds = int(agent.get("max_tool_rounds") or spec.max_tool_rounds)

    try:
        async with httpx.AsyncClient() as client:
            final_message, tool_results, rounds = await run_tool_loop(
                client,
                base_url=base_url,
                model=model,
                system=spec.system_prompt,
                user=_user_prompt(agent, portfolio, session, intended_for, max_rounds),
                registry=registry,
                max_rounds=max_rounds,
                options={"num_predict": 2048},
                label=f"Arena/{agent['slug']}",
                # Portfolio and order results MUST NOT be cached: the book
                # changes with every order the agent places, and serving a stale
                # snapshot would let it spend the same cash twice.
                cache_results=False,
            )

            narrative = _clean_narrative(final_message.get("content") or "")
            if not narrative:
                # The model converged (or exhausted its rounds) with an empty
                # message. That happens often enough to plan for, and the
                # narrative is the published half of this product — so ask once
                # more, in a plain one-shot call, using the orders it ACTUALLY
                # placed. It is the same model accounting for its own real
                # actions, not a summary invented on its behalf.
                narrative = _clean_narrative(
                    await _request_narrative(
                        client,
                        base_url=base_url,
                        model=model,
                        spec=spec,
                        account=account,
                        tools_called=sorted(tool_results),
                        label=agent["slug"],
                    )
                )
    except Exception as exc:
        log.exception("arena: %s decision failed", agent["slug"])
        store.close_decision(
            decision["id"],
            {
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}"[:2000],
                "nav_at_decision": round(nav_at_decision, 2),
                "cash_at_decision": round(cash_at_decision, 2),
                "duration_ms": _elapsed_ms(started),
            },
        )
        return {"slug": agent["slug"], "status": "error", "error": str(exc)}

    accepted, rejected = len(account.accepted), len(account.rejected)

    try:
        resources = provenance.derive(tool_calls)
    except Exception as exc:  # provenance is a nice-to-have, never a run-killer
        log.warning("arena: %s provenance failed: %s", agent["slug"], exc)
        resources = []

    store.close_decision(
        decision["id"],
        {
            "status": "ok",
            "narrative": narrative or None,
            "rounds_used": rounds,
            "tools_called": _tool_counts(tool_calls) or None,
            "resources": resources or None,
            "orders_requested": accepted + rejected,
            "orders_accepted": accepted,
            "orders_rejected": rejected,
            "nav_at_decision": round(nav_at_decision, 2),
            "cash_at_decision": round(cash_at_decision, 2),
            "duration_ms": _elapsed_ms(started),
        },
    )

    return {
        "slug": agent["slug"],
        "status": "ok",
        "model": model,
        "rounds": rounds,
        "orders_accepted": accepted,
        "orders_rejected": rejected,
        "tools_called": sorted(tool_results),
        "resources": len(resources),
        "narrative": narrative,
        "duration_s": round((datetime.now(timezone.utc) - started).total_seconds(), 1),
    }


async def _request_narrative(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    model: str,
    spec: AgentSpec,
    account,
    tools_called: list[str],
    label: str,
) -> str:
    """Ask once for the published summary when the tool loop emitted none.

    Deliberately given only what actually happened — the tools consulted and the
    orders the broker accepted or refused. It cannot invent a trade, because the
    trades are listed for it and nothing it writes here can place one.
    """
    def describe(rows: list[dict], kind: str) -> str:
        if not rows:
            return ""
        return "\n".join(
            f"  - {kind}: {r['side']} {float(r['quantity']):g} {r['ticker']}"
            + (f" — {r['reject_reason']}" if r.get("reject_reason") else "")
            + (f" — your reason: {r['thesis']}" if r.get("thesis") else "")
            for r in rows
        )

    placed = describe(account.accepted, "ORDER PLACED")
    refused = describe(account.rejected, "ORDER REJECTED")
    actions = "\n".join(x for x in (placed, refused) if x) or "  - You placed no orders."

    user = f"""
You have finished researching and trading for today. Here is exactly what you did:

Tools you consulted: {', '.join(tools_called) or 'none'}

{actions}

Now write your published summary: 3-6 sentences in plain English covering what you
saw in the data, what you did about it, and what would make you change your mind.
It appears on the public site under your name, for a reader who cannot see your
tool calls. Do not claim any trade that is not listed above. No preamble, no
markdown headings — just the paragraph.
""".strip()

    try:
        return await simple_chat(
            client,
            base_url=base_url,
            model=model,
            system=spec.system_prompt,
            user=user,
            options={"num_predict": 700},
            think=False,
            label=f"Arena/{label} narrative",
        )
    except Exception as exc:
        log.warning("arena: %s narrative fallback failed: %s", label, exc)
        return ""


def _tool_counts(calls: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for c in calls:
        counts[c["name"]] = counts.get(c["name"], 0) + 1
    return counts


def _elapsed_ms(started: datetime) -> int:
    return int((datetime.now(timezone.utc) - started).total_seconds() * 1000)


_MD_EMPHASIS = re.compile(r"(\*\*|__)(.+?)\1", re.S)
_MD_HEADING = re.compile(r"^#{1,6}\s*", re.M)


def _clean_narrative(raw: str) -> str:
    """Strip the wrappers models add and cap the length.

    The narrative is rendered as plain text on the public page, so inline
    markdown has to come off here — models bold their ticker names however
    firmly the prompt asks them not to, and `**LH**` in published prose just
    looks broken. Headings and code fences go the same way.
    """
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1] if "\n" in text else text
        text = text.removesuffix("```").strip()
    for prefix in ("Summary:", "SUMMARY:", "Final answer:", "Narrative:"):
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()
    text = _MD_EMPHASIS.sub(r"\2", text)
    text = _MD_HEADING.sub("", text)
    return text.strip()[:4000]
