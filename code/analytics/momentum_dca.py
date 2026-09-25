#!/usr/bin/env python3
"""
Monthly momentum DCA backtest.

Each month-end: rank S&P 500 stocks by trailing 12-month price return,
then invest a fixed amount in the #1 stock (bought at the next trading day's
close). Each purchase (lot) is held until its close falls --stop below the
highest close since it was bought (a trailing stop, default 20%), when it is
sold at that close; the proceeds wait in cash and are added to the next
monthly purchase. Compared against putting the same amount into a benchmark (SPY) on the
same days.

Setup:
    pip install yfinance pandas numpy matplotlib lxml requests

Examples:
    python momentum_dca.py --start 2010-01-01 --amount 1000
    python momentum_dca.py --start 2015-01-01 --top 3          # split across top 3
    python momentum_dca.py --start 2010-01-01 --skip 1         # classic 12-1 momentum
    python momentum_dca.py --constituents sp500_history.csv    # point-in-time universe
    python momentum_dca.py --stop 0                            # no stop loss, hold forever
"""
import argparse
import io

import numpy as np
import pandas as pd


# ---------------------------------------------------------------- data
def current_sp500_tickers():
    import requests

    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    html = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30).text
    table = pd.read_html(io.StringIO(html))[0]
    return sorted(table["Symbol"].str.replace(".", "-", regex=False).tolist())


def load_constituents(path):
    """CSV with columns `date,tickers` (tickers comma-separated), one row per
    membership change, e.g. the historical-components file in the
    fja05680/sp500 GitHub repo."""
    df = pd.read_csv(path, parse_dates=["date"]).sort_values("date")
    df["tickers"] = df["tickers"].str.replace(".", "-", regex=False).str.split(",")
    return df.set_index("date")["tickers"]


def download_prices(tickers, start, end):
    import yfinance as yf

    data = yf.download(
        tickers, start=start, end=end, auto_adjust=True, progress=True, threads=True
    )["Close"]
    if isinstance(data, pd.Series):
        data = data.to_frame(tickers[0])
    return data.dropna(how="all", axis=1).sort_index()


