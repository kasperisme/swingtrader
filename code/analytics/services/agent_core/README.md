# services/agent_core

Shared LLM plumbing for every agent and script in `analytics/` that calls Ollama. Provides:

- A **streaming, retrying, heartbeat-logged** chat loop — sidesteps the ~60s
  Ollama Cloud proxy idle timeout that kills non-streaming `:cloud` calls.
- A **tool registry** that's mutable and extendable, so each agent layers
  task-specific tools on top of a shared base set.
- A **base market-tools registry** wrapping `services.rag` so every agent
  starts with the same knowledge surface (cluster trends, ticker sentiment,
  semantic news search, fetch_url, …).

If you're calling Ollama from anywhere new in `analytics/`, use this — don't
re-implement the streaming/retry plumbing.

---

## Quick start

### One-shot generation (no tools)

Use `simple_chat` for prompt → text generation: blog posts, summaries,
captions, JSON outputs.

```python
import httpx
from services.agent_core import simple_chat

async with httpx.AsyncClient() as client:
    text = await simple_chat(
        client,
        base_url="http://localhost:11434",
        model="glm-5.1:cloud",
        system="You are a market analyst.",
        user="Summarize today's tape in 3 sentences.",
        options={"num_predict": 600},
        think=False,
        label="Daily summary",
    )
```

`simple_chat` streams the response, retries transient backend errors (502 /
503 / 504 / 429 / EOF / network drops) with exponential backoff, and logs a
heartbeat every 5 s while generation is in flight.

### Tool-calling loop

Use `run_tool_loop` for agents that need to query data, decide what to
fetch, and return a structured answer.

```python
import httpx
from services.agent_core import build_market_registry, run_tool_loop

registry = build_market_registry()  # 9 base RAG tools + fetch_url
# Add agent-specific tools:
registry.add_function(
    "get_my_thing",
    my_fn,
    description="...",
    parameters={"type": "object", "properties": {}, "required": []},
)

async with httpx.AsyncClient() as client:
    final_message, tool_results, rounds_used = await run_tool_loop(
        client,
        base_url="http://localhost:11434",
        model="glm-5.1:cloud",
        system=SYSTEM_PROMPT,
        user=USER_PROMPT,
        registry=registry,
        max_rounds=10,
        label="MyAgent",
    )
```

The loop calls the model, executes whatever tools it requests, feeds the
results back, and repeats until either the model emits a non-tool response
or `max_rounds` is reached. On budget exhaustion it tells the model to stop
calling tools and emit a final answer with the data already gathered.

---

## Architecture

```
┌───────────────────────────────────────────────────────────────────────┐
│                       services.agent_core                             │
│                                                                       │
│  loop.py                                                              │
│    ├── simple_chat()       — one-shot streaming chat                  │
│    ├── run_tool_loop()     — multi-round tool-calling loop            │
│    ├── ToolRegistry        — name → (schema, fn) bag, extendable      │
│    └── _chat_with_retry()  — streaming + exponential backoff retry    │
│                                                                       │
│  market_tools.py                                                      │
│    ├── build_market_registry()  — 9 RAG tools + fetch_url             │
│    └── build_user_registry()    — per-user RAG tools, user_id bound   │
└───────────────────────────────────────────────────────────────────────┘
                                   ▲
                                   │
        ┌──────────────────────────┼──────────────────────────────┐
        │                          │                              │
┌───────────────────┐  ┌─────────────────────────┐  ┌─────────────────────┐
│ services.agent    │  │ services.podcast        │  │ services.news.llm   │
│   .engine         │  │   .research_agent       │  │   .ollama_client    │
│                   │  │                         │  │                     │
│ Screening agent   │  │ Podcast research agent  │  │ Shared chat() —     │
│   = market tools  │  │   = market tools        │  │   thin wrapper over │
│   + user tools    │  │   + 7 podcast aggregate │  │   simple_chat,      │
│   + FMP MCP       │  │     tools (regime, vix, │  │   preserves         │
│                   │  │     top news, …)        │  │   OllamaError API   │
└───────────────────┘  └─────────────────────────┘  └─────────────────────┘
        │                          │                              │
        ▼                          ▼                              ▼
  user_screening_results       script_prompt.j2          narrative_generator,
  + Telegram delivery          → script_generator          (and any future
                                                           one-shot caller)
                                                                  ▲
                                                                  │
                                              ┌───────────────────┘
                                              │
                                  ┌─────────────────────────────┐
                                  │ scripts/generate_blog_post  │
                                  │   = simple_chat (×3)        │
                                  │     blog body, caveman, X   │
                                  └─────────────────────────────┘
```

