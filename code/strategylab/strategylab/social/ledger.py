"""The sealed prediction ledger, with Supabase as the source of truth.

`predict.PredictionLedger` keeps the ledger in a local SQLite file and treats
Supabase as a mirror. That inverts the moment the programme runs on a schedule.
A scheduled pass is not tied to the machine that started it; the first run
somewhere else opens an empty `predictions.db`, sees no locks, and re-registers
predictions that already exist under a different `made_on` — which is a
retrospective edit wearing a new hash, and precisely the failure Tier 3 exists
to make impossible.

So the ledger moves to the database, and the move makes the record *stricter*
rather than merely more durable:

* **The immutability rule is enforced by the server.** `research_predictions`
  carries a trigger that refuses any change to a sealed field and refuses a
  second resolution. SQLite enforced neither — `predict.py` checked both in
  Python, which is a promise rather than a guarantee.
* **The lock is a content hash, so the move costs nothing.** A row already
  mirrored re-derives to the same primary key. Migration is an INSERT ... ON
  CONFLICT DO NOTHING, and a disagreement between the two stores shows up as a
  failed hash rather than a silent duplicate.
* **`due()` is a query, not a scan.** The partial index on unresolved rows by
  `resolve_on` is already there for it.

## Interface

Deliberately identical to `PredictionLedger` — `register`, `due`, `tampered`,
`record_outcome`, `resolved`, `summary`, `log` — so `predict.score()` and the
existing CLI paths work against either without knowing which they hold. The one
addition is `migrate_from_sqlite()`, used once.

## What is NOT moved

`published`. A prediction being sealed and a prediction being shown are separate
decisions, and the second one stays manual for the same reason it does
everywhere else in the `research_*` family.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path

from .predict import RESOLVERS, TRUE, Prediction

log = logging.getLogger(__name__)


class SupabaseLedger:
    """Append-only, and the append-only part is now the database's job."""

    def __init__(self, schema: str | None = None, publisher=None):
        if publisher is None:
            from .persist import PricedInPublisher
            publisher = PricedInPublisher(schema)
        self.pub = publisher
        self.schema = self.pub.schema

    # ------------------------------------------------------------------
    def _conn(self):
        return self.pub._connect()

    def ready(self) -> tuple[bool, str]:
        return self.pub.ready()

    _COLS = ("lock, ticker, driver, priced_in_pct, p_resolves, move_if_true, "
             "move_if_false, resolver, spec_json, made_on, resolve_on, "
             "price_at_prediction, rationale, outcome, outcome_detail, "
             "resolved_at, price_at_resolution, realised_move")

    def _row(self, r) -> dict:
        """A dict shaped exactly like the SQLite ledger's rows.

        `score()` reads these by key and must not care which store produced
        them, so dates come back as ISO strings and `spec` keeps its SQLite
        name — the alternative is a second scoring path that drifts from the
        first.
        """
        keys = [c.strip() for c in self._COLS.replace("spec_json", "spec").split(",")]
        d = dict(zip(keys, r))
        for k in ("made_on", "resolve_on", "resolved_at"):
            if isinstance(d.get(k), (date, datetime)):
                d[k] = d[k].isoformat()[:10]
        if isinstance(d.get("spec"), (dict, list)):
            d["spec"] = json.dumps(d["spec"], sort_keys=True)
        if isinstance(d.get("outcome_detail"), (dict, list)):
            d["outcome_detail"] = json.dumps(d["outcome_detail"], default=str)
        return d

    def _to_pred(self, d: dict) -> Prediction:
        p = Prediction(
            ticker=d["ticker"], driver=d["driver"],
            priced_in_pct=d["priced_in_pct"], p_resolves=d["p_resolves"],
            move_if_true=d["move_if_true"], move_if_false=d["move_if_false"],
            resolver=d["resolver"], spec=json.loads(d["spec"]),
            resolve_on=d["resolve_on"], made_on=d["made_on"],
            price_at_prediction=d["price_at_prediction"],
            rationale=d["rationale"] or "")
        p.lock = d["lock"]
        return p

    def _select(self, where: str = "", params: tuple = ()) -> list[dict]:
        c = self._conn()
        with c.cursor() as cur:
            cur.execute(f"SELECT {self._COLS} FROM {self.schema}."
                        f"research_predictions {where}", params)
            return [self._row(r) for r in cur.fetchall()]

    # ------------------------------------------------------------------
    def register(self, p: Prediction, priced_in_id: int | None = None) -> str:
        err = p.validate()
        if err:
            raise ValueError(err)
        p.made_on = p.made_on or date.today().isoformat()
        p.seal()
        c = self._conn()
        with c.cursor() as cur:
            cur.execute(f"""
                INSERT INTO {self.schema}.research_predictions
                  (lock, ticker, driver, priced_in_pct, p_resolves, move_if_true,
                   move_if_false, resolver, spec_json, made_on, resolve_on,
                   price_at_prediction, rationale, priced_in_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s)
                ON CONFLICT (lock) DO NOTHING
            """, (p.lock, p.ticker, p.driver, p.priced_in_pct, p.p_resolves,
                  p.move_if_true, p.move_if_false, p.resolver,
                  json.dumps(p.spec, sort_keys=True), p.made_on, p.resolve_on,
                  p.price_at_prediction, p.rationale, priced_in_id))
            fresh = cur.rowcount
        c.commit()
        if fresh:
            self.log("registered", {"ticker": p.ticker}, lock=p.lock)
        return p.lock

    def log(self, kind: str, payload: dict | None = None,
            lock: str | None = None) -> None:
        c = self._conn()
        with c.cursor() as cur:
            cur.execute(f"INSERT INTO {self.schema}.research_prediction_events "
                        f"(kind, lock, payload) VALUES (%s,%s,%s::jsonb)",
                        (kind, lock, json.dumps(payload or {}, default=str)))
        c.commit()

    def due(self, on: date | None = None) -> list[Prediction]:
        rows = self._select("WHERE outcome IS NULL AND resolve_on <= %s",
                            (on or date.today(),))
        return [self._to_pred(d) for d in rows]

    def tampered(self) -> list[str]:
        """Locks whose stored content no longer hashes to the lock.

        Recomputed from what the DATABASE holds, not from anything cached — the
        point of the check is that it is independent of the writer. If this ever
        returns anything the ledger is void, not merely suspect.
        """
        return [d["lock"] for d in self._select()
                if not self._to_pred(d).verify()]

    def record_outcome(self, lock: str, outcome: str, detail: dict,
                       price_now: float | None) -> None:
        rows = self._select("WHERE lock = %s", (lock,))
        if not rows:
            raise KeyError(lock)
        row = rows[0]
        if row["outcome"] is not None:
            # The server trigger would refuse this anyway. Checking first turns
            # a raised exception into a logged no-op, which is what a nightly
            # resolver sweeping every due row actually wants.
            log.info("prediction %s already resolved as %s; leaving it",
                     lock, row["outcome"])
            return
        moved = None
        if price_now and row["price_at_prediction"]:
            moved = price_now / row["price_at_prediction"] - 1.0
        c = self._conn()
        with c.cursor() as cur:
            cur.execute(f"""
                UPDATE {self.schema}.research_predictions
                SET outcome=%s, outcome_detail=%s::jsonb, resolved_at=%s,
                    price_at_resolution=%s, realised_move=%s
                WHERE lock=%s AND outcome IS NULL
            """, (outcome, json.dumps(detail, default=str), date.today(),
                  price_now, moved, lock))
        c.commit()
        self.log("resolved", {"outcome": outcome}, lock=lock)

    def resolved(self) -> list[dict]:
        return self._select("WHERE outcome IN ('TRUE','FALSE')")

    def summary(self) -> dict:
        c = self._conn()
        with c.cursor() as cur:
            cur.execute(f"""
                SELECT count(*),
                       count(*) FILTER (WHERE outcome IN ('TRUE','FALSE')),
                       count(*) FILTER (WHERE outcome = 'UNRESOLVED'),
                       count(DISTINCT ticker) FILTER (WHERE outcome IN ('TRUE','FALSE')),
                       count(*) FILTER (WHERE outcome IS NULL
                                          AND resolve_on < CURRENT_DATE)
                FROM {self.schema}.research_predictions
            """)
            n, res, unres, tickers, overdue = cur.fetchone()
        return {"registered": int(n), "resolved": int(res),
                "unresolved": int(unres),
                "pending": int(n) - int(res) - int(unres),
                "overdue": int(overdue),
                "tampered": self.tampered(),
                "tickers": int(tickers), "store": "supabase"}

    # ------------------------------------------------------------------
    def migrate_from_sqlite(self, path: Path, dry_run: bool = False) -> dict:
        """One-way import of the old local ledger. Idempotent by construction.

        The lock is a hash over the prediction's content, so a row that was
        already mirrored collides on the primary key and is skipped. What this
        can surface — and the reason it reports rather than just inserting — is
        a row whose LOCAL content fails its own lock. That row is not imported:
        a void row does not become sound by changing stores.
        """
        import sqlite3

        path = Path(path)
        if not path.exists():
            return {"error": f"no ledger at {path}"}
        db = sqlite3.connect(path)
        db.row_factory = sqlite3.Row
        local = [dict(r) for r in db.execute("SELECT * FROM predictions")]

        out = {"local_rows": len(local), "inserted": 0, "already_present": 0,
               "void_skipped": [], "resolutions": 0, "dry_run": dry_run}
        remote = {d["lock"] for d in self._select()}
        for r in local:
            p = self._to_pred({**r, "spec": r["spec"]})
            if not p.verify():
                out["void_skipped"].append(r["lock"])
                continue
            if r["lock"] in remote:
                out["already_present"] += 1
            elif not dry_run:
                self.register(p)
                out["inserted"] += 1
            else:
                out["inserted"] += 1
            if r["outcome"] and not dry_run:
                self.record_outcome(r["lock"], r["outcome"],
                                    json.loads(r["outcome_detail"] or "{}"),
                                    r["price_at_resolution"])
                out["resolutions"] += 1
        if not dry_run:
            self.log("migrated_from_sqlite", out)
        return out


