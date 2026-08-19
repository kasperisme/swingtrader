"""Findings — what the researcher is allowed to claim it knows.

Nothing enters this store on the strength of one measurement. Every result this
project produced that looked good on first sight failed to replicate:

  * a pre-filter worth +0.156 Sharpe on one genome: mean +0.030 across seven,
    paired t = 0.66, p = 0.53
  * an "impact law" with R² = 0.83: the same fit on the next window gave
    Y = 0.001, p = 0.92
  * a search worth 5.5x in-sample: worth +0.03 Sharpe on unseen data
  * a "ranking is inverted" diagnostic: fired at p = 0.505, and correcting the
    "defect" cut Sharpe from 0.512 to 0.263

A researcher running unattended will generate these continuously. The store's
job is to make the difference between OBSERVED and CONFIRMED structural, so a
morning report cannot quietly present the first as the second.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class Status(str, Enum):
    OBSERVED = "observed"          # seen once; no claim is licensed
    REPLICATING = "replicating"    # replication attempts under way
    CONFIRMED = "confirmed"        # held up on data that did not produce it
    REFUTED = "refuted"            # tested and failed
    VACUOUS = "vacuous"            # untestable as stated


@dataclass
class Finding:
    claim: str
    evidence: dict = field(default_factory=dict)
    status: Status = Status.OBSERVED
    replications: int = 0
    refutations: int = 0
    source: str = ""
    hypothesis_id: str = ""
    created: float = field(default_factory=time.time)

    @property
    def credible(self) -> bool:
        """Two independent replications and no refutation.

        Deliberately strict. Everything that failed here failed on the FIRST
        honest replication attempt, so one is not enough to be worth the risk of
        an autonomous system asserting it unattended.
        """
        return (self.status is Status.CONFIRMED
                and self.replications >= 2 and self.refutations == 0)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS findings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    created       REAL NOT NULL,
    updated       REAL NOT NULL,
    claim         TEXT NOT NULL UNIQUE,
    status        TEXT NOT NULL,
    replications  INTEGER NOT NULL DEFAULT 0,
    refutations   INTEGER NOT NULL DEFAULT 0,
    evidence_json TEXT,
    source        TEXT,
    hypothesis_id TEXT
);
CREATE TABLE IF NOT EXISTS attempts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         REAL NOT NULL,
    claim      TEXT NOT NULL,
    outcome    TEXT NOT NULL,
    detail     TEXT
);
"""


class FindingStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def observe(self, f: Finding) -> None:
        """Record a first sighting. Never a claim — only a candidate."""
        now = time.time()
        self.conn.execute(
            "INSERT INTO findings (created, updated, claim, status, replications, "
            "refutations, evidence_json, source, hypothesis_id) "
            "VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(claim) DO UPDATE SET updated=?",
            (now, now, f.claim, Status.OBSERVED.value, 0, 0,
             json.dumps(f.evidence, default=str), f.source, f.hypothesis_id, now))
        self.conn.commit()

    def record_attempt(self, claim: str, replicated: bool, detail: str = "") -> Status:
        """Log a replication attempt and update the claim's standing."""
        now = time.time()
        self.conn.execute("INSERT INTO attempts (ts, claim, outcome, detail) VALUES (?,?,?,?)",
                          (now, claim, "replicated" if replicated else "failed", detail))
        row = self.conn.execute(
            "SELECT replications, refutations FROM findings WHERE claim=?", (claim,)).fetchone()
        if row is None:
            self.observe(Finding(claim=claim))
            reps = refs = 0
        else:
            reps, refs = row["replications"], row["refutations"]
        reps += int(replicated)
        refs += int(not replicated)
        # One refutation is decisive. A claim that has failed on honest unseen
        # data does not get to accumulate its way back to CONFIRMED.
        if refs > 0:
            status = Status.REFUTED
        elif reps >= 2:
            status = Status.CONFIRMED
        else:
            status = Status.REPLICATING
        self.conn.execute(
            "UPDATE findings SET replications=?, refutations=?, status=?, updated=? "
            "WHERE claim=?", (reps, refs, status.value, now, claim))
        self.conn.commit()
        return status

    def get(self, claim: str) -> Finding | None:
        r = self.conn.execute("SELECT * FROM findings WHERE claim=?", (claim,)).fetchone()
        if not r:
            return None
        return Finding(claim=r["claim"], status=Status(r["status"]),
                       replications=r["replications"], refutations=r["refutations"],
                       evidence=json.loads(r["evidence_json"] or "{}"),
                       source=r["source"] or "", hypothesis_id=r["hypothesis_id"] or "",
                       created=r["created"])

    def by_status(self, status: Status, limit: int = 50) -> list[Finding]:
        rows = self.conn.execute(
            "SELECT * FROM findings WHERE status=? ORDER BY updated DESC LIMIT ?",
            (status.value, limit)).fetchall()
        return [self.get(r["claim"]) for r in rows]

    def credible(self) -> list[Finding]:
        return [f for f in self.by_status(Status.CONFIRMED, 200) if f and f.credible]

    def summary(self) -> dict:
        counts = {s.value: 0 for s in Status}
        for r in self.conn.execute("SELECT status, COUNT(*) c FROM findings GROUP BY status"):
            counts[r["status"]] = r["c"]
        return {"by_status": counts,
                "credible": len(self.credible()),
                "attempts": self.conn.execute(
                    "SELECT COUNT(*) FROM attempts").fetchone()[0]}
