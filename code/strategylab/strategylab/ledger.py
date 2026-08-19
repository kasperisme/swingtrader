"""Experiment ledger — the replay buffer and the audit trail.

Every trial is written here, including the failures. That is not bookkeeping
hygiene, it is a statistical requirement: the Deflated Sharpe Ratio and the
PBO estimate are both functions of *how many configurations were tried*, so a
search that forgets its failures cannot make an honest claim about its winner.

The ledger also stores each trial's daily return series, which is what lets
`metrics.probability_of_backtest_overfitting` run CSCV across the whole search
at the end rather than on a hand-picked subset.
"""

from __future__ import annotations

import io
import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .genome import Genome

_SCHEMA = """
CREATE TABLE IF NOT EXISTS trials (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            REAL    NOT NULL,
    iteration     INTEGER NOT NULL DEFAULT 0,
    genome_hash   TEXT    NOT NULL,
    genome_json   TEXT    NOT NULL,
    rung          INTEGER NOT NULL,
    valid         INTEGER NOT NULL,
    reason        TEXT,
    reward        REAL,
    sharpe        REAL,
    metrics_json  TEXT,
    folds_json    TEXT,
    diag_json     TEXT,
    parent_hash   TEXT,
    operator      TEXT,
    source        TEXT,
    hypothesis    TEXT
);
CREATE INDEX IF NOT EXISTS ix_trials_hash ON trials(genome_hash, rung);
CREATE INDEX IF NOT EXISTS ix_trials_reward ON trials(rung, reward DESC);

CREATE TABLE IF NOT EXISTS returns (
    genome_hash TEXT NOT NULL,
    rung        INTEGER NOT NULL,
    start_date  TEXT,
    end_date    TEXT,
    payload     BLOB NOT NULL,
    PRIMARY KEY (genome_hash, rung)
);

CREATE TABLE IF NOT EXISTS events (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      REAL NOT NULL,
    kind    TEXT NOT NULL,
    payload TEXT
);
"""


@dataclass
class Trial:
    genome: Genome
    rung: int
    valid: bool
    reward: float
    sharpe: float
    metrics: dict = field(default_factory=dict)
    folds: list = field(default_factory=list)
    diagnostics: dict | None = None
    reason: str = ""
    parent_hash: str | None = None
    operator: str = ""
    source: str = ""
    hypothesis: str = ""
    iteration: int = 0
    returns: np.ndarray | None = None
    dates: np.ndarray | None = None