# ---------------------------------------------------------------- engine
def backtest(
    raw, bench_raw, start, amount, lookback=12, skip=0, top=1, universe=None, stop=0.2
):
    prices = raw.ffill()  # last known price carried after a delisting
    bench = bench_raw.reindex(raw.index).ffill()
    days = raw.index
    month_ends = pd.DatetimeIndex(
        pd.Series(days, index=days).groupby(days.to_period("M")).last().values
    )

    def stop_exit(tk, buy_date, px):
        # trailing stop: first close after purchase <= (1 - stop) * its highest
        # close since purchase (buy price included). Closes only - a gap through
        # the stop fills at that close, not the stop.
        if stop <= 0:
            return pd.NaT, np.nan
        path = prices.loc[prices.index > buy_date, tk]
        high = path.cummax().clip(lower=px)
        hit = path[path <= high * (1 - stop)]
        return (hit.index[0], hit.iloc[0]) if len(hit) else (pd.NaT, np.nan)

    buys = []
    redeployed = 0.0  # stop proceeds already put back into a purchase
    for i in range(lookback + skip, len(month_ends)):
        t = month_ends[i]
        if t < pd.Timestamp(start):
            continue
        later = days[days > t]
        if len(later) == 0:
            break
        exec_day = later[0]
        t_now, t_then = month_ends[i - skip], month_ends[i - skip - lookback]

        ok = raw.loc[t].notna() & raw.loc[t_then].notna() & raw.loc[exec_day].notna()
        if universe is not None:
            members = universe[universe.index <= t]
            if len(members):
                ok &= raw.columns.isin(members.iloc[-1])
        ret = (prices.loc[t_now] / prices.loc[t_then] - 1)[ok].dropna()
        if ret.empty:
            continue

        # stop proceeds realised by today's close ride along with this month's buy
        freed = sum(
            b["proceeds"] for b in buys if b["stopped"] and b["exit_date"] <= exec_day
        )
        recycle = freed - redeployed
        redeployed = freed

        for tk, r in ret.nlargest(top).items():
            px = prices.at[exec_day, tk]
            spend = (amount + recycle) / top
            ex_date, ex_px = stop_exit(tk, exec_day, px)
            buys.append(
                dict(
                    signal_date=t,
                    buy_date=exec_day,
                    ticker=tk,
                    trailing_return=r,
                    price=px,
                    contribution=amount / top,
                    amount=spend,
                    shares=spend / px,
                    exit_date=ex_date,
                    exit_price=ex_px,
                    stopped=pd.notna(ex_date),
                    proceeds=spend / px * ex_px if pd.notna(ex_date) else 0.0,
                )
            )

    log = pd.DataFrame(buys)
    if log.empty:
        raise SystemExit("No purchases made - check dates / data.")
    log["exit_date"] = pd.to_datetime(log.exit_date)

    first = log.buy_date.min()
    idx = days[days >= first]

    exits = log[log.stopped]
    trades = pd.concat(
        [
            log[["buy_date", "ticker", "shares"]].rename(columns={"buy_date": "date"}),
            exits[["exit_date", "ticker", "shares"]]
            .rename(columns={"exit_date": "date"})
            .assign(shares=lambda d: -d.shares),
        ]
    )
    held = (
        trades.pivot_table(index="date", columns="ticker", values="shares", aggfunc="sum")
        .reindex(idx)
        .fillna(0)
        .cumsum()
        .clip(lower=0)  # float dust after a full exit
    )
    proceeds = exits.groupby("exit_date").proceeds.sum().reindex(idx).fillna(0)
    spent = log.groupby("buy_date").amount.sum().reindex(idx).fillna(0)
    contrib = log.groupby("buy_date").contribution.sum().reindex(idx).fillna(0)
    cash = (proceeds - (spent - contrib)).cumsum()
    value = (held * prices.loc[idx, held.columns]).sum(axis=1) + cash

    invested = contrib.cumsum()
    bench_value = (contrib / bench.loc[idx]).cumsum() * bench.loc[idx]

    curve = pd.DataFrame(
        {"strategy": value, "benchmark": bench_value, "invested": invested, "cash": cash}
    )
    return log, curve, contrib, held


