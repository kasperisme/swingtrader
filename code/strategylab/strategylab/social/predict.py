"""Tier 3 — forward predictions, locked at creation and resolved by arithmetic.

Tiers 1 and 2 both failed, and the second failed in the more instructive way: it
produced three believable numbers in a row, every one an artefact of a bug in
the measurement. The common thread is that both were **retrospective** — the
measurement was designed after the data existed, so every degree of freedom in
it (event window, selection rule, article matching) could be turned until
something appeared.

Forward prediction removes that. The claim is fixed before the outcome exists,
so there is nothing left to tune. What has to be engineered instead is the
honesty of the record, and that comes down to three properties:

* **Locked.** Every prediction is hashed at creation over its full content. A
  prediction whose hash no longer matches its content did not survive contact
  with the outcome, and `verify()` will say so. Nothing else in this module
  matters if this one fails.

* **Mechanically resolvable, or not registrable at all.** A prediction must name
  a resolver that already exists in `RESOLVERS` and whose inputs are wired. This
  is the load-bearing rule and it is deliberately restrictive: if resolution
  needs a judgement call made after the fact, the judge knows the outcome, and
  the whole exercise collapses into the Tier-2 failure with extra steps. The
  observables the cases actually want — weekly markdown depth, store-level foot
  traffic — are NOT wired, so predictions about them cannot be registered here.
  That is the correct behaviour: a test we cannot run must not be recorded as
  one we might.

* **Scored against a base rate, never in absolute.** A Brier score of 0.18 means
  nothing on its own. If companies beat consensus 75% of the time and the model
  says "beat" at 80%, it has added no information. Every score here is reported
  next to the base rate and the always-predict-the-base-rate benchmark.

## What is being tested

`priced_in_pct` claims that an unpriced driver, if it resolves in the case's
favour, should move the price MORE than a priced one. So each prediction carries
both a probability and a conditional magnitude, and they are scored separately:

    p_resolves          -> Brier, vs the base rate. Tests the investigation.
    move_if_resolves    -> correlation with the realised move. Tests priced_in_pct.

The second is the one this whole construction exists to validate.

## Power, stated before any data is collected

Brier calibration needs roughly 100 resolved predictions to distinguish a real
edge from noise, and the useful comparison — unpriced drivers versus priced ones
— needs both cells populated, so call it 100 with at least 30 in each half. At
one earnings cycle per ticker per quarter and a handful of resolvable drivers
each, that is **20-30 tickers followed for two to three quarters.** Six months
minimum before this says anything. Writing the number down now is the point: a
harness that reports a "result" at n=20 will be believed, and it should not be.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

# Verdicts a resolver may return. UNRESOLVED is not a failure of the prediction,
# it is a failure to observe, and it must never be scored as a miss.
TRUE, FALSE, UNRESOLVED = "TRUE", "FALSE", "UNRESOLVED"


# ----------------------------------------------------------------------
# Resolvers: the only things a prediction may be about.
# ----------------------------------------------------------------------
def resolve_earnings_beat(ticker: str, spec: dict, asof: date) -> tuple[str, dict]:
    """Did the next report beat consensus EPS? Mechanical, from the cache."""
    from .tools import earnings_surprise_history
    h = earnings_surprise_history(ticker, limit=8)
    if "error" in h:
        return UNRESOLVED, {"reason": h["error"]}
    after = [q for q in h["quarters"] if q["date"] > spec["after"]]
    if not after:
        return UNRESOLVED, {"reason": f"no report after {spec['after']}"}
    q = sorted(after, key=lambda r: r["date"])[0]
    got = q["surprise"] > 0
    return (TRUE if got == bool(spec.get("expect_beat", True)) else FALSE,
            {"quarter": q["date"], "surprise": q["surprise"],
             "surprise_pct": q["surprise_pct"]})


def resolve_segment_growth(ticker: str, spec: dict, asof: date) -> tuple[str, dict]:
    """Did a named revenue segment grow faster than a threshold?"""
    from .tools import segment_revenue_history
    h = segment_revenue_history(ticker, years=3)
    years = h.get("product") or []
    if not years:
        return UNRESOLVED, {"reason": "no segment history"}
    latest = years[0]
    name = spec["segment"]
    match = next((k for k in latest if name.lower() in k.lower()), None)
    if match is None:
        return UNRESOLVED, {"reason": f"segment {name!r} not reported"}
    yoy = latest[match].get("yoy")
    if yoy is None:
        return UNRESOLVED, {"reason": "no YoY for that segment"}
    return (TRUE if yoy >= spec["min_yoy"] else FALSE,
            {"segment": match, "yoy": yoy, "threshold": spec["min_yoy"]})


def resolve_attention_growth(ticker: str, spec: dict, asof: date) -> tuple[str, dict]:
    """Did consumer attention to a named brand grow against its own baseline?"""
    from .tools import attention_series
    a = attention_series(ticker, spec["entity"])
    if "error" in a:
        return UNRESOLVED, {"reason": a["error"]}
    g = a.get("log_growth_vs_own_baseline")
    if g is None:
        return UNRESOLVED, {"reason": "growth undefined (baseline too thin)"}
    return (TRUE if g >= spec["min_log_growth"] else FALSE,
            {"article": a["article"], "log_growth": g,
             "threshold": spec["min_log_growth"]})


RESOLVERS = {
    "earnings_beat": resolve_earnings_beat,
    "segment_growth": resolve_segment_growth,
    "attention_growth": resolve_attention_growth,
}

# Required keys per resolver, checked at registration so a malformed spec fails
# when it is written rather than months later when it is due.
RESOLVER_SPEC = {
    "earnings_beat": ("after", "expect_beat"),
    "segment_growth": ("segment", "min_yoy"),
    "attention_growth": ("entity", "min_log_growth"),
}


# ----------------------------------------------------------------------
@dataclass
class Prediction:
    ticker: str
    driver: str
    priced_in_pct: float
    p_resolves: float             # probability the resolver returns TRUE
    move_if_true: float           # expected % price move if it does
    move_if_false: float
    resolver: str
    spec: dict
    resolve_on: str               # ISO date the resolver may first be run
    made_on: str = ""
    price_at_prediction: float | None = None
    rationale: str = ""
    lock: str = ""

    def payload(self) -> str:
        """Exactly the fields the lock covers. Order is fixed."""
        return json.dumps({
            "ticker": self.ticker, "driver": self.driver,
            "priced_in_pct": round(self.priced_in_pct, 4),
            "p_resolves": round(self.p_resolves, 4),
            "move_if_true": round(self.move_if_true, 6),
            "move_if_false": round(self.move_if_false, 6),
            "resolver": self.resolver, "spec": self.spec,
            "resolve_on": self.resolve_on, "made_on": self.made_on,
            "price_at_prediction": self.price_at_prediction,
        }, sort_keys=True)

    def seal(self) -> "Prediction":
        self.lock = hashlib.sha256(self.payload().encode()).hexdigest()[:32]
        return self

    def verify(self) -> bool:
        return bool(self.lock) and self.lock == hashlib.sha256(
            self.payload().encode()).hexdigest()[:32]

    def validate(self) -> str:
        if self.resolver not in RESOLVERS:
            return (f"unknown resolver {self.resolver!r}; a prediction that cannot "
                    f"be resolved mechanically must not be registered. "
                    f"Available: {sorted(RESOLVERS)}")
        missing = [k for k in RESOLVER_SPEC[self.resolver] if k not in self.spec]
        if missing:
            return f"resolver {self.resolver!r} needs spec keys {missing}"
        if not 0.0 <= self.p_resolves <= 1.0:
            return "p_resolves must be a probability"
        if self.resolve_on <= (self.made_on or date.today().isoformat()):
            return "resolve_on must be in the future at registration"
        return ""

    def to_dict(self) -> dict:
        return asdict(self)


SCHEMA = """
CREATE TABLE IF NOT EXISTS predictions (
    lock TEXT PRIMARY KEY,
    ticker TEXT NOT NULL, driver TEXT NOT NULL,
    priced_in_pct REAL, p_resolves REAL,
    move_if_true REAL, move_if_false REAL,
    resolver TEXT NOT NULL, spec TEXT NOT NULL,
    made_on TEXT NOT NULL, resolve_on TEXT NOT NULL,
    price_at_prediction REAL, rationale TEXT,
    outcome TEXT, outcome_detail TEXT, resolved_at TEXT,
    price_at_resolution REAL, realised_move REAL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT
);
"""


class PredictionLedger:
    """Append-only, and the append-only part is the whole design."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()

    def register(self, p: Prediction) -> str:
        err = p.validate()
        if err:
            raise ValueError(err)
        p.made_on = p.made_on or date.today().isoformat()
        p.seal()
        try:
            self.db.execute(
                "INSERT INTO predictions (lock, ticker, driver, priced_in_pct, "
                "p_resolves, move_if_true, move_if_false, resolver, spec, made_on, "
                "resolve_on, price_at_prediction, rationale) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (p.lock, p.ticker, p.driver, p.priced_in_pct, p.p_resolves,
                 p.move_if_true, p.move_if_false, p.resolver,
                 json.dumps(p.spec, sort_keys=True), p.made_on, p.resolve_on,
                 p.price_at_prediction, p.rationale))
            self.db.commit()
        except sqlite3.IntegrityError:
            return p.lock                    # identical prediction already sealed
        self.log("registered", {"lock": p.lock, "ticker": p.ticker})
        return p.lock

    def log(self, kind: str, payload: dict | None = None) -> None:
        self.db.execute("INSERT INTO events (at, kind, payload) VALUES (?,?,?)",
                        (datetime.now().isoformat(timespec="seconds"), kind,
                         json.dumps(payload or {}, default=str)))
        self.db.commit()

    def _row_to_pred(self, r) -> Prediction:
        p = Prediction(ticker=r["ticker"], driver=r["driver"],
                       priced_in_pct=r["priced_in_pct"], p_resolves=r["p_resolves"],
                       move_if_true=r["move_if_true"], move_if_false=r["move_if_false"],
                       resolver=r["resolver"], spec=json.loads(r["spec"]),
                       resolve_on=r["resolve_on"], made_on=r["made_on"],
                       price_at_prediction=r["price_at_prediction"],
                       rationale=r["rationale"] or "")
        p.lock = r["lock"]
        return p

    def due(self, on: date | None = None) -> list[Prediction]:
        on = (on or date.today()).isoformat()
        return [self._row_to_pred(r) for r in self.db.execute(
            "SELECT * FROM predictions WHERE outcome IS NULL AND resolve_on <= ?",
            (on,))]

    def tampered(self) -> list[str]:
        """Locks whose stored content no longer hashes to the lock.

        If this ever returns anything the ledger is void, not merely suspect.
        """
        out = []
        for r in self.db.execute("SELECT * FROM predictions"):
            if not self._row_to_pred(r).verify():
                out.append(r["lock"])
        return out

    def record_outcome(self, lock: str, outcome: str, detail: dict,
                       price_now: float | None) -> None:
        row = self.db.execute("SELECT * FROM predictions WHERE lock=?",
                              (lock,)).fetchone()
        if row is None:
            raise KeyError(lock)
        if row["outcome"] is not None:
            # An already-resolved prediction is never re-resolved. Re-running a
            # resolver until it agrees is the retrospective failure mode this
            # tier exists to eliminate.
            log.info("prediction %s already resolved as %s; leaving it",
                     lock, row["outcome"])
            return
        moved = None
        if price_now and row["price_at_prediction"]:
            moved = price_now / row["price_at_prediction"] - 1.0
        self.db.execute(
            "UPDATE predictions SET outcome=?, outcome_detail=?, resolved_at=?, "
            "price_at_resolution=?, realised_move=? WHERE lock=?",
            (outcome, json.dumps(detail, default=str),
             date.today().isoformat(), price_now, moved, lock))
        self.db.commit()
        self.log("resolved", {"lock": lock, "outcome": outcome})

    def resolved(self) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM predictions WHERE outcome IN ('TRUE','FALSE')")]

    def summary(self) -> dict:
        n = self.db.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
        res = self.resolved()
        unres = self.db.execute(
            "SELECT COUNT(*) FROM predictions WHERE outcome='UNRESOLVED'").fetchone()[0]
        return {"registered": int(n), "resolved": len(res), "unresolved": int(unres),
                "pending": int(n) - len(res) - int(unres),
                "tampered": self.tampered(),
                "tickers": len({r["ticker"] for r in res})}


