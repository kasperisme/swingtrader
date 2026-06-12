"""Insider & Congress Activity — a "smart money" transaction board.

A STANDALONE activity screener (no price/technical screen): it aggregates the
most recently disclosed buying and selling by company insiders (SEC Form 4) and
by members of Congress (STOCK Act disclosures), then ranks the tickers by how
significant that activity is.

Design follows how the established trackers (OpenInsider, Quiver, Capitol Trades)
do it:
  • Only OPEN-MARKET trades count. Insider code "P" = buy, "S" = sell; the noisy
    codes (M option exercises, A awards, G gifts, F tax-withholding) are dropped
    so the buy signal stays clean.
  • The headline signal is a BUYING CLUSTER — 3+ distinct insiders/members buying
    the same name in the window (academic work links clusters to ~4-8% abnormal
    returns over 6-12 months). C-level and independent-director buys are flagged
    because they're the most informative.
  • Selling is shown for context (net tilt) but weighted far less — insiders sell
    for diversification/taxes/liquidity, so it has weak predictive power.
  • Tickers are ranked by significance: distinct buyers (cluster) → dollar size →
    recency.

Timing caveat surfaced in the data: Form 4 is disclosed within ~2 days, but the
STOCK Act gives Congress ~45 days — so "recent" here means recently DISCLOSED
(newly public), not necessarily recently traded. The window is applied to the
filing/disclosure date.

Congress data sits on higher FMP plan tiers; if it isn't available the board
degrades gracefully to insider-only (``congress_available`` in data_used says
which happened).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

from services.screener.fmp import fmp

from ..types import ScreeningResult

log = logging.getLogger(__name__)

_WINDOW_DAYS = 30
_PAGE_LIMIT = 100
_MAX_INSIDER_PAGES = 30   # ~3000 most-recent Form 4 transactions
_MAX_CONGRESS_PAGES = 10  # congressional feeds are sparse
_MAX_SYMBOLS = 300        # cap the emitted board
_SUMMARY_TOP_N = 25
_CLUSTER_MIN = 3          # distinct buyers for a "cluster" flag

_INS_DATE_KEYS = ("filingDate", "transactionDate", "date")
_CONG_DATE_KEYS = ("disclosureDate", "dateRecieved", "filingDate", "transactionDate", "date")
_SYMBOL_KEYS = ("symbol", "ticker")
_SYM_RE = re.compile(r"^[A-Z][A-Z.\-]{0,9}$")


# ── small parsers ────────────────────────────────────────────────────────────

def _parse_date(v) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.strptime(str(v)[:10], "%Y-%m-%d")
    except Exception:
        return None


def _rec_date(rec: dict, keys) -> datetime | None:
    for k in keys:
        d = _parse_date(rec.get(k))
        if d:
            return d
    return None


def _get(rec: dict, keys):
    for k in keys:
        v = rec.get(k)
        if v not in (None, ""):
            return v
    return None


def _norm_symbol(v) -> str | None:
    if not v:
        return None
    s = str(v).strip().upper()
    return s if _SYM_RE.match(s) else None


def _insider_dir(t) -> str | None:
    """Open-market purchase (P) → buy, sale (S) → sell; everything else dropped."""
    if t is None:
        return None
    head = str(t).strip().upper().split("-")[0].strip()[:1]
    if head == "P":
        return "buy"
    if head == "S":
        return "sell"
    return None


def _congress_dir(t) -> str | None:
    if t is None:
        return None
    s = str(t).strip().lower()
    if "purchase" in s or s == "buy":
        return "buy"
    if "sale" in s or "sell" in s:
        return "sell"
    return None  # exchange / received / unknown


def _amount_mid(a) -> float:
    """Congressional amounts are bucketed ranges ("$15,001 - $50,000"); take the
    midpoint (or the single value)."""
    if a is None:
        return 0.0
    if isinstance(a, (int, float)):
        return float(a) if a == a else 0.0  # NaN guard
    nums = [float(n.replace(",", "")) for n in re.findall(r"[0-9][0-9,]*", str(a))]
    if not nums:
        return 0.0
    if len(nums) >= 2:
        return (nums[0] + nums[1]) / 2.0
    return nums[0]


def _insider_usd(rec: dict) -> float:
    try:
        sh = float(rec.get("securitiesTransacted") or 0)
        px = float(rec.get("price") or 0)
        return abs(sh * px)
    except Exception:
        return 0.0


def _is_c_level(owner: str) -> bool:
    s = owner.lower()
    return any(x in s for x in ("ceo", "cfo", "coo", "chief exec", "chief financ", "chief operating", "president"))


def _is_director(owner: str) -> bool:
    return "director" in owner.lower()


def _politician_name(rec: dict) -> str:
    name = _get(rec, ("representative", "senator", "office", "name"))
    if name:
        return str(name)
    first = rec.get("firstName") or ""
    last = rec.get("lastName") or ""
    full = f"{first} {last}".strip()
    return full or "Member of Congress"


def _new_agg(sym: str) -> dict:
    return {
        "symbol": sym,
        "ins_buy_n": 0, "ins_sell_n": 0,
        "cong_buy_n": 0, "cong_sell_n": 0,
        "ins_buy_usd": 0.0, "ins_sell_usd": 0.0,
        "cong_buy_usd": 0.0, "cong_sell_usd": 0.0,
        "buyers": set(), "sellers": set(),
        "c_level_buy": False, "director_buy": False, "has_congress": False,
        "last_dt": None,
        "top_buyer": None, "top_buyer_usd": 0.0,
    }


def _touch_date(a: dict, dt: datetime | None) -> None:
    if dt and (a["last_dt"] is None or dt > a["last_dt"]):
        a["last_dt"] = dt


# ── feed collection ──────────────────────────────────────────────────────────

def _collect_insider(api, cutoff: datetime) -> list[dict]:
    records: list[dict] = []
    for page in range(_MAX_INSIDER_PAGES):
        try:
            df = api.insider_trading_latest(page=page, limit=_PAGE_LIMIT)
        except Exception as exc:
            log.warning("[insider_congress] insider page %d failed: %s", page, exc)
            break
        if df is None or df.empty:
            break
        recs = df.to_dict("records")
        records.extend(recs)
        oldest = min((d for d in (_rec_date(r, _INS_DATE_KEYS) for r in recs) if d), default=None)
        if oldest is not None and oldest < cutoff:
            break
    else:
        log.warning(
            "[insider_congress] insider page cap (%d) hit before reaching the %d-day cutoff "
            "— board reflects the most recent ~%d filings only.",
            _MAX_INSIDER_PAGES, _WINDOW_DAYS, _MAX_INSIDER_PAGES * _PAGE_LIMIT,
        )
    return records


def _collect_congress(api, cutoff: datetime) -> tuple[list[dict], bool]:
    records: list[dict] = []
    available = False
    for feed_fn, chamber in (
        (api.senate_trades_latest, "senate"),
        (api.house_trades_latest, "house"),
    ):
        for page in range(_MAX_CONGRESS_PAGES):
            df = feed_fn(page=page, limit=_PAGE_LIMIT)
            if df is None or df.empty:
                break
            available = True
            recs = df.to_dict("records")
            for r in recs:
                r["_chamber"] = chamber
            records.extend(recs)
            oldest = min((d for d in (_rec_date(r, _CONG_DATE_KEYS) for r in recs) if d), default=None)
            if oldest is not None and oldest < cutoff:
                break
    return records, available


# ── run ──────────────────────────────────────────────────────────────────────

def run(client, screening: dict) -> ScreeningResult:  # noqa: ARG001 — FMP is the source
    api = fmp()
    today = datetime.today()
    cutoff = today - timedelta(days=_WINDOW_DAYS)

    insider_recs = _collect_insider(api, cutoff)
    congress_recs, congress_available = _collect_congress(api, cutoff)
    log.info(
        "[insider_congress] pulled %d insider + %d congress records (congress_available=%s)",
        len(insider_recs), len(congress_recs), congress_available,
    )

    agg: dict[str, dict] = {}
    ins_used = 0
    cong_used = 0

    # Insider transactions
    for r in insider_recs:
        sym = _norm_symbol(_get(r, _SYMBOL_KEYS))
        dt = _rec_date(r, _INS_DATE_KEYS)
        if not sym or dt is None or dt < cutoff:
            continue
        direction = _insider_dir(_get(r, ("transactionType", "type", "transactionCode")))
        if direction is None:
            continue
        owner = str(_get(r, ("typeOfOwner", "officerTitle", "relationship")) or "")
        name = str(_get(r, ("reportingName", "name")) or "Insider")
        usd = _insider_usd(r)
        a = agg.setdefault(sym, _new_agg(sym))
        _touch_date(a, dt)
        if direction == "buy":
            a["ins_buy_n"] += 1
            a["ins_buy_usd"] += usd
            a["buyers"].add(f"insider:{name}")
            if _is_c_level(owner):
                a["c_level_buy"] = True
            if _is_director(owner):
                a["director_buy"] = True
            if usd > a["top_buyer_usd"]:
                a["top_buyer"], a["top_buyer_usd"] = name, usd
        else:
            a["ins_sell_n"] += 1
            a["ins_sell_usd"] += usd
            a["sellers"].add(f"insider:{name}")
        ins_used += 1

    # Congressional transactions
    for r in congress_recs:
        sym = _norm_symbol(_get(r, _SYMBOL_KEYS))
        dt = _rec_date(r, _CONG_DATE_KEYS)
        if not sym or dt is None or dt < cutoff:
            continue
        direction = _congress_dir(_get(r, ("type", "transactionType", "transaction")))
        if direction is None:
            continue
        name = _politician_name(r)
        usd = _amount_mid(_get(r, ("amount", "range")))
        a = agg.setdefault(sym, _new_agg(sym))
        a["has_congress"] = True
        _touch_date(a, dt)
        if direction == "buy":
            a["cong_buy_n"] += 1
            a["cong_buy_usd"] += usd
            a["buyers"].add(f"congress:{name}")
            if usd > a["top_buyer_usd"]:
                a["top_buyer"], a["top_buyer_usd"] = name, usd
        else:
            a["cong_sell_n"] += 1
            a["cong_sell_usd"] += usd
            a["sellers"].add(f"congress:{name}")
        cong_used += 1

    if not agg:
        return ScreeningResult(
            triggered=False,
            summary="No insider or congressional activity found in the window.",
            ticker_count=0,
            data_used={
                "window_days": _WINDOW_DAYS,
                "insider_txns": ins_used,
                "congress_txns": cong_used,
                "congress_available": congress_available,
            },
            error="empty_result",
        )

    # Rank: distinct buyers (cluster) → gross $ → recency.
    def _gross(a: dict) -> float:
        return a["ins_buy_usd"] + a["ins_sell_usd"] + a["cong_buy_usd"] + a["cong_sell_usd"]

    ranked = sorted(
        agg.values(),
        key=lambda a: (
            -len(a["buyers"]),
            -_gross(a),
            -(a["last_dt"].timestamp() if a["last_dt"] else 0),
        ),
    )[:_MAX_SYMBOLS]

    # Cheap sector enrichment for the ranked subset (batched profile call).
    sector_map: dict[str, str] = {}
    try:
        prof = api.profile([a["symbol"] for a in ranked])
        if prof is not None and not prof.empty and "symbol" in prof.columns:
            for _, pr in prof.iterrows():
                sym = str(pr.get("symbol") or "").upper()
                if sym:
                    sector_map[sym] = pr.get("sector")
    except Exception as exc:
        log.info("[insider_congress] sector enrich skipped: %s", exc)

    symbols_serialized = [_serialize_row(a, sector_map.get(a["symbol"])) for a in ranked]
    clusters = sum(1 for a in ranked if len(a["buyers"]) >= _CLUSTER_MIN)
    summary = _format_summary(ranked, clusters=clusters, congress_available=congress_available)

    return ScreeningResult(
        triggered=True,
        summary=summary,
        ticker_count=len(ranked),
        data_used={
            "window_days": _WINDOW_DAYS,
            "insider_txns": ins_used,
            "congress_txns": cong_used,
            "congress_available": congress_available,
            "buy_clusters": clusters,
            "symbols": symbols_serialized,
        },
    )


def _net_tilt(buy_usd: float, sell_usd: float, total_buys: int, total_sells: int) -> str:
    net = buy_usd - sell_usd
    if net > 0 and total_buys >= total_sells:
        return "BUY"
    if net < 0 and total_sells >= total_buys:
        return "SELL"
    return "MIXED"


def _serialize_row(a: dict, sector) -> dict:
    buy_usd = a["ins_buy_usd"] + a["cong_buy_usd"]
    sell_usd = a["ins_sell_usd"] + a["cong_sell_usd"]
    total_buys = a["ins_buy_n"] + a["cong_buy_n"]
    total_sells = a["ins_sell_n"] + a["cong_sell_n"]
    distinct_buyers = len(a["buyers"])
    return {
        "symbol": a["symbol"],
        "sector": sector,
        "net_tilt": _net_tilt(buy_usd, sell_usd, total_buys, total_sells),
        "cluster_buy": distinct_buyers >= _CLUSTER_MIN,
        "distinct_buyers": distinct_buyers,
        "distinct_sellers": len(a["sellers"]),
        "insider_buys": a["ins_buy_n"],
        "insider_sells": a["ins_sell_n"],
        "congress_buys": a["cong_buy_n"],
        "congress_sells": a["cong_sell_n"],
        "c_level_buy": bool(a["c_level_buy"]),
        "director_buy": bool(a["director_buy"]),
        "has_congress": bool(a["has_congress"]),
        "net_usd": int(round(buy_usd - sell_usd)),
        "gross_usd": int(round(buy_usd + sell_usd)),
        "top_buyer": a["top_buyer"],
        "last_disclosed": a["last_dt"].strftime("%Y-%m-%d") if a["last_dt"] else None,
    }


def _format_summary(ranked: list[dict], clusters: int, congress_available: bool) -> str:
    n = len(ranked)
    cong_note = "" if congress_available else " · congress data unavailable on plan"
    head = (
        f"<b>Insider &amp; Congress Activity</b>\n"
        f"{n} ticker{'s' if n != 1 else ''} with recent disclosed trades · "
        f"{clusters} buying cluster{'s' if clusters != 1 else ''}{cong_note}\n"
    )
    lines = []
    for a in ranked[:_SUMMARY_TOP_N]:
        buy_usd = a["ins_buy_usd"] + a["cong_buy_usd"]
        sell_usd = a["ins_sell_usd"] + a["cong_sell_usd"]
        tilt = _net_tilt(buy_usd, sell_usd, a["ins_buy_n"] + a["cong_buy_n"], a["ins_sell_n"] + a["cong_sell_n"])
        nb = len(a["buyers"])
        flag = " 🟢" if (nb >= _CLUSTER_MIN and tilt == "BUY") else ""
        cong = " · 🏛" if a["has_congress"] else ""
        lines.append(f"• <b>{a['symbol']}</b> — {tilt} · {nb} buyer{'s' if nb != 1 else ''}{cong}{flag}")
    body = "\n".join(lines)
    tail = "" if n <= _SUMMARY_TOP_N else f"\n…and {n - _SUMMARY_TOP_N} more"
    return f"{head}\n{body}{tail}"
