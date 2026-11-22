"""Append-only ledger of everything the drawdown harness seals.

Council round 3: a scorecard overwritten on every run lets anyone re-run the
agents until the list looks right. Files under output/ still get the latest
version (the pages and skills read it), but every run is ALSO archived under
`<date>/runs/<HHMMSS>/` and logged here with a hash of its FULL payload —
groups, margins, cuts, theses, picks. Grading reads the ledger, so a re-run is
always visible: the first entry of a kind for a day is the one that counts.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from .snapshots import ET

PATH = Path(__file__).resolve().parents[2] / "output" / "drawdown" / "ledger.jsonl"


def payload_sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def archive(day_dir: Path, name: str, body: dict) -> Path:
    """Write `name` into day_dir (latest) and an immutable copy under runs/<HHMMSS>/."""
    stamp = datetime.now(ET).strftime("%H%M%S")
    run_dir = day_dir / "runs" / stamp
    run_dir.mkdir(parents=True, exist_ok=True)
    text = json.dumps(body, indent=1, default=str)
    (run_dir / name).write_text(text)
    (day_dir / name).write_text(text)
    return run_dir / name


def append(kind: str, as_of: str, path: Path, body: dict, **extra) -> dict:
    """Log one sealed artefact. Returns the entry, including how many earlier entries of
    this kind exist for the day (0 = this is the one that counts)."""
    PATH.parent.mkdir(parents=True, exist_ok=True)
    prior = 0
    if PATH.exists():
        for line in PATH.read_text().splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            prior += e.get("kind") == kind and e.get("as_of") == as_of
    entry = {"kind": kind, "as_of": as_of, "at": datetime.now(ET).isoformat(), "path": str(path),
             "payload_sha256": payload_sha(body), "prior_entries_today": prior, **extra}
    with PATH.open("a") as f:
        f.write(json.dumps(entry, default=str) + "\n")
    return entry


def first(kind: str, as_of: str) -> dict | None:
    if not PATH.exists():
        return None
    for line in PATH.read_text().splitlines():
        e = json.loads(line)
        if e.get("kind") == kind and e.get("as_of") == as_of:
            return e
    return None
