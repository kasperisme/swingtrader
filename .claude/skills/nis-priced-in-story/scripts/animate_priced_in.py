#!/usr/bin/env python3
"""
animate_priced_in.py — the priced-in story as a vertical reel, beat by beat.

Renders the five-beat spine (SKILL.md) as SIX silent 1080×1920 scenes plus the
narration line that belongs to each, so `build_priced_in_reel.py` can voice them
and stretch each scene to its own sentence. Scene-level sync is the point: a
single long clip stretched to one long voiceover drifts, and the beat where the
price stops believing something is exactly the beat that must land on the word.

    cd code/analytics
    .venv/bin/python ../../.claude/skills/nis-priced-in-story/scripts/animate_priced_in.py --ticker ONON

Reads   output/ads/<date>-priced-in-<ticker>/story.json   (or --story <path>)
Writes  output/setups/priced-in/<TICKER>/scenes/scene_*.mp4
        output/setups/priced-in/<TICKER>/story_silent.mp4   (the whole thing, no audio)
        output/setups/priced-in/<TICKER>/vo.json            (per-scene narration)

Composition obeys the cross-platform safe band — nothing load-bearing above
y=220px or below y=1420px, where the platform's own UI sits. Captions are static
within a scene (an animated caption reads as "made by a brand") and carry the
sound-off read, so they never merely repeat the voiceover.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt                      # noqa: E402
import matplotlib.patheffects as pe                  # noqa: E402
from matplotlib.patches import FancyBboxPatch, Rectangle  # noqa: E402

BG = "#0A0E1A"; INK = "#F5F7FF"; MUT = "#9AA3BC"; MUT2 = "#6B7488"; GRID = "#1C2740"
PANEL = "#111A2C"; AMBER = "#F5A623"; POS = "#3DD68C"; NEG = "#FF6B6B"
W, H, FPS = 1080, 1920, 30

# The safe band, in figure fraction: platform UI owns 220px at the top and 500px
# at the bottom of a 1920px canvas.
TOP = 1 - 220 / H          # 0.885
BOT = 500 / H              # 0.260


def _analytics() -> pathlib.Path:
    for p in pathlib.Path(__file__).resolve().parents:
        if (p / "code" / "analytics").exists():
            return p / "code" / "analytics"
    return pathlib.Path.cwd()


ANALYTICS = _analytics()


def ease(p: float) -> float:
    return 1 - (1 - min(max(p, 0.0), 1.0)) ** 3


def seg(p: float, a: float, b: float) -> float:
    """Progress of a sub-animation running from a..b of the scene's own clock."""
    if b <= a:
        return 1.0
    return min(max((p - a) / (b - a), 0.0), 1.0)


def short_name(name: str) -> str:
    return re.sub(r",?\s+(Inc|Corp|Corporation|Company|Co|Holdings?|Ltd|plc|Group|AG|SA|NV)\.?$",
                  "", (name or "").strip(), flags=re.I).strip() or name


def trim(s: str, n: int) -> str:
    s = re.sub(r"\s+", " ", str(s)).strip().rstrip(".")
    return s if len(s) <= n else s[: n - 1].rsplit(" ", 1)[0] + "…"


_DANGLING = {"for", "of", "to", "and", "with", "the", "a", "an", "in", "on", "by",
             "from", "that", "which", "at", "as", "into", "over", "than", "its"}


def clause(s: str, n: int) -> str:
    """Cut to a COMPLETE thought that fits, not to a character count.

    The reconstruction writes long qualified sentences ("…which would be worth
    roughly 50-60% above the current price based on the median analyst target of
    $43"). Truncated at a fixed width they end in "worth roughly…", which reads as
    a broken render rather than a considered line. Cutting at the last clause
    boundary that fits keeps each row sayable and finished; the qualification
    lives in the caption and the voiceover, where there is room for it."""
    s = re.sub(r"\s+", " ", str(s)).strip().rstrip(".")
    if len(s) <= n:
        return s
    # Search a little PAST the budget: a separator that begins at exactly the
    # limit ("…required rate| and tariffs…") is the cut we want, and it is
    # invisible to a search over a window that stops at the limit.
    head = s[: n + 10]
    # comma boundaries first (they end a thought cleanly), then conjunctions
    for sep in (" — ", ", which ", ", and ", ", ", " and ", " while ", " with "):
        i = head.rfind(sep)
        if n * 0.45 < i <= n:
            cand = head[:i].rstrip(" ,—")
            # "…projection for Blackwell| and Rubin architectures" cuts at a real
            # separator and still leaves a sentence hanging on a preposition.
            # A cut that ends on a function word is worse than a shorter one.
            if cand.rsplit(" ", 1)[-1].lower() not in _DANGLING:
                return cand
    return trim(s, n)


# ---------------------------------------------------------------------------
# stage
# ---------------------------------------------------------------------------

def _fig():
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    return fig, ax


