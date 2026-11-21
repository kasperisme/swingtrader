"""Daily point-in-time snapshots the drawdown recon cannot recover later.

* Analyst consensus estimates (FMP ``/stable/analyst-estimates``, annual) for the
  liquid universe. FMP serves only the CURRENT consensus, so the revision path
  exists only if it is captured every day.
* Macro series (FRED + FMP): HY OAS, 10y real yield, 2y/10y, NFCI, broad dollar,
  VIX, USDJPY. Stored with the date this run first saw each observation.

Every run writes JSONL to ``output/drawdown/snapshots/<date>/`` FIRST, then
upserts into Supabase (migration 20261121120000). If the tables are not there
yet the JSONL is the record, and ``load`` backfills it once they are.
"""

from __future__ import annotations

import csv
import io
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any, Iterable

import requests

from shared.logging import logger

FMP_BASE = "https://financialmodelingprep.com/stable"
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"

OUT_ROOT = Path(__file__).resolve().parents[2] / "output" / "drawdown" / "snapshots"

#: FRED series: id -> what it is for in the regime label (SPEC §5).
FRED_SERIES = {
    "BAMLH0A0HYM2": "ICE BofA US High Yield OAS: systemic / credit tell (FRED keeps ~3y only)",
    "BAA10Y": "Moody's Baa - 10y spread: the credit series the historical study uses (1986+)",
    "DFII10": "10y TIPS real yield: rates-driven growth de-rating",
    "DGS2": "2y Treasury: policy path",
    "DGS10": "10y Treasury",
    "NFCI": "Chicago Fed financial conditions (weekly)",
    "DTWEXBGS": "Broad trade-weighted dollar",
    "VIXCLS": "VIX close",
}
#: FMP EOD series (symbol -> purpose).
FMP_SERIES = {"USDJPY": "carry-unwind tell (Aug 2024 analogue)"}

#: Liquid-universe floor, read from the `tickers` table (SPEC §6.1).
MIN_PRICE = 3.0
MIN_DOLLAR_VOLUME = 5_000_000
#: Keep fiscal periods ending from this many days in the past onward
#: (the just-reported year plus the forward years that carry the revisions).
FISCAL_LOOKBACK_DAYS = 400
MAX_FORWARD_YEARS = 3
#: A run with more failed/empty symbols than this share is `partial` and exits non-zero.
MAX_FAILED_SHARE = 0.05
ET = ZoneInfo("America/New_York")


def market_date() -> date:
    """The US/Eastern calendar date. A UTC date would stamp a 20:00 ET run as tomorrow."""
    return datetime.now(ET).date()


class EmptyResponse(Exception):
    """FMP answered 200 with an error body or no estimates. Counted as a failure."""


def _fmp_key() -> str:
    key = os.environ.get("FMP_API_KEY") or os.environ.get("APIKEY")
    if not key:
        raise RuntimeError("FMP_API_KEY not set")
    return key


def _get(url: str, params: dict, tries: int = 4, timeout: float = 20.0) -> requests.Response:
    delay = 2.0
    for attempt in range(tries):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            if r.status_code == 429 or r.status_code >= 500:
                raise requests.HTTPError(f"{r.status_code}")
            return r
        except (requests.RequestException,) as exc:
            if attempt == tries - 1:
                raise
            logger.warning("retry %s (%s) in %.0fs", url.rsplit("/", 1)[-1], exc, delay)
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("unreachable")


# ── universe ──────────────────────────────────────────────────────────────────


def previously_tracked(before: date) -> set[str]:
    """Every symbol a prior run tracked. A name that falls through the liquidity floor
    keeps being snapshotted: dropping it would erase exactly the revision paths of
    the names that fell hardest (survivorship inside our own history)."""
    seen: set[str] = set()
    if not OUT_ROOT.exists():
        return seen
    for d in OUT_ROOT.iterdir():
        f = d / "universe.txt"
        if d.name < before.isoformat() and f.exists():
            seen.update(x for x in f.read_text().split() if x)
    return seen


def liquid_universe(sb) -> list[str]:
    """Actively traded NYSE/NASDAQ names over the price and dollar-volume floor."""
    rows: list[dict] = []
    page = 0
    while True:
        chunk = (
            sb.schema("swingtrader").table("tickers")
            .select("symbol,price,volume,is_actively_trading")
            .eq("is_actively_trading", True)
            .range(page * 1000, page * 1000 + 999)
            .execute()
            .data
        )
        rows.extend(chunk)
        if len(chunk) < 1000:
            break
        page += 1
    out = sorted(
        r["symbol"]
        for r in rows
        if (r.get("price") or 0) >= MIN_PRICE
        and (r.get("price") or 0) * (r.get("volume") or 0) >= MIN_DOLLAR_VOLUME
    )
    return out


# ── estimates ─────────────────────────────────────────────────────────────────


