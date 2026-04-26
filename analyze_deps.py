#!/usr/bin/env python3
"""
analyze_deps.py — Static dependency analysis for the swingtrader monorepo.

Scans Python (code/analytics) and TypeScript (code/ui/app/actions) to map:
  - DB table/view reads and writes  (Supabase PostgREST + raw psycopg2 SQL)
  - External API calls              (FMP, Telegram, Anthropic, Ollama, Twitter/X)
  - Python function-level deps      (which function touches which table / calls which function)

Two-pass Python analysis:
  Pass 1  Collect all function definitions + imports across all files
  Pass 2  Analyse each function body; resolve cross-file calls via import map

Outputs written to repo root:
  ARCHITECTURE.md   Mermaid diagrams — LLM-readable, renders on GitHub
  deps-graph.json   Machine-readable nodes + edges  (for LLMs / tooling)
  deps-graph.html   Self-contained interactive vis-network browser graph

Usage:
    python analyze_deps.py
"""

from __future__ import annotations

import ast
import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Paths ────────────────────────────────────────────────────────────────────

REPO_ROOT    = Path(__file__).resolve().parent
PY_SCAN_ROOT = REPO_ROOT / "code" / "analytics"
TS_SCAN_ROOT = REPO_ROOT / "code" / "ui" / "app" / "actions"

# ── External API detection ───────────────────────────────────────────────────

EXTERNAL_APIS: dict[str, str] = {
    "financialmodelingprep.com": "FMP_API",
    "api.telegram.org":          "Telegram_API",
    "anthropic":                 "Anthropic_API",
    "11434":                     "Ollama_Local",
    "api.twitter.com":           "Twitter_X_API",
    "tweepy":                    "Twitter_X_API",
}

# ── Node / Edge metadata ─────────────────────────────────────────────────────

NODE_TYPE_LABELS: dict[str, str] = {
    "py_module":    "Python Module",
    "py_func":      "Python Function",
    "ts_action":    "TS Server Action",
    "ts_func":      "TS Function",
    "db_table":     "DB Table",
    "db_view":      "DB View",
    "db_rpc":       "DB RPC",
    "external_api": "External API",
}

NODE_COLORS: dict[str, str] = {
    "py_module":    "#4A90D9",
    "py_func":      "#82C4F8",
    "ts_action":    "#27AE60",
    "ts_func":      "#6FD99A",
    "db_table":     "#E67E22",
    "db_view":      "#F1C40F",
    "db_rpc":       "#9B59B6",
    "external_api": "#E74C3C",
}

EDGE_LABEL: dict[str, str] = {
    "reads":     "reads",
    "writes":    "writes",
    "upserts":   "upserts",
    "calls_rpc": "rpc",
    "fetches":   "http",
    "calls":     "calls",
}

# ── Graph ────────────────────────────────────────────────────────────────────

class Graph:
    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: list[dict[str, Any]] = []
        self._edge_keys: set[tuple[str, str, str]] = set()

    def add_node(self, node_id: str, type_: str, label: str,
                 path: str = "", description: str = "") -> None:
        if node_id not in self.nodes:
            self.nodes[node_id] = {
                "id": node_id, "type": type_,
                "label": label, "path": path, "description": description,
            }

    def add_edge(self, from_id: str, to_id: str, edge_type: str) -> None:
        key = (from_id, to_id, edge_type)
        if key not in self._edge_keys:
            self._edge_keys.add(key)
            self.edges.append({"from": from_id, "to": to_id, "type": edge_type})


def _is_view(name: str) -> bool:
    return name.endswith("_v") or name.endswith("_view")

def _db_type(name: str) -> str:
    return "db_view" if _is_view(name) else "db_table"

def _db_id(name: str) -> str:
    return f"{_db_type(name)}:{name}"

# ── Regex patterns (shared between file- and function-level analysis) ─────────

_PY_TABLE_RE       = re.compile(r'\.table\(\s*["\']([a-z][a-z0-9_]*)["\']', re.I)
_PY_TBL_HELPER_RE  = re.compile(r'_tbl\(\s*\w+\s*,\s*["\']([a-z][a-z0-9_]*)["\']', re.I)
_PY_RPC_RE         = re.compile(r'\.rpc\(\s*["\']([a-z][a-z0-9_]*)["\']', re.I)
_PY_OP_RE          = re.compile(r'\.(select|insert|update|delete|upsert)\s*[\(\[]')
_PY_SQL_READ_RE    = re.compile(r'\b(?:FROM|JOIN)\s+\{schema\}\.([a-z][a-z0-9_]*)', re.I)
_PY_SQL_WRITE_RE   = re.compile(r'\b(?:INTO|UPDATE)\s+\{schema\}\.([a-z][a-z0-9_]*)', re.I)
_PY_SQL_SREAD_RE   = re.compile(r'\b(?:FROM|JOIN)\s+swingtrader\.([a-z][a-z0-9_]*)', re.I)
_PY_SQL_SWRITE_RE  = re.compile(r'\b(?:INTO|UPDATE)\s+swingtrader\.([a-z][a-z0-9_]*)', re.I)
_PY_URL_RE         = re.compile(r'["\']https?://([^\s"\'{}\\]+)', re.I)
_PY_ANTHROPIC_RE   = re.compile(r'\bimport anthropic\b|from anthropic\b')
_PY_TWEEPY_RE      = re.compile(r'\bimport tweepy\b|from tweepy\b')
_PY_OLLAMA_RE      = re.compile(r'11434|ollama', re.I)

_TS_FROM_RE        = re.compile(r'\.from\(\s*["\']([a-z][a-z0-9_]*)["\']', re.I)
_TS_OP_RE          = re.compile(r'\.(select|insert|update|delete|upsert)\s*[\(\[]')
_TS_FETCH_RE       = re.compile(r'`https?://([^`$\s]+)|["\']https?://([^"\']+)["\']')


def _classify_op(op: str) -> str:
    if op == "select":  return "reads"
    if op == "upsert":  return "upserts"
    return "writes"