def _grid(ax):
    for i in range(1, 9):
        ax.axvline(i / 9, color=GRID, lw=0.8, alpha=0.35)
    for i in range(1, 16):
        ax.axhline(i / 16, color=GRID, lw=0.8, alpha=0.35)


def _brand(ax, S, alpha=1.0):
    """Mark + ticker chip, inside the safe band. Present the whole way through:
    an organic reel earns its follow from repetition, not from an end card."""
    ax.add_patch(FancyBboxPatch((0.075, TOP - 0.018), 0.062, 0.030,
                                boxstyle="round,pad=0.006", fc=AMBER, ec="none",
                                mutation_aspect=0.55, alpha=alpha))
    ax.text(0.106, TOP - 0.004, "NIS", color="#0A0E1A", fontsize=21, fontweight="bold",
            ha="center", va="center", alpha=alpha)
    ax.text(0.155, TOP - 0.004, "newsimpactscreener.com", color=INK, fontsize=23,
            fontweight="bold", va="center", alpha=alpha)
    ax.text(0.925, TOP - 0.004, f"${S['ticker']}", color=MUT, fontsize=23,
            family="monospace", ha="right", va="center", alpha=alpha)


def _caption(ax, text, alpha=1.0, y=BOT + 0.035, size=37):
    """The sound-off read: white, heavy, black-stroked, no pill. Static within a
    scene, and never a transcript of the voiceover — it carries the claim while
    the narration carries the argument."""
    lines = textwrap.wrap(text, width=30)[:3]
    for i, ln in enumerate(lines):
        ax.text(0.5, y + (len(lines) - 1 - i) * 0.030, ln, color="#FFFFFF", fontsize=size,
                fontweight="bold", ha="center", va="center", alpha=alpha,
                path_effects=[pe.withStroke(linewidth=8, foreground="#000000")])


def _kicker(ax, text, alpha=1.0, y=TOP - 0.065):
    ax.text(0.075, y, text.upper(), color=AMBER, fontsize=24, family="monospace",
            fontweight="bold", va="center", alpha=alpha)


# ---------------------------------------------------------------------------
# the beats
# ---------------------------------------------------------------------------

def scene_number(ax, S, p):
    """BEAT 1 — the number. A price counting up, and the count of models it
    disagrees with. Nothing interpreted yet; this beat only has to be checkable."""
    _grid(ax); _brand(ax, S)
    _kicker(ax, f"{short_name(S['company'])} · {S['as_of_label']}")

    price = S["price"]
    shown = price * ease(seg(p, 0.0, 0.45))
    ax.text(0.5, 0.66, f"${shown:,.2f}", color=INK, fontsize=132, fontweight="bold",
            ha="center", va="center")
    ax.text(0.5, 0.585, "the share price", color=MUT, fontsize=30, ha="center", va="center")

    a = ease(seg(p, 0.5, 0.75))
    if a > 0:
        ax.text(0.5, 0.47, f"{S['n_targets']} published analyst targets",
                color=MUT, fontsize=34, ha="center", va="center", alpha=a)
        agree = S["n_endorsed"]
        line = "it agrees with none of them" if agree == 0 else f"it agrees with {agree} of them"
        ax.text(0.5, 0.405, line, color=AMBER, fontsize=44, fontweight="bold",
                ha="center", va="center", alpha=a)
    _caption(ax, S["caps"]["number"], alpha=ease(seg(p, 0.25, 0.45)))


def _stake_card(ax, y, h, S, side, p, t0, t1):
    """One side of the trade, as the published models frame it.

    The card is deliberately conditional and deliberately attributed: the label
    is what you would BE (a buyer, a seller) **if** you believe the named
    assumption, and the number beside it is a published third-party target, not
    a view of ours. That is the difference between an actionable frame and a
    recommendation, and it is the only version of this beat that can honestly
    sit on top of a reconstruction that forecasts nothing."""
    a = ease(seg(p, t0, t1))
    if a <= 0:
        return
    st = S["stakes"][side]
    col = POS if side == "buy" else NEG
    ax.add_patch(FancyBboxPatch((0.075, y - h), 0.85, h, boxstyle="round,pad=0.004",
                                fc=PANEL, ec=GRID, lw=2, mutation_aspect=0.35, alpha=a))
    ax.add_patch(Rectangle((0.075, y - h), 0.009, h, color=col, alpha=a))

    ax.text(0.115, y - 0.038, st["label"], color=col, fontsize=44, fontweight="bold",
            va="center", alpha=a)
    ax.text(0.925, y - 0.038, st["move"], color=col, fontsize=40, fontweight="bold",
            family="monospace", ha="right", va="center", alpha=a)
    ax.text(0.115, y - 0.082, "if you believe", color=MUT2, fontsize=25, va="center", alpha=a)
    # two lines, hard: a third runs into the basis line below it, and a BUY/SELL
    # card that needs three lines of reading is not doing its job anyway
    for j, ln in enumerate(textwrap.wrap(st["condition"], width=38)[:2]):
        ax.text(0.115, y - 0.118 - j * 0.032, ln, color=INK, fontsize=29, va="center", alpha=a)
    ax.text(0.115, y - h + 0.030, st["basis"], color=MUT, fontsize=24,
            family="monospace", va="center", alpha=a)


