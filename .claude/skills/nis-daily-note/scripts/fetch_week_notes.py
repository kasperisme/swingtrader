#!/usr/bin/env python3
"""Build the row set for the Notes-list reel: the period's most RELEVANT market stories.

Selection is deterministic and grounded — nothing here is written by a model:
  · pull every article in the window, with its STORY_KEY_POINTS (the scored claims
    the /articles page shows),
  · keep only articles that are BOTH on a market theme and about a ticker with real
    weekly mention volume — this is what filters out the micro-cap noise
    (penny-stock collapses, single-trial biotech) that otherwise wins on raw |impact|,
  · rank every surviving claim by RELEVANCE, not recency:

        relevance = |impact| × log1p(reach) × theme_bonus

    where `reach` is the weekly mention count of the biggest ticker in the story
    (how widely held the name is) and `theme_bonus` lifts claims carrying the
    period's dominant topic (pass --topic from the trend brief).

  · cap per day so one busy session can't fill the whole list, and dedupe near
    -identical claims (the same deal gets written up many times).

    python fetch_week_notes.py --days 7 --limit 18 --topic ai \
        --out output/notes/<date>/rows.json
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import pathlib
import sys
from datetime import datetime, timedelta, timezone


def _find_analytics() -> pathlib.Path:
    here = pathlib.Path(__file__).resolve()
    for p in here.parents:
        c = p / "code" / "analytics"
        if (c / "shared" / "db.py").exists():
            return c
    sys.exit("could not locate code/analytics (shared/db.py)")


ANALYTICS_DIR = _find_analytics()
sys.path.insert(0, str(ANALYTICS_DIR))

from dotenv import load_dotenv           # noqa: E402
from shared.db import get_supabase_client  # noqa: E402

SCHEMA = "swingtrader"

# Market themes — an article must carry one of these to be recap-worthy.
THEMES = {"ai", "semiconductors", "geopolitics", "inflation", "banking", "oil", "energy",
          "data_centers", "capex", "cloud_computing", "fed", "rates", "crypto", "defense",
          "ipo", "m_and_a", "tariffs", "china"}
# A ticker needs this many weekly mentions for its story to count as widely-held news.
TICKER_FLOOR = 40


def _page(table, cols, filt):
    client = get_supabase_client()
    out, frm = [], 0
    while True:
        q = client.schema(SCHEMA).table(table).select(cols)
        q = filt(q)
        rows = q.range(frm, frm + 999).execute().data or []
        out += rows
        if len(rows) < 1000:
            return out
        frm += 1000


def _as_map(v):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except json.JSONDecodeError:
            return {}
    return v or {}


def _fingerprint(claim: str) -> frozenset:
    """Content words, for near-duplicate detection — the same deal is written up
    by a dozen outlets with different wording."""
    stop = {"the", "a", "an", "of", "to", "in", "for", "and", "is", "are", "has", "have",
            "with", "at", "on", "its", "by", "from", "as", "that", "this", "will", "be"}
    return frozenset(w.strip(".,%$()").lower() for w in claim.split()
                     if len(w) > 2 and w.lower() not in stop)


def _numbers(claim: str) -> frozenset:
    """The figures in a claim. Two stories about the same ticker quoting the same
    headline number are the same story, however differently they're worded —
    word overlap alone misses 'NVDA/SK Hynix worth $500B' vs 'SK Group and NVIDIA
    partnership valued at over $500B'."""
    out = set()
    for w in claim.replace("$", " ").replace("%", " ").split():
        t = w.strip(".,()").replace(",", "")
        if t and t[0].isdigit():
            out.add(t.rstrip("."))
    return frozenset(out)


