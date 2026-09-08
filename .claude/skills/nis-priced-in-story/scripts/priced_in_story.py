#!/usr/bin/env python3
"""
priced_in_story.py — turn a published priced-in reconstruction into ad material.

The priced-in programme (`code/strategylab/social/`, written up in
`research/PRICED-IN-FINDINGS.md`) reconstructs what a share price already
contains and publishes it to `swingtrader.research_priced_in`. This script is the
DATA half of the `nis-priced-in-story` creative skill: it picks a company whose
reconstruction tells a story, pulls it, and writes a `story.json` that carries
ONLY facts a public creative may use.

    cd code/analytics
    # 1) what's worth making an ad about this week (ranked, theme-deduped)
    .venv/bin/python ../../.claude/skills/nis-priced-in-story/scripts/priced_in_story.py --shortlist
    # 2) the material for one company
    .venv/bin/python ../../.claude/skills/nis-priced-in-story/scripts/priced_in_story.py --ticker NVDA

Two rules are enforced here rather than left to the author, because both are the
kind of mistake that only shows up after the ad is live:

* **Grounded tier only.** `drivers_json.priced_in_pct` / `value_if_true_pct` are
  the programme's JUDGED tier and are UNVALIDATED — two attempts to validate them
  failed. They are not on the public quote page either, so an ad built on them
  would be both dishonest and incongruent with its own landing page. This script
  never emits them; it emits driver/segment NAMES only (which are grounded in the
  company's own filings and coverage) and the numeric columns, which are
  arithmetic over other people's published targets.
* **The reconstruction has to still describe today's price.** A row is refused
  when it is older than `MAX_AGE_DAYS`, and the live quote is fetched so the
  author can see the drift. A creative quoting a price the market left three
  weeks ago is a false claim, not a stale one.

Writes `<out-dir>/story.json` (default
`output/ads/<today>-priced-in-<ticker>/priced-in/story.json`, which is the folder
layout `nis-ad-image` renders into and `nis-ad-launch` reads as one campaign).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import pathlib
import re
import sys


def _find_analytics() -> pathlib.Path:
    marker = pathlib.Path("shared") / "db.py"
    for c in [pathlib.Path.cwd(), *pathlib.Path.cwd().parents]:
        if (c / marker).exists():
            return c
    for p in pathlib.Path(__file__).resolve().parents:
        if (p / "code" / "analytics" / marker).exists():
            return p / "code" / "analytics"
    sys.exit("run from code/analytics (shared/db.py not found)")


ANALYTICS = _find_analytics()
sys.path.insert(0, str(ANALYTICS))
# Load .env so SUPABASE_* + APIKEY (FMP) are present before importing shared.db.
for _line in ((ANALYTICS / ".env").read_text().splitlines()
              if (ANALYTICS / ".env").exists() else []):
    _line = _line.strip()
    if _line and not _line.startswith("#") and "=" in _line:
        _k, _, _v = _line.partition("=")
        os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

from shared.db import get_supabase_client  # noqa: E402

SCHEMA = "swingtrader"

# Past this the reconstruction describes a different price than today's. Mirrors
# STALE_AFTER_DAYS in ui/lib/quote/priced-in-vote.ts — the panel the ad sends
# people to says so itself, so an ad must not be looser than the page.
MAX_AGE_DAYS = 45
# What a creative should actually run on. Older than this and the story is fine
# but the numbers have had a month of tape to be wrong in.
FRESH_DAYS = 21
# Above this the price has moved away from the reconstruction; the numbers on the
# creative would not match the numbers on the landing page.
MAX_DRIFT = 0.08

# The narrative needs both halves and the question, or there is no story to tell.
MIN_PAYS = 2
MIN_DECLINES = 2
MIN_TARGETS = 5

BASE_URL = "https://www.newsimpactscreener.com"

# Coarse themes, used ONLY to stop a shortlist coming back as ten versions of the
# same "can they convert the AI backlog" story. Order matters: first match wins.
THEMES: list[tuple[str, tuple[str, ...]]] = [
    ("ai-infrastructure", ("data center", "datacenter", "hbm", "gpu", "ai infrastructure",
                           "megawatt", " mw ", "hyperscaler", "backlog", "blackwell")),
    ("crypto", ("bitcoin", "mining", "hashrate", "crypto", "digital asset")),
    ("space-defense", ("satellite", "rocket", "launch", "space", "defense", "orbital")),
    ("energy-materials", ("lithium", "oil", "gas", "power", "utility", "uranium",
                          "rare earth", "magnet", "refinery")),
    ("healthcare", ("fda", "trial", "drug", "patient", "clinical", "therapy", "medicare")),
    ("consumer-brand", ("brand", "consumer", "store", "shopper", "retail", "apparel",
                        "footwear", "beauty", "restaurant", "subscriber", "member")),
    ("software", ("saas", "arr", "seat", "cloud revenue", "software", "platform", "ai agent")),
    ("semis", ("wafer", "foundry", "semiconductor", "chip", "node", "fab")),
    ("financials", ("loan", "deposit", "net interest", "underwriting", "premium", "credit")),
]

_ROW_COLUMNS = (
    "ticker, as_of, price, n_targets, target_low, target_high, target_median, "
    "median_gap, n_rejected_bull, n_rejected_bear, n_endorsed, summary, "
    "summary_json, drivers_json, pipeline_version, model, created_at"
)


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------

def _as_obj(v):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return None
    return v


def _num(v):
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def load_published(client) -> dict[str, dict]:
    """Newest published row per ticker. `published = true` only — the same filter
    the quote page uses, so an ad can never quote a row the page will not show."""
    rows: list[dict] = []
    off = 0
    while True:
        res = (client.schema(SCHEMA).table("research_priced_in")
               .select(_ROW_COLUMNS).eq("published", True)
               .order("as_of", desc=True).order("created_at", desc=True)
               .range(off, off + 499).execute())
        rows += res.data or []
        if len(res.data or []) < 500:
            break
        off += 500
    newest: dict[str, dict] = {}
    for r in rows:                      # as_of desc → the first row per ticker wins
        newest.setdefault(str(r["ticker"]).upper(), r)
    return newest


def load_universe(client) -> dict[str, dict]:
    out: dict[str, dict] = {}
    off = 0
    while True:
        res = (client.schema(SCHEMA).table("research_priced_in_universe")
               .select("symbol, company_name, market_cap, mentions_180d, exchange")
               .range(off, off + 999).execute())
        for x in res.data or []:
            out[str(x["symbol"]).upper()] = x
        if len(res.data or []) < 1000:
            break
        off += 1000
    return out


# ---------------------------------------------------------------------------
# the price basis check — the one that stops a false ad
# ---------------------------------------------------------------------------
#
# The target spread is arithmetic over targets FMP published on their own dates,
# and the reconstruction compares them to the price on `as_of`. Those two numbers
# are only comparable while the share count is. A 2-for-1 split halves the price
# and leaves every pre-split target where it was, which manufactures a ~50% "gap"
# out of nothing — and it lands the affected names at the TOP of any ranking that
# rewards disagreement, i.e. exactly the ones a creative would reach for.
#
# Monster Beverage is the worked example: split 2-for-1 on 2026-08-11, priced at
# $44.99 on 2026-09-02, against eleven targets of $90–$105 posted when the stock
# traded at ~$92. The reconstruction read that as "the market has dismissed the
# bullish consensus". It is a share count, not a view.
#
# So a split inside the target window is a REFUSAL, checked against the corporate
# action feed rather than guessed from the ratio. A large move with no split is
# not a refusal — it is often the better story ("nine analysts set targets when it
# traded at $201; it is $146 and none of them have moved") — but the creative has
# to say so, so it is reported.

_FMP_V3 = "https://financialmodelingprep.com/api/v3"
_FMP_V4 = "https://financialmodelingprep.com/api/v4"
TARGET_WINDOW_DAYS = 120        # matches strategylab.social.analyst.targets
STALE_BASIS = 0.25              # |price / median priceWhenPosted − 1| worth saying out loud


def _fmp_key() -> str | None:
    return os.environ.get("APIKEY") or os.environ.get("FMP_API_KEY")


def _fmp_get(url: str, params: dict):
    import requests                                          # noqa: PLC0415
    key = _fmp_key()
    if not key:
        raise RuntimeError("no APIKEY / FMP_API_KEY in code/analytics/.env")
    r = requests.get(url, params={**params, "apikey": key}, timeout=45)
    if r.status_code != 200:
        raise RuntimeError(f"FMP {r.status_code} for {url}")
    return r.json()


def price_basis(ticker: str, as_of: str, price: float | None) -> dict:
    """Is the spread measured against the same share the price is quoted in?

    Returns `verdict` ∈ {ok, split, stale, unchecked} — `split` is disqualifying,
    `stale` is a copy obligation, `unchecked` means say so before launching.
    """
    out: dict = {"verdict": "unchecked", "note": None, "median_price_when_posted": None,
                 "targets_seen": 0, "oldest_target": None, "newest_target": None,
                 "basis_ratio": None, "split_in_window": None}
    try:
        as_of_d = dt.date.fromisoformat(str(as_of)[:10])
        window_start = as_of_d - dt.timedelta(days=TARGET_WINDOW_DAYS)

        splits = (_fmp_get(f"{_FMP_V3}/historical-price-full/stock_split/{ticker}", {}) or {})
        hits = [s for s in (splits.get("historical") or [])
                if window_start <= dt.date.fromisoformat(str(s.get("date"))[:10]) <= as_of_d]
        if hits:
            s = hits[0]
            out.update(verdict="split", split_in_window=s,
                       note=(f"{s.get('numerator')}-for-{s.get('denominator')} split on "
                             f"{s.get('date')}, inside the {TARGET_WINDOW_DAYS}-day target "
                             f"window — the spread is priced in pre-split shares"))
            return out

        rows = _fmp_get(f"{_FMP_V4}/price-target", {"symbol": ticker}) or []
        pwp, dates = [], []
        for r in rows:
            d = str(r.get("publishedDate", ""))[:10]
            if not d:
                continue
            try:
                pd_ = dt.date.fromisoformat(d)
            except ValueError:
                continue
            if not (window_start <= pd_ <= as_of_d):
                continue
            dates.append(d)
            v = _num(r.get("priceWhenPosted"))
            if v:
                pwp.append(v)
        out["targets_seen"] = len(dates)
        if dates:
            out["oldest_target"], out["newest_target"] = min(dates), max(dates)
        if pwp:
            med = sorted(pwp)[len(pwp) // 2]
            out["median_price_when_posted"] = med
            if price and med:
                ratio = price / med
                out["basis_ratio"] = round(ratio, 3)
                if abs(ratio - 1) > STALE_BASIS:
                    out.update(verdict="stale",
                               note=(f"the models were published when {ticker} traded around "
                                     f"${med:,.2f}; the reconstruction prices ${price:,.2f} "
                                     f"({(ratio-1)*100:+.0f}%). Say so, or the ad implies the "
                                     f"analysts are looking at today's tape."))
                    return out
        out["verdict"] = "ok" if pwp else "unchecked"
        if not pwp:
            out["note"] = "no priceWhenPosted rows in the window — basis unverified"
    except Exception as exc:                                  # noqa: BLE001
        out["note"] = f"basis check failed ({exc.__class__.__name__}: {exc})"
    return out


def live_price(ticker: str) -> float | None:
    """Today's quote, for the drift check. Best-effort: no key, no drift check —
    which the caller reports rather than silently treating as 'no drift'."""
    try:
        rows = _fmp_get(f"{_FMP_V3}/quote/{ticker}", {}) or []
        return _num(rows[0].get("price")) if rows else None
    except Exception as exc:                                  # noqa: BLE001
        print(f"  · live quote unavailable ({exc.__class__.__name__}) — drift unchecked",
              file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# the story score
# ---------------------------------------------------------------------------

def theme_of(text: str) -> str:
    t = f" {text.lower()} "
    for name, keys in THEMES:
        if any(k in t for k in keys):
            return name
    return "other"


def _clean(s: str) -> str:
    """Some rows come back with the generator's own list numbering baked into the
    string ("1. Revenue growth decelerating…"). Left in, it renders as a numbered
    item inside a bulleted block — a small thing that makes the creative look
    machine-made, which is the one impression this material cannot afford."""
    return re.sub(r"^\s*\d+[.)]\s*", "", str(s)).strip()


def parts_of(row: dict) -> tuple[str | None, list[str], list[str], str | None]:
    sj = _as_obj(row.get("summary_json")) or {}
    pays = [_clean(s) for s in (sj.get("pays_for") or [])]
    dec = [_clean(s) for s in (sj.get("declines") or [])]
    return sj.get("position"), pays, dec, sj.get("crux")


def segments_of(row: dict) -> list[str]:
    """Driver + segment NAMES only. The percentages beside them in the same JSON
    are the unvalidated judged tier and never leave this function."""
    out: list[str] = []
    for d in (_as_obj(row.get("drivers_json")) or []):
        if not isinstance(d, dict):
            continue
        name = str(d.get("driver") or "").strip()
        seg = str(d.get("segment") or "").strip()
        if name:
            out.append(f"{name}" + (f" · {seg}" if seg and seg.lower() not in name.lower() else ""))
    return out


def score_row(row: dict, uni: dict, today: dt.date, above_share: float) -> dict | None:
    """Rank a reconstruction on how well it will TELL, not on how bullish it is.

    Every term is a property of the story, and each is grounded in a stored
    number rather than a model's opinion of itself:

      disagreement  |median_gap| — how far the market is from the published
                    consensus. This is the whole premise of the ad.
      refusal       the share of published models the price declines to pay for.
                    "N of M models, ignored" is the line that stops the scroll.
      spread        (high − low) / median — how much the analysts disagree with
                    EACH OTHER. A contested name has a story; a consensus one
                    has a number.
      attention     news mentions in 180 days — a proxy for whether a viewer
                    recognises the company in the half-second the frame gets.
      size          market cap, same reason, on a log scale so a mega-cap does
                    not simply win.
      rarity        a price ABOVE the median is the rarer configuration, and the
                    more surprising ad ("the market is paying MORE than every
                    analyst asked for"). Scaled by how rare it actually is in
                    today's population rather than by a hunch.
      freshness     no bonus, only a penalty as the row ages out.
    """
    t = str(row["ticker"]).upper()
    n = int(row.get("n_targets") or 0)
    lo, hi, med = _num(row.get("target_low")), _num(row.get("target_high")), _num(row.get("target_median"))
    gap = _num(row.get("median_gap"))
    if n < MIN_TARGETS or not (lo and hi and med) or hi <= lo or gap is None:
        return None

    age = (today - dt.date.fromisoformat(str(row["as_of"])[:10])).days
    if age > MAX_AGE_DAYS:
        return None

    position, pays, declines, crux = parts_of(row)
    if not crux or len(pays) < MIN_PAYS or len(declines) < MIN_DECLINES:
        return None

    bull = int(row.get("n_rejected_bull") or 0)
    bear = int(row.get("n_rejected_bear") or 0)
    endorsed = int(row.get("n_endorsed") or 0)
    u = uni.get(t, {})
    mentions = int(u.get("mentions_180d") or 0)
    mcap = float(u.get("market_cap") or 0)

    disagreement = min(abs(gap), 0.60) / 0.60
    refusal = max(bull, bear) / n
    spread = min((hi - lo) / med, 1.2) / 1.2
    attention = min(math.log10(max(mentions, 1)) / 3.0, 1.0)
    size = min(math.log10(max(mcap, 1)) / 12.0, 1.0)
    # A configuration seen in `above_share` of the population is worth (1 - share)
    # of a rarity point — so the bonus shrinks automatically if the market rotates.
    rarity = (1.0 - above_share) if gap > 0 else (1.0 - (1.0 - above_share))
    stale_penalty = 0.0 if age <= FRESH_DAYS else min((age - FRESH_DAYS) / 24.0, 1.0) * 0.20

    score = (0.30 * disagreement + 0.22 * refusal + 0.10 * spread
             + 0.18 * attention + 0.08 * size + 0.12 * rarity - stale_penalty)

    return {
        "ticker": t,
        "company": u.get("company_name") or t,
        "as_of": str(row["as_of"])[:10],
        "age_days": age,
        "score": round(score, 4),
        "direction": "above" if gap > 0 else "below",
        "median_gap_pct": round(gap * 100, 1),
        "n_targets": n,
        "n_endorsed": endorsed,
        "n_refused_bull": bull,
        "n_refused_bear": bear,
        "spread_pct": round((hi - lo) / med * 100, 1),
        "mentions_180d": mentions,
        "market_cap": mcap,
        "theme": theme_of(f"{crux} {' '.join(declines)}"),
        "crux": crux,
        "_row": row,
        "_parts": (position, pays, declines, crux),
        "_score_parts": {"disagreement": round(disagreement, 3), "refusal": round(refusal, 3),
                         "spread": round(spread, 3), "attention": round(attention, 3),
                         "size": round(size, 3), "rarity": round(rarity, 3),
                         "stale_penalty": round(stale_penalty, 3)},
    }


def shortlist(cands: list[dict], n: int, per_theme: int, direction: str) -> list[dict]:
    """Ranked, theme-capped. The cap is the point: ten names that all turn on the
    same question are one ad idea, not ten, and a batch built from them reaches
    one pocket of the audience over and over."""
    if direction != "any":
        cands = [c for c in cands if c["direction"] == direction]
    seen: dict[str, int] = {}
    out: list[dict] = []
    for c in sorted(cands, key=lambda c: -c["score"]):
        k = c["theme"]
        if seen.get(k, 0) >= per_theme:
            continue
        seen[k] = seen.get(k, 0) + 1
        out.append(c)
        if len(out) >= n:
            break
    return out


# ---------------------------------------------------------------------------
# story.json
# ---------------------------------------------------------------------------

def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def build_story(cand: dict, price_now: float | None, basis: dict, coverage: int) -> dict:
    row = cand["_row"]
    position, pays, declines, crux = cand["_parts"]
    price = _num(row.get("price"))
    lo, hi, med = _num(row.get("target_low")), _num(row.get("target_high")), _num(row.get("target_median"))
    n = cand["n_targets"]
    drift = (price_now / price - 1) if (price_now and price) else None
    t = cand["ticker"]

    # The one arithmetic claim the creative leads with, spelled out here so the
    # copy cannot round it in a flattering direction: of the M published models,
    # the price sits with `n_endorsed` of them and declines the rest.
    refused = max(cand["n_refused_bull"], cand["n_refused_bear"])

    story = {
        "ticker": t,
        "company": cand["company"],
        "as_of": cand["as_of"],
        "age_days": cand["age_days"],
        "pipeline_version": row.get("pipeline_version"),
        "price_at_as_of": price,
        "live_price": price_now,
        "drift_pct": round(drift * 100, 1) if drift is not None else None,

        # ---- the grounded tier: arithmetic over other people's published models
        "spread": {
            "n_targets": n,
            "low": lo, "median": med, "high": hi,
            "median_gap_pct": cand["median_gap_pct"],
            "n_endorsed": cand["n_endorsed"],
            "n_refused_bull": cand["n_refused_bull"],
            "n_refused_bear": cand["n_refused_bear"],
            "refused": refused,
            "spread_pct": cand["spread_pct"],
        },

        # ---- the reconstruction's own prose (a language model's writing, and
        # attributed as such wherever it is shown)
        "position": position,
        "pays_for": pays,
        "declines": declines,
        "crux": crux,
        "segments": segments_of(row),

        # How many companies the programme currently PUBLISHES. Copy that claims
        # coverage must read this rather than repeat a number from a past ad —
        # the universe grows every week and a stale count is a false claim about
        # the product, which is the easiest kind to make and the worst to make.
        "coverage_published_now": coverage,

        "theme": cand["theme"],
        "story_score": cand["score"],
        "score_parts": cand["_score_parts"],

        "destination": f"{BASE_URL}/quote/{t}#priced-in",
        "beats": {
            "1_the_number": {
                "material": f"${price:,.2f}" if price else None,
                "grounded_claim": (
                    f"{n} published analyst models on {t}. "
                    f"The price agrees with {cand['n_endorsed']} of them."),
            },
            "2_what_it_believes": {"material": pays[:3]},
            "3_what_it_refuses": {"material": declines[:3], "gated_on_site": True},
            "4_the_crux": {"material": crux},
            "5_where_to_read_it": {"destination": f"{BASE_URL}/quote/{t}#priced-in"},
        },

        "price_basis": basis,

        "grounding": {
            "table": f"{SCHEMA}.research_priced_in",
            "ticker": t,
            "as_of": cand["as_of"],
            "pipeline_version": row.get("pipeline_version"),
            "model": row.get("model"),
            "published": True,
            "queried_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        },
        "checks": {
            "judged_tier": "excluded",          # priced_in_pct / value_if_true_pct never emitted
            "age_ok": cand["age_days"] <= FRESH_DAYS,
            "renderable_on_site": n >= MIN_TARGETS and bool(lo and hi and med),
            "drift_ok": (abs(drift) <= MAX_DRIFT) if drift is not None else None,
            "price_basis_ok": basis.get("verdict") == "ok",
            "max_age_days": MAX_AGE_DAYS,
            "fresh_days": FRESH_DAYS,
            "max_drift_pct": MAX_DRIFT * 100,
        },
    }
    return story


def default_out_dir(ticker: str) -> pathlib.Path:
    """The CAMPAIGN root. `story.json` is campaign-level material — every variant
    ad set under it (`rail/`, `ledger/`, …) renders from the same reconstruction,
    which is what makes an A/B between them an A/B of the CREATIVE rather than of
    two different sets of facts."""
    today = dt.date.today().isoformat()
    return ANALYTICS / "output" / "ads" / f"{today}-priced-in-{_slug(ticker)}"


# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Priced-in reconstruction → ad story material.")
    ap.add_argument("--ticker", help="the company to build story.json for")
    ap.add_argument("--shortlist", action="store_true",
                    help="rank what is worth an ad this week (theme-capped)")
    ap.add_argument("--n", type=int, default=15, help="shortlist length (default 15)")
    ap.add_argument("--per-theme", type=int, default=2,
                    help="max candidates per theme in the shortlist (default 2)")
    ap.add_argument("--direction", choices=("any", "below", "above"), default="any",
                    help="price below the median models, above them, or either")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--no-quote", action="store_true", help="skip the live-price drift check")
    ap.add_argument("--no-basis", action="store_true",
                    help="skip the split / target-basis check (offline; not for a launch)")
    ap.add_argument("--force", action="store_true",
                    help="build the story even if the price basis is disqualifying")
    args = ap.parse_args()

    if not args.ticker and not args.shortlist:
        ap.error("pass --shortlist or --ticker")

    client = get_supabase_client()
    today = dt.date.today()
    rows = load_published(client)
    uni = load_universe(client)

    scored = [s for s in (score_row(r, uni, today, 0.5) for r in rows.values()) if s]
    # The rarity term needs the population it is measuring, so score twice: the
    # first pass only establishes how common an above-median price is today.
    above_share = (sum(1 for s in scored if s["direction"] == "above") / len(scored)) if scored else 0.5
    scored = [s for s in (score_row(r, uni, today, above_share) for r in rows.values()) if s]

    if args.shortlist:
        print(f"{len(rows)} published reconstructions · {len(scored)} tell a complete story "
              f"· {above_share*100:.0f}% sit ABOVE their median model")
        # Verify in rank order and keep going until N survive: the price-basis
        # check disqualifies names, and it disqualifies them disproportionately
        # at the top (a split fakes the exact disagreement this ranks on).
        pool = shortlist(scored, args.n * 3, args.per_theme, args.direction)
        picks, refused_rows = [], []
        for c in pool:
            if len(picks) >= args.n:
                break
            b = ({"verdict": "unchecked", "note": "skipped (--no-basis)"} if args.no_basis
                 else price_basis(c["ticker"], c["as_of"], _num(c["_row"].get("price"))))
            c["_basis"] = b
            (refused_rows if b["verdict"] == "split" else picks).append(c)
        print(f"{'':2}  checked {len(picks) + len(refused_rows)} · "
              f"{len(refused_rows)} refused on the price basis\n")

        print(f"{'#':>2}  {'TICKER':<7}{'SCORE':>6}  {'GAP':>7} {'MODELS':>7} {'AGREE':>6} "
              f"{'REFUSED':>8} {'AGE':>5}  {'BASIS':<9}{'THEME':<18} COMPANY")
        for i, c in enumerate(picks, 1):
            refused = max(c["n_refused_bull"], c["n_refused_bear"])
            print(f"{i:>2}  {c['ticker']:<7}{c['score']:>6.3f}  {c['median_gap_pct']:>+6.0f}% "
                  f"{c['n_targets']:>7} {c['n_endorsed']:>6} {refused:>8} {c['age_days']:>4}d  "
                  f"{c['_basis']['verdict']:<9}{c['theme']:<18} {c['company'][:30]}")
        if refused_rows:
            print("\nrefused — the spread is not measured against today's share:")
            for c in refused_rows:
                print(f"  ✗ {c['ticker']:<6} {c['_basis']['note']}")
        print("\nPick on legibility, not on score alone: the viewer has to recognise the company")
        print("and the crux has to be sayable in one breath. The score cannot judge either.")
        print("A `stale` basis is not a defect — it is usually the sharper ad, as long as the")
        print("copy says when the models were written.\n")
        for i, c in enumerate(picks[:5], 1):
            print(f"  {i}. {c['ticker']} — {c['crux'][:150]}")
        return

    t = args.ticker.upper().strip()
    cand = next((s for s in scored if s["ticker"] == t), None)
    if cand is None:
        row = rows.get(t)
        if row is None:
            sys.exit(f"{t}: no PUBLISHED reconstruction. The quote page has none either — "
                     f"there is nothing for an ad to point at.")
        _, pays, declines, crux = parts_of(row)
        age = (today - dt.date.fromisoformat(str(row["as_of"])[:10])).days
        sys.exit(f"{t}: published, but not usable as a story — "
                 f"age {age}d (max {MAX_AGE_DAYS}), {len(pays)} pays_for (min {MIN_PAYS}), "
                 f"{len(declines)} declines (min {MIN_DECLINES}), crux={'yes' if crux else 'NO'}.")

    basis = ({"verdict": "unchecked", "note": "skipped (--no-basis)"} if args.no_basis
             else price_basis(t, cand["as_of"], _num(cand["_row"].get("price"))))
    if basis["verdict"] == "split" and not args.force:
        sys.exit(f"{t}: REFUSED — {basis['note']}.\n"
                 f"     The gap this row reports is a share count, not a market view, and an ad\n"
                 f"     built on it would be false. Pick another name (--force overrides, but the\n"
                 f"     quote page carries the same bad row, so fix the row instead).")

    price_now = None if args.no_quote else live_price(t)
    story = build_story(cand, price_now, basis, coverage=len(rows))

    out_dir = pathlib.Path(args.out_dir) if args.out_dir else default_out_dir(t)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "story.json").write_text(json.dumps(story, indent=2) + "\n")

    s = story["spread"]
    print(f"{t} · {story['company']}  ({story['as_of']}, {story['age_days']}d old)")
    print(f"  price at as_of ${story['price_at_as_of']:,.2f}"
          + (f" · live ${story['live_price']:,.2f} ({story['drift_pct']:+.1f}%)"
             if story["live_price"] else " · live price unchecked"))
    print(f"  {s['n_targets']} published models  ${s['low']:,.0f} … ${s['median']:,.0f} … ${s['high']:,.0f}"
          f"  ({s['median_gap_pct']:+.0f}% vs median)")
    print(f"  agrees with {s['n_endorsed']} · declines {s['refused']}")
    print(f"  crux: {story['crux'][:160]}")
    for flag, ok in story["checks"].items():
        if ok is False:
            print(f"  ⚠ check failed: {flag}", file=sys.stderr)
    if story["checks"]["drift_ok"] is None:
        print("  ⚠ drift unchecked — verify the live price before launching", file=sys.stderr)
    print(f"\n→ {out_dir / 'story.json'}")


if __name__ == "__main__":
    main()