def scene_stakes(ax, S, p):
    """BEAT 1c — the decision, up front.

    Most viewers will not stay for the full ledger, so the actionable frame goes
    early rather than at the end: which side of the published spread you are on
    follows from one thing you either believe or don't. Both cases come from the
    same distribution — the upside target and the lowest published model — so
    nothing here is a call, only the two sides other people have already put in
    writing."""
    _grid(ax); _brand(ax, S)
    _kicker(ax, "which side are you on")
    _stake_card(ax, 0.790, 0.200, S, "buy", p, 0.04, 0.32)
    _stake_card(ax, 0.560, 0.200, S, "sell", p, 0.40, 0.68)
    _caption(ax, S["caps"]["stakes"], alpha=ease(seg(p, 0.15, 0.32)))


def scene_rail(ax, S, p):
    """BEAT 1b — the distribution. Three positions are drawn because three are
    known (low, median, high); the count lives in the label. Drawing N evenly
    spaced ticks would invent a distribution the stored row does not contain."""
    _grid(ax); _brand(ax, S)
    _kicker(ax, f"{S['n_targets']} published models")

    lo, hi, med, price = S["low"], S["high"], S["median"], S["price"]
    span = max(hi - lo, 1e-9)
    L, R, y = 0.11, 0.89, 0.60

    def px(v):
        return L + max(0.0, min(1.0, (v - lo) / span)) * (R - L)

    w = ease(seg(p, 0.0, 0.35))
    ax.add_patch(FancyBboxPatch((L, y - 0.007), (R - L) * w, 0.014,
                                boxstyle="round,pad=0.002", fc=GRID, ec="none"))
    if w > 0.98:
        for v, col, lw in ((lo, MUT2, 3), (hi, MUT2, 3)):
            ax.plot([px(v), px(v)], [y - 0.020, y + 0.020], color=col, lw=lw)
        # below the price chip, not beside it: the price sits on the low end in
        # most of these stories, which is exactly where the low label lives
        ax.text(L, y - 0.118, f"${lo:,.0f}", color=MUT, fontsize=26, family="monospace", va="center")
        ax.text(R, y - 0.118, f"${hi:,.0f}", color=MUT, fontsize=26, family="monospace",
                ha="right", va="center")

    m = ease(seg(p, 0.35, 0.55))
    if m > 0:
        ax.plot([px(med), px(med)], [y - 0.026, y + 0.026], color=INK, lw=4, alpha=m)
        ax.text(px(med), y + 0.052, f"median ${med:,.0f}", color=INK, fontsize=28,
                family="monospace", ha="center", va="center", alpha=m)

    d = seg(p, 0.55, 0.82)
    if d > 0:
        # the price marker travels in from the high end and settles where it sits
        cur = px(hi) + (px(price) - px(hi)) * ease(d)
        ax.plot([cur], [y], marker="o", markersize=26, color=AMBER, zorder=5)
        chip = ease(seg(p, 0.78, 0.92))
        if chip > 0:
            cx = min(max(cur, L + 0.06), R - 0.06)
            ax.add_patch(FancyBboxPatch((cx - 0.085, y - 0.088), 0.17, 0.042,
                                        boxstyle="round,pad=0.006", fc=AMBER, ec="none",
                                        mutation_aspect=0.5, alpha=chip))
            ax.text(cx, y - 0.067, f"${price:,.2f}", color="#0A0E1A", fontsize=32,
                    fontweight="bold", ha="center", va="center", alpha=chip)

    g = ease(seg(p, 0.86, 1.0))
    if g > 0:
        ax.text(0.5, 0.44, S["gap_line"], color=AMBER, fontsize=42, fontweight="bold",
                ha="center", va="center", alpha=g)
    _caption(ax, S["caps"]["rail"], alpha=ease(seg(p, 0.15, 0.32)))


ROW_WRAP = 32          # characters per line at 30pt in the 0.155..0.94 column
LINE_H = 0.0335        # figure fraction per wrapped line
ROW_PAD = 0.042        # breathing room under each row


def row_lines(t: str) -> list[str]:
    return textwrap.wrap(t, width=ROW_WRAP)


def row_height(t: str) -> float:
    return len(row_lines(t)) * LINE_H + ROW_PAD


