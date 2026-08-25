"""The persistent record of every thesis and every link ever run.

Same discipline as `discover/registry.py`, and for the same reason: a lab that
remembers only its interesting results is not keeping a record, it is curating
one. Links are registered *before* they run, failures are kept forever, and the
lab-wide trial count is reported next to every verdict so a reader can see how
much searching stands behind a number.

The one addition over the discovery registry is `link_runs`. A single link may
be measured several times — a wider universe, a longer window, a different
control — and each of those is an arm of a search even when the link id does not
change. Counting arms rather than links is what stops a thesis from quietly
sweeping twenty variants and reporting the best one as a single pre-registered
test.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .thesis import PENDING, LinkResult, Thesis

SCHEMA = """
CREATE TABLE IF NOT EXISTS theses (
    id            TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    mechanism     TEXT,
    source        TEXT,
    registered_at TEXT NOT NULL,
    verdict       TEXT DEFAULT 'PENDING',
    reason        TEXT,
    settled_at    TEXT
);
CREATE TABLE IF NOT EXISTS links (
    key         TEXT PRIMARY KEY,
    thesis_id   TEXT NOT NULL,
    link_id     TEXT NOT NULL,
    claim       TEXT, null_claim TEXT, outcome TEXT, control TEXT,
    kill        TEXT, data TEXT, cost TEXT, direction INTEGER, anchor TEXT,
    registered_at TEXT NOT NULL,
    verdict     TEXT DEFAULT 'PENDING',
    UNIQUE(thesis_id, link_id)
);
CREATE TABLE IF NOT EXISTS link_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at          TEXT NOT NULL,
    thesis_id   TEXT NOT NULL,
    link_id     TEXT NOT NULL,
    arm         TEXT NOT NULL DEFAULT 'main',
    verdict     TEXT,
    effect      REAL, t_stat REAL, n_obs INTEGER,
    placebo_t   REAL, control_effect REAL, bar REAL,
    vault_effect REAL, vault_t REAL,
    note        TEXT, detail TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT
);
"""


class ThesisRegistry:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    # ---------------------------------------------------------- register ----
    def register(self, th: Thesis) -> None:
        """Record the thesis and every link BEFORE anything runs."""
        now = datetime.now().isoformat(timespec="seconds")
        self.db.execute(
            "INSERT OR IGNORE INTO theses (id, title, mechanism, source, registered_at) "
            "VALUES (?,?,?,?,?)", (th.id, th.title, th.mechanism, th.source, now))
        for ln in th.links:
            self.db.execute(
                "INSERT OR IGNORE INTO links (key, thesis_id, link_id, claim, null_claim, "
                "outcome, control, kill, data, cost, direction, anchor, registered_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (ln.key(th.id), th.id, ln.id, ln.claim, ln.null, ln.outcome, ln.control,
                 ln.kill, json.dumps(list(ln.data)), ln.cost, ln.direction, ln.anchor, now))
        self.db.commit()
        self.log("thesis_registered", {"thesis": th.id, "links": len(th.links)})

    # --------------------------------------------------------------- run ----
    def record(self, thesis_id: str, r: LinkResult, arm: str = "main") -> None:
        self.db.execute(
            "INSERT INTO link_runs (at, thesis_id, link_id, arm, verdict, effect, t_stat, "
            "n_obs, placebo_t, control_effect, bar, vault_effect, vault_t, note, detail) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (datetime.now().isoformat(timespec="seconds"), thesis_id, r.link_id, arm,
             r.verdict, r.effect, r.t_stat, r.n_obs, r.placebo_t, r.control_effect,
             r.bar, r.vault_effect, r.vault_t, r.note,
             json.dumps(r.detail, default=str)))
        self.db.execute("UPDATE links SET verdict=? WHERE thesis_id=? AND link_id=?",
                        (r.verdict, thesis_id, r.link_id))
        self.db.commit()

    def settle(self, thesis_id: str, verdict: str, reason: str) -> None:
        self.db.execute("UPDATE theses SET verdict=?, reason=?, settled_at=? WHERE id=?",
                        (verdict, reason, datetime.now().isoformat(timespec="seconds"),
                         thesis_id))
        self.db.commit()
        self.log("thesis_settled", {"thesis": thesis_id, "verdict": verdict,
                                    "reason": reason})

    def log(self, kind: str, payload: dict | None = None) -> None:
        self.db.execute("INSERT INTO events (at, kind, payload) VALUES (?,?,?)",
                        (datetime.now().isoformat(timespec="seconds"), kind,
                         json.dumps(payload or {}, default=str)))
        self.db.commit()

    # ------------------------------------------------------------- reads ----
    def arms_run(self, thesis_id: str) -> int:
        """Every measurement inside this thesis — the count an exploratory
        link's bar is computed from."""
        return int(self.db.execute(
            "SELECT COUNT(*) FROM link_runs WHERE thesis_id=?", (thesis_id,)).fetchone()[0])

    def results(self, thesis_id: str) -> dict[str, LinkResult]:
        """Latest run per link."""
        out: dict[str, LinkResult] = {}
        for r in self.db.execute(
                "SELECT * FROM link_runs WHERE thesis_id=? ORDER BY id", (thesis_id,)):
            out[r["link_id"]] = LinkResult(
                link_id=r["link_id"], verdict=r["verdict"], effect=r["effect"],
                t_stat=r["t_stat"], n_obs=r["n_obs"] or 0, placebo_t=r["placebo_t"],
                control_effect=r["control_effect"], bar=r["bar"],
                vault_effect=r["vault_effect"], vault_t=r["vault_t"],
                note=r["note"] or "", detail=json.loads(r["detail"] or "{}"))
        return out

    def theses(self) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM theses ORDER BY registered_at")]

    def links(self, thesis_id: str) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM links WHERE thesis_id=? ORDER BY rowid", (thesis_id,))]

    def lab_trials(self, discover_db: Path | None = None) -> dict:
        """Total measurements taken across the lab.

        Reported alongside every verdict. It does NOT set a pre-registered
        link's bar (see `thesis.link_bar`) — it exists so nobody can read a
        t-statistic without also seeing how many draws it was selected from.
        """
        mine = int(self.db.execute("SELECT COUNT(*) FROM link_runs").fetchone()[0])
        disc = 0
        if discover_db and Path(discover_db).exists():
            try:
                con = sqlite3.connect(discover_db)
                disc = int(con.execute(
                    "SELECT COUNT(*) FROM hypotheses WHERE tested_at IS NOT NULL"
                ).fetchone()[0])
                con.close()
            except sqlite3.Error:
                disc = 0
        return {"thesis_arms": mine, "discover_hypotheses": disc, "total": mine + disc}
