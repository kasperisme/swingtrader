#!/usr/bin/env python3
"""
Monthly DCA: momentum picks vs simply buying the biggest companies.

Same engine as momentum_dca.py, same money on the same days, three books:
  - momentum:  top-N S&P 500 stocks by trailing 12m return, trailing stop
  - megacap:   top-M S&P 500 stocks by market cap at the signal date, held
  - megacap + the same trailing stop (so the stop is not the difference)
plus the SPY DCA benchmark.

Market caps are point-in-time daily history from FMP
(/stable/historical-market-capitalization), cached to --cache, so "the 10
biggest" in 2012 is the 10 biggest of 2012, not of today. The universe is
still today's S&P 500 members (survivorship bias) unless --constituents.

    python megacap_vs_momentum.py --start 2010-01-01 --amount 1000
"""
import argparse
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import requests

from momentum_dca import (
    backtest,
    current_sp500_tickers,
    download_prices,
    load_constituents,
    stats,
)

# second share class of the same company: ranking both would give one company
# two of the ten slots
DUAL_CLASS = {"GOOG", "FOX", "NWS"}

FMP_URL = "https://financialmodelingprep.com/stable/historical-market-capitalization"


def _fmp_mcap(symbol, start, end, key):
    # FMP returns at most ~5000 rows per call; split into 10-year windows
    rows, lo = [], pd.Timestamp(start)
    end = pd.Timestamp(end)
    while lo <= end:
        hi = min(lo + pd.DateOffset(years=10), end)
        for attempt in range(8):
            try:
                r = requests.get(
                    FMP_URL,
                    params={
                        "symbol": symbol,
                        "from": lo.date(),
                        "to": hi.date(),
                        "limit": 10000,
                        "apikey": key,
                    },
                    timeout=30,
                )
                if r.status_code == 200:
                    d = r.json()
                    rows += d if isinstance(d, list) else []
                    break
                if r.status_code != 429:
                    break
            except requests.RequestException:
                pass
            time.sleep(2 ** attempt)  # rate limited: back off
        lo = hi + pd.DateOffset(days=1)
    if not rows:
        return None
    s = pd.DataFrame(rows).set_index("date")["marketCap"]
    s.index = pd.to_datetime(s.index)
    return s.rename(symbol).sort_index()


def market_caps(tickers, start, end, cache):
    cache = Path(cache)
    have = pd.read_pickle(cache) if cache.exists() else pd.DataFrame()
    missing = [t for t in tickers if t not in have.columns]
    if missing:
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).parent / ".env")
        key = os.environ["FMP_API_KEY"]
        print(f"Fetching market-cap history for {len(missing)} tickers from FMP ...")
        with ThreadPoolExecutor(4) as ex:
            got = [
                s
                for s in ex.map(lambda t: _fmp_mcap(t, start, end, key), missing)
                if s is not None
            ]
        print(f"  got {len(got)} of {len(missing)}")
        if got:
            have = pd.concat([have, *got], axis=1).sort_index()
            cache.parent.mkdir(parents=True, exist_ok=True)
            have.to_pickle(cache)
    return have[[t for t in tickers if t in have.columns and t not in DUAL_CLASS]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2010-01-01")
    ap.add_argument("--end", default=None)
    ap.add_argument("--amount", type=float, default=1000)
    ap.add_argument("--momentum-top", type=int, default=5)
    ap.add_argument("--megacap-top", type=int, default=10)
    ap.add_argument("--stop", type=float, default=0.2)
    ap.add_argument("--benchmark", default="SPY")
    ap.add_argument("--constituents", default=None)
    ap.add_argument("--cache", default="output/momentum_dca/market_caps.pkl")
    ap.add_argument("--out", default="output/momentum_dca/megacap_vs_momentum")
    a = ap.parse_args()

    universe = load_constituents(a.constituents) if a.constituents else None
    if universe is not None:
        tickers = sorted(
            {
                t
                for lst in universe[
                    universe.index >= pd.Timestamp(a.start) - pd.DateOffset(years=2)
                ]
                for t in lst
            }
        )
    else:
        tickers = current_sp500_tickers()
        print("WARNING: today's S&P 500 members for the whole history (survivorship bias).")

    dl_start = (pd.Timestamp(a.start) - pd.DateOffset(months=14)).date()
    end = a.end or pd.Timestamp.today().date()
    raw = download_prices(tickers, dl_start, a.end)
    bench_raw = download_prices([a.benchmark], dl_start, a.end)[a.benchmark]
    caps = market_caps(list(raw.columns), dl_start, end, a.cache)

    books = {
        f"Momentum top-{a.momentum_top}, {a.stop:.0%} trail": dict(
            top=a.momentum_top, stop=a.stop
        ),
        f"Biggest {a.megacap_top}, hold": dict(top=a.megacap_top, stop=0, rank=caps),
        f"Biggest {a.megacap_top}, {a.stop:.0%} trail": dict(
            top=a.megacap_top, stop=a.stop, rank=caps
        ),
    }
    curves, rows, logs = {}, {}, {}
    for name, kw in books.items():
        log, curve, contrib, _ = backtest(
            raw, bench_raw, a.start, a.amount, universe=universe, **kw
        )
        curves[name], logs[name] = curve.strategy, log
        rows[name] = stats(curve.strategy, contrib)
    rows[f"{a.benchmark} DCA"] = stats(curve.benchmark, contrib)
    curves[f"{a.benchmark} DCA"] = curve.benchmark
    curves["Invested"] = curve.invested

    table = pd.DataFrame(rows).T
    print(f"\nPeriod: {curve.index[0].date()} -> {curve.index[-1].date()}, "
          f"invested {curve.invested.iloc[-1]:,.0f}\n")
    fmt = table.copy()
    fmt["final_value"] = table.final_value.map("{:,.0f}".format)
    for c in table.columns.drop("final_value"):
        fmt[c] = table[c].map("{:.1%}".format)
    print(fmt.to_string())

    # regime split: IRR-free, just the time-weighted return inside each window
    eq = pd.DataFrame(curves)
    print("\nTime-weighted return by regime:")
    contrib_all = contrib.reindex(eq.index).fillna(0)
    for lo, hi in [("2010", "2019"), ("2020", "2021"), ("2022", "2022"), ("2023", "2026")]:
        w = eq.loc[lo:hi]
        if len(w) < 2:
            continue
        c = contrib_all.loc[lo:hi]
        out = {}
        for col in eq.columns.drop("Invested"):
            v = w[col]
            r = ((v - c) / v.shift(1) - 1).fillna(0)
            out[col] = (1 + r).prod() - 1
        print(f"  {lo}-{hi}: " + "  ".join(f"{k.split(',')[0]}: {v:+.0%}" for k, v in out.items()))

    held = logs[f"Biggest {a.megacap_top}, hold"]
    print("\nMost-bought megacaps:",
          ", ".join(f"{t} ({n})" for t, n in held.ticker.value_counts().head(15).items()))

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    eq.to_csv(f"{a.out}_equity.csv")
    table.to_csv(f"{a.out}_stats.csv")

    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(11, 6))
    for col in eq.columns:
        eq[col].plot(ax=ax, label=col, **({"ls": "--", "c": "grey"} if col == "Invested" else {}))
    ax.set_title(f"{a.amount:,.0f}/month: momentum picks vs the biggest companies")
    ax.set_ylabel("Portfolio value")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(f"{a.out}_chart.png", dpi=130)
    print(f"\nSaved {a.out}_equity.csv, _stats.csv, _chart.png")


if __name__ == "__main__":
    main()