# ----------------------------------------------------------------------
MIN_FOR_CALIBRATION = 100          # stated before any data was collected
MIN_PER_CELL = 30


def score(ledger: PredictionLedger) -> dict:
    """Brier against the base rate, and the priced_in_pct test.

    Reports how far short of power it is rather than pretending otherwise —
    every earlier tier in this programme produced a believable number before it
    had the observations to support one.
    """
    rows = ledger.resolved()
    n = len(rows)
    out = {"n_resolved": n, "min_for_calibration": MIN_FOR_CALIBRATION,
           "powered": n >= MIN_FOR_CALIBRATION}
    if n < 8:
        out["note"] = f"{n} resolved; nothing is computed below 8."
        return out

    y = np.array([1.0 if r["outcome"] == TRUE else 0.0 for r in rows])
    p = np.array([r["p_resolves"] for r in rows], dtype=float)
    base = float(y.mean())
    out["base_rate"] = base
    out["brier"] = float(np.mean((p - y) ** 2))
    out["brier_base_rate_benchmark"] = float(np.mean((base - y) ** 2))
    out["beats_base_rate"] = bool(out["brier"] < out["brier_base_rate_benchmark"])

    # The priced_in_pct test: among predictions that RESOLVED TRUE, does the
    # realised move track the move we said an unpriced driver would produce?
    t = [r for r in rows if r["outcome"] == TRUE
         and r["realised_move"] is not None]
    if len(t) >= 8:
        pred = np.array([r["move_if_true"] for r in t], dtype=float)
        real = np.array([r["realised_move"] for r in t], dtype=float)
        if pred.std() > 1e-9 and real.std() > 1e-9:
            out["move_corr"] = float(np.corrcoef(pred, real)[0, 1])
            out["n_move_scored"] = len(t)
        lo = [r["realised_move"] for r in t if r["priced_in_pct"] <= 30]
        hi = [r["realised_move"] for r in t if r["priced_in_pct"] >= 70]
        out["unpriced_cell_n"], out["priced_cell_n"] = len(lo), len(hi)
        if len(lo) >= MIN_PER_CELL and len(hi) >= MIN_PER_CELL:
            out["unpriced_mean_move"] = float(np.mean(np.abs(lo)))
            out["priced_mean_move"] = float(np.mean(np.abs(hi)))
        else:
            out["cells_note"] = (f"need {MIN_PER_CELL} per cell; have "
                                 f"{len(lo)} unpriced / {len(hi)} priced")
    out["verdict"] = ("POWERED" if out["powered"] else
                      f"UNDERPOWERED — {MIN_FOR_CALIBRATION - n} more resolutions "
                      f"needed before this means anything")
    return out


