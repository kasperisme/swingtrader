"""Where FMP calls come from: a per-process tally of every request to
financialmodelingprep.com, attributed to the job and the code that made it.

The FMP dashboard counts calls per endpoint and nothing else, and ~20 modules
reach FMP with bare ``requests``/``httpx`` calls rather than through one client.
So this counts at the transport: ``install()`` wraps ``requests.Session.send``
and ``httpx.(Async)Client.send``, and every FMP request, from any module
(including ones written after this), is tallied under

    job       the process entrypoint           services.arena.cli run-day
    endpoint  the path as FMP's dashboard      /v3/historical-price-full
              names it (symbol stripped)       /mcp[quote]  (hosted MCP tool calls)
    caller    the first three project frames   screener/fmp.py:daily_chart
              on the stack, innermost first      < services/arena/marks.py:_bars < ...
    status    2xx / 4xx / 5xx / err

with the call count, total latency and the decoded response bytes. Bytes are
the number that matters: FMP's binding limit is a 30-day BANDWIDTH cap (a 429
reading "Bandwidth Limit Reach"), and one year of daily bars weighs as much as
~2,000 quotes.

Counts live in memory and are appended as JSONL to
``<repo>/logs/fmp_usage/<UTC date>.jsonl`` every 60 s and at exit, so a call
costs a stack walk and a dict increment, never a write. A SIGKILLed process
loses at most its last minute.

    python -m shared.fmp_usage report --days 7            # per endpoint by MB, top callers
    python -m shared.fmp_usage report --days 1 --by job   # per job, its endpoints

Installed by ``services/__init__.py`` (every ``python -m services.…`` process)
and by strategylab's FMP client. Off under pytest; ``FMP_USAGE_LOG=0`` turns it
off anywhere; ``FMP_USAGE_JOB`` overrides the job label; ``FMP_USAGE_DIR``
moves the log.

This only sees the Mac Mini (and any laptop run). Vercel's calls from
``code/ui/app/actions/fmp.ts`` never pass through here, so the dashboard total
minus this log is what the website costs.
"""

from __future__ import annotations

import argparse
import atexit
import json
import os
import re
import socket
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

_FMP_HOST = "financialmodelingprep.com"
_REPO = Path(__file__).resolve().parents[3]
_REPO_PREFIX = str(_REPO) + os.sep
_FLUSH_EVERY_S = 60.0
_CALLER_DEPTH = 3

# v3/v4 put the symbol (or a comma list of them) in the path; the dashboard
# groups without it. Lowercase segments (`1day`, `stock_split`) are routes.
_SYMBOL_SEGMENT = re.compile(r"^[A-Z0-9^][A-Z0-9.^=,\-]*$")

_lock = threading.Lock()
_counts: dict[tuple[str, str, str], list[float]] = defaultdict(lambda: [0, 0.0, 0])  # n, ms, bytes
_last_flush = time.monotonic()
_originals: dict[str, tuple[object, str, object]] = {}


def endpoint_of(url: str, body: bytes | str | None = None) -> str:
    """``https://…/api/v3/quote/AAPL,MSFT?apikey=…`` → ``/v3/quote``."""
    path = urlsplit(str(url)).path.rstrip("/")
    if path.startswith("/api/"):
        path = path[4:]
    parts = path.split("/")
    last = parts[-1]
    if len(parts) > 2 and _SYMBOL_SEGMENT.match(last) and any(c.isalpha() or c == "^" for c in last):
        parts = parts[:-1]
    endpoint = "/".join(parts) or "/"
    if endpoint == "/mcp":
        tool = _mcp_tool(body)
        if tool:
            endpoint = f"/mcp[{tool}]"
    return endpoint


def _mcp_tool(body: bytes | str | None) -> str | None:
    """The tool a JSON-RPC ``tools/call`` names; the method name otherwise.

    FMP's hosted MCP server calls its REST endpoints under our key, so an agent's
    tool call is REST usage that no code path here ever names directly."""
    if not body:
        return None
    try:
        msg = json.loads(body)
    except (ValueError, TypeError):
        return None
    if not isinstance(msg, dict):
        return None
    if msg.get("method") != "tools/call":
        return msg.get("method")
    params = msg.get("params") or {}
    name = params.get("name") or "?"
    sub = (params.get("arguments") or {}).get("endpoint")
    return f"{name}:{sub}" if sub else name


