"""The persistent record of every hypothesis ever tested.

This is the load-bearing component, and it is load-bearing precisely because it
remembers failures. The significance bar is a function of how many hypotheses
have been tried; a bar computed only from the ones that looked interesting is
not a bar at all, it is the selection effect wearing a lab coat.

The registry is append-only and survives restarts. A loop resumed tomorrow
inherits today's trial count and therefore today's — higher — bar.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS hypotheses (
    key         TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    primitive   TEXT, transform TEXT, outcome TEXT, horizon INTEGER,
    registered_at TEXT NOT NULL,
    tested_at   TEXT,
    rung        INTEGER DEFAULT 0,
    effect      REAL, t_stat REAL, p_value REAL,
    placebo_t   REAL, control_effect REAL, n_obs INTEGER,
    bar         REAL, cleared INTEGER DEFAULT 0,
    vault_effect REAL, vault_t REAL, confirmed INTEGER DEFAULT 0,
    payload     TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT
);
"""


@dataclass
class ScoredHypothesis:
    key: str
    name: str
    effect: float = float("nan")
    t_stat: float = float("nan")
    p_value: float = float("nan")
    placebo_t: float = float("nan")
    control_effect: float = float("nan")
    n_obs: int = 0
    rung: int = 0
    bar: float = float("nan")
    cleared: bool = False
    vault_effect: float = float("nan")
    vault_t: float = float("nan")
    confirmed: bool = False
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class Registry:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    # ------------------------------------------------------------------
    def register(self, h) -> None:
        """Record a hypothesis BEFORE it runs. Pre-registration, per trial."""
        self.db.execute(
            "INSERT OR IGNORE INTO hypotheses (key, name, primitive, transform, "
            "outcome, horizon, registered_at) VALUES (?,?,?,?,?,?,?)",
            (h.key, h.name, h.primitive, h.transform, h.outcome, h.horizon,
             datetime.now().isoformat(timespec="seconds")))
        self.db.commit()

    def record(self, s: ScoredHypothesis) -> None:
        self.db.execute(
            "UPDATE hypotheses SET tested_at=?, rung=?, effect=?, t_stat=?, p_value=?, "
            "placebo_t=?, control_effect=?, n_obs=?, bar=?, cleared=?, vault_effect=?, "
            "vault_t=?, confirmed=?, payload=? WHERE key=?",
            (datetime.now().isoformat(timespec="seconds"), s.rung, s.effect, s.t_stat,
             s.p_value, s.placebo_t, s.control_effect, s.n_obs, s.bar, int(s.cleared),
             s.vault_effect, s.vault_t, int(s.confirmed),
             json.dumps(s.detail, default=str), s.key))
        self.db.commit()

    def log(self, kind: str, payload: dict | None = None) -> None:
        self.db.execute("INSERT INTO events (at, kind, payload) VALUES (?,?,?)",
                        (datetime.now().isoformat(timespec="seconds"), kind,
                         json.dumps(payload or {}, default=str)))
        self.db.commit()

    # ------------------------------------------------------------------
    def tested_keys(self) -> set[str]:
        return {r["key"] for r in
                self.db.execute("SELECT key FROM hypotheses WHERE tested_at IS NOT NULL")}

    def n_tested(self) -> int:
        """The trial count that sets the bar. Counts EVERY tested hypothesis,
        including the ones that failed — that is the entire point."""
        return int(self.db.execute(
            "SELECT COUNT(*) FROM hypotheses WHERE tested_at IS NOT NULL").fetchone()[0])

    def best(self, n: int = 10) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM hypotheses WHERE tested_at IS NOT NULL "
            "ORDER BY ABS(COALESCE(t_stat,0)) DESC LIMIT ?", (n,))]

    def confirmed(self) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM hypotheses WHERE confirmed=1 ORDER BY ABS(t_stat) DESC")]

    def cleared(self) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM hypotheses WHERE cleared=1 ORDER BY ABS(t_stat) DESC")]

    def summary(self) -> dict:
        n = self.n_tested()
        row = self.db.execute(
            "SELECT MAX(ABS(t_stat)) AS max_t, AVG(ABS(t_stat)) AS mean_t "
            "FROM hypotheses WHERE tested_at IS NOT NULL").fetchone()
        return {"tested": n, "registered": int(self.db.execute(
                    "SELECT COUNT(*) FROM hypotheses").fetchone()[0]),
                "cleared": len(self.cleared()), "confirmed": len(self.confirmed()),
                "max_abs_t": row["max_t"], "mean_abs_t": row["mean_t"]}