# ----------------------------------------------------------------------
# Turning a decomposition into predictions.
# ----------------------------------------------------------------------
PREDICT_SYSTEM = """You convert drivers of a stock's priced-in baseline into
FORWARD PREDICTIONS that a machine can resolve without you.

For each driver you may either produce a prediction or decline it. Declining is
the right answer whenever the driver cannot be settled by one of the resolvers
listed — most cannot, and a prediction dressed up to fit a resolver it does not
match is worse than none, because it will resolve cleanly and mean nothing.

For each prediction give:
 - resolver + spec, from the list. The spec must be exactly what that resolver
   needs, with thresholds you actually intend, not round numbers chosen to be
   safe.
 - p_resolves: your probability the resolver returns TRUE. Be calibrated, not
   bold: if you think it is a coin flip, say 0.5. You are scored against the
   base rate, so a confident answer that matches the base rate earns nothing.
 - move_if_true / move_if_false: the percentage price move you expect over the
   window if it resolves each way, as decimals (0.08 = +8%). THIS IS THE TEST OF
   THE PRICED-IN FIGURE: a driver the price does not reflect should move it
   substantially when it resolves; one the price already contains should barely
   move it. Make those two cases differ accordingly, and let the priced_in_pct
   you were given drive the difference.
 - rationale: one sentence, the mechanism.

You are not being asked to be right. You are being asked to be calibrated and
specific enough to be scored."""