def _caller() -> str:
    frame = sys._getframe(2)
    chain: list[str] = []
    while frame is not None and len(chain) < _CALLER_DEPTH:
        fn = frame.f_code.co_filename
        if fn.startswith(_REPO_PREFIX) and "site-packages" not in fn and fn != __file__:
            rel = fn[len(_REPO_PREFIX):].removeprefix("code/analytics/").removeprefix("code/")
            item = f"{rel}:{frame.f_code.co_name}"
            if not chain or chain[-1] != item:
                chain.append(item)
        frame = frame.f_back
    return " < ".join(chain) or "?"


def _job() -> str:
    if os.environ.get("FMP_USAGE_JOB"):
        return os.environ["FMP_USAGE_JOB"]
    spec = getattr(sys.modules.get("__main__"), "__spec__", None)
    if spec is not None and spec.name:
        name = spec.name.removesuffix(".__main__")
    else:
        name = Path(sys.argv[0]).name if sys.argv and sys.argv[0] else "?"
    # The subcommand is part of the job: `arena.cli run-day` is not `arena.cli standings`.
    sub = next((a for a in sys.argv[1:] if not a.startswith("-")), None)
    return f"{name} {sub}" if sub else name


def _size(resp) -> int:
    """Decoded body bytes when the client already read the body; the wire
    length for a streamed response (reading it here would consume it)."""
    try:
        body = getattr(resp, "_content", None)  # requests: bytes once read
        if isinstance(body, bytes):
            return len(body)
        return len(resp.content)  # httpx: raises ResponseNotRead when streamed
    except Exception:
        try:
            return int(resp.headers.get("content-length") or 0)
        except Exception:
            return 0


def _record(url, body, status: str, started: float, caller: str, size: int = 0) -> None:
    try:
        key = (endpoint_of(url, body), caller, status)
        ms = (time.perf_counter() - started) * 1000
        with _lock:
            c = _counts[key]
            c[0] += 1
            c[1] += ms
            c[2] += size
            due = time.monotonic() - _last_flush >= _FLUSH_EVERY_S
        if due:
            flush()
    except Exception:
        pass  # a tally must never break the request it is counting


def _log_dir() -> Path:
    return Path(os.environ.get("FMP_USAGE_DIR") or _REPO / "logs" / "fmp_usage")