def build_rows(days: int, limit: int, per_day_cap: int, topic: str | None) -> list[dict]:
    client = get_supabase_client()
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    arts = _page("news_articles", "id,title,published_at,search_tags",
                 lambda q: q.gte("published_at", since))
    ids = [a["id"] for a in arts]

    tickers = collections.defaultdict(list)
    heads = {}
    for i in range(0, len(ids), 300):
        chunk = ids[i:i + 300]
        for r in (client.schema(SCHEMA).table("news_article_tickers")
                  .select("article_id,ticker").in_("article_id", chunk).execute().data or []):
            tickers[r["article_id"]].append(r["ticker"])
        for r in (client.schema(SCHEMA).table("news_impact_heads")
                  .select("article_id,scores_json,reasoning_json")
                  .in_("article_id", chunk).eq("cluster", "STORY_KEY_POINTS")
                  .execute().data or []):
            heads[r["article_id"]] = r

    mentions = collections.Counter(t for v in tickers.values() for t in v)
    big = {t for t, n in mentions.items() if n >= TICKER_FLOOR}

    topic = (topic or "").lower().strip()
    candidates = []
    for a in arts:
        tags = {str(t).lower() for t in (a.get("search_tags") or [])}
        tk = set(tickers.get(a["id"], []))
        if not (tags & THEMES) or not (tk & big):
            continue
        h = heads.get(a["id"])
        if not h:
            continue
        reach = max((mentions[t] for t in tk & big), default=1)
        theme_bonus = 1.35 if topic and topic in tags else 1.0
        scores, reasons = _as_map(h.get("scores_json")), _as_map(h.get("reasoning_json"))
        for k, v in scores.items():
            claim = (reasons.get(k) or "").split(" — ")[0].strip()
            if len(claim) < 25:
                continue
            candidates.append({
                "date": a["published_at"][:10],
                "impact": float(v),
                "claim": claim,
                # Ordered by reach, so tickers[0] is the story's actual subject —
                # alphabetical order would make an AMD+NVDA story "lead" with AMD.
                "tickers": sorted(tk & big, key=lambda t: -mentions[t])[:3],
                "reach": reach,
                "relevance": abs(float(v)) * math.log1p(reach) * theme_bonus,
                "published_at": a["published_at"],
            })

    # Most relevant first — this ordering IS the reel's running order.
    rows, seen = [], []
    per_day, per_ticker = collections.Counter(), collections.Counter()
    for it in sorted(candidates, key=lambda r: -r["relevance"]):
        lead = it["tickers"][0] if it["tickers"] else "—"
        tset = set(it["tickers"])
        fp, nums = _fingerprint(it["claim"]), _numbers(it["claim"])
        dup = False
        for s_fp, s_nums, s_tset in seen:
            if len(fp & s_fp) / max(1, min(len(fp), len(s_fp))) > 0.6:
                dup = True                                   # reworded near-copy
            elif (tset & s_tset) and nums and (nums & s_nums):
                dup = True     # a shared name quoting a shared figure = one story,
                               # even when it resurfaces on a different day
            if dup:
                break
        if dup or per_day[it["date"]] >= per_day_cap:
            continue
        # Variety: one story per name per day, and no name dominating the list.
        if per_ticker[(lead, it["date"])] >= 1 or per_ticker[lead] >= 3:
            continue
        seen.append((fp, nums, tset))
        per_day[it["date"]] += 1
        per_ticker[lead] += 1
        per_ticker[(lead, it["date"])] += 1
        rows.append(it)
        if len(rows) >= limit:
            break
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch the period's per-day market stories.")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--limit", type=int, default=18, help="how many notes the list shows")
    ap.add_argument("--per-day-cap", type=int, default=3,
                    help="max notes from any single day, so one session can't fill the list")
    ap.add_argument("--topic", help="dominant topic tag from the trend brief (relevance bonus)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    load_dotenv()
    rows = build_rows(args.days, args.limit, args.per_day_cap, args.topic)
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=2))
    print(f"✓ {len(rows)} rows across {len({r['date'] for r in rows})} days → {out}")
    for i, r in enumerate(rows[:8], 1):
        print(f"  {i:2d}. {r['date']}  rel={r['relevance']:5.2f}  "
              f"[{r['impact']:+.2f}] reach={r['reach']:<4d} {r['claim'][:74]}")


if __name__ == "__main__":
    main()