def parse_estimates(symbol: str, payload: Any, snapshot_date: date) -> list[dict]:
    """FMP annual estimates -> rows for the periods that carry revisions.

    FMP returns the farthest fiscal year first and includes long-past years.
    Keep the just-reported year and up to MAX_FORWARD_YEARS ahead.
    """
    if not isinstance(payload, list):
        return []
    rows = []
    for rec in payload:
        try:
            fiscal = date.fromisoformat(str(rec["date"])[:10])
        except (KeyError, ValueError):
            continue
        if (snapshot_date - fiscal).days > FISCAL_LOOKBACK_DAYS:
            continue
        rows.append(
            {
                "snapshot_date": snapshot_date.isoformat(),
                "symbol": symbol,
                "fiscal_date": fiscal.isoformat(),
                "eps_avg": rec.get("epsAvg"),
                "eps_high": rec.get("epsHigh"),
                "eps_low": rec.get("epsLow"),
                "revenue_avg": rec.get("revenueAvg"),
                "revenue_high": rec.get("revenueHigh"),
                "revenue_low": rec.get("revenueLow"),
                "ebitda_avg": rec.get("ebitdaAvg"),
                "net_income_avg": rec.get("netIncomeAvg"),
                "num_analysts_eps": rec.get("numAnalystsEps"),
                "num_analysts_revenue": rec.get("numAnalystsRevenue"),
            }
        )
    rows.sort(key=lambda r: r["fiscal_date"])
    # past year (at most one) + forward years
    past = [r for r in rows if r["fiscal_date"] <= snapshot_date.isoformat()][-1:]
    fwd = [r for r in rows if r["fiscal_date"] > snapshot_date.isoformat()][:MAX_FORWARD_YEARS]
    return past + fwd


def fetch_estimates(symbols: Iterable[str], snapshot_date: date, workers: int = 6) -> tuple[list[dict], list[str], list[str]]:
    key = _fmp_key()
    rows: list[dict] = []
    failed: list[str] = []
    empty: list[str] = []

    def one(sym: str) -> list[dict]:
        r = _get(f"{FMP_BASE}/analyst-estimates", {"symbol": sym, "period": "annual", "limit": 10, "apikey": key})
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}")
        body = r.json()
        if not isinstance(body, list):
            raise EmptyResponse(str(body)[:120])
        return parse_estimates(sym, body, snapshot_date)

    syms = list(symbols)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(one, s): s for s in syms}
        for i, fut in enumerate(as_completed(futs), 1):
            sym = futs[fut]
            try:
                got = fut.result()
                if got:
                    rows.extend(got)
                else:
                    empty.append(sym)  # a real answer: no analyst coverage for these periods
            except Exception as exc:  # noqa: BLE001 - one bad symbol must not stop the run
                failed.append(sym)
                logger.info("estimates %s failed: %s", sym, exc)
            if i % 250 == 0:
                logger.info("estimates: %d/%d symbols, %d rows, %d failed", i, len(syms), len(rows), len(failed))
    logger.info("estimates: %d symbols had no coverage", len(empty))
    return rows, failed, empty


# ── macro ─────────────────────────────────────────────────────────────────────


def parse_fred_csv(series_id: str, text: str, since: date) -> list[dict]:
    out = []
    for rec in csv.DictReader(io.StringIO(text)):
        d = rec.get("observation_date") or rec.get("DATE")
        v = rec.get(series_id)
        if not d or v in (None, "", "."):
            continue
        if date.fromisoformat(d) < since:
            continue
        out.append({"series_id": f"FRED:{series_id}", "obs_date": d, "value": float(v), "source": "fred"})
    return out


def fetch_macro(since: date) -> tuple[list[dict], list[str]]:
    rows: list[dict] = []
    failed: list[str] = []
    for sid in FRED_SERIES:
        try:
            r = _get(FRED_CSV, {"id": sid, "cosd": since.isoformat()})
            r.raise_for_status()
            rows.extend(parse_fred_csv(sid, r.text, since))
        except Exception as exc:  # noqa: BLE001
            failed.append(f"FRED:{sid}")
            logger.warning("FRED %s failed: %s", sid, exc)
    key = _fmp_key()
    for sym in FMP_SERIES:
        try:
            r = _get(f"{FMP_BASE}/historical-price-eod/light", {"symbol": sym, "from": since.isoformat(), "apikey": key})
            r.raise_for_status()
            for rec in r.json():
                rows.append({"series_id": f"FMP:{sym}", "obs_date": rec["date"][:10], "value": rec["price"], "source": "fmp"})
        except Exception as exc:  # noqa: BLE001
            failed.append(f"FMP:{sym}")
            logger.warning("FMP %s failed: %s", sym, exc)
    return rows, failed


# ── persistence ───────────────────────────────────────────────────────────────


@dataclass
class RunResult:
    snapshot_date: str
    universe: int
    estimate_rows: int
    estimate_symbols: int
    estimate_failed: int
    estimate_no_coverage: int
    macro_rows: int
    macro_failed: list[str]
    status: str  # "complete" | "partial"
    db: str  # "written" | "skipped: <reason>"
    out_dir: str


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r, default=str) + "\n")