def _rows(ax, items, p, positive, start=0.10, end=0.80, top=0.735):
    """Ledger rows arriving one at a time, each on its own beat.

    Laid out on a cursor rather than a fixed pitch, so a four-line assumption and
    a one-line one both sit correctly and NOTHING is truncated. Truncating here
    would defeat the point of the format: the viewer is being handed the whole
    reading, and a row ending in "…" is the one thing that tells them otherwise."""
    n = max(len(items), 1)
    yy = top
    for i, t in enumerate(items):
        a = ease(seg(p, start + (end - start) * i / n, start + (end - start) * (i + 0.75) / n))
        lines = row_lines(t)
        if a > 0:
            col = POS if positive else AMBER
            ax.add_patch(FancyBboxPatch((0.085, yy - 0.018), 0.038, 0.036,
                                        boxstyle="round,pad=0.004", fc=col, ec="none",
                                        mutation_aspect=1.0, alpha=a))
            ax.text(0.104, yy, "✓" if positive else "✕", color="#0A0E1A", fontsize=26,
                    fontweight="bold", ha="center", va="center", alpha=a)
            for j, ln in enumerate(lines):
                ax.text(0.155, yy + 0.014 - j * LINE_H, ln, color=INK, fontsize=30,
                        va="center", alpha=a)
        yy -= len(lines) * LINE_H + ROW_PAD


def make_ledger_scene(rows, positive, part, parts, caption):
    """One page of the ledger.

    The whole ledger is shown — every assumption the price pays for and every one
    it refuses — because this is an organic post, not an ad. A reel that withholds
    the interesting half to sell a click is the kind of thing people scroll past
    twice and then mute; a reel that hands over the entire reading is the kind
    people save and send to someone. So a long list becomes several scenes rather
    than a truncated one, and the counter says how far through it you are."""
    label = "It pays for" if positive else "It declines to pay for"
    kicker = ("what the price already believes" if positive
              else "what it refuses to pay for")

    def draw(ax, S, p):
        _grid(ax); _brand(ax, S)
        _kicker(ax, kicker)
        head = label if part == 1 else f"{label} (cont.)"
        ax.text(0.075, 0.795, head, color=MUT, fontsize=36, va="center")
        if parts > 1:
            ax.text(0.925, 0.795, f"{part}/{parts}", color=MUT2, fontsize=30,
                    family="monospace", ha="right", va="center")
        _rows(ax, rows, p, positive=positive)
        _caption(ax, caption, alpha=ease(seg(p, 0.1, 0.25)))

    return draw


def scene_crux(ax, S, p):
    """BEAT 4 — the open loop. A question that will actually resolve, and an
    honest word about whether anything wired can settle it."""
    _grid(ax); _brand(ax, S)
    _kicker(ax, "the question that settles it")
    # Fit the WHOLE question by stepping the type down, never by cutting it: the
    # crux is the one line in the reel that has to survive intact, and a
    # half-question ("…pace to justify the") is worse than a smaller one.
    # (width, size, line-height) — first rung whose block fits the column.
    for width, size, lh in ((22, 48, 0.068), (26, 42, 0.058),
                            (30, 36, 0.050), (34, 31, 0.044), (38, 27, 0.039)):
        lines = textwrap.wrap(S["crux_short"], width=width)
        if len(lines) * lh <= 0.40:
            break
    top = 0.72
    step = max(0.06, 0.85 / max(len(lines), 1))
    for i, ln in enumerate(lines):
        a = ease(seg(p, 0.05 + step * i, 0.22 + step * i))
        ax.text(0.075, top - i * lh, ln, color=INK, fontsize=size, fontweight="bold",
                va="center", alpha=a)
    base = top - (len(lines) - 1) * lh
    u = ease(seg(p, 0.6, 0.85))
    if u > 0:
        ax.add_patch(Rectangle((0.075, base - 0.045), 0.5 * u, 0.008, color=AMBER))
    t = ease(seg(p, 0.72, 0.92))
    if t > 0:
        ax.text(0.075, base - 0.10, S["crux_testable"], color=MUT, fontsize=30,
                va="center", alpha=t)
    _caption(ax, S["caps"]["crux"], alpha=ease(seg(p, 0.15, 0.3)))


def scene_outro(ax, S, p):
    """BEAT 5 — where to read it. One line about the machine, at the end, once
    the story has earned it."""
    _grid(ax); _brand(ax, S)
    a = ease(seg(p, 0.0, 0.3))
    ax.text(0.075, 0.70, "Every price is a list", color=INK, fontsize=58,
            fontweight="bold", va="center", alpha=a)
    ax.text(0.075, 0.635, "of assumptions.", color=INK, fontsize=58,
            fontweight="bold", va="center", alpha=a)
    b = ease(seg(p, 0.3, 0.6))
    ax.text(0.075, 0.535, f"We write down what {S['coverage']}", color=AMBER,
            fontsize=34, va="center", alpha=b)
    ax.text(0.075, 0.485, "assume. Every night.", color=AMBER, fontsize=34,
            va="center", alpha=b)
    c = ease(seg(p, 0.55, 0.85))
    ax.add_patch(FancyBboxPatch((0.075, 0.375), 0.50, 0.055, boxstyle="round,pad=0.008",
                                fc=AMBER, ec="none", mutation_aspect=0.5, alpha=c))
    ax.text(0.325, 0.4025, f"${S['ticker']} · free to read", color="#0A0E1A", fontsize=30,
            fontweight="bold", ha="center", va="center", alpha=c)
    _caption(ax, S["caps"]["outro"], alpha=ease(seg(p, 0.2, 0.4)))


