#!/usr/bin/env python3
"""
dimension_significance_cli.py — Statistical significance testing for company vector dimensions.

Fetches tickers live from FMP API, builds dimension vectors, then tests each dimension
for predictive power against a target variable, printing a ranked table ordered by
effect size / correlation magnitude.

Usage:
    python dimension_significance_cli.py
    python dimension_significance_cli.py --target price_change_1m
    python dimension_significance_cli.py --target price_change_3m --top 20 --plot
    python dimension_significance_cli.py --index SP500 --target price_change_1m
    python dimension_significance_cli.py --index SP500 NASDAQ100 --target price_change_1m
    python dimension_significance_cli.py --tickers AAPL MSFT NVDA --target price_momentum
    python dimension_significance_cli.py --output results.csv
    python dimension_significance_cli.py --no-cache --target price_change_1m

Indexes (--index):
    NASDAQ100  (default) — NASDAQ-100 constituents
    SP500                — S&P 500 constituents
    DOWJONES             — Dow Jones 30 constituents

Targets:
    price_momentum  (default) — continuous 0-1: price vs 52-week high (from dimensions)
    price_change_1m           — continuous: 1-month price change % from FMP
    price_change_3m           — continuous: 3-month price change % from FMP

Statistical tests applied (all targets are continuous):
    - Spearman rank correlation ρ + p-value
    - Pearson correlation r + p-value
    - Mutual information (sklearn, 5 neighbours)

Output columns:
    dimension, cluster, higher_is, n_total,
    spearman_rho, spearman_p, pearson_r, pearson_p, mutual_info,
    rank_score  — abs(spearman_rho) × -log10(spearman_p) + normalized_MI
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=_ROOT / ".env")

sys.path.insert(0, str(_ROOT))

from news_impact.dimensions import ALL_DIMENSIONS  # noqa: E402


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

_INDEX_ENDPOINTS = {
    "SP500":     "https://financialmodelingprep.com/api/v3/sp500_constituent",
    "NASDAQ100": "https://financialmodelingprep.com/api/v3/nasdaq_constituent",
    "DOWJONES":  "https://financialmodelingprep.com/api/v3/dowjones_constituent",
}


def fetch_index_tickers(indexes: list[str]) -> list[str]:
    """
    Fetch constituent tickers for the given FMP indexes.
    Returns sorted deduplicated list of ticker symbols.
    """
    import requests

    apikey = os.environ.get("APIKEY") or os.environ.get("FMP_API_KEY")
    if not apikey:
        raise RuntimeError("FMP API key not set (APIKEY or FMP_API_KEY in .env)")

    tickers: set[str] = set()
    for idx in indexes:
        url = _INDEX_ENDPOINTS.get(idx.upper())
        if not url:
            raise ValueError(f"Unknown index '{idx}'. Valid: {list(_INDEX_ENDPOINTS)}")
        print(f"Fetching {idx} constituents from FMP…")
        r = requests.get(url, params={"apikey": apikey}, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"FMP returned {r.status_code} for {idx}")
        data = r.json()
        if not data:
            print(f"  Warning: no constituents for {idx}")
            continue
        chunk = {row["symbol"] for row in data if row.get("symbol")}
        print(f"  {len(chunk)} tickers from {idx}")
        tickers |= chunk

    result = sorted(tickers)
    print(f"Total tickers: {len(result)}")
    return result


def load_vectors_from_fmp(
    tickers: list[str],
    use_cache: bool = True,
) -> pd.DataFrame:
    """
    Build dimension vectors live from FMP API.
    Returns DataFrame with columns: ticker, vector_date, + one column per dimension.
    """
    import asyncio
    from news_impact.company_vector import build_vectors

    vectors = asyncio.run(build_vectors(tickers, use_cache=use_cache))

    rows = []
    for cv in vectors:
        row = {"ticker": cv.ticker, "vector_date": cv.fetched_at.date().isoformat()}
        for dim in ALL_DIMENSIONS:
            row[dim["key"]] = cv.dimensions.get(dim["key"])
        rows.append(row)

    df = pd.DataFrame(rows)
    print(f"Built {len(df)} vectors from FMP")
    return df


def load_fmp_price_change(tickers: list[str]) -> pd.DataFrame:
    """
    Fetch price change % for tickers from FMP stock-price-change endpoint.
    Returns DataFrame with columns: ticker, change_1m, change_3m.
    """
    import requests

    apikey = os.environ.get("APIKEY") or os.environ.get("FMP_API_KEY")
    if not apikey:
        raise RuntimeError("FMP API key not set")

    chunk_size = 500
    frames = []
    for i in range(0, len(tickers), chunk_size):
        chunk = tickers[i : i + chunk_size]
        joined = ",".join(chunk)
        url = f"https://financialmodelingprep.com/api/v3/stock-price-change/{joined}"
        r = requests.get(url, params={"apikey": apikey}, timeout=30)
        if r.status_code != 200:
            print(f"Warning: price-change API returned {r.status_code} for chunk {i // chunk_size}")
            continue
        data = r.json()
        if data:
            frames.append(pd.DataFrame(data))

    if not frames:
        raise RuntimeError("No price change data returned from FMP")

    df = pd.concat(frames, ignore_index=True)
    df = df.rename(columns={"symbol": "ticker", "1M": "change_1m", "3M": "change_3m"})
    keep = [c for c in ["ticker", "change_1m", "change_3m"] if c in df.columns]
    return df[keep]


# ---------------------------------------------------------------------------
# Statistical tests
# ---------------------------------------------------------------------------

def test_continuous(
    dim_vals: np.ndarray,
    target: np.ndarray,
    min_samples: int = 10,
) -> dict:
    from scipy import stats
    from sklearn.feature_selection import mutual_info_regression

    mask = ~np.isnan(dim_vals) & ~np.isnan(target)
    x = dim_vals[mask]
    y = target[mask]

    result = {
        "n_total": len(x),
        "spearman_rho": float("nan"),
        "spearman_p": float("nan"),
        "pearson_r": float("nan"),
        "pearson_p": float("nan"),
        "mutual_info": float("nan"),
    }

    if len(x) < min_samples:
        return result

    rho, sp_p = stats.spearmanr(x, y)
    result["spearman_rho"] = float(rho)
    result["spearman_p"] = float(sp_p)

    pr, pp = stats.pearsonr(x, y)
    result["pearson_r"] = float(pr)
    result["pearson_p"] = float(pp)

    try:
        mi = mutual_info_regression(x.reshape(-1, 1), y, n_neighbors=5, random_state=42)
        result["mutual_info"] = float(mi[0])
    except Exception:
        pass

    return result


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------

def rank_results(df_results: pd.DataFrame) -> pd.DataFrame:
    """
    rank_score = abs(spearman_rho) × -log10(spearman_p) + normalized_MI
    """
    df = df_results.copy()
    sig_weight = (-np.log10(df["spearman_p"].clip(lower=1e-300))).clip(upper=10.0)
    mi_norm = df["mutual_info"] / (df["mutual_info"].max() + 1e-9)
    df["rank_score"] = df["spearman_rho"].abs() * sig_weight + mi_norm
    return df.sort_values("rank_score", ascending=False)


# ---------------------------------------------------------------------------
# Formatting & display
# ---------------------------------------------------------------------------

_SIG_STARS = {0.001: "***", 0.01: "**", 0.05: "*", 1.0: ""}


def _stars(p: float) -> str:
    for threshold, stars in _SIG_STARS.items():
        if p < threshold:
            return stars
    return ""


def print_results_table(df: pd.DataFrame, target_name: str, top: Optional[int] = None) -> None:
    if top:
        df = df.head(top)

    header = (
        f"{'#':>3}  {'Dimension':<44} {'Cluster':<24} {'Dir':<6} "
        f"{'n':>5} {'Spearman_ρ':>11} {'Spearman_p':>11} {'Sig':>4} "
        f"{'Pearson_r':>10} {'MutInfo':>8} {'Score':>7}"
    )
    print(f"\nTarget: {target_name}")
    print("=" * len(header))
    print(header)
    print("=" * len(header))

    for rank, (_, row) in enumerate(df.iterrows(), 1):
        sig = _stars(row["spearman_p"]) if not np.isnan(row["spearman_p"]) else ""
        print(
            f"{rank:>3}  {row['dimension']:<44} {row['cluster']:<24} {row['higher_is']:<6} "
            f"{int(row['n_total']):>5} {row['spearman_rho']:>11.4f} "
            f"{row['spearman_p']:>11.4e} {sig:>4} "
            f"{row['pearson_r']:>10.4f} {row['mutual_info']:>8.4f} {row['rank_score']:>7.3f}"
        )

    print("=" * len(header))
    print("Significance: *** p<0.001  ** p<0.01  * p<0.05")


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

def plot_results(df: pd.DataFrame, target_name: str, top: int = 20) -> None:
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError:
        print("plotly not available, skipping plot")
        return

    df_plot = df.head(top).copy()
    colors = ["#2ecc71" if r > 0 else "#e74c3c" for r in df_plot["spearman_rho"]]

    fig = make_subplots(
        rows=1, cols=2,
        subplot_titles=[f"Spearman ρ vs {target_name}", "Mutual Information"],
        horizontal_spacing=0.15,
    )

    fig.add_trace(
        go.Bar(
            x=df_plot["spearman_rho"],
            y=df_plot["dimension"],
            orientation="h",
            marker_color=colors,
            name="Spearman ρ",
            text=[f"{v:.3f}" for v in df_plot["spearman_rho"]],
            textposition="outside",
        ),
        row=1, col=1,
    )

    fig.add_trace(
        go.Bar(
            x=df_plot["mutual_info"],
            y=df_plot["dimension"],
            orientation="h",
            marker_color="#9b59b6",
            name="MI",
            text=[f"{v:.4f}" for v in df_plot["mutual_info"]],
            textposition="outside",
        ),
        row=1, col=2,
    )

    fig.update_layout(
        title=f"Dimension Predictive Power — {target_name}",
        height=max(500, top * 30),
        showlegend=False,
        plot_bgcolor="#1a1a2e",
        paper_bgcolor="#16213e",
        font=dict(color="#eee"),
    )
    fig.update_yaxes(autorange="reversed")
    fig.add_vline(x=0, line_dash="dot", line_color="white", row=1, col=1)
    fig.add_vline(x=-np.log10(0.05), line_dash="dot", line_color="orange", row=1, col=1)

    fig.show()


# ---------------------------------------------------------------------------
# Cluster summary
# ---------------------------------------------------------------------------

def print_cluster_summary(df: pd.DataFrame) -> None:
    summary = (
        df.groupby("cluster")["rank_score"]
        .agg(["mean", "max", "count"])
        .sort_values("mean", ascending=False)
        .rename(columns={"mean": "avg_score", "max": "max_score", "count": "n_dims"})
    )
    print("\n--- Cluster Summary (by avg rank_score) ---")
    print(summary.to_string(float_format="{:.3f}".format))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(
    target: str = "price_momentum",
    top: Optional[int] = None,
    output: Optional[str] = None,
    plot: bool = False,
    min_samples: int = 10,
    indexes: Optional[list[str]] = None,
    tickers_override: Optional[list[str]] = None,
    no_cache: bool = False,
) -> pd.DataFrame:

    # Load vectors
    if tickers_override:
        ticker_list = tickers_override
        print(f"Using {len(ticker_list)} provided tickers")
    else:
        ticker_list = fetch_index_tickers(indexes or ["NASDAQ100"])

    df_vec = load_vectors_from_fmp(ticker_list, use_cache=not no_cache)

    # Resolve target
    if target in ("price_change_1m", "price_change_3m"):
        col = "change_1m" if target == "price_change_1m" else "change_3m"
        df_price = load_fmp_price_change(df_vec["ticker"].tolist())
        df_vec = df_vec.merge(df_price[["ticker", col]], on="ticker", how="inner")
        print(f"Joined {len(df_vec)} tickers with price-change data")
        target_series = pd.to_numeric(df_vec[col], errors="coerce")
        target_label = f"{target} % (FMP)"
    elif target == "price_momentum":
        target_series = df_vec["price_momentum"].astype(float)
        target_label = "price_momentum (from dimensions)"
    else:
        raise ValueError(f"Unknown target: {target}. Use: price_momentum, price_change_1m, price_change_3m")

    target_arr = target_series.values.astype(float)

    # Run tests per dimension
    results = []
    for dim in ALL_DIMENSIONS:
        key = dim["key"]
        dim_arr = df_vec[key].astype(float).values if key in df_vec.columns else np.full(len(df_vec), np.nan)
        stats = test_continuous(dim_arr, target_arr, min_samples=min_samples)
        results.append({
            "dimension": key,
            "cluster": dim["cluster"],
            "higher_is": dim["higher_is"],
            **stats,
        })

    df_ranked = rank_results(pd.DataFrame(results))
    print_results_table(df_ranked, target_name=target_label, top=top)
    print_cluster_summary(df_ranked)

    if output:
        df_ranked.to_csv(output, index=False)
        print(f"\nResults saved to: {output}")

    if plot:
        plot_results(df_ranked, target_name=target_label, top=top or 20)

    return df_ranked


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dimension significance testing — fetches tickers live from FMP API"
    )
    parser.add_argument(
        "--target",
        default="price_momentum",
        choices=["price_momentum", "price_change_1m", "price_change_3m"],
        help="Target variable (default: price_momentum)",
    )
    parser.add_argument(
        "--index",
        nargs="+",
        default=None,
        metavar="INDEX",
        help="Index constituents to test against: SP500, NASDAQ100, DOWJONES (default: NASDAQ100)",
    )
    parser.add_argument(
        "--tickers",
        nargs="+",
        default=None,
        metavar="TICKER",
        help="Explicit ticker list instead of screener",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Bypass 24h vector cache and force fresh FMP fetch",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=None,
        metavar="N",
        help="Show only top N dimensions (default: all)",
    )
    parser.add_argument(
        "--output",
        default=None,
        metavar="FILE.csv",
        help="Save full results to CSV",
    )
    parser.add_argument(
        "--plot",
        action="store_true",
        help="Open interactive Plotly charts",
    )
    parser.add_argument(
        "--min-samples",
        type=int,
        default=10,
        metavar="N",
        help="Minimum sample size for statistical tests (default: 10)",
    )

    args = parser.parse_args()
    run(
        target=args.target,
        top=args.top,
        output=args.output,
        plot=args.plot,
        min_samples=args.min_samples,
        indexes=args.index,
        tickers_override=args.tickers,
        no_cache=args.no_cache,
    )


if __name__ == "__main__":
    main()
