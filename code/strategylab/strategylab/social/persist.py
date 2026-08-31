"""Push the priced-in programme's record to Supabase.

Reuses `autonomous.publish.Publisher` for the connection rather than opening a
second path to the same database — the research_* family already has a writer
and a convention, and this is an extension of that family, not a new one.

Two things are persisted, and they are different kinds of object:

* **Decompositions** (`research_priced_in`) — an analysis OUTPUT. Re-runnable,
  supersedable, keyed on (ticker, as_of, pipeline_version) so a second run at a
  different pipeline version sits beside the first instead of overwriting it.
  Read `drivers_json` with the caveat attached: `priced_in_pct` is the JUDGED
  tier and is unvalidated.

* **Predictions** (`research_predictions`) — a SEALED record. The `lock` is a
  hash over the prediction's own content and is the primary key, so the database
  can refuse an edit rather than trusting this code to behave. Two things follow
  that are worth stating because they are easy to design away by accident:

  1. The local ledger stays the source of truth for registration. Supabase is a
     durable mirror, and `verify_locks()` recomputes every hash from the remote
     content on the way back — a row that fails is not a warning, it means the
     ledger is void.
  2. Outcomes are pushed as an UPDATE and the server trigger allows exactly one.
     A second resolution is refused by the database, which is where that rule
     belongs: re-running a resolver until it agrees is precisely the failure
     Tier 3 exists to prevent, and a client-side check is not a guarantee.

Nothing is published (`published = false`) by default. Same rule as the rest of
the family: nothing is visible until someone decides it is — and the honest
state of this programme is two failed tiers and one open one, which is not a
result to put on a public page.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

from ..autonomous.publish import ResearchPublisher

log = logging.getLogger(__name__)

# /2 = structured summary, {price} token
# /3 = cases are per-DRIVER investigations (coverage read + wired measurement),
#      not per-analyst reconstructions. The shape of `cases_json` changed, so the
#      version has to move: (ticker, as_of, pipeline_version) is unique, which
#      lets a /3 row sit beside the /2 one it supersedes instead of overwriting
#      a row the UI still knows how to render.
PIPELINE_VERSION = "priced-in/3"


class PricedInPublisher(ResearchPublisher):
    """The research_* publisher, extended with this programme's two tables."""

    def ready(self) -> tuple[bool, str]:
        try:
            c = self._connect()
            with c.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema=%s AND table_name IN "
                    "('research_priced_in','research_predictions')", (self.schema,))
                n = cur.fetchone()[0]
            if n < 2:
                return False, (f"only {n}/2 tables exist in '{self.schema}' — apply "
                               "20260825120000_research_priced_in.sql first")
            return True, ""
        except Exception as exc:                              # noqa: BLE001
            return False, str(exc)[:200]

    # ------------------------------------------------------------------
    def publish_decomposition(self, payload: dict, ticker: str,
                              as_of: date | None = None,
                              note_slug: str = "priced-in-findings",
                              model: str = "") -> int | None:
        """One decomposition. Returns its id, for predictions to reference."""
        dec = payload.get("decomposition") or {}
        vote = payload.get("vote") or {}
        imp = payload.get("implied") or {}
        fin = imp.get("financials") or {}
        if not dec:
            log.info("%s: nothing to publish (no decomposition)", ticker)
            return None
        as_of = as_of or date.fromisoformat(payload.get("as_of") or
                                            date.today().isoformat())
        positions = vote.get("positions") or []

        def _n(stance: str) -> int:
            return sum(1 for p in positions if p.get("stance") == stance)

        c = self._connect()
        with c.cursor() as cur:
            cur.execute(f"""
                INSERT INTO {self.schema}.research_priced_in
                  (ticker, as_of, price, implied_revenue_cagr, discount_rate,
                   terminal_growth, fcf_margin, n_targets, target_low,
                   target_high, target_median, median_gap, n_rejected_bull,
                   n_rejected_bear, n_endorsed, drivers_json, cases_json,
                   summary, summary_json, pipeline_version, model,
                   generation_is_pit, note_slug)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                        %s::jsonb,%s::jsonb,%s,%s::jsonb,%s,%s,%s,%s)
                ON CONFLICT (ticker, as_of, pipeline_version) DO UPDATE SET
                  price = EXCLUDED.price,
                  drivers_json = EXCLUDED.drivers_json,
                  cases_json = EXCLUDED.cases_json,
                  summary = EXCLUDED.summary,
                  summary_json = EXCLUDED.summary_json
                RETURNING id
            """, (ticker, as_of, vote.get("price") or fin.get("price"),
                  imp.get("implied_revenue_cagr"), imp.get("discount_rate"),
                  imp.get("terminal_growth"), fin.get("fcf_margin"),
                  vote.get("n_targets"), vote.get("low"), vote.get("high"),
                  vote.get("median"), vote.get("median_gap"),
                  _n("rejected_bull"), _n("rejected_bear"), _n("endorsed"),
                  json.dumps(dec.get("drivers") or []),
                  json.dumps(payload.get("cases") or []),
                  dec.get("summary", ""),
                  json.dumps({k: dec.get(k) for k in
                              ("position", "pays_for", "declines", "crux")
                              if dec.get(k)}) if any(
                      dec.get(k) for k in
                      ("position", "pays_for", "declines", "crux")) else None,
                  PIPELINE_VERSION, model,
                  # A past as_of makes the DATA point-in-time; it never makes the
                  # MODEL point-in-time. False unless the leakage probe cleared it.
                  False, note_slug))
            new_id = cur.fetchone()[0]
        c.commit()
        return int(new_id)

    def publish_predictions(self, ledger, priced_in_ids: dict | None = None) -> dict:
        """Mirror the sealed ledger. Refuses to push a tampered row."""
        tampered = ledger.tampered()
        if tampered:
            return {"error": "LOCAL LEDGER VOID — locks do not match content",
                    "tampered": tampered}
        rows = [dict(r) for r in ledger.db.execute("SELECT * FROM predictions")]
        ids = priced_in_ids or {}
        c = self._connect()
        pushed = resolved = 0
        with c.cursor() as cur:
            for r in rows:
                cur.execute(f"""
                    INSERT INTO {self.schema}.research_predictions
                      (lock, ticker, driver, priced_in_pct, p_resolves,
                       move_if_true, move_if_false, resolver, spec_json,
                       made_on, resolve_on, price_at_prediction, rationale,
                       priced_in_id)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s)
                    ON CONFLICT (lock) DO NOTHING
                """, (r["lock"], r["ticker"], r["driver"], r["priced_in_pct"],
                      r["p_resolves"], r["move_if_true"], r["move_if_false"],
                      r["resolver"], r["spec"], r["made_on"], r["resolve_on"],
                      r["price_at_prediction"], r["rationale"],
                      ids.get(r["ticker"])))
                pushed += cur.rowcount
                if r["outcome"]:
                    # The server trigger allows this exactly once. A second
                    # attempt raises, which is the correct place for that rule.
                    try:
                        cur.execute(f"""
                            UPDATE {self.schema}.research_predictions
                            SET outcome=%s, outcome_detail=%s::jsonb,
                                resolved_at=%s, price_at_resolution=%s,
                                realised_move=%s
                            WHERE lock=%s AND outcome IS NULL
                        """, (r["outcome"], r["outcome_detail"] or "{}",
                              r["resolved_at"], r["price_at_resolution"],
                              r["realised_move"], r["lock"]))
                        resolved += cur.rowcount
                    except Exception as exc:                  # noqa: BLE001
                        c.rollback()
                        log.warning("resolution refused for %s: %s",
                                    r["lock"], str(exc).splitlines()[0][:120])
        c.commit()
        return {"rows": len(rows), "inserted": pushed, "resolutions": resolved}

    def verify_locks(self) -> dict:
        """Recompute every hash from the REMOTE content.

        The point of a mirror is that it can be checked independently. A row
        that fails here was edited in the database, and the trigger should have
        made that impossible — so a failure means either the trigger was
        bypassed or the content was rewritten by a path that does not exist yet.
        Either way the ledger is void, not suspect.
        """
        from .predict import Prediction
        c = self._connect()
        bad = []
        with c.cursor() as cur:
            cur.execute(f"""
                SELECT lock, ticker, driver, priced_in_pct, p_resolves,
                       move_if_true, move_if_false, resolver, spec_json::text,
                       made_on, resolve_on, price_at_prediction
                FROM {self.schema}.research_predictions
            """)
            for row in cur.fetchall():
                p = Prediction(
                    ticker=row[1], driver=row[2], priced_in_pct=row[3],
                    p_resolves=row[4], move_if_true=row[5], move_if_false=row[6],
                    resolver=row[7], spec=json.loads(row[8]),
                    resolve_on=row[10].isoformat(), made_on=row[9].isoformat(),
                    price_at_prediction=row[11])
                p.lock = row[0]
                if not p.verify():
                    bad.append(row[0])
        return {"checked": True, "tampered": bad,
                "verdict": "clean" if not bad else "LEDGER VOID"}