# The ledger column runs from y=0.70 down to the caption at ~0.34, so a scene can
# carry about that much of rows. Chunking on measured height rather than a row
# count is what lets one four-line assumption and three one-liners both fit.
LEDGER_BUDGET = 0.42
MAX_ROWS_PER_SCENE = 3


def _chunks(items, budget=LEDGER_BUDGET, max_rows=MAX_ROWS_PER_SCENE):
    out, cur, used = [], [], 0.0
    for t in items:
        h = row_height(t)
        if cur and (used + h > budget or len(cur) >= max_rows):
            out.append(cur); cur, used = [], 0.0
        cur.append(t); used += h
    if cur:
        out.append(cur)
    return out or [[]]


def vo_seconds(text: str) -> float:
    """How long the narration will run, so the silent scene is cut to roughly that
    length before stretching. ElevenLabs reads at ~160 words a minute; a scene
    built at its own VO length only needs a nudge to sync, where one built to a
    fixed duration gets stretched to a crawl or clipped."""
    return max(3.0, len(str(text).split()) / 2.65 + 0.9)


def build_scenes(S: dict) -> list[tuple[str, object, float, str, str]]:
    """(name, draw, seconds, voiceover, caption) — the reel, sized to the story.

    Length follows the reconstruction rather than a target runtime: a company
    whose price rests on five assumptions gets five on screen. Instagram will
    carry a 60–90s reel perfectly well when every second of it is content."""
    scenes: list[tuple[str, object, float, str, str]] = [
        ("number", scene_number, vo_seconds(S["vo_number"]), S["vo_number"], S["caps"]["number"]),
        # The actionable frame goes SECOND, before the distribution is even
        # explained: most viewers leave before the ledger, and the one who leaves
        # at fifteen seconds should still have got the decision.
        ("stakes", scene_stakes, vo_seconds(S["stakes"]["vo"]),
         S["stakes"]["vo"], S["caps"]["stakes"]),
        ("rail", scene_rail, vo_seconds(S["vo_rail"]), S["vo_rail"], S["caps"]["rail"]),
    ]

    pay_chunks = _chunks(S["pays"])
    for i, ch in enumerate(pay_chunks, 1):
        cap = (S["caps"]["believes"] if i == 1 else f"…and {len(ch)} more it already pays for.")
        lead = "So what does that price actually believe? " if i == 1 else "It also pays for: "
        vo = lead + " ".join(_speakable(t, lower_first=(i > 1 and j == 0))
                             for j, t in enumerate(ch))
        scenes.append((f"believes{i}", make_ledger_scene(ch, True, i, len(pay_chunks), cap),
                       vo_seconds(vo), vo, cap))

    ref_chunks = _chunks(S["refuses"])
    for i, ch in enumerate(ref_chunks, 1):
        cap = (S["caps"]["refuses"] if i == 1 else f"…and {len(ch)} more it will not fund.")
        lead = ("Here is what it refuses to pay for — the interesting half. " if i == 1
                else "It also refuses to pay for: ")
        vo = lead + " ".join(_speakable(t, lower_first=(i > 1 and j == 0))
                             for j, t in enumerate(ch))
        scenes.append((f"refuses{i}", make_ledger_scene(ch, False, i, len(ref_chunks), cap),
                       vo_seconds(vo), vo, cap))

    scenes.append(("crux", scene_crux, vo_seconds(S["vo_crux"]), S["vo_crux"], S["caps"]["crux"]))
    scenes.append(("outro", scene_outro, vo_seconds(S["vo_outro"]), S["vo_outro"], S["caps"]["outro"]))
    return scenes


# ---------------------------------------------------------------------------
# the spec the scenes draw from
# ---------------------------------------------------------------------------

_BEAR_RE = re.compile(r"bear[- ]case|collapse|worsen|deteriorat|permanent|erode|crush", re.I)


