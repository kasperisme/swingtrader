#!/usr/bin/env python3
"""
pair_data.py — gather everything for a ticker-pair divergence reel into pair.json.

Pulls the relationship from swingtrader.ticker_pair_stats (cointegration / hedge
ratio / spread mean+std / live z-score) and the news-derived link type from
ticker_pair_candidates_v, fetches both price series (FMP), builds the normalized
"do they follow each other" lines + the evolving z-score, and derives the
mean-reversion trade setup. Company logos come from the FMP profile.

Run from code/analytics with its venv:
  cd code/analytics
  .venv/bin/python ../../.claude/skills/ticker-pair-divergence/scripts/pair_data.py --pair DNUT/MCD
  # or auto-pick the most-diverged cointegrated pair:
  .venv/bin/python ../../.claude/skills/ticker-pair-divergence/scripts/pair_data.py --auto

Writes output/setups/pairs/<A>_<B>/pair.json (+ downloads logo PNGs).
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys


def _find_analytics() -> pathlib.Path:
    marker = pathlib.Path("services") / "pairs" / "store.py"
    for c in [pathlib.Path.cwd(), *pathlib.Path.cwd().parents]:
        if (c / marker).exists():
            return c
    for p in pathlib.Path(__file__).resolve().parents:
        if (p / "code" / "analytics" / marker).exists():
            return p / "code" / "analytics"
    sys.exit("run from code/analytics (services/pairs/store.py not found)")


ANALYTICS = _find_analytics()
sys.path.insert(0, str(ANALYTICS))
# load .env so APIKEY (FMP) + SUPABASE_* are present before importing shared.db
for line in (ANALYTICS / ".env").read_text().splitlines() if (ANALYTICS / ".env").exists() else []:
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import requests  # noqa: E402

from shared.db import get_supabase_client  # noqa: E402
from services.screener.fmp import fmp as FMPClient  # noqa: E402
from services.pairs.prices import fetch_daily_closes  # noqa: E402
from services.viral_reels import data_sources as ds  # noqa: E402

SCHEMA = "swingtrader"
DISPLAY = 140          # trading days shown on the chart
ENTRY_Z = 2.0          # classic pairs entry band
# A readable phrase for each news-derived relationship type (non-obvious first).
REL_PHRASE = {
    "supplier": "one supplies the other",
    "customer": "one is the other's customer",
    "partner": "they're partners",
    "acquirer": "one tried to buy the other",
    "competitor": "they're rivals",
}
REL_PRIORITY = ["supplier", "customer", "partner", "acquirer", "competitor"]


def _norm(a, b):
    a, b = a.upper().strip(), b.upper().strip()
    return (a, b) if a < b else (b, a)


def fetch_pair_row(a, b):
    c = get_supabase_client()
    res = (c.schema(SCHEMA).table("ticker_pair_stats")
           .select("*").eq("ticker_a", a).eq("ticker_b", b).limit(1).execute())
    return (res.data or [None])[0]


def fetch_rel(a, b):
    c = get_supabase_client()
    res = (c.schema(SCHEMA).table("ticker_pair_candidates_v")
           .select("rel_types, article_count").eq("ticker_a", a).eq("ticker_b", b).limit(1).execute())
    row = (res.data or [None])[0] or {}
    rels = row.get("rel_types") or []
    return [str(r) for r in rels], int(row.get("article_count") or 0)


def auto_pick():
    """Most-diverged cointegrated pair (honest mean-reversion thesis)."""
    c = get_supabase_client()
    res = (c.schema(SCHEMA).table("ticker_pair_stats")
           .select("ticker_a, ticker_b, current_zscore")
           .eq("is_cointegrated", True).not_.is_("current_zscore", "null").execute())
    rows = sorted(res.data or [], key=lambda r: -abs(r.get("current_zscore") or 0))
    if not rows:
        sys.exit("no cointegrated pairs with a live z-score found")
    return rows[0]["ticker_a"], rows[0]["ticker_b"]


def save_logo(url, path):
    try:
        r = requests.get(url, timeout=20)
        if r.status_code == 200 and r.content:
            path.write_bytes(r.content)
            return str(path)
    except Exception:
        pass
    return None


def main():
    ap = argparse.ArgumentParser(description="Gather a ticker-pair divergence into pair.json.")
    ap.add_argument("--pair", help="e.g. DNUT/MCD")
    ap.add_argument("--auto", action="store_true", help="auto-pick the most-diverged cointegrated pair")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()

    if args.auto or not args.pair:
        a, b = auto_pick()
    else:
        parts = args.pair.replace(",", "/").split("/")
        if len(parts) != 2:
            sys.exit("--pair must look like DNUT/MCD")
        a, b = parts
    a, b = _norm(a, b)

    row = fetch_pair_row(a, b)
    if not row:
        sys.exit(f"{a}/{b} not in ticker_pair_stats — calibrate it first (services/pairs/calibrate_cli.py)")
    rels, article_count = fetch_rel(a, b)
    rel = next((r for r in REL_PRIORITY if r in rels), (rels[0] if rels else None))

    hedge = float(row["hedge_ratio"]); s_mean = float(row["spread_mean"]); s_std = float(row["spread_std"])
    window = int(row.get("window_days") or 252)

    client = FMPClient()
    closes = fetch_daily_closes(client, [a, b], window_days=window)
    if a not in closes or b not in closes:
        sys.exit(f"could not fetch prices for {a}/{b}")
    df = pd.DataFrame({a: closes[a], b: closes[b]}).dropna().sort_index()
    if len(df) < 40:
        sys.exit("not enough aligned price history")
    df = df.tail(DISPLAY)
    ra, rb = df[a].to_numpy(float), df[b].to_numpy(float)
    dates = [d.isoformat() for d in df.index]

    a_norm = (ra / ra[0] * 100).round(2).tolist()
    b_norm = (rb / rb[0] * 100).round(2).tolist()
    spread = ra - hedge * rb
    z = ((spread - s_mean) / s_std).round(3).tolist()
    rets = np.diff(np.log(np.vstack([ra, rb])), axis=1)
    corr = float(np.corrcoef(rets[0], rets[1])[0, 1])

    z_now = float(row.get("current_zscore") if row.get("current_zscore") is not None else z[-1])
    # divergence point: first bar in the recent third where |z| crosses 1.5 (the
    # spread starting to stretch — "a setup is forming").
    start = int(len(z) * 0.6)
    div_idx = next((i for i in range(start, len(z)) if abs(z[i]) >= 1.5), int(np.argmax(np.abs(z))))

    # mean-reversion trade: z>0 → spread rich → short A / long B; expect z→0.
    if z_now >= 0:
        long_t, short_t = b, a
    else:
        long_t, short_t = a, b
    actionable = abs(z_now) >= ENTRY_Z
    status = ("actionable — the spread is stretched past 2 sigma" if actionable
              else "forming — the spread is stretching toward the 2-sigma band")
    half_life = float(row["half_life_days"]) if row.get("half_life_days") else None

    out_dir = (pathlib.Path(args.out_dir) if args.out_dir
               else ANALYTICS / "output" / "setups" / "pairs" / f"{a}_{b}")
    out_dir.mkdir(parents=True, exist_ok=True)

    prof_a, prof_b = ds.company_profile(a) or {}, ds.company_profile(b) or {}
    logo_a = save_logo(prof_a.get("image"), out_dir / f"logo_{a}.png") if prof_a.get("image") else None
    logo_b = save_logo(prof_b.get("image"), out_dir / f"logo_{b}.png") if prof_b.get("image") else None

    snapshot = {
        "pair": f"{a}/{b}",
        "a": {"ticker": a, "name": (prof_a.get("companyName") or a), "sector": prof_a.get("sector"), "logo": logo_a},
        "b": {"ticker": b, "name": (prof_b.get("companyName") or b), "sector": prof_b.get("sector"), "logo": logo_b},
        "relationship": {"rel_types": rels, "primary": rel,
                          "phrase": REL_PHRASE.get(rel, "they're linked"), "article_count": article_count},
        "stats": {
            "coint_pvalue": float(row["coint_pvalue"]) if row.get("coint_pvalue") is not None else None,
            "is_cointegrated": bool(row.get("is_cointegrated")),
            "half_life_days": half_life,
            "hedge_ratio": hedge,
            "correlation": round(corr, 3),
            "current_zscore": round(z_now, 2),
            "n_obs": int(row.get("n_obs") or 0),
            "window_days": window,
        },
        "series": {"dates": dates, "a_norm": a_norm, "b_norm": b_norm, "z": z, "divergence_idx": div_idx},
        "trade": {
            "kind": "mean-reversion (pairs)",
            "status": status,
            "actionable": actionable,
            "long": long_t, "short": short_t,
            "entry_z": ENTRY_Z, "target_z": 0.0, "stop_z": round(np.sign(z_now) * 3.0, 1),
            "half_life_days": half_life,
        },
    }
    (out_dir / "pair.json").write_text(json.dumps(snapshot, indent=2))
    print(json.dumps({"pair": snapshot["pair"], "out_dir": str(out_dir),
                      "z_now": z_now, "coint_pvalue": snapshot["stats"]["coint_pvalue"],
                      "half_life": half_life, "rel": rel, "trade": snapshot["trade"]}, indent=2))


if __name__ == "__main__":
    main()
