"""Tier-1 flow estimators, computed from daily OHLCV alone.

Every matrix is (n_days, n_symbols), aligned to the price panel, and every value
at row t uses only information available at the close of day t.

One deliberate departure from the source spec, documented here because it
changes what is being measured:

    The spec defines rho as the AR(1) coefficient of *weekly EMA-smoothed* flow.
    An EMA induces autocorrelation by construction — feed it white noise with a
    10-day half-life and weekly samples still come back with rho about 0.7. That
    is the filter's memory, not the stock's. Every name would score high, the
    cross-sectional ranking would be mostly noise, and the placebo test would
    pass while measuring nothing.

    So the primary estimator is the AR(1) of weekly *summed* raw flow, which has
    no smoothing between the observations being correlated. The spec's smoothed
    variant is computed alongside as `rho_ema` precisely so the two can be
    compared — under the placebo (randomly re-signed volume) `rho` should
    collapse and `rho_ema` should not. That contrast is the diagnostic.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..data.prices import Panel

TRADING_DAYS = 252

# Literature priors, NOT fitted values. The spec is explicit that these are to
# be re-estimated on a training window and then frozen.
Y_IMPACT_PRIOR = 0.75        # square-root law coefficient, reported range 0.5-1.0
EMA_HALFLIFE_DAYS = 10       # spec value for the smoothed forcing function
AR_WINDOW_WEEKS = 26         # spec value for the rho estimation window
FLOW_SUM_DAYS = 20           # spec value for the F numerator (~1 month)
ILLIQ_WINDOW = 21


@dataclass
class FlowSignals:
    """Every Tier-1 quantity, on the panel's daily grid."""

    dates: np.ndarray
    symbols: list[str]
    ret: np.ndarray
    dollar_volume: np.ndarray
    adv: np.ndarray
    sigma: np.ndarray
    flow: np.ndarray             # f_t = sign(r_t) * dollar volume
    phi: np.ndarray              # EMA-smoothed forcing function
    rho: np.ndarray              # inertia coefficient (weekly summed flow)
    rho_ema: np.ndarray          # the spec's smoothed variant, for comparison
    t_half: np.ndarray           # weeks
    illiq: np.ndarray            # Amihud
    q_break_sqrt: np.ndarray     # square-root-law route
    q_break_amihud: np.ndarray   # Amihud route
    q_break_ratio: np.ndarray    # agreement between the two routes
    forcing: np.ndarray          # F = cumulative flow / Q_break(1)
    slippage_gap: np.ndarray     # realised minus flow-implied move
    turnover: np.ndarray         # volume / shares outstanding
    market_cap: np.ndarray       # point-in-time, from filing-aligned share counts
    mom_12_1: np.ndarray         # control: 12-month momentum skipping last month
    strev: np.ndarray            # control: 1-month reversal

    def frame(self, name: str) -> pd.DataFrame:
        return pd.DataFrame(getattr(self, name), index=pd.DatetimeIndex(self.dates),
                            columns=self.symbols)


def _shift(mat: np.ndarray, k: int) -> np.ndarray:
    out = np.full_like(mat, np.nan)
    if k > 0:
        out[k:] = mat[:-k]
    elif k < 0:
        out[:k] = mat[-k:]
    else:
        out[:] = mat
    return out