def build_stakes(story: dict, pays: list[str], refuses: list[str],
                 bull_if: str | None, bear_if: str | None) -> dict:
    """The two sides of the published spread, and what you have to believe to be
    on each — derived, never invented.

    The upside leg points at the median model when the price sits below it, and
    at the highest model when the price has already run past the median; the
    downside leg points at the lowest published model. Both are arithmetic on
    other people's targets, so the claim on screen is "N analysts have written
    this down", not "we think this". Where the spread does not actually contain a
    side — a price under every published model has no published downside — the
    card says so instead of manufacturing one.

    The CONDITIONS come from the reconstruction: the bull condition is the top
    thing the price refuses to pay for (by definition, the unpriced upside), and
    the bear condition is the reconstruction's own bear-case line where it has
    one. Override either with --bull-if / --bear-if when the derived phrasing is
    clumsy; the numbers are never overridable."""
    sp = story["spread"]
    price = float(story["price_at_as_of"])
    lo, med, hi = float(sp["low"]), float(sp["median"]), float(sp["high"])
    n = sp["n_targets"]

    # --- the buy side: the nearest published target ABOVE the price
    up_target, up_label = (med, f"median of {n} models") if med > price else (
        (hi, f"highest of {n} models") if hi > price else (None, None))
    if up_target:
        up_move = f"+{(up_target / price - 1) * 100:.0f}%"
        up_basis = f"{up_label} · ${up_target:,.0f}"
    else:
        up_move, up_basis = "—", f"no published model above ${price:,.2f}"

    # --- the sell side: the lowest published target, when it is below the price
    if lo < price:
        dn_move = f"−{(1 - lo / price) * 100:.0f}%"
        dn_basis = f"lowest of {n} models · ${lo:,.0f}"
    else:
        dn_move, dn_basis = "—", f"no published model below ${price:,.2f}"

    bull = bull_if or (clause(refuses[0], 74) if refuses else
                       "the price is too pessimistic about this business")
    if bear_if:
        bear = bear_if
    else:
        bear_row = next((r for r in refuses if _BEAR_RE.search(r)), None)
        # The fallback must not be a trimmed pays_for row: those are long and
        # qualified, and "…to a 19.0% compound… — and no better" reads as broken.
        bear = (clause(bear_row, 74) if bear_row else
                "what the price already assumes — and nothing better")

    return {
        "buy": {"label": "BUY", "condition": bull, "move": up_move, "basis": up_basis},
        "sell": {"label": "SELL", "condition": bear, "move": dn_move, "basis": dn_basis},
        # Spoken numbers are built from the figures, not from the display strings:
        # "median of 17 models · $43" read aloud is a mess of punctuation.
        "vo": (
            f"So, the decision, up front. If you believe {_speakable(bull, True)[:-1]}, "
            + (f"you are a buyer: {up_label} sits at {up_target:,.0f} dollars, "
               f"{(up_target / price - 1) * 100:.0f} percent above today. "
               if up_target else "you are a buyer, though no published model sits above the price. ")
            + f"If instead you believe {_speakable(bear, True)[:-1]}, "
            + (f"you are a seller: the lowest of the {n} is {lo:,.0f} dollars, "
               f"{(1 - lo / price) * 100:.0f} percent below."
               if lo < price else
               f"you are on your own — there is no published model below the price at all. "
               f"All {n} of them sit above it.")),
    }


def build_scene_spec(story: dict, max_rows: int | None) -> dict:
    sp = story["spread"]
    company = short_name(story["company"])
    gap = sp["median_gap_pct"]
    price = story["price_at_as_of"]

    # Everything the reconstruction found, unless a cap is passed deliberately.
    pays = [clause(s, 160) for s in (story["pays_for"][:max_rows] if max_rows
                                     else story["pays_for"])]
    refuses = [clause(s, 160) for s in (story["declines"][:max_rows] if max_rows
                                        else story["declines"])]

    crux = re.sub(r"\s+", " ", story["crux"]).strip()
    # The crux carries TWO things: the question, and a clause about whether any
    # wired series can settle it. Split them — the question goes on screen at a
    # readable size, the measurability note sits under it as its own line.
    head, tail = crux, ""
    m = re.search(r"^(.*?)(?:,\s+(?:and|but|which)\s+(?:the\s+)?"
                  r"(?:wired|available|only|this)\b|\s+—\s+|(?<=[?.])\s+)(.*)$", crux)
    if m and m.group(1):
        head, tail = m.group(1).strip(), m.group(2).strip()
    head = head.rstrip(" ,")
    if head and not head.endswith(("?", ".")):
        head += "?" if re.match(r"^(does|do|can|will|whether|is|are|has|have)\b", head, re.I) else "."

    # Read the measurability clause NEGATION-AWARE. "cannot measure hyperscaler
    # capital commitments" contains "measur" and means the exact opposite of
    # measurable; a plain keyword match prints a claim the reconstruction denies.
    note = tail or crux
    if re.search(r"\b(cannot|can't|can not|no|nothing|not)\b[^.]{0,60}"
                 r"(settle|test|measur|answer)", note, re.I):
        testable = "Nothing wired can settle it — which is worth saying."
    elif re.search(r"can be tested|testable|can be measured|measurable|measure[sd]? (?:via|with|using)",
                   note, re.I):
        testable = "Measurable with the wired data."
    else:
        testable = "Nothing wired can settle it — which is worth saying."

    as_of = dt.date.fromisoformat(story["as_of"])
    return {
        "ticker": story["ticker"],
        "company": story["company"],
        "as_of_label": as_of.strftime("%-d %b %Y"),
        "price": price,
        "low": sp["low"], "median": sp["median"], "high": sp["high"],
        "n_targets": sp["n_targets"], "n_endorsed": sp["n_endorsed"],
        "gap_line": f"{abs(gap):.0f}% {'below' if gap < 0 else 'above'} the median model",
        "pays": pays,
        "refuses": refuses,
        "crux_short": head.strip(),
        "crux_testable": testable,
        "coverage": f"{story['coverage_published_now']} US companies",
        # The sound-off captions. Each says something the narration does not.
        # Sound-off captions, keyed by beat so inserting a beat cannot silently
        # shift every caption onto the wrong scene.
        "caps": {
            "number": f"{sp['n_targets']} analysts priced {company}. The market ignored them.",
            "stakes": "Two published cases. Pick the one you believe.",
            "rail": f"The price sits {abs(gap):.0f}% {'below' if gap < 0 else 'above'} the median target.",
            "believes": f"All {len(pays)} things it already believes.",
            "refuses": f"All {len(refuses)} things it will not fund.",
            "crux": "One question decides it.",
            "outro": "The whole reading, free. Link in bio.",
        },
        "vo_number": (
            f"{sp['n_targets']} analysts publish a price target on {company}. "
            + ("The share price agrees with none of them."
               if sp["n_endorsed"] == 0 else
               f"The share price agrees with {sp['n_endorsed']} of them.")),
        "vo_rail": (
            f"They range from {sp['low']:,.0f} dollars to {sp['high']:,.0f} dollars. The median "
            f"is {sp['median']:,.0f}. The price is {price:,.2f} — {abs(gap):.0f} percent "
            f"{'below' if gap < 0 else 'above'} that median."),
        "vo_crux": "One question decides it. " + _speakable(head),
        "vo_outro": (
            f"Every price is a list of assumptions. We write down what "
            f"{story['coverage_published_now']} US companies' prices assume, every night. "
            f"That's the whole reading for {story['ticker']} — nothing held back."),
    }


