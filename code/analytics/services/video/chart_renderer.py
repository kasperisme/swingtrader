from __future__ import annotations

import logging
from pathlib import Path

import plotly.graph_objects as go

from .config import (
    VIDEO_WIDTH,
    VIDEO_HEIGHT,
    BG_COLOR,
    TEXT_COLOR,
    TEXT_COLOR_DIM,
    BRAND_COLOR,
    BRAND_COLOR_DIM,
    ACCENT_GREEN,
    ACCENT_RED,
    ACCENT_YELLOW,
    OUTPUT_DIR,
    SAFE_ZONE_RIGHT,
    SAFE_ZONE_BOTTOM,
)

log = logging.getLogger(__name__)

FONT_SANS = "Helvetica Neue, Helvetica, Arial, sans-serif"
FONT_MONO = "Courier New, Courier, monospace"

_LAYOUT_BASE = dict(
    width=VIDEO_WIDTH,
    height=VIDEO_HEIGHT,
    paper_bgcolor=BG_COLOR,
    plot_bgcolor=BG_COLOR,
    margin=dict(l=0, r=0, t=0, b=0),
    xaxis=dict(visible=False, range=[0, 1]),
    yaxis=dict(visible=False, range=[0, 1]),
    font=dict(family=FONT_SANS, color=TEXT_COLOR),
)

_TICKER_Y0 = 0.962
_TICKER_Y1 = 0.998
_TICKER_TEXT_Y = 0.980
_TICKER_BADGE_X1 = 0.13
_TICKER_DATA_X0 = 0.14

_HEADER_LABEL_Y = 0.943
_HEADER_RULE_Y = 0.922