def resolve_due(led, on: date | None = None, price_lookup=None) -> list[dict]:
    """Run every due resolver once. The nightly job.

    Split out of the CLI so the scheduled path and the interactive one are the
    same code. A prediction whose lock does not verify is reported and NOT
    resolved — resolving a row that was edited would launder the edit.
    """
    from .implied import fetch_financials

    price_lookup = price_lookup or (lambda t: getattr(fetch_financials(t),
                                                      "price", None))
    out = []
    for p in led.due(on):
        if not p.verify():
            out.append({"lock": p.lock, "ticker": p.ticker, "status": "VOID",
                        "detail": "content does not hash to its lock"})
            led.log("void_at_resolution", {"ticker": p.ticker}, lock=p.lock)
            continue
        try:
            outcome, detail = RESOLVERS[p.resolver](p.ticker, p.spec,
                                                    on or date.today())
        except Exception as exc:                              # noqa: BLE001
            # A resolver that throws is not a FALSE. Leaving the row unresolved
            # keeps it due, which is the honest state — the observation was not
            # made, and scoring it as a miss would flatter or punish nothing.
            out.append({"lock": p.lock, "ticker": p.ticker, "status": "ERROR",
                        "detail": str(exc)[:200]})
            led.log("resolver_error", {"ticker": p.ticker,
                                       "error": str(exc)[:200]}, lock=p.lock)
            continue
        price = None
        try:
            price = price_lookup(p.ticker)
        except Exception as exc:                              # noqa: BLE001
            log.info("no price for %s at resolution: %s", p.ticker, exc)
        led.record_outcome(p.lock, outcome, detail, price)
        out.append({"lock": p.lock, "ticker": p.ticker, "driver": p.driver,
                    "status": outcome, "detail": detail})
    return out


__all__ = ["SupabaseLedger", "resolve_due", "TRUE"]