def _speakable(s: str, lower_first: bool = False) -> str:
    """Prose a voice can read.

    Every fix here is one a narrator got wrong on the first pass: "$32 target"
    read as "32 dollars target", "64.5%+" read as "64.5 percent plus", and a list
    item spoken after a lead-in kept its capital letter, which the model renders
    as a hard restart mid-sentence."""
    s = str(s)
    # Money with a magnitude, in the three shapes the reconstruction writes it:
    #   "$120–230 billion in revenue"   → a range, spoken as a range
    #   "$40 billion-per-gigawatt"      → a compound, the hyphen spoken as "per"
    #   "$1 trillion projection"        → ADJECTIVAL: "one trillion dollar projection"
    #   "$96.22 billion in Q2 revenue"  → STANDALONE: "…billion dollars in Q2"
    # The last distinction is the one a naive rule gets wrong in both directions,
    # and it is audible: "the one trillion dollars projection" is not English.
    _MAG = r"(trillion|billion|million)"
    s = re.sub(rf"\$(\d[\d,.]*)\s*[–—-]\s*(\d[\d,.]*)\s*{_MAG}",
               r"\1 to \2 \3 dollars", s, flags=re.I)
    s = re.sub(rf"\$(\d[\d,.]*)\s*{_MAG}-per-(\w+)",
               r"\1 \2 dollars per \3", s, flags=re.I)

    # words that mean the amount stands alone rather than qualifying a noun
    _STANDALONE = {"in", "of", "to", "for", "at", "from", "and", "or", "is", "was",
                   "were", "that", "which", "per", "by", "with", "on", "as", "into"}

    def _mag(m):
        nxt = m.group(3)                    # kept verbatim — it carries the space
        probe = nxt.strip()
        first = re.sub(r"^[^\w(]+", "", probe).split(" ", 1)[0].lower().strip(".,;:")
        standalone = (not first) or first in _STANDALONE or probe.startswith("(")
        return f"{m.group(1)} {m.group(2)} dollar{'s' if standalone else ''}{nxt}"

    s = re.sub(rf"\$(\d[\d,.]*)\s*{_MAG}(\s*\S*)", _mag, s, flags=re.I)
    s = re.sub(r"\$(\d[\d,.]*)(\s+(?:target|price|level|model))", r"\1 dollar\2", s)
    s = re.sub(r"\$(\d[\d,.]*)", r"\1 dollars", s)
    s = re.sub(r"(\d(?:\.\d+)?)%\+", r"\1 percent or better", s)
    s = re.sub(r"(\d)%", r"\1 percent", s)
    s = re.sub(r"\bFY(\d{4})\b", r"fiscal \1", s)
    s = re.sub(r"\bFY(\d{2})\b", lambda m: f"fiscal 20{m.group(1)}", s)
    s = re.sub(r"\s+", " ", s).strip()
    first = s.split(" ", 1)[0] if s else ""
    # "A tougher…" must lowercase; "U.S. tariffs…" and "EBITDA margin…" must not —
    # so the acronym guard looks at the whole first WORD, not the first two chars.
    if lower_first and first[:1].isupper() and not (len(first) > 1 and first.isupper()):
        s = s[0].lower() + s[1:]
    return s if s.endswith((".", "?", "!")) else s + "."


