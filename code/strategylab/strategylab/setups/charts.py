"""Draw a detected base with its contraction sequence marked.

A face-validity check on `vcp.py`. The features are numbers and numbers can be
computed from noise; this puts the swing points, the pullback depths and the
volume profile on the actual price bars so a human can say whether the detector
is finding the pattern it claims to find.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from .vcp import _pullbacks, _structure, _swings

UP, DOWN = "#1a7f4b", "#c0392b"


def draw_base(panel, setup, out: Path, base_len: int = 40, pre: int = 25,
              post: int = 25, swing_k: int = 2, title_extra: str = "") -> Path:
    """One chart: the base, its swings, the pivot, the breakout and volume."""
    j, t = setup.col, setup.day
    lo = max(0, t - base_len - pre)
    hi = min(panel.close.shape[0], t + post + 1)
    o = panel.open[lo:hi, j]; h = panel.high[lo:hi, j]
    l = panel.low[lo:hi, j]; c = panel.close[lo:hi, j]
    v = panel.volume[lo:hi, j]
    dates = panel.dates[lo:hi]
    x = np.arange(len(c))
    b0 = (t - base_len) - lo          # base start, in local coords
    b1 = t - lo                       # trigger bar

    fig, (ax, av) = plt.subplots(2, 1, figsize=(12, 7), dpi=140,
                                 gridspec_kw={"height_ratios": [3, 1]}, sharex=True)
    ax.axvspan(b0, b1, color="#f0f4f8", zorder=0)
    for i in range(len(c)):
        if not np.isfinite(c[i]):
            continue
        col = UP if c[i] >= o[i] else DOWN
        ax.plot([i, i], [l[i], h[i]], color=col, lw=0.8, zorder=2)
        ax.plot([i - 0.3, i], [o[i], o[i]], color=col, lw=0.8, zorder=2)
        ax.plot([i, i + 0.3], [c[i], c[i]], color=col, lw=0.8, zorder=2)

    bh, bl = h[b0:b1], l[b0:b1]
    sw = _swings(bh, bl, k=swing_k)
    depths = _pullbacks(sw)
    pivot = float(np.nanmax(bh))
    ax.axhline(pivot, color="#333", ls="--", lw=1.0, zorder=3)
    ax.text(len(c) - 1, pivot, f"  pivot {pivot:.2f}", va="center", fontsize=8)

    for idx, kind, val in sw:
        ax.plot(b0 + idx, val, marker="v" if kind == "H" else "^",
                color="#8e44ad" if kind == "H" else "#2980b9", ms=7, zorder=5)

    # Label each high->low contraction with its depth.
    di = 0
    for a_, b_ in zip(sw, sw[1:]):
        if a_[1] == "H" and b_[1] == "L" and di < len(depths):
            xm = b0 + (a_[0] + b_[0]) / 2
            ax.annotate("", xy=(b0 + b_[0], b_[2]), xytext=(b0 + a_[0], a_[2]),
                        arrowprops=dict(arrowstyle="<->", color="#555", lw=1.0))
            ax.text(xm, (a_[2] + b_[2]) / 2, f" {depths[di]:.1%}", fontsize=9,
                    color="#111", fontweight="bold",
                    bbox=dict(fc="white", ec="none", alpha=0.85, pad=1))
            di += 1

    ax.axvline(b1, color="#e67e22", lw=1.6, zorder=4)
    ax.plot(b1, c[b1], marker="*", ms=16, color="#e67e22", zorder=6)
    seq = " → ".join(f"{d:.1%}" for d in depths) if depths else "none"
    ax.set_title(f"{setup.symbol}   base {str(dates[b0])[:10]} → {str(dates[b1])[:10]}"
                 f"   contractions: {seq}{title_extra}", fontsize=11, loc="left")
    ax.set_ylabel("price")
    ax.grid(alpha=0.25, lw=0.5)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)

    third = max(3, base_len // 3)
    v1 = np.nanmean(v[b0:b0 + third]); v2 = np.nanmean(v[b1 - third:b1])
    av.bar(x, v, color=["#9bbfd4" if i < b0 or i >= b1 else "#4a90b8"
                        for i in range(len(v))], width=0.8)
    av.hlines(v1, b0, b0 + third, color="#c0392b", lw=2)
    av.hlines(v2, b1 - third, b1, color="#1a7f4b", lw=2)
    av.text(b0, v1, f" first third {v1/1e6:.1f}M", fontsize=8, va="bottom", color="#c0392b")
    av.text(b1 - third, v2, f" last third {v2/1e6:.1f}M", fontsize=8, va="bottom",
            color="#1a7f4b")
    av.set_ylabel("volume")
    av.grid(alpha=0.25, lw=0.5)
    for s in ("top", "right"):
        av.spines[s].set_visible(False)
    step = max(1, len(c) // 8)
    av.set_xticks(x[::step])
    av.set_xticklabels([str(d)[:10] for d in dates[::step]], fontsize=8, rotation=0)

    out.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
    return out


def _draw_low_ladder(ax, sw, b0, depths):
    """Connect the swing lows, coloured by whether they ascend.

    This is the half of the pattern the first version of the detector missed:
    a tightening ladder whose lows DESCEND is a descending triangle, not a
    volatility contraction. Drawing the line makes the difference impossible to
    miss on a chart, which the depth annotations alone did not.
    """
    lows = [(b0 + i, v) for i, k, v in sw if k == "L"]
    highs = [(b0 + i, v) for i, k, v in sw if k == "H"]
    st = _structure(sw)
    share = st.get("higher_lows_share")
    if len(lows) >= 2:
        col = "#1a7f4b" if (share or 0) >= 1.0 else ("#d68910" if (share or 0) >= 0.5
                                                     else "#c0392b")
        ax.plot([x for x, _ in lows], [v for _, v in lows], color=col, lw=2.0,
                ls="-", marker="^", ms=7, zorder=6, alpha=0.95)
    if len(highs) >= 2:
        ax.plot([x for x, _ in highs], [v for _, v in highs], color="#8e44ad",
                lw=1.1, ls=":", marker="v", ms=6, zorder=5, alpha=0.8)
    return st


def draw_vcp(panel, setup, out: Path, base_len: int = 40, pre: int = 15,
             post: int = 20, swing_k: int = 2, subtitle: str = "") -> Path:
    """One base, with BOTH halves of the pattern drawn: the depth ladder and
    the low structure."""
    j, t = setup.col, setup.day
    lo = max(0, t - base_len - pre)
    hi = min(panel.close.shape[0], t + post + 1)
    o = panel.open[lo:hi, j]; h = panel.high[lo:hi, j]
    l = panel.low[lo:hi, j]; c = panel.close[lo:hi, j]
    v = panel.volume[lo:hi, j]
    dates = panel.dates[lo:hi]
    x = np.arange(len(c))
    b0, b1 = (t - base_len) - lo, t - lo

    fig, (ax, av) = plt.subplots(2, 1, figsize=(12, 7), dpi=140,
                                 gridspec_kw={"height_ratios": [3, 1]}, sharex=True)
    ax.axvspan(b0, b1, color="#f2f6fa", zorder=0)
    for i in range(len(c)):
        if not np.isfinite(c[i]):
            continue
        col = UP if c[i] >= o[i] else DOWN
        ax.plot([i, i], [l[i], h[i]], color=col, lw=0.9, zorder=2)
        ax.plot([i - 0.32, i], [o[i], o[i]], color=col, lw=0.9, zorder=2)
        ax.plot([i, i + 0.32], [c[i], c[i]], color=col, lw=0.9, zorder=2)

    sw = _swings(h[b0:b1], l[b0:b1], k=swing_k)
    depths = _pullbacks(sw)
    pivot = float(np.nanmax(h[b0:b1]))
    ax.axhline(pivot, color="#333", ls="--", lw=1.0, zorder=3)
    ax.text(len(c) - 1, pivot, f"  pivot {pivot:.2f}", va="center", fontsize=8)
    st = _draw_low_ladder(ax, sw, b0, depths)

    di = 0
    for a_, bb in zip(sw, sw[1:]):
        if a_[1] == "H" and bb[1] == "L" and di < len(depths):
            ax.text(b0 + (a_[0] + bb[0]) / 2, (a_[2] + bb[2]) / 2,
                    f"{depths[di]:.0%}", fontsize=9, fontweight="bold", color="#7b241c",
                    ha="center", bbox=dict(fc="white", ec="none", alpha=0.85, pad=1))
            di += 1

    ax.axvline(b1, color="#e67e22", lw=1.6, zorder=4)
    ax.plot(b1, c[b1], marker="*", ms=17, color="#e67e22", zorder=7)
    seq = " → ".join(f"{d:.0%}" for d in depths) if depths else "none"
    hl = st.get("higher_lows_share")
    verdict = ("ALL lows higher" if (hl or 0) >= 1.0
               else f"{hl:.0%} of lows higher" if hl is not None and np.isfinite(hl)
               else "too few lows")
    ax.set_title(f"{setup.symbol}   {str(dates[b0])[:10]} → {str(dates[b1])[:10]}"
                 f"\ncontractions {seq}   |   {verdict}{subtitle}",
                 fontsize=11, loc="left")
    ax.set_ylabel("price")
    ax.grid(alpha=0.25, lw=0.5)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)

    third = max(3, base_len // 3)
    v1 = np.nanmean(v[b0:b0 + third]); v2 = np.nanmean(v[b1 - third:b1])
    av.bar(x, v, color=["#a9c4d6" if i < b0 or i >= b1 else "#3d7ea6"
                        for i in range(len(v))], width=0.8)
    av.hlines(v1, b0, b0 + third, color="#c0392b", lw=2)
    av.hlines(v2, b1 - third, b1, color="#1a7f4b", lw=2)
    av.text(b1 - third, v2, f" dry-up {v2/v1:.2f}x", fontsize=8, va="bottom",
            color="#1a7f4b", fontweight="bold")
    av.set_ylabel("volume"); av.grid(alpha=0.25, lw=0.5)
    for sp in ("top", "right"):
        av.spines[sp].set_visible(False)
    step = max(1, len(c) // 8)
    av.set_xticks(x[::step])
    av.set_xticklabels([str(d)[:10] for d in dates[::step]], fontsize=8)

    out.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
    return out


def draw_grid(panel, setups_meta, out: Path, base_len: int = 40, pre: int = 12,
              post: int = 18, swing_k: int = 2, ncols: int = 3) -> Path:
    """A compact grid of bases — one small panel each, for eyeballing many at once.

    `setups_meta` is a list of (setup, label) pairs. Deliberately stripped back:
    price line, the base shaded, the contraction ladder, the pivot, the trigger.
    """
    n = len(setups_meta)
    nrows = int(np.ceil(n / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(5.0 * ncols, 3.3 * nrows), dpi=140)
    axes = np.atleast_1d(axes).ravel()

    for ax, (s, label) in zip(axes, setups_meta):
        j, t = s.col, s.day
        lo = max(0, t - base_len - pre)
        hi = min(panel.close.shape[0], t + post + 1)
        c = panel.close[lo:hi, j]; h = panel.high[lo:hi, j]; l = panel.low[lo:hi, j]
        x = np.arange(len(c))
        b0, b1 = (t - base_len) - lo, t - lo

        ax.axvspan(b0, b1, color="#eef3f8", zorder=0)
        ax.plot(x, c, color="#1f3b52", lw=1.3, zorder=3)
        ax.fill_between(x, l, h, color="#8fa9bd", alpha=0.28, lw=0, zorder=1)

        sw = _swings(h[b0:b1], l[b0:b1], k=swing_k)
        depths = _pullbacks(sw)
        pivot = float(np.nanmax(h[b0:b1]))
        ax.axhline(pivot, color="#666", ls="--", lw=0.9, zorder=2)

        di = 0
        for a_, bb in zip(sw, sw[1:]):
            if a_[1] == "H" and bb[1] == "L" and di < len(depths):
                ax.annotate("", xy=(b0 + bb[0], bb[2]), xytext=(b0 + a_[0], a_[2]),
                            arrowprops=dict(arrowstyle="<->", color="#c0392b", lw=1.0))
                ax.text(b0 + (a_[0] + bb[0]) / 2, (a_[2] + bb[2]) / 2,
                        f"{depths[di]:.0%}", fontsize=8, fontweight="bold",
                        color="#7b241c", ha="center",
                        bbox=dict(fc="white", ec="none", alpha=0.85, pad=0.8))
                di += 1

        _draw_low_ladder(ax, sw, b0, depths)
        ax.plot(b1, c[b1], marker="*", ms=13, color="#e67e22", zorder=7)
        ax.axvline(b1, color="#e67e22", lw=1.1, zorder=4)
        ax.set_title(label, fontsize=9, loc="left")
        ax.set_xticks([]); ax.tick_params(labelsize=7)
        ax.grid(alpha=0.2, lw=0.4)
        for sp in ("top", "right", "bottom"):
            ax.spines[sp].set_visible(False)

    for ax in axes[n:]:
        ax.axis("off")
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.suptitle("Volatility contraction bases — pullback depths tighten into the pivot",
                 fontsize=12, x=0.01, ha="left")
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig(out)
    plt.close(fig)
    return out


def draw_cup(panel, setup, cup, out: Path, pre: int = 20, post: int = 25) -> Path:
    """Mark the cup's anatomy: left rim, bottom, right rim, handle, pivot.

    Drawing the named parts rather than a generic swing sequence is what makes a
    cup-with-handle checkable by eye. The ladder charts could show that
    something tightened; they could not show whether it was this shape.
    """
    j = setup.col
    lo = max(0, cup.left_idx - pre)
    hi = min(panel.close.shape[0], cup.trigger + post + 1)
    o = panel.open[lo:hi, j]; h = panel.high[lo:hi, j]
    l = panel.low[lo:hi, j]; c = panel.close[lo:hi, j]
    v = panel.volume[lo:hi, j]
    dates = panel.dates[lo:hi]
    x = np.arange(len(c))
    L, B, R, HL, T = (cup.left_idx - lo, cup.bottom_idx - lo,
                      cup.right_idx - lo, cup.handle_low_idx - lo, cup.trigger - lo)

    fig, (ax, av) = plt.subplots(2, 1, figsize=(12.5, 7), dpi=140,
                                 gridspec_kw={"height_ratios": [3, 1]}, sharex=True)
    ax.axvspan(L, R, color="#eef4fa", zorder=0, label="cup")
    ax.axvspan(R, T, color="#fdf3e3", zorder=0, label="handle")
    ax.plot(x, c, color="#1f3b52", lw=1.3, zorder=3)
    ax.fill_between(x, l, h, color="#93a9bb", alpha=0.25, lw=0, zorder=1)

    ax.axhline(cup.pivot, color="#333", ls="--", lw=1.0, zorder=3)
    ax.text(len(c) - 1, cup.pivot, f"  pivot {cup.pivot:.2f}", va="center", fontsize=8)
    rim = float(panel.high[cup.left_idx, j])
    bottom = float(panel.low[cup.bottom_idx, j])
    third = bottom + (rim - bottom) / 3.0
    ax.axhline(third, color="#7f8c8d", ls=":", lw=0.9, zorder=2)
    ax.text(L, third, " lower third (U vs V)", fontsize=7.5, color="#7f8c8d", va="bottom")
    mid = bottom + (rim - bottom) / 2.0
    ax.axhline(mid, color="#2980b9", ls=":", lw=0.9, zorder=2)
    ax.text(R, mid, " cup midpoint", fontsize=7.5, color="#2980b9", va="bottom")

    for idx, val, lab, col in ((L, rim, "left rim", "#8e44ad"),
                               (B, bottom, "bottom", "#c0392b"),
                               (R, cup.pivot, "right rim / pivot", "#8e44ad"),
                               (HL, float(panel.low[cup.handle_low_idx, j]),
                                "handle low", "#e67e22")):
        ax.plot(idx, val, marker="o", ms=8, color=col, zorder=6)
        ax.annotate(lab, (idx, val), textcoords="offset points", xytext=(0, -16),
                    ha="center", fontsize=8, color=col, fontweight="bold")

    ax.annotate("", xy=(B, bottom), xytext=(B, rim),
                arrowprops=dict(arrowstyle="<->", color="#c0392b", lw=1.4))
    ax.text(B + 1, (rim + bottom) / 2, f" cup {cup.cup_depth:.0%}", fontsize=9,
            color="#7b241c", fontweight="bold")
    ax.plot(T, c[T], marker="*", ms=17, color="#e67e22", zorder=7)

    ax.set_title(
        f"{setup.symbol}   cup {cup.cup_depth:.0%} over {cup.cup_bars} bars "
        f"({cup.cup_bars/5:.0f} wks)   |   handle {cup.handle_depth:.0%} over "
        f"{cup.handle_bars} bars at {cup.handle_position:.0%} up the cup   |   "
        f"roundness {cup.round_share:.0%}, handle vol {cup.handle_volume_ratio:.2f}x, "
        f"prior advance {cup.prior_advance:+.0%}", fontsize=10, loc="left")
    ax.set_ylabel("price"); ax.grid(alpha=0.22, lw=0.5)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)

    av.bar(x, v, color=["#a9c4d6" if i < L or i >= T else
                        ("#e0b070" if i >= R else "#4a90b8") for i in range(len(v))],
           width=0.85)
    av.set_ylabel("volume"); av.grid(alpha=0.22, lw=0.5)
    for s in ("top", "right"):
        av.spines[s].set_visible(False)
    step = max(1, len(c) // 9)
    av.set_xticks(x[::step])
    av.set_xticklabels([str(d)[:10] for d in dates[::step]], fontsize=8)

    out.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout(); fig.savefig(out); plt.close(fig)
    return out