def _save_fig(fig: go.Figure, path: Path) -> Path:
    fig.write_image(str(path), width=VIDEO_WIDTH, height=VIDEO_HEIGHT, scale=1)
    log.debug("Saved %s (%d KB)", path.name, path.stat().st_size // 1024)
    return path



def _section_label(fig: go.Figure, text: str, y: float = _HEADER_LABEL_Y) -> None:
    fig.add_annotation(
        text=text,
        x=0.05, y=y, showarrow=False,
        font=dict(size=22, color=BRAND_COLOR, family=FONT_SANS),
        xanchor="left",
    )


def _rule(fig: go.Figure, y: float, x0: float = 0.05, x1: float | None = None,
          color: str = BRAND_COLOR_DIM, width: int = 1) -> None:
    x1 = x1 if x1 is not None else SAFE_ZONE_RIGHT
    fig.add_shape(
        type="line", x0=x0, y0=y, x1=x1, y1=y,
        line=dict(color=color, width=width),
    )


def _left_stripe(fig: go.Figure, color: str = BRAND_COLOR, width: float = 0.014) -> None:
    fig.add_shape(
        type="rect", x0=0, y0=0, x1=width, y1=1,
        fillcolor=color, line=dict(width=0), layer="below",
    )


def _score_color(score: float) -> str:
    if score > 0.05:
        return ACCENT_GREEN
    if score < -0.05:
        return ACCENT_RED
    return ACCENT_YELLOW


def _score_label(score: float) -> str:
    abs_s = abs(score)
    if abs_s >= 0.6:
        tier = "STRONG"
    elif abs_s >= 0.3:
        tier = "MODERATE"
    elif abs_s >= 0.1:
        tier = "MILD"
    else:
        return "NEUTRAL"
    arrow = "▲" if score > 0 else "▼"
    return f"{tier} {arrow}"


def _magnitude_label(rank: int) -> tuple[str, str]:
    if rank == 0:
        return "TOP", "STORY"
    if rank == 1:
        return "HIGH", "IMPACT"
    if rank == 2:
        return "MED", "IMPACT"
    return "LOW", "IMPACT"


def _ticker_bar(fig: go.Figure, cluster_ranking: list[dict] | None, slide_index: int = 0) -> None:
    if not cluster_ranking:
        return

    fig.add_shape(
        type="rect", x0=0, y0=_TICKER_Y0, x1=SAFE_ZONE_RIGHT, y1=_TICKER_Y1,
        fillcolor=BRAND_COLOR_DIM, opacity=0.55, line=dict(width=0), layer="below",
    )
    fig.add_shape(
        type="line", x0=0, y0=_TICKER_Y0, x1=SAFE_ZONE_RIGHT, y1=_TICKER_Y0,
        line=dict(color=BRAND_COLOR, width=2),
    )

    fig.add_shape(
        type="rect", x0=0, y0=_TICKER_Y0, x1=_TICKER_BADGE_X1, y1=_TICKER_Y1,
        fillcolor=BRAND_COLOR, opacity=0.12, line=dict(width=0),
    )
    fig.add_annotation(
        text="<b>PRE-MARKET</b>",
        x=_TICKER_BADGE_X1 / 2, y=_TICKER_TEXT_Y, showarrow=False,
        font=dict(size=15, color=BRAND_COLOR, family=FONT_SANS),
        xanchor="center",
    )

    items = []
    for c in cluster_ranking[:8]:
        label = c.get("label", c.get("cluster", "")).upper()
        score = c.get("score", 0) or 0
        arrow = "▲" if score > 0.05 else ("▼" if score < -0.05 else "●")
        items.append(f"{arrow} {label}")

    separator = "  ·  "
    ticker = separator.join(items)
    full_ticker = (ticker + separator) * 4

    offset = -(slide_index * 0.18)

    fig.add_annotation(
        text=f"<b>{full_ticker}</b>",
        x=_TICKER_DATA_X0 + offset, y=_TICKER_TEXT_Y, showarrow=False,
        font=dict(size=15, color=TEXT_COLOR_DIM, family=FONT_MONO),
        xanchor="left",
    )


# ─────────────────────────────────────────────
# Block 1 — Hook / Title
# ─────────────────────────────────────────────

def render_title_slide(
    date_str: str,
    output_dir: Path,
    top_cluster: dict | None = None,
    cluster_ranking: list[dict] | None = None,
    slide_index: int = 0,
) -> Path:
    fig = go.Figure()
    _left_stripe(fig)
    _ticker_bar(fig, cluster_ranking, slide_index)

    _section_label(fig, "PRE-MARKET BRIEF")
    fig.add_annotation(
        text=date_str.upper(),
        x=SAFE_ZONE_RIGHT - 0.01, y=_HEADER_LABEL_Y, showarrow=False,
        font=dict(size=22, color=TEXT_COLOR_DIM, family=FONT_SANS),
        xanchor="right",
    )
    _rule(fig, y=_HEADER_RULE_Y, color=BRAND_COLOR, width=2)

    if top_cluster:
        score = top_cluster.get("score", 0) or 0
        label = top_cluster.get("label", "")
        count = top_cluster.get("article_count", 0)
        color = _score_color(score)
        tier_text = _score_label(score)

        fig.add_annotation(
            text="LEADING NARRATIVE",
            x=0.05, y=0.855, showarrow=False,
            font=dict(size=22, color=TEXT_COLOR_DIM, family=FONT_SANS),
            xanchor="left",
        )

        fig.add_annotation(
            text=f"<b>{label}</b>",
            x=0.05, y=0.775, showarrow=False,
            font=dict(size=58, color=TEXT_COLOR, family=FONT_SANS),
            xanchor="left",
        )

        fig.add_annotation(
            text=f"<b>{tier_text}</b>",
            x=0.05, y=0.685, showarrow=False,
            font=dict(size=48, color=color, family=FONT_MONO),
            xanchor="left",
        )

        fig.add_annotation(
            text=f"{count} articles this session",
            x=0.05, y=0.618, showarrow=False,
            font=dict(size=24, color=TEXT_COLOR_DIM, family=FONT_SANS),
            xanchor="left",
        )

        _rule(fig, y=0.575, color=BRAND_COLOR_DIM)

        direction_word = "BULLISH" if score > 0.05 else ("BEARISH" if score < -0.05 else "NEUTRAL")
        fig.add_shape(
            type="rect", x0=0.014, y0=0.09, x1=SAFE_ZONE_RIGHT, y1=0.545,
            fillcolor=color, opacity=0.04, line=dict(width=0), layer="below",
        )
        fig.add_shape(
            type="line", x0=0.014, y0=0.09, x1=0.014, y1=0.545,
            line=dict(color=color, width=3),
        )
        fig.add_annotation(
            text=f"<b>{direction_word}</b>",
            x=0.05, y=0.495, showarrow=False,
            font=dict(size=90, color=color, family=FONT_SANS),
            xanchor="left", opacity=0.15,
        )
        fig.add_annotation(
            text=f"<b>{direction_word}</b>",
            x=0.05, y=0.495, showarrow=False,
            font=dict(size=90, color=color, family=FONT_SANS),
            xanchor="left", opacity=0.9,
        )

        fig.add_annotation(
            text="TODAY'S SIGNAL",
            x=0.05, y=0.385, showarrow=False,
            font=dict(size=22, color=TEXT_COLOR_DIM, family=FONT_SANS),
            xanchor="left",
        )
    else:
        fig.add_annotation(
            text="<b>PRE-MARKET</b>",
            x=0.05, y=0.72, showarrow=False,
            font=dict(size=86, color=TEXT_COLOR, family=FONT_SANS),
            xanchor="left",
        )
        fig.add_annotation(
            text="<b>BRIEF</b>",
            x=0.05, y=0.60, showarrow=False,
            font=dict(size=86, color=BRAND_COLOR, family=FONT_SANS),
            xanchor="left",
        )
        fig.add_annotation(
            text=date_str.upper(),
            x=0.05, y=0.50, showarrow=False,
            font=dict(size=28, color=TEXT_COLOR_DIM, family=FONT_SANS),
            xanchor="left",
        )


    fig.update_layout(**_LAYOUT_BASE)
    return _save_fig(fig, output_dir / "01_title.png")


# ─────────────────────────────────────────────
# Block 2 — Market Regime
# ─────────────────────────────────────────────

def render_market_regime_slide(
    regime_text: str,
    regime_label: str,
    regime_direction: str,
    output_dir: Path,
    cluster_ranking: list[dict] | None = None,
    slide_index: int = 0,
) -> Path:
    direction = regime_direction.lower()
    accent = ACCENT_GREEN if direction == "bullish" else (ACCENT_RED if direction == "bearish" else ACCENT_YELLOW)

    fig = go.Figure()
    _left_stripe(fig, color=accent, width=0.025)
    _ticker_bar(fig, cluster_ranking, slide_index)

    _section_label(fig, "MARKET REGIME")
    fig.add_annotation(
        text="newsimpactscreener.com",
        x=SAFE_ZONE_RIGHT - 0.01, y=_HEADER_LABEL_Y, showarrow=False,
        font=dict(size=20, color=BRAND_COLOR_DIM, family=FONT_SANS),
        xanchor="right",
    )
    _rule(fig, y=_HEADER_RULE_Y, color=accent, width=2)

    label_upper = regime_label.strip().upper()
    words = label_upper.split()

    if len(words) >= 2:
        line1 = words[0]
        line2 = " ".join(words[1:])
        fig.add_annotation(
            text=f"<b>{line1}</b>",
            x=0.05, y=0.800, showarrow=False,
            font=dict(size=104, color=accent, family=FONT_SANS),
            xanchor="left",
        )
        fig.add_annotation(
            text=f"<b>{line2}</b>",
            x=0.05, y=0.680, showarrow=False,
            font=dict(size=104, color=accent, family=FONT_SANS),
            xanchor="left",
        )
        rule_y = 0.625
    else:
        fig.add_annotation(
            text=f"<b>{label_upper}</b>",
            x=0.05, y=0.740, showarrow=False,
            font=dict(size=104, color=accent, family=FONT_SANS),
            xanchor="left",
        )
        rule_y = 0.670

    _rule(fig, y=rule_y, color=BRAND_COLOR_DIM)

    words_text = regime_text.split()
    lines: list[str] = []
    current = ""
    for w in words_text:
        if len(current) + len(w) + 1 > 42:
            lines.append(current.strip())
            current = w
        else:
            current += " " + w
    if current.strip():
        lines.append(current.strip())

    for j, line in enumerate(lines[:3]):
        fig.add_annotation(
            text=line, x=0.05, y=(rule_y - 0.065) - j * 0.065,
            showarrow=False,
            font=dict(size=30, color=TEXT_COLOR_DIM, family=FONT_SANS),
            xanchor="left",
        )

    fig.add_shape(
        type="rect", x0=0.025, y0=0, x1=SAFE_ZONE_RIGHT, y1=1,
        fillcolor=accent, opacity=0.03, line=dict(width=0), layer="below",
    )


    fig.update_layout(**_LAYOUT_BASE)
    return _save_fig(fig, output_dir / "02_market_regime.png")


# ─────────────────────────────────────────────
# Block 3 — Signal (cluster data)
# ─────────────────────────────────────────────

def render_signal_slide(
    cluster_ranking: list[dict],
    output_dir: Path,
    slide_index: int = 0,
) -> Path:
    top = cluster_ranking[:8]

    fig = go.Figure()
    _ticker_bar(fig, cluster_ranking, slide_index)

    _section_label(fig, "THE SETUP")
    _rule(fig, y=_HEADER_RULE_Y, color=BRAND_COLOR, width=1)

    row_height = 0.093
    start_y = 0.860

    for i, c in enumerate(top):
        label = c.get("label", c.get("cluster", ""))
        score = c.get("score", 0) or 0
        count = c.get("article_count", 0) or 0
        color = _score_color(score)
        tier = _score_label(score)

        y_center = start_y - i * row_height
        y_bot = y_center - row_height * 0.46

        _rule(fig, y=y_bot, color=BRAND_COLOR_DIM, x0=0.05, x1=SAFE_ZONE_RIGHT)

        fig.add_shape(
            type="rect", x0=0, y0=y_bot, x1=0.008, y1=y_center + row_height * 0.46,
            fillcolor=color, line=dict(width=0),
        )

        label_size = 26 if i < 3 else 22
        tier_size = 20 if i < 3 else 18

        direction_char = "▲" if score > 0.05 else ("▼" if score < -0.05 else "●")
        fig.add_annotation(
            text=f"<b>{direction_char}  {label}</b>",
            x=0.05, y=y_center + 0.015, showarrow=False,
            font=dict(size=label_size, color=TEXT_COLOR, family=FONT_SANS),
            xanchor="left",
        )
        fig.add_annotation(
            text=f"{count} articles",
            x=0.05, y=y_center - 0.024, showarrow=False,
            font=dict(size=18, color=TEXT_COLOR_DIM, family=FONT_SANS),
            xanchor="left",
        )

        fig.add_annotation(
            text=f"<b>{tier}</b>",
            x=SAFE_ZONE_RIGHT, y=y_center, showarrow=False,
            font=dict(size=tier_size, color=color, family=FONT_MONO),
            xanchor="right",
        )


    fig.update_layout(**_LAYOUT_BASE)
    return _save_fig(fig, output_dir / "03_signal.png")


# ─────────────────────────────────────────────
# Block 4 — Why It Matters (top dimensions)
# ─────────────────────────────────────────────

def render_why_it_matters_slide(
    top_dims: list[dict],
    output_dir: Path,
    cluster_ranking: list[dict] | None = None,
    slide_index: int = 0,
) -> Path:
    top = top_dims[:6]

    labels = [d.get("label", d.get("key", "")) for d in top]
    scores = [d.get("avg_score", 0) for d in top]

    fig = go.Figure()
    _ticker_bar(fig, cluster_ranking, slide_index)

    _section_label(fig, "WHY IT MOVES")
    _rule(fig, y=_HEADER_RULE_Y, color=BRAND_COLOR, width=1)

    zero_x = 0.50
    max_bar_half = 0.34

    fig.add_shape(
        type="line", x0=zero_x, y0=0.08, x1=zero_x, y1=0.880,
        line=dict(color=BRAND_COLOR_DIM, width=1),
    )
    fig.add_annotation(
        text="BEARISH ◀",
        x=zero_x - 0.02, y=0.06, showarrow=False,
        font=dict(size=16, color=TEXT_COLOR_DIM, family=FONT_SANS),
        xanchor="right",
    )
    fig.add_annotation(
        text="▶ BULLISH",
        x=zero_x + 0.02, y=0.06, showarrow=False,
        font=dict(size=16, color=TEXT_COLOR_DIM, family=FONT_SANS),
        xanchor="left",
    )

    row_height = 0.128
    start_y = 0.842

    for i in range(len(top)):
        y_center = start_y - i * row_height
        score = scores[i]
        color = _score_color(score)
        bar_len = min(abs(score), 1.0) * max_bar_half

        x0_bar = zero_x if score >= 0 else zero_x - bar_len
        x1_bar = zero_x + bar_len if score >= 0 else zero_x

        fig.add_shape(
            type="rect",
            x0=x0_bar, y0=y_center - 0.034, x1=x1_bar, y1=y_center + 0.034,
            fillcolor=color, opacity=0.85, line=dict(width=0),
        )

        _rule(fig, y=y_center - row_height * 0.5, color=BRAND_COLOR_DIM, x0=0.05, x1=SAFE_ZONE_RIGHT)

        fig.add_annotation(
            text=f"<b>{labels[i]}</b>",
            x=0.05, y=y_center + 0.010, showarrow=False,
            font=dict(size=22, color=TEXT_COLOR, family=FONT_SANS),
            xanchor="left",
        )

        tier = _score_label(score)
        score_x = min(x1_bar + 0.015, SAFE_ZONE_RIGHT) if score >= 0 else max(x0_bar - 0.015, 0.03)
        anchor = "left" if score >= 0 else "right"
        fig.add_annotation(
            text=f"<b>{tier}</b>",
            x=score_x, y=y_center, showarrow=False,
            font=dict(size=18, color=color, family=FONT_MONO),
            xanchor=anchor,
        )


    fig.update_layout(**_LAYOUT_BASE)
    return _save_fig(fig, output_dir / "04_why_it_matters.png")


# ─────────────────────────────────────────────
# Block 5 — What To Watch (headlines)
# ─────────────────────────────────────────────

def render_what_to_watch_slide(
    articles: list[dict],
    tickers_map: dict[int, list[str]],
    output_dir: Path,
    cluster_ranking: list[dict] | None = None,
    slide_index: int = 0,
) -> Path:
    fig = go.Figure()
    _ticker_bar(fig, cluster_ranking, slide_index)

    _section_label(fig, "WATCH LIST")
    _rule(fig, y=_HEADER_RULE_Y, color=BRAND_COLOR, width=1)

    top_4 = articles[:4]
    row_height = 0.197
    start_y = 0.834

    for i, a in enumerate(top_4):
        y_center = start_y - i * row_height
        y_top = y_center + row_height * 0.47
        y_bot = y_center - row_height * 0.47

        title = a.get("title", "Untitled")
        if len(title) > 48:
            title = title[:45] + "…"
        tickers = tickers_map.get(a["id"], [])
        ticker_str = "  ·  ".join(tickers[:4])
        magnitude = a.get("magnitude", 0) or 0

        border_color = ACCENT_GREEN if magnitude > 0 else (ACCENT_RED if magnitude < 0 else ACCENT_YELLOW)
        line1, line2 = _magnitude_label(i)

        fig.add_shape(
            type="rect", x0=0.05, y0=y_bot + 0.006, x1=0.062, y1=y_top - 0.006,
            fillcolor=border_color, line=dict(width=0),
        )

        _rule(fig, y=y_bot, color=BRAND_COLOR_DIM, x0=0.05, x1=SAFE_ZONE_RIGHT)

        fig.add_annotation(
            text=f"<b>{line1}</b>",
            x=0.105, y=y_center + 0.024, showarrow=False,
            font=dict(size=22, color=border_color, family=FONT_MONO),
            xanchor="center",
        )
        fig.add_annotation(
            text=f"<b>{line2}</b>",
            x=0.105, y=y_center - 0.018, showarrow=False,
            font=dict(size=18, color=border_color, family=FONT_MONO),
            xanchor="center",
        )

        fig.add_shape(
            type="line",
            x0=0.135, y0=y_bot + 0.018, x1=0.135, y1=y_top - 0.018,
            line=dict(color=BRAND_COLOR_DIM, width=1),
        )

        fig.add_annotation(
            text=f"<b>{title}</b>",
            x=0.148, y=y_center + 0.022, showarrow=False,
            font=dict(size=22, color=TEXT_COLOR, family=FONT_SANS),
            xanchor="left", align="left",
        )

        if ticker_str:
            fig.add_annotation(
                text=ticker_str,
                x=0.148, y=y_center - 0.040, showarrow=False,
                font=dict(size=18, color=BRAND_COLOR, family=FONT_MONO),
                xanchor="left",
            )


    fig.update_layout(**_LAYOUT_BASE)
    return _save_fig(fig, output_dir / "05_what_to_watch.png")


# ─────────────────────────────────────────────
# Block 6 — Contrarian Note
# ─────────────────────────────────────────────

def render_contrarian_slide(
    contrarian_text: str,
    output_dir: Path,
    cluster_ranking: list[dict] | None = None,
    slide_index: int = 0,
) -> Path:
    fig = go.Figure()
    _left_stripe(fig, color=ACCENT_RED, width=0.025)
    _ticker_bar(fig, cluster_ranking, slide_index)

    fig.add_shape(
        type="rect", x0=0.025, y0=0, x1=SAFE_ZONE_RIGHT, y1=1,
        fillcolor=ACCENT_RED, opacity=0.03, line=dict(width=0), layer="below",
    )

    _section_label(fig, "THESIS RISK")
    _rule(fig, y=_HEADER_RULE_Y, color=ACCENT_RED, width=2)

    words = contrarian_text.split()
    lines: list[str] = []
    current = ""
    for w in words:
        if len(current) + len(w) + 1 > 34:
            lines.append(current.strip())
            current = w
        else:
            current += " " + w
    if current.strip():
        lines.append(current.strip())

    total_lines = min(len(lines), 5)
    line_gap = 0.095
    first_y = 0.70 + ((total_lines - 1) * line_gap / 2)

    for j, line in enumerate(lines[:5]):
        size = 44 if j == 0 else 38
        fig.add_annotation(
            text=f"<b>{line}</b>",
            x=0.05, y=first_y - j * line_gap, showarrow=False,
            font=dict(size=size, color=TEXT_COLOR, family=FONT_SANS),
            xanchor="left",
        )

    _rule(fig, y=0.235, color=BRAND_COLOR_DIM)
    fig.add_annotation(
        text="INVALIDATION SCENARIO",
        x=0.05, y=0.185, showarrow=False,
        font=dict(size=22, color=ACCENT_RED, family=FONT_SANS),
        xanchor="left",
    )


    fig.update_layout(**_LAYOUT_BASE)
    return _save_fig(fig, output_dir / "06_contrarian.png")


# ─────────────────────────────────────────────
# Block 7 — CTA
# ─────────────────────────────────────────────

def render_cta(
    output_dir: Path,
    cluster_ranking: list[dict] | None = None,
    slide_index: int = 0,
) -> Path:
    fig = go.Figure()
    _left_stripe(fig)
    _ticker_bar(fig, cluster_ranking, slide_index)

    _section_label(fig, "DAILY PRE-MARKET ANALYSIS")
    _rule(fig, y=_HEADER_RULE_Y, color=BRAND_COLOR, width=1)

    fig.add_annotation(
        text="<b>FOLLOW</b>",
        x=0.05, y=0.780, showarrow=False,
        font=dict(size=92, color=TEXT_COLOR, family=FONT_SANS),
        xanchor="left",
    )

    fig.add_annotation(
        text="<b>@newsimpactscrnr</b>",
        x=0.05, y=0.665, showarrow=False,
        font=dict(size=44, color=BRAND_COLOR, family=FONT_MONO),
        xanchor="left",
    )

    _rule(fig, y=0.605, color=BRAND_COLOR_DIM)

    fig.add_annotation(
        text="newsimpactscreener.com",
        x=0.05, y=0.550, showarrow=False,
        font=dict(size=28, color=TEXT_COLOR_DIM, family=FONT_SANS),
        xanchor="left",
    )

    fig.add_annotation(
        text="#StockMarket  ·  #PreMarket  ·  #Trading",
        x=0.05, y=0.480, showarrow=False,
        font=dict(size=22, color=BRAND_COLOR_DIM, family=FONT_SANS),
        xanchor="left",
    )

    fig.add_shape(
        type="rect", x0=0.014, y0=0, x1=SAFE_ZONE_RIGHT, y1=0.13,
        fillcolor=BRAND_COLOR_DIM, opacity=0.4, line=dict(width=0), layer="below",
    )
    _rule(fig, y=0.13, color=BRAND_COLOR, width=1, x0=0.014, x1=SAFE_ZONE_RIGHT)
    fig.add_annotation(
        text="NEWS IMPACT SCORES — QUANTIFIED MARKET NARRATIVES",
        x=0.05, y=0.065, showarrow=False,
        font=dict(size=18, color=BRAND_COLOR, family=FONT_SANS),
    )

    fig.update_layout(**_LAYOUT_BASE)
    return _save_fig(fig, output_dir / "07_cta.png")


# ─────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────

def render_all_slides(
    summary: dict,
    articles: list[dict],
    tickers_map: dict[int, list[str]],
    date_str: str,
    script: dict,
    output_dir: Path | None = None,
) -> list[Path]:
    output_dir = output_dir or OUTPUT_DIR / "slides"
    output_dir.mkdir(parents=True, exist_ok=True)

    slides = []
    cluster_ranking = summary.get("cluster_ranking", [])
    idx = 0

    log.info("Rendering title slide (block 1: hook)")
    top_cluster = cluster_ranking[0] if cluster_ranking else None
    slides.append(render_title_slide(
        date_str, output_dir,
        top_cluster=top_cluster,
        cluster_ranking=cluster_ranking,
        slide_index=idx,
    ))
    idx += 1

    log.info("Rendering market regime slide (block 2)")
    slides.append(render_market_regime_slide(
        regime_text=script.get("market_regime", ""),
        regime_label=script.get("market_regime_label", "MIXED SIGNALS"),
        regime_direction=script.get("regime_direction", "neutral"),
        output_dir=output_dir,
        cluster_ranking=cluster_ranking,
        slide_index=idx,
    ))
    idx += 1

    log.info("Rendering signal slide (block 3)")
    slides.append(render_signal_slide(
        cluster_ranking, output_dir,
        slide_index=idx,
    ))
    idx += 1

    log.info("Rendering why-it-matters slide (block 4)")
    if summary["top_dimensions"]:
        slides.append(render_why_it_matters_slide(
            summary["top_dimensions"], output_dir,
            cluster_ranking=cluster_ranking,
            slide_index=idx,
        ))
        idx += 1

    log.info("Rendering what-to-watch slide (block 5)")
    if articles:
        slides.append(render_what_to_watch_slide(
            articles, tickers_map, output_dir,
            cluster_ranking=cluster_ranking,
            slide_index=idx,
        ))
        idx += 1

    log.info("Rendering contrarian slide (block 6)")
    slides.append(render_contrarian_slide(
        script.get("contrarian", ""), output_dir,
        cluster_ranking=cluster_ranking,
        slide_index=idx,
    ))
    idx += 1

    log.info("Rendering CTA slide (block 7)")
    slides.append(render_cta(
        output_dir,
        cluster_ranking=cluster_ranking,
        slide_index=idx,
    ))

    log.info("Rendered %d slides to %s", len(slides), output_dir)
    return slides