def _safe_div(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return a / np.where(np.abs(b) > 0, b, np.nan)


def _rolling_ar1(weekly: pd.DataFrame, window: int) -> pd.DataFrame:
    """Rolling AR(1) slope of each column on its own one-period lag.

    Computed from rolling moments rather than a loop of regressions:
        rho = Cov(w_t, w_{t-1}) / Var(w_{t-1})
    which is the OLS slope, and is what "persistence of the forcing function"
    means in the Vayanos-Woolley sense.
    """
    y = weekly
    x = weekly.shift(1)
    n = window
    mx = x.rolling(n, min_periods=n).mean()
    my = y.rolling(n, min_periods=n).mean()
    mxy = (x * y).rolling(n, min_periods=n).mean()
    mxx = (x * x).rolling(n, min_periods=n).mean()
    cov = (mxy - mx * my) * (n / (n - 1))
    var = (mxx - mx * mx) * (n / (n - 1))
    return cov / var.where(var.abs() > 0)


def _weekly_to_daily(weekly: pd.DataFrame, daily_index: pd.DatetimeIndex) -> np.ndarray:
    """Broadcast a weekly statistic onto the daily grid.

    The value for a week is only knowable once that week has closed, so it is
    shifted one period before being forward-filled. Without the shift, the last
    days of a week would carry a statistic computed partly from their own future.
    """
    return (weekly.shift(1)
                  .reindex(daily_index.union(weekly.index))
                  .ffill()
                  .reindex(daily_index)
                  .to_numpy(dtype=np.float64))


def compute_flow_signals(panel: Panel, shares_out: np.ndarray | None = None,
                         y_impact: float = Y_IMPACT_PRIOR,
                         ema_halflife: int = EMA_HALFLIFE_DAYS,
                         ar_window: int = AR_WINDOW_WEEKS,
                         flow_sum_days: int = FLOW_SUM_DAYS) -> FlowSignals:
    idx = pd.DatetimeIndex(panel.dates)
    close = panel.close
    prev = _shift(close, 1)
    ret = _safe_div(close, prev) - 1.0

    dollar_volume = close * panel.volume
    df_dv = pd.DataFrame(dollar_volume, index=idx, columns=panel.symbols)
    df_ret = pd.DataFrame(ret, index=idx, columns=panel.symbols)

    # ---- the forcing function ------------------------------------------
    # sign(r_t) * dollar volume. Crude by construction: it attributes a whole
    # day's volume to the direction of that day's return, so it conflates flow
    # with volatility. That weakness is the reason for the placebo test.
    flow = np.sign(ret) * dollar_volume
    df_flow = pd.DataFrame(flow, index=idx, columns=panel.symbols)
    phi = df_flow.ewm(halflife=ema_halflife, min_periods=ema_halflife).mean()

    # ---- inertia: persistence of the forcing function -------------------
    weekly_flow = df_flow.resample("W-FRI").sum(min_count=3)
    weekly_phi = phi.resample("W-FRI").last()
    rho_w = _rolling_ar1(weekly_flow, ar_window)
    rho_ema_w = _rolling_ar1(weekly_phi, ar_window)

    rho = _weekly_to_daily(rho_w, idx)
    rho_ema = _weekly_to_daily(rho_ema_w, idx)

    # T_half = ln2 / -ln(rho), defined only for a decaying-persistent process.
    # rho <= 0 means no inertia (the concept does not apply); rho >= 1 means an
    # explosive estimate, which is an estimation artefact, not a real memory.
    with np.errstate(divide="ignore", invalid="ignore"):
        t_half = np.where((rho > 0.02) & (rho < 0.995),
                          np.log(2.0) / -np.log(np.clip(rho, 1e-6, 0.995)), np.nan)

    # ---- resistance: what it costs to move the price --------------------
    sigma = df_ret.rolling(ILLIQ_WINDOW, min_periods=10).std().to_numpy()
    adv = df_dv.rolling(ILLIQ_WINDOW, min_periods=10).mean().to_numpy()
    illiq = (df_ret.abs() / df_dv.where(df_dv > 0)).rolling(
        ILLIQ_WINDOW, min_periods=10).mean().to_numpy()

    # Route 1: invert the square-root law. Q to move price k*sigma.
    q_break_sqrt = adv * (1.0 / y_impact) ** 2
    # Route 2: Amihud. ILLIQ has units 1/$, so sigma/ILLIQ is dollars.
    q_break_amihud = _safe_div(sigma, illiq)
    # Their ratio is a data-quality diagnostic: the spec expects agreement
    # within a factor of ~2-3 on liquid names. Systematic disagreement means one
    # of the two routes is mis-specified for this universe.
    q_break_ratio = _safe_div(q_break_sqrt, q_break_amihud)

    # ---- forcing over resistance ---------------------------------------
    flow_sum = df_flow.rolling(flow_sum_days, min_periods=flow_sum_days // 2).sum().to_numpy()
    forcing = _safe_div(flow_sum, q_break_sqrt)

    # ---- the diagnostic residual ---------------------------------------
    # Realised move minus the move the impact law says this flow should have
    # produced. Persistently positive => unobserved flow pushing the same way;
    # persistently negative => elastic capital absorbing it.
    realised = _safe_div(close, _shift(close, flow_sum_days)) - 1.0
    implied = y_impact * np.sign(forcing) * np.sqrt(np.abs(forcing)) * sigma * np.sqrt(flow_sum_days)
    slippage_gap = realised - implied

    # ---- controls -------------------------------------------------------
    mom_12_1 = _safe_div(_shift(close, 21), _shift(close, 252)) - 1.0
    strev = _safe_div(close, _shift(close, 21)) - 1.0

    if shares_out is not None:
        turnover = _safe_div(panel.volume, shares_out)
        market_cap = close * shares_out
    else:
        turnover = np.full_like(close, np.nan)
        market_cap = np.full_like(close, np.nan)

    return FlowSignals(
        dates=panel.dates, symbols=list(panel.symbols), ret=ret,
        dollar_volume=dollar_volume, adv=adv, sigma=sigma,
        flow=flow, phi=phi.to_numpy(), rho=rho, rho_ema=rho_ema, t_half=t_half,
        illiq=illiq, q_break_sqrt=q_break_sqrt, q_break_amihud=q_break_amihud,
        q_break_ratio=q_break_ratio, forcing=forcing, slippage_gap=slippage_gap,
        turnover=turnover, market_cap=market_cap, mom_12_1=mom_12_1, strev=strev,
    )


def placebo_flow_signals(panel: Panel, seed: int = 0, **kwargs) -> FlowSignals:
    """The spec's falsification test 4: rebuild everything on randomly re-signed
    volume.

    Volume magnitudes and all volatility clustering are preserved; only the
    direction is destroyed. Any signal that survives this is a volume/volatility
    effect wearing a flow costume, and the whole thesis fails on it.
    """
    rng = np.random.default_rng(seed)
    fake = Panel(
        dates=panel.dates, symbols=list(panel.symbols), open=panel.open,
        high=panel.high, low=panel.low, close=panel.close, volume=panel.volume,
    )
    sig = compute_flow_signals(fake, **kwargs)
    signs = rng.choice([-1.0, 1.0], size=sig.flow.shape)
    df_flow = pd.DataFrame(np.abs(sig.flow) * signs,
                           index=pd.DatetimeIndex(panel.dates), columns=panel.symbols)

    idx = pd.DatetimeIndex(panel.dates)
    weekly = df_flow.resample("W-FRI").sum(min_count=3)
    sig.flow = df_flow.to_numpy()
    sig.rho = _weekly_to_daily(_rolling_ar1(weekly, AR_WINDOW_WEEKS), idx)
    phi = df_flow.ewm(halflife=EMA_HALFLIFE_DAYS, min_periods=EMA_HALFLIFE_DAYS).mean()
    sig.phi = phi.to_numpy()
    sig.rho_ema = _weekly_to_daily(_rolling_ar1(phi.resample("W-FRI").last(),
                                                AR_WINDOW_WEEKS), idx)
    flow_sum = df_flow.rolling(FLOW_SUM_DAYS, min_periods=FLOW_SUM_DAYS // 2).sum().to_numpy()
    sig.forcing = _safe_div(flow_sum, sig.q_break_sqrt)
    return sig