def flush() -> None:
    global _last_flush
    with _lock:
        items = list(_counts.items())
        _counts.clear()
        _last_flush = time.monotonic()
    if not items:
        return
    try:
        now = datetime.now(timezone.utc)
        d = _log_dir()
        d.mkdir(parents=True, exist_ok=True)
        base = {"ts": now.isoformat(timespec="seconds"), "host": socket.gethostname(),
                "pid": os.getpid(), "job": _job()}
        fd = os.open(d / f"{now:%Y-%m-%d}.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            # One small write per line: O_APPEND keeps concurrent processes from
            # interleaving inside a line, which a buffered multi-KB write can't promise.
            for (endpoint, caller, status), (n, ms, size) in items:
                row = {**base, "endpoint": endpoint, "caller": caller, "status": status,
                       "n": int(n), "ms": round(ms), "bytes": int(size)}
                os.write(fd, (json.dumps(row) + "\n").encode())
        finally:
            os.close(fd)
    except Exception:
        pass


def _wrap_sync(orig):
    def send(self, request, *args, **kwargs):
        if _FMP_HOST not in str(request.url):
            return orig(self, request, *args, **kwargs)
        caller, started = _caller(), time.perf_counter()
        body = getattr(request, "body", None)  # requests.PreparedRequest
        if body is None:
            try:
                body = request.content  # httpx.Request
            except Exception:
                body = None
        try:
            resp = orig(self, request, *args, **kwargs)
        except Exception:
            _record(request.url, body, "err", started, caller)
            raise
        _record(request.url, body, f"{resp.status_code // 100}xx", started, caller, _size(resp))
        return resp
    send._fmp_usage = True
    return send


def _wrap_async(orig):
    async def send(self, request, *args, **kwargs):
        if _FMP_HOST not in str(request.url):
            return await orig(self, request, *args, **kwargs)
        caller, started = _caller(), time.perf_counter()
        try:
            body = request.content
        except Exception:
            body = None
        try:
            resp = await orig(self, request, *args, **kwargs)
        except Exception:
            _record(request.url, body, "err", started, caller)
            raise
        _record(request.url, body, f"{resp.status_code // 100}xx", started, caller, _size(resp))
        return resp
    send._fmp_usage = True
    return send


def _disabled() -> bool:
    return os.environ.get("FMP_USAGE_LOG", "").lower() in ("0", "false", "off", "no")


def install(*, force: bool = False) -> None:
    """Patch the HTTP clients once per process. Idempotent even across two
    copies of this module (strategylab loads it by path), because the mark is
    on the patched function, not in module state."""
    if _disabled() or ("pytest" in sys.modules and not force):
        return
    targets = []
    try:
        import requests
        targets.append(("requests", requests.Session, _wrap_sync))
    except ImportError:
        pass
    try:
        import httpx
        targets.append(("httpx", httpx.Client, _wrap_sync))
        targets.append(("httpx-async", httpx.AsyncClient, _wrap_async))
    except ImportError:
        pass
    patched = False
    for label, cls, wrap in targets:
        orig = cls.send
        if getattr(orig, "_fmp_usage", False):
            continue
        cls.send = wrap(orig)
        _originals[label] = (cls, "send", orig)
        patched = True
    if patched:
        atexit.register(flush)
        if hasattr(os, "register_at_fork"):
            # A forked child inherits the parent's unflushed counts; drop them
            # or both processes write the same calls.
            os.register_at_fork(after_in_child=_counts.clear)


def uninstall() -> None:
    for cls, attr, orig in _originals.values():
        setattr(cls, attr, orig)
    _originals.clear()


# ── report ──────────────────────────────────────────────────────────────────

def load(days: int, directory: Path | None = None) -> list[dict]:
    d = directory or _log_dir()
    today = datetime.now(timezone.utc).date()
    rows: list[dict] = []
    for i in range(days):
        path = d / f"{today - timedelta(days=i):%Y-%m-%d}.jsonl"
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def report(days: int = 7, by: str = "endpoint", top: int = 8, directory: Path | None = None) -> str:
    rows = load(days, directory)
    if not rows:
        return f"no FMP usage logged in the last {days} day(s) under {directory or _log_dir()}"
    span = len({r["ts"][:10] for r in rows}) or 1
    outer, inner = ("endpoint", "source") if by == "endpoint" else ("job", "endpoint")

    def source(r: dict) -> str:
        return f"{r['job']}  |  {r['caller']}"

    # [calls, bytes, non-2xx calls] per group, and per (group, sub-row).
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    detail: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0, 0]))
    for r in rows:
        k = r[outer]
        sub = source(r) if inner == "source" else r[inner]
        for t in (totals[k], detail[k][sub]):
            t[0] += r["n"]
            t[1] += r.get("bytes", 0)
            t[2] += r["n"] if r["status"] != "2xx" else 0

    mb = lambda b: b / 1e6  # noqa: E731
    calls = sum(t[0] for t in totals.values())
    size = sum(t[1] for t in totals.values())
    out = [
        f"FMP usage logged over {span} day(s) with data: {calls:,} calls, {mb(size):,.1f} MB "
        f"(≈{calls / span:,.0f} calls, {mb(size) / span:,.1f} MB per day). Sorted by MB — "
        "bandwidth is the plan's binding cap.",
        "",
        f"{'MB':>10} {'MB/day':>8} {'calls':>9} {'KB/call':>8} {'non-2xx':>8}  {outer}",
    ]
    for k, (n, b, bad) in sorted(totals.items(), key=lambda kv: (-kv[1][1], -kv[1][0])):
        out.append(f"{mb(b):>10,.1f} {mb(b) / span:>8,.1f} {n:>9,} {b / n / 1e3:>8,.1f} {bad / n:>8.0%}  {k}")
        for sub, (m, sb, _) in sorted(detail[k].items(), key=lambda kv: (-kv[1][1], -kv[1][0]))[:top]:
            out.append(f"{mb(sb):>10,.1f} {'':>8} {m:>9,} {sb / m / 1e3:>8,.1f} {'':>8}    {sub}")
        out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="python -m shared.fmp_usage")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report", help="aggregate the usage log")
    r.add_argument("--days", type=int, default=7)
    r.add_argument("--by", choices=("endpoint", "job"), default="endpoint")
    r.add_argument("--top", type=int, default=8, help="rows shown under each group")
    r.add_argument("--dir", type=Path, default=None)
    a = p.parse_args(argv)
    print(report(a.days, a.by, a.top, a.dir))


if __name__ == "__main__":
    main()