def upsert(sb, estimates: list[dict], macro: list[dict], first_seen: str, manifest: dict) -> None:
    """Estimates upsert (re-run refreshes values AND fetched_at); macro inserts only
    unseen observations (ignore_duplicates keeps the original first_seen, and two
    concurrent runs cannot collide). The run manifest is written LAST: readers trust
    a day only when its manifest row says status=complete."""
    t = sb.schema("swingtrader")
    now = datetime.now(timezone.utc).isoformat()
    # One row per key: a symbol listed twice in `tickers` (seen: QBTS) yields the
    # same rows twice, and Postgres rejects an upsert batch that hits a key twice.
    est = list({(r["symbol"], r["fiscal_date"]): dict(r, fetched_at=now) for r in estimates}.values())
    macro = list({(m["series_id"], m["obs_date"]): m for m in macro}.values())
    for i in range(0, len(est), 1000):
        t.table("drawdown_estimate_snapshots").upsert(
            est[i : i + 1000], on_conflict="snapshot_date,symbol,fiscal_date"
        ).execute()
    mac = [dict(m, first_seen=first_seen, fetched_at=now) for m in macro]
    for i in range(0, len(mac), 1000):
        t.table("drawdown_macro_snapshots").upsert(
            mac[i : i + 1000], on_conflict="series_id,obs_date", ignore_duplicates=True
        ).execute()
    t.table("drawdown_snapshot_runs").upsert(dict(manifest, finished_at=now), on_conflict="snapshot_date").execute()


def run(limit: int | None = None, macro_since: date | None = None, write_db: bool = True) -> RunResult:
    """Snapshot TODAY (US/Eastern). There is deliberately no date argument: FMP serves
    the current consensus, so stamping it with any other date would forge history."""
    from shared.db import get_supabase_client

    snapshot_date = market_date()
    macro_since = macro_since or date(snapshot_date.year - 1, snapshot_date.month, 1)
    sb = get_supabase_client()

    liquid = liquid_universe(sb)
    universe = sorted(set(liquid) | previously_tracked(snapshot_date))
    if limit:
        universe = universe[:limit]
    logger.info("drawdown snapshot %s: %d symbols", snapshot_date, len(universe))

    est, est_failed, est_empty = fetch_estimates(universe, snapshot_date)
    macro, macro_failed = fetch_macro(macro_since)

    out_dir = OUT_ROOT / snapshot_date.isoformat()
    _write_jsonl(out_dir / "estimates.jsonl", est)
    _write_jsonl(out_dir / "macro.jsonl", macro)
    (out_dir / "failed_symbols.txt").write_text("\n".join(sorted(est_failed)))
    (out_dir / "universe.txt").write_text("\n".join(universe))

    failed_share = len(est_failed) / max(len(universe), 1)
    status = "complete" if failed_share <= MAX_FAILED_SHARE and not macro_failed and est else "partial"
    manifest = {
        "snapshot_date": snapshot_date.isoformat(),
        "status": status,
        "universe": len(universe),
        "estimate_rows": len(est),
        "estimate_failed": len(est_failed),
        "estimate_no_coverage": len(est_empty),
        "macro_rows": len(macro),
        "macro_failed": macro_failed,
    }

    db = "skipped: --no-db"
    if write_db:
        try:
            upsert(sb, est, macro, snapshot_date.isoformat(), manifest)
            db = "written"
        except Exception as exc:  # noqa: BLE001 - JSONL is the record; report, don't lose the day
            db = f"skipped: {str(exc)[:160]}"
            logger.warning("Supabase write skipped (%s); JSONL kept in %s", exc, out_dir)

    res = RunResult(
        snapshot_date=snapshot_date.isoformat(),
        universe=len(universe),
        estimate_rows=len(est),
        estimate_symbols=len({r["symbol"] for r in est}),
        estimate_failed=len(est_failed),
        estimate_no_coverage=len(est_empty),
        macro_rows=len(macro),
        macro_failed=macro_failed,
        status=status,
        db=db,
        out_dir=str(out_dir),
    )
    (out_dir / "run.json").write_text(json.dumps(res.__dict__, indent=2))
    return res


def load(snapshot_date: date) -> RunResult:
    """Backfill Supabase from a day's JSONL (after the migration is applied)."""
    from shared.db import get_supabase_client

    out_dir = OUT_ROOT / snapshot_date.isoformat()
    est = [json.loads(l) for l in (out_dir / "estimates.jsonl").read_text().splitlines() if l]
    macro = [json.loads(l) for l in (out_dir / "macro.jsonl").read_text().splitlines() if l]
    prev = json.loads((out_dir / "run.json").read_text())
    prev.setdefault("status", "complete" if prev.get("estimate_failed", 0) / max(prev.get("universe", 1), 1) <= MAX_FAILED_SHARE else "partial")
    prev.setdefault("estimate_no_coverage", 0)
    manifest = {k: prev[k] for k in ("snapshot_date", "status", "universe", "estimate_rows", "estimate_failed",
                                     "estimate_no_coverage", "macro_rows", "macro_failed")}
    upsert(get_supabase_client(), est, macro, snapshot_date.isoformat(), manifest)
    prev["db"] = "written (backfilled)"
    (out_dir / "run.json").write_text(json.dumps(prev, indent=2))
    return RunResult(**prev)
