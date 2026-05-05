"""Shared Ollama tool-calling agent core.

Reusable plumbing for any agent that calls Ollama with tools: a streaming
+ retrying chat loop, a tool registry that's extendable per-agent, and a
default market-wide tool set built on services/rag.

Typical use:

    from services.agent_core import (
        build_market_registry,
        build_user_registry,
        run_tool_loop,
    )

    registry = build_market_registry()
    registry.extend(build_user_registry(user_id))
    # registry.add_function("my_extra_tool", my_fn, description="...", parameters={...})

    async with httpx.AsyncClient() as client:
        final_message, tool_results, rounds_used = await run_tool_loop(
            client,
            base_url=OLLAMA_BASE_URL,
            model=OLLAMA_MODEL,
            system=SYSTEM_PROMPT,
            user=USER_PROMPT,
            registry=registry,
            max_rounds=10,
            label="MyAgent",
        )
"""

from .loop import (
    Tool,
    ToolRegistry,
    is_transient_ollama_error,
    run_tool_loop,
    simple_chat,
)
from .market_tools import (
    build_market_registry,
    build_user_registry,
    fetch_url,
)

__all__ = [
    "Tool",
    "ToolRegistry",
    "build_market_registry",
    "build_user_registry",
    "fetch_url",
    "is_transient_ollama_error",
    "run_tool_loop",
    "simple_chat",
]