# ---------------------------------------------------------------- metrics
def xirr(dates, amounts):
    t = np.array([(d - dates[0]).days / 365.25 for d in dates])
    a = np.array(amounts, dtype=float)
    f = lambda r: np.sum(a / (1 + r) ** t)
    lo, hi = -0.99, 10.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if f(lo) * f(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return mid


def stats(values, contrib):
    # time-weighted return index strips out the effect of new contributions
    prev = values.shift(1)
    r = ((values - contrib) / prev - 1).fillna(0).replace([np.inf, -np.inf], 0)
    twr = (1 + r).cumprod()
    years = (values.index[-1] - values.index[0]).days / 365.25
    flows = contrib[contrib > 0]
    irr = xirr(
        list(flows.index) + [values.index[-1]], list(-flows.values) + [values.iloc[-1]]
    )
    return {
        "final_value": values.iloc[-1],
        "money_weighted_irr": irr,
        "time_weighted_cagr": twr.iloc[-1] ** (1 / years) - 1 if years > 0 else np.nan,
        "max_drawdown": (twr / twr.cummax() - 1).min(),
        "annual_vol": r.std() * np.sqrt(252),
    }


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2010-01-01")
    ap.add_argument("--end", default=None)
    ap.add_argument("--amount", type=float, default=1000)
    ap.add_argument("--lookback", type=int, default=12, help="months")
    ap.add_argument(
        "--skip",
        type=int,
        default=0,
        help="skip most recent N months (1 = 12-1 momentum)",
    )
    ap.add_argument(
        "--top", type=int, default=1, help="split each month's amount across top N"
    )
    ap.add_argument(
        "--stop",
        type=float,
        default=0.2,
        help="trailing stop: sell a lot when it closes this fraction below its "
        "highest close since purchase (0 = off)",
    )
    ap.add_argument("--benchmark", default="SPY")
    ap.add_argument(
        "--constituents", default=None, help="CSV of historical S&P 500 members"
    )
    ap.add_argument("--out", default="momentum_dca")
    a = ap.parse_args()

    universe = None
    if a.constituents:
        universe = load_constituents(a.constituents)
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
        print(
            "WARNING: using TODAY's S&P 500 members for the whole history "
            "(survivorship bias - results will look better than reality)."
        )

    dl_start = (
        pd.Timestamp(a.start) - pd.DateOffset(months=a.lookback + a.skip + 2)
    ).date()
    print(f"Downloading {len(tickers)} tickers from {dl_start} ...")
    raw = download_prices(tickers, dl_start, a.end)
    bench_raw = download_prices([a.benchmark], dl_start, a.end)[a.benchmark]
    print(f"Got prices for {raw.shape[1]} of {len(tickers)} tickers.")

    log, curve, contrib, held = backtest(
        raw, bench_raw, a.start, a.amount, a.lookback, a.skip, a.top, universe, a.stop
    )

    s, b = stats(curve.strategy, contrib), stats(curve.benchmark, contrib)
    print(
        f"\nPeriod: {curve.index[0].date()} -> {curve.index[-1].date()}  "
        f"({len(log)} buys, {log.ticker.nunique()} distinct stocks)"
    )
    print(f"Total invested: {curve.invested.iloc[-1]:,.0f}")
    if a.stop > 0:
        print(
            f"Trailing stop {a.stop:.0%}: {log.stopped.sum()} of {len(log)} lots stopped out, "
            f"cash now {abs(curve.cash.iloc[-1]):,.0f}"
        )
    print()
    print(f"{'':24}{'Strategy':>14}{a.benchmark:>14}")
    for k, fmt in [
        ("final_value", "{:,.0f}"),
        ("money_weighted_irr", "{:.1%}"),
        ("time_weighted_cagr", "{:.1%}"),
        ("max_drawdown", "{:.1%}"),
        ("annual_vol", "{:.1%}"),
    ]:
        print(f"{k:24}{fmt.format(s[k]):>14}{fmt.format(b[k]):>14}")

    last = curve.index[-1]
    pos = held.loc[last]
    pos = pos[pos > 0]
    positions = pd.DataFrame(
        {
            "times_bought": log.groupby("ticker").size(),
            "cost": log.groupby("ticker").amount.sum(),
            "value_now": pos * raw.ffill().loc[last, pos.index],
            "stopped_proceeds": log.groupby("ticker").proceeds.sum(),
        }
    ).fillna({"value_now": 0})
    positions["gain_%"] = (
        (positions.value_now + positions.stopped_proceeds) / positions.cost - 1
    ) * 100
    positions = positions.sort_values("value_now", ascending=False)
    print("\nTop positions by current value:")
    print(positions.head(15).round(1).to_string())

    log.to_csv(f"{a.out}_buys.csv", index=False)
    positions.to_csv(f"{a.out}_positions.csv")
    curve.to_csv(f"{a.out}_equity.csv")

    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(11, 6))
    curve.strategy.plot(ax=ax, label=f"Top-{a.top} {a.lookback}m momentum")
    curve.benchmark.plot(ax=ax, label=f"{a.benchmark} DCA")
    curve.invested.plot(ax=ax, label="Cash invested", ls="--", c="grey")
    stop_note = f", {a.stop:.0%} trailing stop" if a.stop > 0 else ""
    ax.set_title(
        f"{a.amount:,.0f}/month into the S&P 500's top trailing performer{stop_note}"
    )
    ax.set_ylabel("Portfolio value")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(f"{a.out}_chart.png", dpi=130)
    print(f"\nSaved {a.out}_buys.csv, _positions.csv, _equity.csv, _chart.png")


if __name__ == "__main__":
    main()