def prediction_schema(resolvers: list[str]) -> dict:
    return {
        "type": "object", "additionalProperties": False,
        "required": ["predictions"],
        "properties": {"predictions": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["driver_index", "driver", "resolver", "spec_json",
                         "p_resolves", "move_if_true", "move_if_false", "rationale"],
            "properties": {
                "driver_index": {"type": "integer",
                                 "description": "the [n] index of the driver this "
                                                "prediction is about"},
                "driver": {"type": "string"},
                "resolver": {"type": "string", "enum": resolvers},
                "spec_json": {"type": "string",
                              "description": "JSON object of the resolver's spec"},
                "p_resolves": {"type": "number"},
                "move_if_true": {"type": "number"},
                "move_if_false": {"type": "number"},
                "rationale": {"type": "string"}}}}}}


def predictions_from_decomposition(ticker: str, drivers: list[dict],
                                   price: float, resolve_on: date,
                                   business_brief: str = "",
                                   model: str | None = None,
                                   effort: str = "medium") -> list[Prediction]:
    """Ask for predictions, then refuse anything that will not resolve."""
    from .llm import available as _llm_available, complete_json

    ok, why = _llm_available()
    if not ok:
        log.warning("prediction generation skipped for %s: %s", ticker, why)
        return []

    spec_help = "\n".join(
        f"  {name}: spec keys {list(keys)}" for name, keys in RESOLVER_SPEC.items())
    # Indexed, because the driver is looked up by index on the way back. Keying
    # on the driver TEXT failed silently: the model paraphrases the driver when
    # it restates it, the lookup missed, and every prediction was registered
    # with priced_in_pct = 0 — the exact quantity the tier exists to test.
    body = "\n".join(
        f"  [{i}] ({d.get('priced_in_pct', 0):.0f}% priced in) {d.get('driver','')}"
        f"  | basis: {d.get('basis','')[:200]}" for i, d in enumerate(drivers))
    user = (f"{business_brief}\n\nTicker {ticker}, current price ${price:,.2f}.\n"
            f"Resolution date: {resolve_on.isoformat()}.\n\n"
            f"RESOLVERS AVAILABLE (nothing else can be used):\n{spec_help}\n\n"
            f"DRIVERS OF THE PRICED-IN BASELINE (cite the [index]):\n{body}")
    res = complete_json(PREDICT_SYSTEM, user,
                        prediction_schema(sorted(RESOLVERS)),
                        max_tokens=8000, effort=effort, model=model)
    if not res.ok:
        log.warning("prediction generation failed for %s: %s", ticker, res.error)
        return []
    payload = res.data

    out = []
    for row in payload.get("predictions", []):
        try:
            spec = json.loads(row.get("spec_json") or "{}")
        except json.JSONDecodeError:
            log.info("%s: unparseable spec, dropped", ticker)
            continue
        idx = row.get("driver_index")
        if not isinstance(idx, int) or not 0 <= idx < len(drivers):
            log.info("%s: prediction cites driver index %r, out of range; dropped",
                     ticker, idx)
            continue
        src = drivers[idx]
        p = Prediction(
            ticker=ticker, driver=row.get("driver", ""),
            priced_in_pct=float(src.get("priced_in_pct") or 0),
            p_resolves=float(row.get("p_resolves") or 0.5),
            move_if_true=float(row.get("move_if_true") or 0),
            move_if_false=float(row.get("move_if_false") or 0),
            resolver=row.get("resolver", ""), spec=spec,
            resolve_on=resolve_on.isoformat(), made_on=date.today().isoformat(),
            price_at_prediction=price, rationale=row.get("rationale", ""))
        err = p.validate()
        if err:
            log.info("%s: dropped a prediction — %s", ticker, err)
            continue
        out.append(p)
    return out
