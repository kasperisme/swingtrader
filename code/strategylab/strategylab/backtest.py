"""Event-driven portfolio simulator.

Design commitments, each of which exists to prevent a specific way backtests
lie:

* **Signal at close t, fill at open t+1.** No exception, anywhere. The most
  common source of fake alpha is a rule that decides on today's close and
  transacts at today's close.
* **Fills are checked against the bar that actually happened.** A gap through
  the entry price cancels the trade the same way it would in a live account; a
  gap through a stop fills at the open, not at the stop.
* **Stop before target inside a bar.** When a single daily bar spans both, the
  simulator assumes the loss. Daily data cannot resolve the sequence, and the
  optimistic assumption is worth several points of fake Sharpe.
* **Capacity is enforced.** An order larger than a fixed share of the name's
  20-day ADV is truncated, and impact is charged on what fills — so the search
  cannot discover "alpha" that only exists in illiquid names it could not
  actually buy.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import LabConfig
from .data.prices import Panel
from .genome import Genome
from .strategy import Signals


@dataclass
class Trade:
    symbol: str
    sector: str
    side: int                  # +1 long, -1 short
    entry_idx: int
    exit_idx: int
    entry_date: np.datetime64
    exit_date: np.datetime64
    entry_price: float
    exit_price: float
    shares: float
    initial_stop: float
    final_stop: float          # after trailing/breakeven ratchets
    risk_per_share: float
    pnl: float
    r_multiple: float
    return_pct: float
    hold_days: int
    mae_r: float          # max adverse excursion, in R
    mfe_r: float          # max favourable excursion, in R
    exit_reason: str
    entry_score: float
    entry_rs_rank: float
    entry_adr: float
    entry_weight: float
    costs: float
    borrow_cost: float    # accrued stock-loan fee (shorts only)
    truncated: bool       # capacity-limited fill


@dataclass
class BacktestResult:
    dates: np.ndarray
    equity: np.ndarray
    cash: np.ndarray
    exposure: np.ndarray
    n_positions: np.ndarray
    returns: np.ndarray
    trades: list[Trade] = field(default_factory=list)
    rejected: dict[str, int] = field(default_factory=dict)
    gate_pass_counts: dict[str, int] = field(default_factory=dict)
    initial_equity: float = 100_000.0
    net_exposure: np.ndarray | None = None   # long minus short, as a share of equity
    vol_scale: np.ndarray | None = None      # the risk-management multiplier applied

    def trades_frame(self) -> pd.DataFrame:
        if not self.trades:
            return pd.DataFrame(columns=[f.name for f in Trade.__dataclass_fields__.values()])
        return pd.DataFrame([t.__dict__ for t in self.trades])


class _Position:
    """A position in either direction.

    `side` is +1 or -1 and every price comparison below is written in terms of
    it, so there is exactly one code path rather than a long branch and a short
    branch that drift apart. The three identities that make this work:

        profit per share      =  side * (price - entry)
        stop                  =  entry - side * risk_per_share
        "stop has been hit"   =  side * (price - stop) <= 0

    Under those, a short is a long with side = -1 and nothing else changes.
    """

    __slots__ = ("j", "symbol", "sector", "side", "shares", "entry_price", "entry_idx",
                 "stop", "initial_stop", "risk_per_share", "target", "best", "worst",
                 "entry_score", "entry_rs_rank", "entry_adr", "entry_costs",
                 "entry_weight", "truncated", "breakeven_done", "borrow_accrued")

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def run_backtest(g: Genome, panel: Panel, sig: Signals, sectors: list[str],
                 cfg: LabConfig, rs_rank: np.ndarray | None = None,
                 adr: np.ndarray | None = None,
                 dollar_volume_20d: np.ndarray | None = None) -> BacktestResult:
    n, m = panel.close.shape
    o, h, l, c = panel.open, panel.high, panel.low, panel.close

    eq0 = cfg.initial_equity
    cash = eq0
    equity = np.full(n, np.nan)
    cash_curve = np.full(n, np.nan)
    exposure = np.zeros(n)
    net_exposure = np.zeros(n)
    n_pos_curve = np.zeros(n)

    positions: dict[int, _Position] = {}
    trades: list[Trade] = []
    rejected = {"gap": 0, "no_cash": 0, "capacity": 0, "slots": 0,
                "sector_cap": 0, "bad_stop": 0, "no_price": 0, "short_slots": 0,
                "gross_cap": 0}

    one_way_bps = (cfg.costs.slippage_bps + cfg.costs.spread_bps) / 10_000.0
    comm_bps = cfg.costs.commission_bps / 10_000.0

    max_positions = int(g["pf.max_positions"])
    max_new = int(g["pf.max_new_per_day"])
    max_weight = float(g["pf.max_weight"])
    max_gross = float(g["pf.max_gross_exposure"])
    max_sector = int(g["pf.max_sector_positions"])
    sizing = g["pf.sizing"]
    risk_frac = float(g["pf.risk_pct"]) / 100.0
    target_vol = float(g["pf.target_vol_annual"])
    max_gap = float(g["entry.max_gap_pct"])

    # Risk-managed momentum: scale the whole book by target / realised strategy
    # volatility. Momentum's own vol is far more predictable than its return, so
    # this is the rare overlay that improves risk-adjusted performance without
    # needing to forecast anything about direction.
    vol_scaling = bool(g["pf.vol_scaling"])
    vol_target_pf = float(g["pf.vol_target_portfolio"])
    vol_lookback = int(g["pf.vol_lookback"])
    vol_cap = float(g["pf.vol_scale_cap"])
    daily_ret = np.zeros(n)
    scale_curve = np.ones(n)

    short_on = bool(g["short.enabled"])
    max_shorts = int(g["short.max_positions"]) if short_on else 0
    max_short_gross = float(g["short.max_gross"]) if short_on else 0.0
    borrow_daily = (float(g["short.borrow_bps_annual"]) / 10_000.0 / 252.0) if short_on else 0.0

    # Per-side exit parameters, indexed by side so the loop stays branch-free.
    P = {
        +1: dict(stop_type=g["exit.stop_type"], stop_atr=float(g["exit.stop_atr_mult"]),
                 stop_pct=float(g["exit.stop_pct"]) / 100.0,
                 target_r=float(g["exit.target_r"]),
                 trail_on=bool(g["exit.trail_enabled"]),
                 trail_after_r=float(g["exit.trail_after_r"]),
                 trail_mult=float(g["exit.trail_atr_mult"]),
                 be_after_r=float(g["exit.breakeven_after_r"]),
                 max_hold=int(g["exit.max_hold_days"]),
                 time_stop_days=int(g["exit.time_stop_days"]),
                 time_stop_min_r=float(g["exit.time_stop_min_r"])),
        -1: dict(stop_type="atr", stop_atr=float(g["short.stop_atr_mult"]),
                 stop_pct=0.0, target_r=float(g["short.target_r"]),
                 trail_on=bool(g["short.trail_enabled"]),
                 trail_after_r=1.0,
                 trail_mult=float(g["short.trail_atr_mult"]),
                 be_after_r=0.0,
                 max_hold=int(g["short.max_hold_days"]),
                 time_stop_days=0, time_stop_min_r=0.0),
    }
    regime_exit = bool(g["exit.regime_exit"])
    sma_break_exit = bool(g["exit.exit_on_sma_break"])
    cover_on_regime = bool(g["short.cover_on_regime"]) if short_on else False

    atr = sig.atr
    pending: list[tuple[int, int]] = []   # (symbol index, side) signalled yesterday

    def mark_to_market(t: int) -> float:
        val = 0.0
        for pos in positions.values():
            px = c[t, pos.j]
            if not np.isfinite(px):
                px = pos.entry_price
            val += pos.side * pos.shares * px
        return val

    def gross_value(t: int) -> tuple[float, float]:
        """(gross, short) notional at t."""
        gross = short = 0.0
        for pos in positions.values():
            px = c[t, pos.j]
            if not np.isfinite(px):
                px = pos.entry_price
            v = pos.shares * px
            gross += v
            if pos.side < 0:
                short += v
        return gross, short

    def trim_position(pos: _Position, t: int, raw_price: float, fraction: float) -> float:
        """Reduce a position without ending it, and return the notional shed.

        This is what "rescale the position" means in the risk-managed momentum
        literature. Closing and re-opening instead — the obvious shortcut in an
        entry-and-hold engine — pays a full round trip every time exposure is
        adjusted, and on this strategy that churn cost more than the risk
        management saved (Sharpe 0.086 -> -0.088, trades 570 -> 1169).

        The shed portion is booked as its own trade so the blotter stays exact.
        """
        nonlocal cash
        fraction = min(0.95, max(0.0, fraction))
        shed = pos.shares * fraction
        if shed <= 0:
            return 0.0
        exit_fill = raw_price * (1.0 - pos.side * one_way_bps)
        gross = shed * exit_fill
        cost = gross * comm_bps
        cash += pos.side * gross - cost
        risk = max(pos.risk_per_share, 1e-9)
        entry_share = pos.entry_costs * fraction
        borrow_share = pos.borrow_accrued * fraction
        trades.append(Trade(
            symbol=panel.symbols[pos.j], sector=sectors[pos.j], side=pos.side,
            entry_idx=pos.entry_idx, exit_idx=t,
            entry_date=panel.dates[pos.entry_idx], exit_date=panel.dates[t],
            entry_price=pos.entry_price, exit_price=exit_fill, shares=shed,
            initial_stop=pos.initial_stop, final_stop=pos.stop, risk_per_share=risk,
            pnl=pos.side * shed * (exit_fill - pos.entry_price) - cost - entry_share - borrow_share,
            r_multiple=pos.side * (exit_fill - pos.entry_price) / risk,
            return_pct=pos.side * (exit_fill / pos.entry_price - 1.0) * 100.0,
            hold_days=t - pos.entry_idx,
            mae_r=pos.side * (pos.worst - pos.entry_price) / risk,
            mfe_r=pos.side * (pos.best - pos.entry_price) / risk,
            exit_reason="vol_trim", entry_score=pos.entry_score,
            entry_rs_rank=pos.entry_rs_rank, entry_adr=pos.entry_adr,
            entry_weight=pos.entry_weight * fraction,
            costs=cost + entry_share, borrow_cost=borrow_share,
            truncated=pos.truncated,
        ))
        pos.shares -= shed
        pos.entry_costs -= entry_share
        pos.borrow_accrued -= borrow_share
        return shed * raw_price

    def close_position(pos: _Position, t: int, raw_price: float, reason: str) -> None:
        nonlocal cash
        # Selling a long and covering a short both cross the spread against you.
        exit_fill = raw_price * (1.0 - pos.side * one_way_bps)
        gross = pos.shares * exit_fill
        cost = gross * comm_bps
        cash += pos.side * gross - cost
        risk = max(pos.risk_per_share, 1e-9)
        pnl = pos.side * pos.shares * (exit_fill - pos.entry_price) \
            - cost - pos.entry_costs - pos.borrow_accrued
        trades.append(Trade(
            symbol=panel.symbols[pos.j], sector=sectors[pos.j], side=pos.side,
            entry_idx=pos.entry_idx, exit_idx=t,
            entry_date=panel.dates[pos.entry_idx], exit_date=panel.dates[t],
            entry_price=pos.entry_price, exit_price=exit_fill, shares=pos.shares,
            initial_stop=pos.initial_stop, final_stop=pos.stop, risk_per_share=risk,
            pnl=pnl, r_multiple=pos.side * (exit_fill - pos.entry_price) / risk,
            return_pct=pos.side * (exit_fill / pos.entry_price - 1.0) * 100.0,
            hold_days=t - pos.entry_idx,
            mae_r=pos.side * (pos.worst - pos.entry_price) / risk,
            mfe_r=pos.side * (pos.best - pos.entry_price) / risk,
            exit_reason=reason, entry_score=pos.entry_score,
            entry_rs_rank=pos.entry_rs_rank, entry_adr=pos.entry_adr,
            entry_weight=pos.entry_weight,
            costs=cost + pos.entry_costs, borrow_cost=pos.borrow_accrued,
            truncated=pos.truncated,
        ))

    for t in range(1, n):
        # ---------------- 1. fill yesterday's signals at today's open ------
        # One multiplier for the day, from the strategy's OWN realised volatility
        # over the trailing window. Recorded every session so the curve reflects
        # portfolio state rather than only the days that happened to trade.
        size_scale = 1.0
        if vol_scaling:
            lo_i = max(1, t - vol_lookback)
            hist = daily_ret[lo_i:t]
            hist = hist[np.isfinite(hist)]
            if hist.size >= 30:
                realised = float(hist.std(ddof=1)) * np.sqrt(252.0)
                if realised > 1e-6:
                    size_scale = min(vol_cap, vol_target_pf / realised)
        scale_curve[t] = size_scale

        if pending:
            equity_now = cash + mark_to_market(t - 1)
            gross_now, short_now = gross_value(t - 1)
            new_today = 0
            sector_counts: dict[str, int] = {}
            n_short = 0
            for pos in positions.values():
                sector_counts[pos.sector] = sector_counts.get(pos.sector, 0) + 1
                if pos.side < 0:
                    n_short += 1

            for j, side in pending:
                if new_today >= max_new or len(positions) >= max_positions:
                    rejected["slots"] += 1
                    break
                if j in positions:
                    continue
                if side < 0 and n_short >= max_shorts:
                    rejected["short_slots"] += 1
                    continue
                px_open = o[t, j]
                if not np.isfinite(px_open) or px_open <= 0:
                    rejected["no_price"] += 1
                    continue
                gap = sig.gap_pct[t, j]
                if np.isfinite(gap) and abs(gap) > max_gap:
                    rejected["gap"] += 1
                    continue
                sec = sectors[j]
                if sector_counts.get(sec, 0) >= max_sector:
                    rejected["sector_cap"] += 1
                    continue

                par = P[side]
                fill = px_open * (1.0 + side * one_way_bps)
                a = atr[t - 1, j]
                if par["stop_type"] == "pct" and side > 0:
                    stop = fill * (1.0 - par["stop_pct"])
                elif par["stop_type"] == "ma" and side > 0:
                    ma = sig.stop_ma[t - 1, j]
                    stop = min(ma, fill * 0.98) if np.isfinite(ma) else np.nan
                else:
                    stop = fill - side * par["stop_atr"] * a if np.isfinite(a) else np.nan
                # The stop must sit on the losing side of the entry, whichever
                # way the position points.
                if not np.isfinite(stop) or stop <= 0 or side * (fill - stop) <= 0:
                    rejected["bad_stop"] += 1
                    continue

                risk_ps = side * (fill - stop)
                if sizing == "risk_atr":
                    shares = (equity_now * risk_frac) / risk_ps
                elif sizing == "equal_weight":
                    shares = (equity_now * min(max_weight, max_gross / max_positions)) / fill
                else:
                    vol = (a / fill * np.sqrt(252.0)) if np.isfinite(a) and fill > 0 else np.nan
                    if not np.isfinite(vol) or vol <= 0:
                        rejected["bad_stop"] += 1
                        continue
                    shares = (equity_now * min(max_weight, target_vol / vol)) / fill

                shares *= size_scale
                shares = min(shares, equity_now * max_weight / fill)
                room = max(0.0, equity_now * max_gross - gross_now)
                if side < 0:
                    room = min(room, max(0.0, equity_now * max_short_gross - short_now))
                shares = min(shares, room / fill)
                if shares <= 0:
                    rejected["gross_cap"] += 1
                    continue

                truncated = False
                if dollar_volume_20d is not None:
                    advol = dollar_volume_20d[t - 1, j]
                    if np.isfinite(advol) and advol > 0:
                        cap_notional = advol * cfg.costs.max_adv_participation
                        if shares * fill > cap_notional:
                            shares = cap_notional / fill
                            truncated = True
                            rejected["capacity"] += 1

                notional = shares * fill
                # A long consumes cash; a short raises it but still needs the
                # margin, which the gross-exposure cap above is standing in for.
                if side > 0 and notional > cash:
                    shares = max(0.0, cash / fill)
                    notional = shares * fill
                if shares <= 0 or notional < 1.0:
                    rejected["no_cash"] += 1
                    continue

                participation = 0.0
                if dollar_volume_20d is not None:
                    advol = dollar_volume_20d[t - 1, j]
                    if np.isfinite(advol) and advol > 0:
                        participation = notional / advol
                impact = notional * (cfg.costs.impact_coef_bps / 10_000.0) * participation
                cost = notional * comm_bps + impact
                cash -= side * notional + cost

                hi_t = h[t, j] if np.isfinite(h[t, j]) else fill
                lo_t = l[t, j] if np.isfinite(l[t, j]) else fill
                positions[j] = _Position(
                    j=j, symbol=panel.symbols[j], sector=sec, side=side, shares=shares,
                    entry_price=fill, entry_idx=t, stop=stop, initial_stop=stop,
                    risk_per_share=risk_ps,
                    target=(fill + side * par["target_r"] * risk_ps)
                    if par["target_r"] > 0 else (np.inf if side > 0 else -np.inf),
                    best=hi_t if side > 0 else lo_t,
                    worst=lo_t if side > 0 else hi_t,
                    entry_score=float(sig.score[t - 1, j] if side > 0
                                      else sig.short_score[t - 1, j]),
                    entry_rs_rank=float(rs_rank[t - 1, j]) if rs_rank is not None else np.nan,
                    entry_adr=float(adr[t - 1, j]) if adr is not None else np.nan,
                    entry_costs=cost, entry_weight=notional / max(equity_now, 1e-9),
                    truncated=truncated, breakeven_done=False, borrow_accrued=0.0,
                )
                gross_now += notional
                if side < 0:
                    short_now += notional
                    n_short += 1
                sector_counts[sec] = sector_counts.get(sec, 0) + 1
                new_today += 1
            pending = []

        # ---------------- 2. manage open positions on today's bar ----------
        for j in list(positions):
            pos = positions[j]
            side = pos.side
            par = P[side]
            hi, lo, cl, op = h[t, j], l[t, j], c[t, j], o[t, j]
            if not np.isfinite(cl):
                continue

            # Favourable and adverse extremes swap with direction.
            fav = hi if side > 0 else lo
            adv_ = lo if side > 0 else hi
            if np.isfinite(fav):
                pos.best = max(pos.best, fav) if side > 0 else min(pos.best, fav)
            if np.isfinite(adv_):
                pos.worst = min(pos.worst, adv_) if side > 0 else max(pos.worst, adv_)

            if side < 0 and borrow_daily > 0:
                # Stock loan is paid daily, in cash. Accruing it only at exit
                # would leave the equity curve overstating every open short for
                # its whole life, and a long-held short is exactly where borrow
                # matters most.
                fee = pos.shares * cl * borrow_daily
                pos.borrow_accrued += fee
                cash -= fee

            if t == pos.entry_idx:
                # Entry bar: the stop is live from the fill, but the bar's
                # extremes may predate it. Only honour a close beyond the stop,
                # so no intrabar sequence is invented.
                if side * (cl - pos.stop) <= 0:
                    close_position(pos, t, cl, "stop")
                    del positions[j]
                continue

            exited = False
            if np.isfinite(op) and side * (op - pos.stop) <= 0:
                close_position(pos, t, op, "stop_gap")     # gapped through
                exited = True
            elif np.isfinite(adv_) and side * (adv_ - pos.stop) <= 0:
                close_position(pos, t, pos.stop, "stop")
                exited = True
            elif np.isfinite(pos.target) and abs(pos.target) < np.inf \
                    and np.isfinite(fav) and side * (fav - pos.target) >= 0:
                px = op if (np.isfinite(op) and side * (op - pos.target) >= 0) else pos.target
                close_position(pos, t, px, "target")
                exited = True

            if exited:
                del positions[j]
                continue

            held = t - pos.entry_idx
            r_now = side * (cl - pos.entry_price) / max(pos.risk_per_share, 1e-9)
            reason = None
            if held >= par["max_hold"]:
                reason = "max_hold"
            elif par["time_stop_days"] > 0 and held >= par["time_stop_days"] \
                    and r_now < par["time_stop_min_r"]:
                reason = "time_stop"
            elif side > 0 and sma_break_exit and np.isfinite(sig.exit_ma[t, j]) \
                    and cl < sig.exit_ma[t, j]:
                reason = "sma_break"
            elif side > 0 and regime_exit and not sig.regime_ok[t]:
                reason = "regime"
            elif side < 0 and cover_on_regime and sig.regime_ok[t]:
                # The market turned back up: staying short into it is the way a
                # short book gives back a year of gains in a fortnight.
                reason = "regime_cover"
            if reason:
                close_position(pos, t, cl, reason)
                del positions[j]
                continue

            if par["be_after_r"] > 0 and not pos.breakeven_done and r_now >= par["be_after_r"]:
                pos.stop = pos.entry_price
                pos.breakeven_done = True
            if par["trail_on"] and r_now >= par["trail_after_r"]:
                a = atr[t, j]
                if np.isfinite(a):
                    anchor = pos.best if par["stop_type"] == "chandelier" else cl
                    new_stop = anchor - side * par["trail_mult"] * a
                    # Ratchet only toward profit: up for a long, down for a short.
                    if side * (new_stop - pos.stop) > 0:
                        pos.stop = new_stop

        # ---------------- 2b. de-risk if the book is too big for the vol ---
        # Scaling only NEW entries is not the Barroso & Santa-Clara mechanism:
        # theirs rescales the whole position each period. An entry-and-hold
        # engine cannot resize, but it can shed risk — so when realised vol
        # pushes the target gross below what is actually held, positions are
        # closed (worst open P&L first) until the book fits.
        if vol_scaling and positions:
            eq_t = cash + mark_to_market(t)
            if eq_t > 0:
                gross_t, _sh = gross_value(t)
                allowed = eq_t * max_gross * size_scale
                # A 15% band: adjusting exposure is not free, so the book is
                # only rescaled when it is meaningfully oversized.
                if gross_t > allowed * 1.15 and gross_t > 0:
                    # Trim every position by the same fraction — the portfolio
                    # keeps its shape, which is the point of a risk overlay.
                    fraction = 1.0 - (allowed / gross_t)
                    for pos in list(positions.values()):
                        px = c[t, pos.j]
                        if np.isfinite(px):
                            trim_position(pos, t, px, fraction)
                    # Anything trimmed to dust is closed outright.
                    for pos in list(positions.values()):
                        px = c[t, pos.j]
                        if np.isfinite(px) and pos.shares * px < 1.0:
                            close_position(pos, t, px, "vol_derisk")
                            del positions[pos.j]

        # ---------------- 3. mark the book, then signal for tomorrow -------
        held_value = mark_to_market(t)
        equity[t] = cash + held_value
        prev_eq = equity[t - 1] if np.isfinite(equity[t - 1]) else eq0
        daily_ret[t] = (equity[t] / prev_eq - 1.0) if prev_eq > 0 else 0.0
        gross_t, short_t = gross_value(t)
        exposure[t] = gross_t / equity[t] if equity[t] > 0 else 0.0
        net_exposure[t] = (gross_t - 2 * short_t) / equity[t] if equity[t] > 0 else 0.0
        n_pos_curve[t] = len(positions)

        if equity[t] <= 0:
            equity[t:] = 0.0
            break

        if len(positions) < max_positions:
            cand: list[tuple[float, int, int]] = []
            if sig.regime_ok[t]:
                idx = np.flatnonzero(sig.trigger[t])
                for jj in idx:
                    if jj not in positions:
                        cand.append((float(sig.score[t, jj]), int(jj), +1))
            if short_on:
                idx = np.flatnonzero(sig.short_trigger[t])
                for jj in idx:
                    if jj not in positions:
                        cand.append((float(sig.short_score[t, jj]), int(jj), -1))
            if cand:
                cand.sort(key=lambda x: -x[0])
                pending = [(j, s) for _sc, j, s in cand[: max_new * 3]]

    # Close whatever is still open on the final bar. Their P&L is already in
    # the equity curve via mark-to-market, but without this they never reach
    # the blotter — so hit rate, expectancy and trade count would all be
    # computed on a biased subset that excludes the longest-held positions.
    last = n - 1
    for j in list(positions):
        pos = positions[j]
        px = c[last, pos.j]
        if np.isfinite(px):
            close_position(pos, last, px, "end_of_data")
        del positions[j]

    equity[0] = eq0
    cash_curve[0] = eq0
    equity = pd.Series(equity).ffill().fillna(eq0).to_numpy()
    cash_curve = pd.Series(cash_curve).ffill().fillna(eq0).to_numpy()
    returns = np.zeros(n)
    returns[1:] = equity[1:] / np.where(equity[:-1] > 0, equity[:-1], np.nan) - 1.0
    returns = np.nan_to_num(returns, nan=0.0, posinf=0.0, neginf=0.0)

    res = BacktestResult(
        dates=panel.dates, equity=equity, cash=cash_curve, exposure=exposure,
        n_positions=n_pos_curve, returns=returns, trades=trades,
        rejected=rejected, gate_pass_counts=dict(sig.gate_pass_counts),
        initial_equity=eq0,
    )
    res.net_exposure = net_exposure
    res.vol_scale = scale_curve
    return res
