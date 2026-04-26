---
name: deps-graph
description: "How to read the dependency network graph (deps-graph.html / deps-graph.json / ARCHITECTURE.md) to gain fast project orientation, and how to regenerate it after code changes."
triggers:
  - "deps graph"
  - "dependency graph"
  - "network graph"
  - "analyze deps"
  - "update deps"
  - "/deps-graph"
---

# Dependency Graph Skill

The project ships three auto-generated dependency artefacts:

| File | Best for |
|------|---------|
| `deps-graph.html` | Human exploration — interactive vis-network, click nodes for docstrings |
| `deps-graph.json` | LLM consumption — machine-readable nodes + edges + cross-reference |
| `ARCHITECTURE.md` | GitHub / LLM — Mermaid diagrams rendered inline |

---

## How LLMs Should Use the Graph

### 1. Orient fast from `deps-graph.json`

Read the top-level keys first — don't load the whole file:

```json
{
  "nodes":               [...],   // every module, function, DB table, API endpoint
  "edges":               [...],   // directed relationships (reads/writes/calls/fetches)
  "db_cross_reference":  {...},   // which tables/views appear in which files
  "function_call_graph": {...}    // which functions call which other functions
}
```

To find which files touch a specific table (e.g. `news_articles`):

```python
import json
g = json.load(open("deps-graph.json"))
hits = [e for e in g["edges"] if e["to"] == "db::news_articles"]
# → each edge has: from, to, type (reads/writes/upserts/calls_rpc)
```

To find which functions a caller depends on:

```python
cg = g["function_call_graph"]
callers_of = {fn: callers for fn, callers in cg.items() if "target_func" in callers}
```

### 2. Use node types to narrow scope

| `type` | What it represents |
|--------|-------------------|
| `py_module` | Python file |
| `py_func` | Python exported/top-level function |
| `ts_action` | TypeScript `"use server"` file |
| `ts_func` | Exported TypeScript function |
| `db_table` | Supabase/Postgres table |
| `db_view` | DB view (read-only) |
| `db_rpc` | Postgres RPC / stored procedure |
| `external_api` | Third-party HTTP endpoint (FMP, Telegram, etc.) |

### 3. Click nodes in `deps-graph.html` for docstrings

Open `deps-graph.html` in a browser. Click any function node to see:
- Full file path
- Docstring (Python `"""..."""` or TypeScript `/** ... */`)
- Node type

Four view modes in the sidebar:
- **File overview** — file-level only (no function nodes)
- **Function → DB** — functions and the DB objects they touch
- **Function calls** — inter-function call graph
- **Everything** — full graph (dense; use filters)

### 4. Read `ARCHITECTURE.md` for Mermaid diagrams

Four diagrams are embedded:
1. File-level DB connections
2. Function-level DB connections
3. Function call graph
4. External API graph

Plus a `db_cross_reference` table mapping every DB object to its source files.

---

## How to Update the Graph

Run from the repo root after any code change:

```bash
python analyze_deps.py
```

This rewrites all three artefacts atomically:
- `deps-graph.json`
- `deps-graph.html`
- `ARCHITECTURE.md`

Takes ~5 seconds. Safe to run repeatedly. No side effects.

### When to regenerate

- After adding a new Python module or TypeScript server action
- After adding or renaming a function that touches the DB
- After writing new docstrings (they appear in the HTML click panel)
- After adding a new Supabase table/view reference

---

## Common LLM Workflows

**"Which file writes to `user_scheduled_screenings`?"**

```python
g = json.load(open("deps-graph.json"))
writers = [e["from"] for e in g["edges"]
           if "user_scheduled_screenings" in e["to"] and e["type"] in ("writes", "upserts")]
```

**"What does function X call?"**

```python
calls = [e["to"] for e in g["edges"] if e["from"] == "func::module::X" and e["type"] == "calls"]
```

**"Which functions are missing docstrings?"**

```python
missing = [n for n in g["nodes"] if n["type"] in ("py_func", "ts_func") and not n.get("docstring")]
```

**"How many times is function X called?"**

```python
count = sum(1 for e in g["edges"] if e["to"].endswith("::X") and e["type"] == "calls")
```

---

## Graph Node ID Format

Node IDs follow a consistent pattern — use them for exact edge lookups:

| Type | ID format |
|------|-----------|
| `py_module` | `pymod::<relative_path>` e.g. `pymod::src/db.py` |
| `py_func` | `pyfunc::<module>::<func_name>` |
| `ts_action` | `tsact::<relative_path>` |
| `ts_func` | `tsfunc::<module>::<func_name>` |
| `db_table` | `db::<table_name>` |
| `db_view` | `dbv::<view_name>` |
| `db_rpc` | `dbrpc::<rpc_name>` |
| `external_api` | `ext::<hostname>` |