# ---------------------------------------------------------------------------

def render_scene(name, fn, seconds, S, out: pathlib.Path, tmp: pathlib.Path) -> pathlib.Path:
    frames = max(1, round(seconds * FPS))
    d = tmp / name
    d.mkdir(parents=True, exist_ok=True)
    for i in range(frames):
        fig, ax = _fig()
        fn(ax, S, i / max(frames - 1, 1))
        fig.savefig(d / f"f{i:04d}.png", facecolor=BG)
        plt.close(fig)
    mp4 = out / f"scene_{name}.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS),
                    "-i", str(d / "f%04d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-r", str(FPS), str(mp4)], check=True)
    return mp4


def main() -> None:
    ap = argparse.ArgumentParser(description="Animate a priced-in reconstruction as reel scenes.")
    ap.add_argument("--ticker")
    ap.add_argument("--story", help="path to story.json (defaults to today's campaign folder)")
    ap.add_argument("--out-dir")
    ap.add_argument("--only", default=None,
                    help="re-render just this scene (e.g. stakes) and leave the rest — "
                         "the scene mp4s are separate files, so iterating on one beat "
                         "should not cost the other eight")
    ap.add_argument("--bull-if", default=None,
                    help="override the buy-side condition (the numbers are never overridable)")
    ap.add_argument("--bear-if", default=None, help="override the sell-side condition")
    ap.add_argument("--max-rows", type=int, default=None,
                    help="cap the ledger rows per side (default: show every one — the "
                         "reel gets longer instead of shorter)")
    args = ap.parse_args()

    if args.story:
        story_path = pathlib.Path(args.story)
    else:
        if not args.ticker:
            ap.error("pass --ticker or --story")
        today = dt.date.today().isoformat()
        story_path = (ANALYTICS / "output" / "ads" /
                      f"{today}-priced-in-{args.ticker.lower()}" / "story.json")
    if not story_path.exists():
        sys.exit(f"no story.json at {story_path} — run priced_in_story.py --ticker <T> first")

    story = json.loads(story_path.read_text())
    if story.get("price_basis", {}).get("verdict") == "split":
        sys.exit(f"{story['ticker']}: refused — {story['price_basis']['note']}")

    S = build_scene_spec(story, args.max_rows)
    S["stakes"] = build_stakes(story, S["pays"], S["refuses"], args.bull_if, args.bear_if)
    out = (pathlib.Path(args.out_dir) if args.out_dir
           else ANALYTICS / "output" / "setups" / "priced-in" / story["ticker"])
    scenes_dir = out / "scenes"
    scenes_dir.mkdir(parents=True, exist_ok=True)

    scene_list = build_scenes(S)
    tmp = pathlib.Path(tempfile.mkdtemp(prefix=f"pireel_{story['ticker']}_"))
    paths = []
    try:
        for i, (name, fn, secs, _vo, _cap) in enumerate(scene_list):
            existing = scenes_dir / f"scene_{name}.mp4"
            if args.only and name != args.only and existing.exists():
                paths.append(existing)
                continue
            print(f"[{i+1}/{len(scene_list)}] {name} ({secs:.1f}s)…", flush=True)
            paths.append(render_scene(name, fn, secs, S, scenes_dir, tmp))
        lst = tmp / "list.txt"
        lst.write_text("".join(f"file '{p}'\n" for p in paths))
        silent = out / "story_silent.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                        "-i", str(lst), "-c", "copy", str(silent)], check=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    (out / "vo.json").write_text(json.dumps({
        "ticker": story["ticker"],
        "scenes": [{"name": n, "video": str(p), "seconds": s, "vo": v, "caption": c}
                   for (n, _fn, s, v, c), p in zip(scene_list, paths)],
        "points_shown": {"pays_for": len(S["pays"]), "declines": len(S["refuses"])},
        "stakes": {k: v for k, v in S["stakes"].items() if k != "vo"},
        "story": str(story_path),
    }, indent=2) + "\n")

    total = sum(s for _n, _f, s, _v, _c in scene_list)
    print(f"\n{len(scene_list)} scenes · {total:.0f}s silent · "
          f"{len(S['pays'])} pays-for + {len(S['refuses'])} refusals, all shown")
    print(f"scenes → {scenes_dir}")
    print(f"silent → {silent}")
    print(f"vo     → {out / 'vo.json'}   (voice it with build_priced_in_reel.py)")


if __name__ == "__main__":
    main()