def _table_ops_from_source(source: str) -> list[tuple[str, str]]:
    """Return deduplicated (table_name, edge_type) from a source string."""
    seen: set[tuple[str, str]] = set()
    out:  list[tuple[str, str]] = []

    def _add(t: str, e: str) -> None:
        k = (t.lower(), e)
        if k not in seen:
            seen.add(k)
            out.append(k)

    for m in _PY_TABLE_RE.finditer(source):
        ahead  = source[m.end(): m.end() + 800]
        op_m   = _PY_OP_RE.search(ahead)
        _add(m.group(1).lower(), _classify_op(op_m.group(1)) if op_m else "reads")

    for m in _PY_TBL_HELPER_RE.finditer(source):
        ahead  = source[m.end(): m.end() + 400]
        op_m   = _PY_OP_RE.search(ahead)
        _add(m.group(1).lower(), _classify_op(op_m.group(1)) if op_m else "reads")

    for m in _PY_SQL_READ_RE.finditer(source):   _add(m.group(1).lower(), "reads")
    for m in _PY_SQL_WRITE_RE.finditer(source):  _add(m.group(1).lower(), "writes")
    for m in _PY_SQL_SREAD_RE.finditer(source):  _add(m.group(1).lower(), "reads")
    for m in _PY_SQL_SWRITE_RE.finditer(source): _add(m.group(1).lower(), "writes")

    return out


def _rpc_from_source(source: str) -> list[str]:
    return list({m.group(1).lower() for m in _PY_RPC_RE.finditer(source)})


def _apis_from_source(source: str) -> list[str]:
    found: set[str] = set()
    if _PY_ANTHROPIC_RE.search(source): found.add("Anthropic_API")
    if _PY_TWEEPY_RE.search(source):    found.add("Twitter_X_API")
    if _PY_OLLAMA_RE.search(source):    found.add("Ollama_Local")
    for m in _PY_URL_RE.finditer(source):
        url = m.group(1)
        for pat, api in EXTERNAL_APIS.items():
            if pat in url:
                found.add(api)
                break
    return list(found)


# ── AST helpers ──────────────────────────────────────────────────────────────

@dataclass
class FuncInfo:
    name:          str
    file_path:     Path
    start_line:    int
    end_line:      int
    ast_node:      ast.FunctionDef | ast.AsyncFunctionDef
    docstring:     str = field(default="", compare=False)
    # Set after pass 1
    node_id:       str = field(default="", compare=False)
    file_node_id:  str = field(default="", compare=False)

    def __post_init__(self) -> None:
        rel = str(self.file_path.relative_to(REPO_ROOT))
        self.node_id      = f"py_func:{rel}::{self.name}"
        self.file_node_id = f"py_module:{rel}"

    def source_slice(self, source_lines: list[str]) -> str:
        return "\n".join(source_lines[self.start_line - 1: self.end_line])


def _collect_funcs(tree: ast.Module, file_path: Path) -> list[FuncInfo]:
    """Collect all top-level and nested function/method definitions."""
    funcs: list[FuncInfo] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.append(FuncInfo(
                name       = node.name,
                file_path  = file_path,
                start_line = node.lineno,
                end_line   = getattr(node, "end_lineno", node.lineno + 1),
                ast_node   = node,
                docstring  = ast.get_docstring(node) or "",
            ))
    return funcs