---

## Consumers

| Consumer | Uses | Tool stack |
|---|---|---|
| `services.agent.engine` | `run_tool_loop` | `build_market_registry` + `build_user_registry(user_id)` + FMP MCP (when `FMP_API_KEY` set) |
| `services.podcast.research_agent` | `run_tool_loop` | `build_market_registry` + 7 podcast-specific aggregates (regime/breadth, VIX, top news, watchlist, earnings, insider, 24h news stats) |
| `services.news.llm.ollama_client` | `simple_chat` | none (one-shot) |
| `scripts/generate_blog_post.py` | `simple_chat` | none (one-shot, ×3 — blog body, caveman, X thread) |

The shared base (`build_market_registry`) gives every agent the same
9 market tools: `get_cluster_trends`, `get_dimension_trends`,
`get_ticker_sentiment`, `get_top_articles`, `get_ticker_relationships`,
`get_company_vectors`, `get_ticker_news`, `search_news`, and `fetch_url`.

---

## Tool registry — extension patterns

```python
registry = build_market_registry()

# 1. Add a single Python callable.
registry.add_function(
    "get_my_aggregate",
    my_fn,                          # sync or async; gets run via asyncio.to_thread
    description="What the model needs to know to decide whether to call this.",
    parameters={"type": "object", "properties": {}, "required": []},
)

# 2. Layer in a pre-built registry.
registry.extend(build_user_registry(user_id))   # user-scoped RAG tools

# 3. Bulk-register tools that share one dispatcher (e.g. an MCP server).
registry.add_schemas(get_fmp_tool_schemas(), call_fmp_tool)
```

User-scoped tools use `build_user_registry(user_id)` which pre-binds
`user_id` as the first arg of each fn — the agent loop dispatches by name
without threading user context through every call site.

---

## Why streaming is mandatory

`OLLAMA_BLOG_MODEL=glm-5.1:cloud` and similar `:cloud` models proxy through
Ollama Cloud. The cloud proxy closes idle connections after ~60 s. With
`stream: false` the proxy waits for the full generation to complete before
sending any bytes back; for typical `num_predict` sizes (≥ 600) generation
exceeds 60 s and the connection drops with `httpx.RemoteProtocolError` /
"unexpected EOF" / `ReadTimeout` — regardless of how high you set the
client timeout.

`agent_core` always streams. The proxy sees bytes flow token-by-token, so
the idle clock resets continuously and generation can run as long as it
needs.

This is the same lesson re-learned three times in `analytics/` before
`agent_core` existed (`engine.py` originally non-streaming;
`research_agent.py` rebuilt streaming from scratch; `script_generator.py`
rebuilt streaming again; `generate_blog_post.py` shipped non-streaming and
hit the timeout). New Ollama callers should not re-implement this.

---

## Knobs

| Env var | Effect |
|---|---|
| `OLLAMA_BASE_URL` | Default `http://localhost:11434`. Set to `https://ollama.com` for direct cloud (rare; usually you want the local daemon to proxy). |
| `OLLAMA_NUM_PREDICT` | Default 1024. Per-call `num_predict` falls back to this when not specified. |

The retry attempt count and round budget are per-agent — see each
consumer's module for its `_RETRY_MAX_ATTEMPTS` / `_MAX_TOOL_ROUNDS`
constants.