class Ledger:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # -------------------------------------------------------- writing ----
    def record(self, t: Trial) -> int:
        cur = self.conn.execute(
            """INSERT INTO trials (ts, iteration, genome_hash, genome_json, rung, valid,
                                   reason, reward, sharpe, metrics_json, folds_json,
                                   diag_json, parent_hash, operator, source, hypothesis)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (time.time(), t.iteration, t.genome.hash, t.genome.canonical(), t.rung,
             int(t.valid), t.reason, t.reward, t.sharpe, json.dumps(t.metrics),
             json.dumps(t.folds), json.dumps(t.diagnostics) if t.diagnostics else None,
             t.parent_hash, t.operator, t.source, t.hypothesis))
        if t.returns is not None and t.returns.size:
            buf = io.BytesIO()
            np.save(buf, np.asarray(t.returns, dtype=np.float32))
            self.conn.execute(
                "INSERT OR REPLACE INTO returns VALUES (?,?,?,?,?)",
                (t.genome.hash, t.rung,
                 str(t.dates[0]) if t.dates is not None and len(t.dates) else None,
                 str(t.dates[-1]) if t.dates is not None and len(t.dates) else None,
                 buf.getvalue()))
        self.conn.commit()
        return int(cur.lastrowid)

    def log_event(self, kind: str, payload: dict | None = None) -> None:
        self.conn.execute("INSERT INTO events (ts, kind, payload) VALUES (?,?,?)",
                          (time.time(), kind, json.dumps(payload or {})))
        self.conn.commit()

    # -------------------------------------------------------- reading ----
    def seen(self, genome_hash: str, rung: int | None = None) -> bool:
        if rung is None:
            q = "SELECT 1 FROM trials WHERE genome_hash=? LIMIT 1"
            args = (genome_hash,)
        else:
            q = "SELECT 1 FROM trials WHERE genome_hash=? AND rung>=? LIMIT 1"
            args = (genome_hash, rung)
        return self.conn.execute(q, args).fetchone() is not None

    def count(self, rung: int | None = None, distinct: bool = True) -> int:
        col = "DISTINCT genome_hash" if distinct else "*"
        if rung is None:
            return int(self.conn.execute(f"SELECT COUNT({col}) FROM trials").fetchone()[0])
        return int(self.conn.execute(
            f"SELECT COUNT({col}) FROM trials WHERE rung=?", (rung,)).fetchone()[0])

    def rows(self, rung: int | None = None, valid_only: bool = False,
             order: str = "reward DESC", limit: int = 50) -> list[dict]:
        where, args = [], []
        if rung is not None:
            where.append("rung=?")
            args.append(rung)
        if valid_only:
            where.append("valid=1")
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        q = f"SELECT * FROM trials {clause} ORDER BY {order} LIMIT ?"
        args.append(limit)
        return [dict(r) for r in self.conn.execute(q, args).fetchall()]

    def best(self, n: int = 5, rung: int = 1) -> list[dict]:
        """Top distinct genomes at a rung, best first."""
        q = """SELECT * FROM trials t
               WHERE rung=? AND valid=1
                 AND reward = (SELECT MAX(reward) FROM trials x
                               WHERE x.genome_hash=t.genome_hash AND x.rung=t.rung)
               GROUP BY genome_hash
               ORDER BY reward DESC LIMIT ?"""
        return [dict(r) for r in self.conn.execute(q, (rung, n)).fetchall()]

    def recent(self, n: int = 10, rung: int | None = None) -> list[dict]:
        if rung is None:
            q, args = "SELECT * FROM trials ORDER BY id DESC LIMIT ?", (n,)
        else:
            q, args = "SELECT * FROM trials WHERE rung=? ORDER BY id DESC LIMIT ?", (rung, n)
        return [dict(r) for r in self.conn.execute(q, args).fetchall()]

    def sharpes(self, rung: int = 1) -> list[float]:
        return [float(r[0]) for r in self.conn.execute(
            "SELECT sharpe FROM trials WHERE rung=? AND sharpe IS NOT NULL", (rung,)).fetchall()]

    def rewards(self, rung: int = 1) -> list[tuple[str, float]]:
        return [(r[0], float(r[1])) for r in self.conn.execute(
            "SELECT genome_hash, reward FROM trials WHERE rung=? AND reward IS NOT NULL "
            "AND valid=1", (rung,)).fetchall()]

    def genome_of(self, genome_hash: str) -> Genome | None:
        row = self.conn.execute(
            "SELECT genome_json FROM trials WHERE genome_hash=? LIMIT 1",
            (genome_hash,)).fetchone()
        return Genome(json.loads(row[0])) if row else None

    def operator_stats(self, rung: int = 1) -> dict[str, dict]:
        """Per-operator reward statistics — the bandit's observation history."""
        out: dict[str, dict] = {}
        for r in self.conn.execute(
                "SELECT operator, reward, valid FROM trials WHERE rung=? AND operator IS NOT NULL "
                "AND operator != ''", (rung,)).fetchall():
            op = r[0]
            s = out.setdefault(op, {"n": 0, "sum": 0.0, "sumsq": 0.0, "valid": 0, "best": -9e9})
            v = float(r[1]) if r[1] is not None else -5.0
            s["n"] += 1
            s["sum"] += v
            s["sumsq"] += v * v
            s["valid"] += int(r[2])
            s["best"] = max(s["best"], v)
        for s in out.values():
            s["mean"] = s["sum"] / max(1, s["n"])
            s["valid_rate"] = s["valid"] / max(1, s["n"])
        return out

    def returns_for(self, genome_hash: str, rung: int = 1) -> np.ndarray | None:
        """The stored daily return series for one genome.

        Reading this back rather than re-running is what makes `finalize`
        reproducible: a re-evaluation silently depends on whatever happens to be
        in the price cache TODAY, so syncing more symbols between the search and
        the finalize changes the answer for a genome nobody touched.
        """
        row = self.conn.execute(
            "SELECT payload FROM returns WHERE genome_hash=? AND rung=?",
            (genome_hash, rung)).fetchone()
        if not row:
            return None
        return np.load(io.BytesIO(row["payload"])).astype(np.float64)

    # ------------------------------------------------- CSCV support ------
    def returns_matrix(self, rung: int = 1, limit: int = 120) -> tuple[np.ndarray, list[str]]:
        """(n_periods, n_trials) matrix of aligned daily returns.

        Only trials that share an identical timeline are kept — comparing
        configurations across different windows would make the CSCV meaningless.
        """
        rows = self.conn.execute(
            "SELECT genome_hash, start_date, end_date, payload FROM returns WHERE rung=?",
            (rung,)).fetchall()
        if not rows:
            return np.zeros((0, 0)), []
        spans: dict[tuple, list] = {}
        for r in rows:
            spans.setdefault((r["start_date"], r["end_date"]), []).append(r)
        best_span = max(spans.values(), key=len)[:limit]
        arrays, names = [], []
        length = None
        for r in best_span:
            a = np.load(io.BytesIO(r["payload"]))
            if length is None:
                length = a.size
            if a.size != length:
                continue
            arrays.append(a.astype(np.float64))
            names.append(r["genome_hash"])
        if len(arrays) < 2:
            return np.zeros((0, 0)), []
        return np.column_stack(arrays), names

    def inherited_trials(self) -> int:
        """Configurations searched by the run(s) that produced this run's seed.

        Without this, restarting a search from its own winner resets the trial
        count to 1 and the deflated Sharpe stops accounting for the search that
        actually did the selecting.
        """
        row = self.conn.execute(
            "SELECT payload FROM events WHERE kind='run_started' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not row:
            return 0
        try:
            return int(json.loads(row[0]).get("inherited_trials") or 0)
        except Exception:
            return 0

    def holdout_uses(self) -> int:
        """How many times the never-searched window has been consulted.

        Once is evidence. Ten times is a training set with extra steps.
        """
        return int(self.conn.execute(
            "SELECT COUNT(*) FROM events WHERE kind='holdout_used'").fetchone()[0])

    def summary(self) -> dict:
        return {
            "trials_total": self.count(distinct=False),
            "genomes_distinct": self.count(distinct=True),
            "rung0": self.count(rung=0, distinct=False),
            "rung1": self.count(rung=1, distinct=False),
            "vault": self.count(rung=2, distinct=False),
            "vault_opened": self.conn.execute(
                "SELECT COUNT(*) FROM events WHERE kind='vault_opened'").fetchone()[0],
            "holdout_uses": self.holdout_uses(),
        }