def _collect_imports(tree: ast.Module, file_path: Path) -> dict[str, tuple[str, str]]:
    """
    Return {local_name: (module_str, original_name)}.
    Used to resolve call names to their definition files.
    """
    imports: dict[str, tuple[str, str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for alias in node.names:
                local = alias.asname or alias.name
                imports[local] = (mod, alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name
                imports[local] = (alias.name, alias.name)
    return imports


def _find_call_names(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """All plain function/name call targets inside a function body."""
    names: set[str] = set()
    for node in ast.walk(func_node):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            names.add(node.func.id)
    return names


def _resolve_module_to_path(module: str, current_file: Path) -> Path | None:
    """Try to map a module string to an absolute .py path."""
    if not module:
        return None

    # Relative import: leading dots
    leading = len(module) - len(module.lstrip("."))
    if leading:
        rel_mod = module[leading:]
        base = current_file.parent
        for _ in range(leading - 1):
            base = base.parent
        parts = rel_mod.replace(".", "/") if rel_mod else ""
        for candidate in (
            base / (parts + ".py") if parts else None,
            base / parts / "__init__.py" if parts else None,
        ):
            if candidate and candidate.exists():
                return candidate
        return None

    # Absolute: try relative to PY_SCAN_ROOT
    parts = module.replace(".", "/")
    for candidate in (
        PY_SCAN_ROOT / (parts + ".py"),
        PY_SCAN_ROOT / parts / "__init__.py",
    ):
        if candidate.exists():
            return candidate
    return None


# ── Pass 1: build global registries ──────────────────────────────────────────

# func_name → list of FuncInfo objects that define it
_func_registry:  dict[str, list[FuncInfo]] = defaultdict(list)
# file_path → {local_name: (module_str, original_name)}
_file_imports:   dict[Path, dict[str, tuple[str, str]]] = {}
# file_path → parsed source lines (for slicing)
_file_lines:     dict[Path, list[str]] = {}
# file_path → list of FuncInfo
_file_funcs:     dict[Path, list[FuncInfo]] = {}


def _pass1_file(path: Path) -> None:
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return

    lines  = source.splitlines()
    funcs  = _collect_funcs(tree, path)
    imps   = _collect_imports(tree, path)

    _file_lines[path]   = lines
    _file_funcs[path]   = funcs
    _file_imports[path] = imps

    for fi in funcs:
        _func_registry[fi.name].append(fi)


# ── Pass 2: analyse function bodies ──────────────────────────────────────────

def _resolve_call_to_func(
    call_name: str,
    caller_path: Path,
) -> list[FuncInfo]:
    """
    Given a call name seen in caller_path, return the FuncInfo(s) it most
    likely refers to.  Priority:
      1. Imported name that resolves to a scanned file
      2. Same-file definition
      3. Any single match across all scanned files (fallback)
    """
    imps = _file_imports.get(caller_path, {})

    if call_name in imps:
        mod_str, orig_name = imps[call_name]
        target_path = _resolve_module_to_path(mod_str, caller_path)
        if target_path:
            candidates = [
                fi for fi in _func_registry.get(orig_name, [])
                if fi.file_path == target_path
            ]
            if candidates:
                return candidates

    # Same-file definition
    same_file = [
        fi for fi in _func_registry.get(call_name, [])
        if fi.file_path == caller_path
    ]
    if same_file:
        return same_file

    # Unique global match
    global_matches = _func_registry.get(call_name, [])
    if len(global_matches) == 1:
        return global_matches

    return []


def _pass2_file(path: Path, graph: Graph) -> None:
    funcs  = _file_funcs.get(path, [])
    lines  = _file_lines.get(path, [])
    if not funcs:
        return

    rel          = str(path.relative_to(REPO_ROOT))
    file_node_id = f"py_module:{rel}"

    for fi in funcs:
        src_slice = fi.source_slice(lines)

        # Collect what this function touches
        table_ops = _table_ops_from_source(src_slice)
        rpcs      = _rpc_from_source(src_slice)
        apis      = _apis_from_source(src_slice)
        call_names = _find_call_names(fi.ast_node)

        # Resolve cross-function calls  (skip builtins / standard names)
        called_funcs: list[FuncInfo] = []
        for cname in call_names:
            if cname == fi.name:   # skip recursion
                continue
            targets = _resolve_call_to_func(cname, path)
            # Only add calls to functions that have their own deps
            # (avoid cluttering graph with pure utility helpers)
            called_funcs.extend(targets)

        # Only add a py_func node if the function has at least one dependency
        # (DB, API, or calls a function that has deps)
        has_deps = bool(table_ops or rpcs or apis or called_funcs)
        if not has_deps:
            continue

        # Register node
        graph.add_node(fi.node_id, "py_func", fi.name, rel,
                       description=fi.docstring or f"def {fi.name} in {rel}:{fi.start_line}")

        # DB edges
        for table, edge in table_ops:
            t_id = _db_id(table)
            graph.add_node(t_id, _db_type(table), table)
            graph.add_edge(fi.node_id, t_id, edge)

        # RPC edges
        for rpc in rpcs:
            rpc_id = f"db_rpc:{rpc}"
            graph.add_node(rpc_id, "db_rpc", rpc)
            graph.add_edge(fi.node_id, rpc_id, "calls_rpc")

        # API edges
        for api in apis:
            api_id = f"external_api:{api}"
            graph.add_node(api_id, "external_api", api)
            graph.add_edge(fi.node_id, api_id, "fetches")

        # Cross-function call edges
        for target_fi in called_funcs:
            # Ensure the target node exists
            graph.add_node(target_fi.node_id, "py_func", target_fi.name,
                           str(target_fi.file_path.relative_to(REPO_ROOT)))
            graph.add_edge(fi.node_id, target_fi.node_id, "calls")


# ── File-level Python analysis (unchanged from v1) ───────────────────────────

def _analyze_py_file_level(path: Path, graph: Graph) -> None:
    """Add the py_module node + its file-level DB/API edges."""
    rel     = str(path.relative_to(REPO_ROOT))
    node_id = f"py_module:{rel}"

    source = _file_lines.get(path)
    if source is None:
        return
    src = "\n".join(source)

    graph.add_node(node_id, "py_module", path.name, rel)

    for table, edge in _table_ops_from_source(src):
        t_id = _db_id(table)
        graph.add_node(t_id, _db_type(table), table)
        graph.add_edge(node_id, t_id, edge)

    for rpc in _rpc_from_source(src):
        rpc_id = f"db_rpc:{rpc}"
        graph.add_node(rpc_id, "db_rpc", rpc)
        graph.add_edge(node_id, rpc_id, "calls_rpc")

    for api in _apis_from_source(src):
        api_id = f"external_api:{api}"
        graph.add_node(api_id, "external_api", api)
        graph.add_edge(node_id, api_id, "fetches")


# ── TypeScript analysis (unchanged) ──────────────────────────────────────────

def _ts_table_ops(source: str) -> list[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    out:  list[tuple[str, str]] = []
    for m in _TS_FROM_RE.finditer(source):
        ahead = source[m.end(): m.end() + 600]
        op_m  = _TS_OP_RE.search(ahead)
        k     = (m.group(1).lower(), _classify_op(op_m.group(1)) if op_m else "reads")
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def _ts_apis(source: str) -> list[str]:
    found: set[str] = set()
    for m in _TS_FETCH_RE.finditer(source):
        url = m.group(1) or m.group(2) or ""
        for pat, api in EXTERNAL_APIS.items():
            if pat in url:
                found.add(api)
                break
    return list(found)


# ── TypeScript function + JSDoc extraction ────────────────────────────────────

_TS_EXPORTED_FUNC_RE = re.compile(
    r'^[ \t]*export\s+(?:async\s+)?function\s+(\w+)\s*[(<]',
    re.MULTILINE,
)


def _extract_jsdoc_before(lines: list[str], func_line_idx: int) -> str:
    """Return the cleaned JSDoc comment (/** ... */) immediately before line idx."""
    j = func_line_idx - 1
    while j >= 0 and not lines[j].strip():
        j -= 1
    if j < 0 or not lines[j].strip().endswith("*/"):
        return ""
    end = j
    while j >= 0 and "/**" not in lines[j]:
        j -= 1
    if j < 0:
        return ""
    raw = "\n".join(lines[j: end + 1])
    raw = re.sub(r'/\*\*|\*/', '', raw)
    raw = re.sub(r'^\s*\*\s?', '', raw, flags=re.MULTILINE)
    return raw.strip()


def _func_body_end(lines: list[str], start_idx: int) -> int:
    """Return the line index where the function body ends (matching `}`)."""
    depth, started = 0, False
    for i in range(start_idx, len(lines)):
        for ch in lines[i]:
            if ch == '{':
                depth += 1
                started = True
            elif ch == '}':
                depth -= 1
        if started and depth == 0:
            return i
    return len(lines) - 1


def _extract_ts_funcs(source: str) -> list[tuple[str, str, str]]:
    """
    Return [(func_name, jsdoc, body_source), ...] for every exported function.
    body_source is the full function text, used for scoped DB/API analysis.
    """
    lines   = source.splitlines()
    results = []
    for m in _TS_EXPORTED_FUNC_RE.finditer(source):
        func_name    = m.group(1)
        func_line    = source[: m.start()].count("\n")
        jsdoc        = _extract_jsdoc_before(lines, func_line)
        end_line     = _func_body_end(lines, func_line)
        body         = "\n".join(lines[func_line: end_line + 1])
        results.append((func_name, jsdoc, body))
    return results


def _analyze_ts(path: Path, graph: Graph) -> None:
    rel     = str(path.relative_to(REPO_ROOT))
    node_id = f"ts_action:{rel}"
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return

    # File-level node
    graph.add_node(node_id, "ts_action", path.name, rel)

    for table, edge in _ts_table_ops(source):
        t_id = _db_id(table)
        graph.add_node(t_id, _db_type(table), table)
        graph.add_edge(node_id, t_id, edge)

    for api in _ts_apis(source):
        api_id = f"external_api:{api}"
        graph.add_node(api_id, "external_api", api)
        graph.add_edge(node_id, api_id, "fetches")

    # Function-level nodes with JSDoc + scoped DB/API analysis
    for func_name, jsdoc, body in _extract_ts_funcs(source):
        func_id = f"ts_func:{rel}::{func_name}"
        graph.add_node(func_id, "ts_func", func_name, rel, description=jsdoc)

        for table, edge in _ts_table_ops(body):
            t_id = _db_id(table)
            graph.add_node(t_id, _db_type(table), table)
            graph.add_edge(func_id, t_id, edge)

        for api in _ts_apis(body):
            api_id = f"external_api:{api}"
            graph.add_node(api_id, "external_api", api)
            graph.add_edge(func_id, api_id, "fetches")


# ── Directory scanners ────────────────────────────────────────────────────────

_SKIP_DIRS = {".venv", "__pycache__", ".git", "node_modules", ".next", "dist"}
_SKIP_PY   = {"test_", "_test.py", "conftest"}
_SKIP_TS   = {".test.", ".spec."}


def _scan_python(graph: Graph) -> tuple[int, int]:
    if not PY_SCAN_ROOT.exists():
        print(f"[warn] Python root not found: {PY_SCAN_ROOT}", file=sys.stderr)
        return 0, 0

    py_files = [
        p for p in sorted(PY_SCAN_ROOT.rglob("*.py"))
        if not any(part in _SKIP_DIRS for part in p.parts)
        and not any(s in p.name for s in _SKIP_PY)
    ]

    # Pass 1
    for path in py_files:
        _pass1_file(path)

    # Pass 2 + file-level nodes
    for path in py_files:
        _analyze_py_file_level(path, graph)
        _pass2_file(path, graph)

    func_nodes = sum(1 for n in graph.nodes.values() if n["type"] == "py_func")
    return len(py_files), func_nodes


def _scan_typescript(graph: Graph) -> int:
    if not TS_SCAN_ROOT.exists():
        print(f"[warn] TypeScript root not found: {TS_SCAN_ROOT}", file=sys.stderr)
        return 0
    count = 0
    for path in sorted(TS_SCAN_ROOT.rglob("*.ts")):
        if not any(s in path.name for s in _SKIP_TS):
            _analyze_ts(path, graph)
            count += 1
    return count


# ── JSON output ───────────────────────────────────────────────────────────────

def _build_json(graph: Graph) -> dict[str, Any]:
    by_type: dict[str, int] = defaultdict(int)
    for n in graph.nodes.values():
        by_type[n["type"]] += 1

    # DB cross-reference (file- and function-level combined)
    xref: dict[str, dict[str, Any]] = {}
    for e in graph.edges:
        to = graph.nodes.get(e["to"], {})
        if to.get("type") not in ("db_table", "db_view", "db_rpc"):
            continue
        tname = to["label"]
        if tname not in xref:
            xref[tname] = {"type": to["type"], "accessed_by": [], "operations": {}}
        src = graph.nodes.get(e["from"], {})
        src_label = f"{src.get('label','')} ({src.get('path','')})"
        if src_label not in xref[tname]["accessed_by"]:
            xref[tname]["accessed_by"].append(src_label)
        ops = xref[tname]["operations"].setdefault(src_label, [])
        if e["type"] not in ops:
            ops.append(e["type"])

    # Function call graph summary
    func_calls: dict[str, list[str]] = {}
    for e in graph.edges:
        if e["type"] != "calls":
            continue
        frm = graph.nodes.get(e["from"], {})
        to  = graph.nodes.get(e["to"],  {})
        if frm.get("type") == "py_func" and to.get("type") == "py_func":
            caller = f"{frm['label']} ({frm['path']})"
            callee = f"{to['label']} ({to['path']})"
            func_calls.setdefault(caller, []).append(callee)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "description": (
            "Swingtrader monorepo dependency graph. "
            "Auto-generated by analyze_deps.py — do not edit manually."
        ),
        "how_to_read": {
            "nodes":               "py_module = file; py_func = individual function; db_table/view = DB object; external_api = HTTP endpoint.",
            "edges":               "reads/writes/upserts = DB ops; fetches = HTTP; calls = function→function.",
            "db_cross_reference":  "Inverted index: for each DB object, which functions/files access it.",
            "function_call_graph": "Which functions call which other functions (cross-file resolved via imports).",
        },
        "summary": {k: v for k, v in sorted(by_type.items())},
        "node_types": NODE_TYPE_LABELS,
        "edge_types": {
            "reads":     "SELECT query",
            "writes":    "INSERT / UPDATE / DELETE",
            "upserts":   "UPSERT",
            "calls_rpc": "PostgreSQL RPC call",
            "fetches":   "HTTP call to external API",
            "calls":     "Python function call (cross-file resolved)",
        },
        "nodes":               list(graph.nodes.values()),
        "edges":               graph.edges,
        "db_cross_reference":  xref,
        "function_call_graph": func_calls,
    }


# ── Mermaid helpers ───────────────────────────────────────────────────────────

def _mid(node_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", node_id)


def _mermaid_db_graph(graph: Graph) -> str:
    db_types  = {"db_table", "db_view", "db_rpc"}
    src_types = {"py_module", "ts_action"}
    rel_edges = [e for e in graph.edges
                 if graph.nodes.get(e["to"], {}).get("type") in db_types
                 and graph.nodes.get(e["from"], {}).get("type") in src_types]
    if not rel_edges:
        return ""

    rel_from = {e["from"] for e in rel_edges}
    rel_to   = {e["to"]   for e in rel_edges}

    lines = ["graph LR"]
    lines.append('  subgraph SRC["Source Files"]')
    for nid in sorted(rel_from):
        n   = graph.nodes.get(nid, {})
        tag = "PY" if n.get("type") == "py_module" else "TS"
        lbl = n["label"].replace('"', "'")
        lines.append(f'    {_mid(nid)}["[{tag}] {lbl}"]')
    lines.append("  end")

    lines.append('  subgraph DB["Database — swingtrader schema"]')
    for nid in sorted(rel_to):
        n   = graph.nodes.get(nid, {})
        tag = {"db_table": "TABLE", "db_view": "VIEW", "db_rpc": "RPC"}.get(n.get("type",""), "")
        lbl = n["label"].replace('"', "'")
        lines.append(f'    {_mid(nid)}["[{tag}] {lbl}"]')
    lines.append("  end")

    for e in rel_edges:
        lbl = EDGE_LABEL.get(e["type"], e["type"])
        lines.append(f'  {_mid(e["from"])} -->|"{lbl}"| {_mid(e["to"])}')

    return "\n".join(lines)


def _mermaid_func_db_graph(graph: Graph) -> str:
    """Function nodes → DB objects (subset: only cross-file interesting funcs)."""
    db_types  = {"db_table", "db_view", "db_rpc"}
    rel_edges = [e for e in graph.edges
                 if graph.nodes.get(e["to"],   {}).get("type") in db_types
                 and graph.nodes.get(e["from"], {}).get("type") == "py_func"]
    if not rel_edges:
        return ""

    rel_from = {e["from"] for e in rel_edges}
    rel_to   = {e["to"]   for e in rel_edges}

    lines = ["graph LR"]
    # Group functions by file
    file_groups: dict[str, list[str]] = defaultdict(list)
    for nid in sorted(rel_from):
        n    = graph.nodes.get(nid, {})
        path = n.get("path", "unknown")
        file_groups[path].append(nid)

    for fpath, nids in sorted(file_groups.items()):
        sg_id = _mid(f"file_{fpath}")
        short = Path(fpath).name
        lines.append(f'  subgraph {sg_id}["{short}"]')
        for nid in nids:
            n   = graph.nodes.get(nid, {})
            lbl = n["label"].replace('"', "'")
            lines.append(f'    {_mid(nid)}["{lbl}"]')
        lines.append("  end")

    lines.append('  subgraph DB["Database"]')
    for nid in sorted(rel_to):
        n   = graph.nodes.get(nid, {})
        tag = {"db_table": "TABLE", "db_view": "VIEW", "db_rpc": "RPC"}.get(n.get("type",""), "")
        lbl = n["label"].replace('"', "'")
        lines.append(f'    {_mid(nid)}["[{tag}] {lbl}"]')
    lines.append("  end")

    for e in rel_edges:
        lbl = EDGE_LABEL.get(e["type"], e["type"])
        lines.append(f'  {_mid(e["from"])} -->|"{lbl}"| {_mid(e["to"])}')

    return "\n".join(lines)


def _mermaid_call_graph(graph: Graph) -> str:
    """Function → Function call edges."""
    call_edges = [e for e in graph.edges if e["type"] == "calls"]
    if not call_edges:
        return ""

    involved = {e["from"] for e in call_edges} | {e["to"] for e in call_edges}
    file_groups: dict[str, list[str]] = defaultdict(list)
    for nid in sorted(involved):
        n    = graph.nodes.get(nid, {})
        path = n.get("path", "unknown")
        file_groups[path].append(nid)

    lines = ["graph LR"]
    for fpath, nids in sorted(file_groups.items()):
        sg_id = _mid(f"cg_{fpath}")
        short = Path(fpath).name
        lines.append(f'  subgraph {sg_id}["{short}"]')
        for nid in nids:
            n   = graph.nodes.get(nid, {})
            lbl = n["label"].replace('"', "'")
            lines.append(f'    {_mid(nid)}["{lbl}"]')
        lines.append("  end")

    for e in call_edges:
        lines.append(f'  {_mid(e["from"])} -->|"calls"| {_mid(e["to"])}')

    return "\n".join(lines)


def _mermaid_api_graph(graph: Graph) -> str:
    rel_edges = [e for e in graph.edges
                 if graph.nodes.get(e["to"], {}).get("type") == "external_api"
                 and graph.nodes.get(e["from"], {}).get("type") in ("py_module", "ts_action")]
    if not rel_edges:
        return ""

    rel_from = {e["from"] for e in rel_edges}
    rel_to   = {e["to"]   for e in rel_edges}

    lines = ["graph LR"]
    lines.append('  subgraph SRC["Source Files"]')
    for nid in sorted(rel_from):
        n   = graph.nodes.get(nid, {})
        tag = "PY" if n.get("type") == "py_module" else "TS"
        lbl = n["label"].replace('"', "'")
        lines.append(f'    {_mid(nid)}["[{tag}] {lbl}"]')
    lines.append("  end")

    lines.append('  subgraph EXT["External APIs"]')
    for nid in sorted(rel_to):
        n   = graph.nodes.get(nid, {})
        lbl = n["label"].replace('"', "'")
        lines.append(f'    {_mid(nid)}["{lbl}"]')
    lines.append("  end")

    for e in rel_edges:
        lines.append(f'  {_mid(e["from"])} -.->|"http"| {_mid(e["to"])}')

    return "\n".join(lines)


def _db_xref_table(graph: Graph) -> str:
    db_types = {"db_table", "db_view", "db_rpc"}
    data: dict[str, dict[str, Any]] = {}

    for e in graph.edges:
        to = graph.nodes.get(e["to"], {})
        if to.get("type") not in db_types:
            continue
        tname = to["label"]
        ttype = to["type"]
        if tname not in data:
            data[tname] = {"type": ttype, "by": {}}
        src     = graph.nodes.get(e["from"], {})
        src_key = f"{src.get('label','')} ({src.get('type','')})"
        data[tname]["by"].setdefault(src_key, set()).add(e["type"])

    if not data:
        return ""

    rows = ["| DB Object | Kind | Accessed By (operations) |",
            "|-----------|------|--------------------------|"]
    for tname in sorted(data):
        info = data[tname]
        kind = {"db_table": "TABLE", "db_view": "VIEW", "db_rpc": "RPC"}.get(info["type"], info["type"])
        by   = [f"`{k}` ({'+'.join(sorted(ops))})" for k, ops in sorted(info["by"].items())]
        rows.append(f"| `{tname}` | {kind} | {', '.join(by)} |")

    return "\n".join(rows)


# ── Markdown output ───────────────────────────────────────────────────────────

def _build_markdown(graph: Graph) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    count = lambda t: sum(1 for n in graph.nodes.values() if n["type"] == t)
    mmd_db    = _mermaid_db_graph(graph)
    mmd_fdb   = _mermaid_func_db_graph(graph)
    mmd_calls = _mermaid_call_graph(graph)
    mmd_api   = _mermaid_api_graph(graph)
    xref      = _db_xref_table(graph)

    py_nodes  = [n for n in graph.nodes.values() if n["type"] == "py_module"]
    ts_nodes  = [n for n in graph.nodes.values() if n["type"] == "ts_action"]

    parts: list[str] = []

    parts.append(f"""\
<!-- AUTO-GENERATED — DO NOT EDIT MANUALLY -->
<!-- Regenerate: python analyze_deps.py (from repo root) -->
<!-- Last updated: {now} -->

# Architecture & Dependency Map

> **For LLMs:** Canonical dependency reference for the swingtrader repo.
> `deps-graph.json` has the same data in structured form.
> `deps-graph.html` is an interactive browser graph (file-level + function-level views).

## Summary

| Category | Count |
|----------|------:|
| Python modules scanned | {count("py_module")} |
| Python functions mapped | {count("py_func")} |
| TypeScript server actions | {count("ts_action")} |
| DB tables referenced | {count("db_table")} |
| DB views referenced | {count("db_view")} |
| DB RPCs referenced | {count("db_rpc")} |
| External APIs | {count("external_api")} |
| Total edges | {len(graph.edges)} |
""")

    parts.append("""\
## Stack Overview

```
Browser / Next.js App Router  (code/ui/)
├── Server Actions             code/ui/app/actions/*.ts
│   ├── Supabase JS client  →  swingtrader schema (PostgREST over HTTPS)
│   └── FMP API             →  financialmodelingprep.com
└── Pages, Components, Lib

Python Analytics               code/analytics/
├── screen_agent/              LLM agent loop (Ollama) → data tools → Telegram
├── news_impact/               News ingestion, embeddings, impact scoring (Anthropic)
├── tiktok/                    TikTok video pipeline
├── src/db.py                  Supabase / psycopg2 connection layer
├── src/fmp.py                 FMP API client (Python)
└── src/telegram.py            Telegram bot delivery

Database: Supabase — schema: swingtrader
├── Tables  news_articles, user_scan_runs, user_trades, ...
└── Views   *_v  (e.g. ticker_sentiment_heads_v, news_trends_cluster_daily_v)
```
""")

    if mmd_db:
        parts.append(f"""\
## File-Level DB Dependency Graph

Source files → DB tables and views.

```mermaid
{mmd_db}
```
""")

    if mmd_fdb:
        parts.append(f"""\
## Function-Level DB Dependencies

Individual functions → DB tables and views.
Each subgraph is one Python file; nodes are functions inside it.

```mermaid
{mmd_fdb}
```
""")

    if mmd_calls:
        parts.append(f"""\
## Function Call Graph

Python function → Python function (cross-file calls resolved via imports).

```mermaid
{mmd_calls}
```
""")

    if mmd_api:
        parts.append(f"""\
## External API Calls

```mermaid
{mmd_api}
```
""")

    if xref:
        parts.append(f"""\
## DB Objects Cross-Reference

Quick lookup: "what touches `user_scan_runs`?"
Includes both file-level and function-level accessors.

{xref}
""")

    # Per-file tables
    py_rows = ["| Module | DB objects | External APIs |",
               "|--------|-----------|---------------|"]
    for n in sorted(py_nodes, key=lambda x: x["label"]):
        nid = n["id"]
        db_t = sorted({graph.nodes[e["to"]]["label"]
                       for e in graph.edges if e["from"] == nid
                       and graph.nodes.get(e["to"], {}).get("type") in ("db_table","db_view","db_rpc")})
        api_t = sorted({graph.nodes[e["to"]]["label"]
                        for e in graph.edges if e["from"] == nid
                        and graph.nodes.get(e["to"], {}).get("type") == "external_api"})
        py_rows.append(f"| `{n['path']}` | {', '.join(f'`{t}`' for t in db_t) or '—'} "
                       f"| {', '.join(f'`{a}`' for a in api_t) or '—'} |")
    parts.append("## Python Modules\n\n" + "\n".join(py_rows))

    ts_rows = ["| Action file | DB objects | External APIs |",
               "|------------|-----------|---------------|"]
    for n in sorted(ts_nodes, key=lambda x: x["label"]):
        nid = n["id"]
        db_t = sorted({graph.nodes[e["to"]]["label"]
                       for e in graph.edges if e["from"] == nid
                       and graph.nodes.get(e["to"], {}).get("type") in ("db_table","db_view")})
        api_t = sorted({graph.nodes[e["to"]]["label"]
                        for e in graph.edges if e["from"] == nid
                        and graph.nodes.get(e["to"], {}).get("type") == "external_api"})
        ts_rows.append(f"| `{n['path']}` | {', '.join(f'`{t}`' for t in db_t) or '—'} "
                       f"| {', '.join(f'`{a}`' for a in api_t) or '—'} |")
    parts.append("## TypeScript Server Actions\n\n" + "\n".join(ts_rows))

    return "\n\n".join(parts)


# ── HTML output ───────────────────────────────────────────────────────────────

def _build_html(graph: Graph) -> str:
    vis_nodes: list[dict] = []
    func_types = {"py_func", "ts_func"}
    for n in graph.nodes.values():
        color     = NODE_COLORS.get(n["type"], "#999")
        type_lbl  = NODE_TYPE_LABELS.get(n["type"], n["type"])
        # Short hover tooltip
        hover     = type_lbl
        if n.get("path"):
            hover += f"\\n{n['path']}"
        # Docstring (first 120 chars) in hover
        doc = (n.get("description") or "").strip()
        if doc:
            short_doc = (doc[:120] + "…") if len(doc) > 120 else doc
            hover += f"\\n\\n{short_doc}"
        vis_nodes.append({
            "id":        n["id"],
            "label":     n["label"],
            "title":     hover,            # vis-network hover tooltip
            "docstring": doc,              # full docstring for click panel
            "nodetype":  type_lbl,
            "nodepath":  n.get("path", ""),
            "color":     {"background": color, "border": color},
            "group":     n["type"],
            "font":      {"color": "#111" if n["type"] in ("db_view", "ts_func", "py_func") else "#fff"},
            "hidden":    n["type"] in func_types,
        })

    edge_colors = {
        "reads":     "#4A90D9",
        "writes":    "#E67E22",
        "upserts":   "#9B59B6",
        "calls_rpc": "#8E44AD",
        "fetches":   "#E74C3C",
        "calls":     "#82C4F8",
    }
    vis_edges: list[dict] = []
    for i, e in enumerate(graph.edges):
        from_node = graph.nodes.get(e["from"], {})
        to_node   = graph.nodes.get(e["to"],   {})
        color     = edge_colors.get(e["type"], "#888")
        # Hide edges involving function-level nodes by default
        hidden    = (from_node.get("type") in func_types or to_node.get("type") in func_types)
        vis_edges.append({
            "id":    i,
            "from":  e["from"],
            "to":    e["to"],
            "label": EDGE_LABEL.get(e["type"], e["type"]),
            "arrows": "to",
            "color": {"color": color, "highlight": color, "opacity": 0.7},
            "font":  {"size": 9, "color": "#888"},
            "hidden": hidden,
        })

    nodes_json = json.dumps(vis_nodes)
    edges_json = json.dumps(vis_edges)

    legend_html = "".join(
        f'<div class="leg-item"><div class="leg-dot" style="background:{color}"></div>'
        f'<span>{NODE_TYPE_LABELS[k]}</span></div>'
        for k, color in NODE_COLORS.items()
    )

    func_count = sum(1 for n in graph.nodes.values() if n["type"] == "py_func")
    call_edges = sum(1 for e in graph.edges if e["type"] == "calls")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Swingtrader — Dependency Graph</title>
<script src="https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js"></script>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:system-ui,sans-serif;background:#0d0d0d;color:#e0e0e0;height:100vh;display:flex;flex-direction:column}}
#hdr{{padding:10px 16px;background:#161616;border-bottom:1px solid #2a2a2a;display:flex;align-items:center;gap:12px;flex-shrink:0}}
#hdr h1{{font-size:14px;font-weight:600;color:#fff}}
#hdr span{{font-size:11px;color:#666}}
#wrap{{flex:1;display:flex;overflow:hidden}}
#net{{flex:1}}
#side{{width:230px;background:#161616;border-left:1px solid #2a2a2a;padding:14px;overflow-y:auto;flex-shrink:0;font-size:12px}}
h2{{font-size:10px;text-transform:uppercase;letter-spacing:.07em;color:#555;margin-bottom:8px;margin-top:14px}}
h2:first-child{{margin-top:0}}
.leg-item{{display:flex;align-items:center;gap:6px;margin:4px 0;color:#ccc}}
.leg-dot{{width:11px;height:11px;border-radius:2px;flex-shrink:0}}
.edge-row{{margin:3px 0;font-size:11px;color:#777}}
.edge-row b{{font-weight:600}}
#info-content{{font-size:11px;color:#aaa;line-height:1.6;margin-top:6px;word-break:break-word}}
.info-type{{font-size:10px;color:#555;margin-bottom:2px}}
.info-path{{font-size:10px;color:#4A90D9;margin-bottom:8px;word-break:break-all}}
.info-doc{{font-size:11px;color:#bbb;line-height:1.6;margin-top:8px;padding:8px;background:#1e1e1e;border-left:2px solid #333;border-radius:2px;white-space:pre-wrap}}
#stats{{margin-top:12px;font-size:10px;color:#444;line-height:1.7}}
.view-btn{{display:block;width:100%;padding:6px 10px;border-radius:4px;border:1px solid #333;background:#1a1a1a;color:#999;cursor:pointer;font-size:11px;margin:3px 0;text-align:left}}
.view-btn:hover{{background:#222;color:#ccc}}
.view-btn.on{{background:#2a3a4a;border-color:#4A90D9;color:#82C4F8}}
.fbtn{{padding:3px 8px;border-radius:3px;border:1px solid #333;background:#1a1a1a;color:#777;cursor:pointer;font-size:10px;margin:2px}}
.fbtn:hover,.fbtn.on{{background:#222;color:#ccc}}
</style>
</head>
<body>
<div id="hdr">
  <h1>Swingtrader — Dependency Graph</h1>
  <span>Auto-generated · re-run: <code style="background:#222;padding:1px 5px;border-radius:3px">python analyze_deps.py</code></span>
</div>
<div id="wrap">
  <div id="net"></div>
  <div id="side">

    <h2>View Mode</h2>
    <button class="view-btn on" id="btn-file"     onclick="setView('file')">File overview</button>
    <button class="view-btn"    id="btn-func-db"  onclick="setView('func-db')">Function → DB</button>
    <button class="view-btn"    id="btn-func-call" onclick="setView('func-call')">Function call graph</button>
    <button class="view-btn"    id="btn-all"      onclick="setView('all')">Everything</button>

    <h2>Node Types</h2>
    {legend_html}

    <h2>Edge Types</h2>
    <div class="edge-row"><b style="color:#4A90D9">reads</b> — SELECT</div>
    <div class="edge-row"><b style="color:#E67E22">writes</b> — INSERT/UPDATE/DELETE</div>
    <div class="edge-row"><b style="color:#9B59B6">upserts</b> — UPSERT</div>
    <div class="edge-row"><b style="color:#8E44AD">rpc</b> — stored procedure</div>
    <div class="edge-row"><b style="color:#E74C3C">http</b> — external fetch</div>
    <div class="edge-row"><b style="color:#82C4F8">calls</b> — function call</div>

    <h2>Selected Node</h2>
    <div id="info-content">Click a node</div>

    <div id="stats"></div>
  </div>
</div>
<script>
const ALL_NODES = {nodes_json};
const ALL_EDGES = {edges_json};

// Categorise nodes
const FILE_TYPES  = new Set(['py_module','ts_action','db_table','db_view','db_rpc','external_api']);
const FUNC_TYPES  = new Set(['py_func','ts_func','db_table','db_view','db_rpc','external_api']);
const DB_TYPES    = new Set(['db_table','db_view','db_rpc']);

const nodeSet = new vis.DataSet(ALL_NODES);
const edgeSet = new vis.DataSet(ALL_EDGES);

const net = new vis.Network(
  document.getElementById('net'),
  {{nodes: nodeSet, edges: edgeSet}},
  {{
    nodes: {{shape:'box',borderWidth:1,shadow:{{enabled:true,size:3}},font:{{size:12}}}},
    edges: {{smooth:{{type:'curvedCW',roundness:0.15}},width:1.5}},
    physics: {{
      forceAtlas2Based: {{
        gravitationalConstant:-55,centralGravity:0.006,
        springLength:180,springConstant:0.06,damping:0.4
      }},
      solver:'forceAtlas2Based',
      stabilization:{{iterations:300}}
    }},
    interaction: {{hover:true,tooltipDelay:100,navigationButtons:true,keyboard:true}},
  }}
);

net.on('click', function(p) {{
  const el = document.getElementById('info-content');
  if (p.nodes.length) {{
    const n = ALL_NODES.find(x => x.id === p.nodes[0]);
    if (!n) return;
    let html = '<b style="color:#fff;font-size:13px">' + escHtml(n.label) + '</b>';
    if (n.nodetype) html += '<div class="info-type">' + escHtml(n.nodetype) + '</div>';
    if (n.nodepath) html += '<div class="info-path">' + escHtml(n.nodepath) + '</div>';
    if (n.docstring) {{
      html += '<div class="info-doc">' + escHtml(n.docstring) + '</div>';
    }}
    el.innerHTML = html;
  }} else {{
    el.innerHTML = '<span style="color:#444">Click a node</span>';
  }}
}});

function escHtml(s) {{
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}}

function setView(mode) {{
  document.querySelectorAll('.view-btn').forEach(b => b.classList.remove('on'));
  document.getElementById('btn-' + mode)?.classList.add('on');

  let visNodeIds, visEdgeTypes;

  if (mode === 'file') {{
    // File-level: modules/actions + DB + APIs; no py_func
    visNodeIds   = new Set(ALL_NODES.filter(n => FILE_TYPES.has(n.group)).map(n => n.id));
    visEdgeTypes = new Set(['reads','writes','upserts','calls_rpc','fetches']);
  }} else if (mode === 'func-db') {{
    // Functions → DB objects (+ DB nodes + API nodes)
    visNodeIds   = new Set(ALL_NODES.filter(n => FUNC_TYPES.has(n.group)).map(n => n.id));
    visEdgeTypes = new Set(['reads','writes','upserts','calls_rpc','fetches']);
  }} else if (mode === 'func-call') {{
    // Only py_func nodes + call edges (+ any DB they touch)
    const callEdges = ALL_EDGES.filter(e => e.label === 'calls');
    const funcInCall = new Set(callEdges.flatMap(e => [e.from, e.to]));
    visNodeIds   = funcInCall;
    visEdgeTypes = new Set(['calls']);
  }} else {{
    // Everything
    visNodeIds   = new Set(ALL_NODES.map(n => n.id));
    visEdgeTypes = new Set(Object.keys({{reads:1,writes:1,upserts:1,calls_rpc:1,fetches:1,calls:1}}));
  }}

  nodeSet.update(ALL_NODES.map(n => ({{id:n.id, hidden:!visNodeIds.has(n.id)}})));
  edgeSet.update(ALL_EDGES.map(e => ({{
    id: e.id,
    hidden: !visEdgeTypes.has(e.label) || !visNodeIds.has(e.from) || !visNodeIds.has(e.to)
  }})));

  const vis_n = ALL_NODES.filter(n => visNodeIds.has(n.id)).length;
  const vis_e = ALL_EDGES.filter(e =>
    !e.hidden && visEdgeTypes.has(e.label) &&
    visNodeIds.has(e.from) && visNodeIds.has(e.to)
  ).length;
  document.getElementById('stats').innerHTML =
    vis_n + ' nodes &middot; ' + vis_e + ' edges shown<br>'
    + '({func_count} functions · {call_edges} call edges total)';
}}

setView('file');
</script>
</body>
</html>
"""


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    argparse.ArgumentParser(description=__doc__,
                            formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()

    graph = Graph()

    print("Scanning Python (pass 1 + 2)…")
    py_files, func_nodes = _scan_python(graph)
    print(f"  {py_files} files, {func_nodes} functions with deps")

    print("Scanning TypeScript…")
    ts_count = _scan_typescript(graph)
    print(f"  {ts_count} files")

    call_edges = sum(1 for e in graph.edges if e["type"] == "calls")
    print(f"Graph: {len(graph.nodes)} nodes, {len(graph.edges)} edges "
          f"({call_edges} function-call edges)")

    json_path = REPO_ROOT / "deps-graph.json"
    json_path.write_text(json.dumps(_build_json(graph), indent=2), encoding="utf-8")
    print(f"Written: {json_path.name}")

    md_path = REPO_ROOT / "ARCHITECTURE.md"
    md_path.write_text(_build_markdown(graph), encoding="utf-8")
    print(f"Written: {md_path.name}")

    html_path = REPO_ROOT / "deps-graph.html"
    html_path.write_text(_build_html(graph), encoding="utf-8")
    print(f"Written: {html_path.name}")

    print("\nDone. Open deps-graph.html in browser — use the View Mode buttons to switch layers.")


if __name__ == "__main__":
    main()
