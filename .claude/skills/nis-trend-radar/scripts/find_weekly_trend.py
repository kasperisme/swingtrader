#!/usr/bin/env python3
"""Find the most talked-about news topic/trend in the last week — a *trend brief*
for downstream ad generation (nis-ad-image).

Reuses the SAME pre-aggregated views the public /articles trend board reads
(so the brief always agrees with what the site shows):

  swingtrader.news_trends_tag_daily_v      (bucket_day, tag, article_count)
  swingtrader.news_trends_ticker_daily_v   (bucket_day, ticker, mention_count,
                                            scored_count, avg_sentiment, weighted_sentiment)

It buckets a current vs immediately-prior N-day window, folds each key into
current / previous / delta / spark, ranks tags + tickers three ways
(mentions · growth · new), then picks the single dominant TOPIC by a heat score
that rewards both volume and acceleration. For that topic it pulls evidence
headlines via the `search_news_by_tags` RPC (the /articles search) and links the
tickers in play (from `news_article_tickers`) — ranked by **over-index** (how
concentrated the name is in this trend vs its baseline share of all news this week,
so gold on an inflation week beats a mega-cap mentioned everywhere), with the
topic's sentiment on each.

Output → output/trends/<end-date>/trend_brief.{json,md}

Run from code/analytics:
  .venv/bin/python ../../.claude/skills/nis-trend-radar/scripts/find_weekly_trend.py \
      --window-days 7 --top 8
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote_plus

BRAND = "https://www.newsimpactscreener.com"


def _find_analytics() -> Path:
    """Locate code/analytics (holds `shared` + `services`). Search CWD upward,
    then the repo tree relative to this script — so the script runs from anywhere."""
    marker = Path("shared") / "db.py"
    candidates = [Path.cwd(), *Path.cwd().parents]
    for p in Path(__file__).resolve().parents:
        candidates.append(p / "code" / "analytics")
    for c in candidates:
        if (c / marker).exists():
            return c
    sys.exit("could not locate code/analytics (shared/db.py)")


ANALYTICS_DIR = _find_analytics()
sys.path.insert(0, str(ANALYTICS_DIR))

from shared.db import get_supabase_client  # noqa: E402

SCHEMA = "swingtrader"
# Write outputs under code/analytics/output/trends/ regardless of CWD.
OUT_ROOT = ANALYTICS_DIR / "output" / "trends"

# Volume floors so a 1→3 blip can't top the board (mirror lib/trends.ts).
MIN_CURRENT_FOR_GROWTH = 5
MIN_CURRENT_FOR_NEW = 3
MIN_CURRENT_FOR_TOPIC = 8          # the winning topic must have real volume
# A ticker must clear this many in-topic mentions before its over-index counts —
# otherwise a 1–2 mention obscure name (over-indexed by accident) would top the board.
TICKER_MENTION_FLOOR = 3
PAGE_SIZE = 1000
MAX_PAGES = 60

# Structural / process tags that describe an article *type*, not a *trend*. They
# are always high-volume (every week has "earnings"), so they'd win the topic pick
# and make a dead ad hook. Excluded from the TOPIC choice + runner-ups only — they
# still appear in the raw boards. Compared with underscores normalized to spaces.
GENERIC_TAGS = {
    "earnings", "earnings beat", "earnings miss", "guidance", "outlook", "valuation",
    "dividend", "dividends", "buyback", "buybacks", "ipo", "spinoff", "merger", "m&a",
    "class action", "lawsuit", "lawsuits", "litigation", "settlement", "investigation",
    "analyst rating", "analyst ratings", "ratings", "rating", "upgrade", "downgrade",
    "price target", "insider", "insider trading", "sec filing", "sec", "options",
    "stocks", "stock", "market", "markets", "us", "world", "news", "economy",
    "wall street", "trading", "investing", "shares",
}


def _is_generic(key: str) -> bool:
    return key.replace("_", " ").strip().lower() in GENERIC_TAGS


# ── window helpers ────────────────────────────────────────────────────────────

def _day(d: date) -> str:
    return d.isoformat()


def span_days(span: int) -> list[str]:
    """Ordered YYYY-MM-DD keys for the last `span` days (oldest first, UTC)."""
    today = datetime.now(timezone.utc).date()
    return [_day(today - timedelta(days=i)) for i in range(span - 1, -1, -1)]


# ── paged fetch ───────────────────────────────────────────────────────────────

def _fetch_all(table: str, cols: str, since: str, order_cols: list[str]) -> list[dict]:
    client = get_supabase_client()
    out: list[dict] = []
    for page in range(MAX_PAGES):
        frm = page * PAGE_SIZE
        q = client.schema(SCHEMA).from_(table).select(cols).gte("bucket_day", since)
        for c in order_cols:
            q = q.order(c, desc=False)
        rows = q.range(frm, frm + PAGE_SIZE - 1).execute().data or []
        out.extend(rows)
        if len(rows) < PAGE_SIZE:
            break
    return out


# ── fold + rank (mirror of lib/trends.ts) ─────────────────────────────────────

def _fold(by_key: dict[str, dict[str, float]], days: list[str], window: int,
          sentiment: dict[str, dict[str, tuple[float, float]]] | None, kind: str) -> list[dict]:
    prev_days = set(days[:window])
    cur_days = set(days[window:])
    items: list[dict] = []
    for key, counts in by_key.items():
        current = sum(c for d, c in counts.items() if d in cur_days)
        previous = sum(c for d, c in counts.items() if d in prev_days)
        if current == 0:
            continue
        spark = [counts.get(d, 0) for d in days]
        avg_sent = None
        if sentiment and key in sentiment:
            s_sum = s_w = 0.0
            for d in cur_days:
                if d in sentiment[key]:
                    val, w = sentiment[key][d]
                    s_sum += val
                    s_w += w
            if s_w > 0:
                avg_sent = s_sum / s_w
        items.append({
            "key": key,
            "label": key if kind == "ticker" else key.replace("_", " "),
            "kind": kind,
            "current": int(current),
            "previous": int(previous),
            "deltaPct": ((current - previous) / previous) if previous > 0 else None,
            "isNew": previous == 0,
            "avgSentiment": avg_sent,
            "spark": [int(x) for x in spark],
        })
    return items


def _rank(items: list[dict], mode: str, limit: int) -> list[dict]:
    if mode == "new":
        fresh = [it for it in items if it["isNew"] and it["current"] >= MIN_CURRENT_FOR_NEW]
        pool = fresh if len(fresh) >= limit else [it for it in items if it["isNew"]]
        return sorted(pool, key=lambda it: -it["current"])[:limit]
    established = [it for it in items if not it["isNew"]]
    if mode == "mentions":
        return sorted(established, key=lambda it: (-it["current"], -(it["deltaPct"] or 0)))[:limit]
    # growth
    elig = [it for it in established if it["current"] >= MIN_CURRENT_FOR_GROWTH]
    pool = elig if len(elig) >= limit else established
    return sorted(pool, key=lambda it: (-(it["deltaPct"] or 0), -it["current"]))[:limit]


# ── heat: volume × acceleration → the single dominant topic ────────────────────

def _heat(it: dict) -> float:
    """Reward both size and rise, but tilt toward *acceleration* so a big rising
    theme beats a bigger flat one (a flat evergreen isn't a trend). New-but-sizable
    topics get the full boost."""
    growth = 1.0 if it["isNew"] else max(0.0, min(1.5, it["deltaPct"] or 0.0))
    return it["current"] * (1.0 + 2.0 * growth)


# ── index builders ────────────────────────────────────────────────────────────

def build_tag_index(window: int):
    span = window * 2
    days = span_days(span)
    rows = _fetch_all("news_trends_tag_daily_v", "bucket_day, tag, article_count",
                      days[0], ["bucket_day", "tag"])
    by_key: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for r in rows:
        tag = str(r.get("tag") or "").lower().strip()
        if not tag or tag.isdigit():        # drop numeric foreign tickers
            continue
        by_key[tag][str(r["bucket_day"])[:10]] += float(r.get("article_count") or 0)
    return _fold(by_key, days, window, None, "tag")


def build_ticker_index(window: int):
    span = window * 2
    days = span_days(span)
    rows = _fetch_all(
        "news_trends_ticker_daily_v",
        "bucket_day, ticker, mention_count, scored_count, avg_sentiment, weighted_sentiment",
        days[0], ["bucket_day", "ticker"])
    by_key: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    sent: dict[str, dict[str, tuple[float, float]]] = defaultdict(dict)
    for r in rows:
        tk = str(r.get("ticker") or "").upper().strip()
        if not tk:
            continue
        day = str(r["bucket_day"])[:10]
        by_key[tk][day] += float(r.get("mention_count") or 0)
        score = r.get("weighted_sentiment")
        if score is None:
            score = r.get("avg_sentiment")
        scored = float(r.get("scored_count") or 0)
        if score is not None and scored > 0:
            sent[tk][day] = (float(score) * scored, scored)
    return _fold(by_key, days, window, sent, "ticker")


# ── story key points (news_impact_heads → STORY_KEY_POINTS head) ──────────────

def _as_map(v) -> dict:
    """jsonb comes back as a dict; tolerate a JSON string too."""
    if isinstance(v, dict):
        return v
    if isinstance(v, str):
        try:
            d = json.loads(v)
            return d if isinstance(d, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


def story_key_points(article_ids: list) -> dict:
    """For each article, its STORY_KEY_POINTS: the scored claims that explain the
    story. `scores_json` maps point-id → impact, `reasoning_json` → the claim text
    (exactly what the /articles page renders). Returns {article_id: [{text, impact}]}."""
    if not article_ids:
        return {}
    client = get_supabase_client()
    out: dict = defaultdict(list)
    try:
        rows = (client.schema(SCHEMA).table("news_impact_heads")
                .select("article_id, scores_json, reasoning_json")
                .in_("article_id", article_ids[:500])
                .eq("cluster", "STORY_KEY_POINTS").execute().data or [])
    except Exception as e:                       # noqa: BLE001
        print(f"  (story key points failed: {e})")
        return {}
    for r in rows:
        scores = _as_map(r.get("scores_json"))
        texts = _as_map(r.get("reasoning_json"))
        pts = [{"text": (texts.get(pid) or "").strip(), "impact": float(imp or 0)}
               for pid, imp in scores.items() if (texts.get(pid) or "").strip()]
        pts.sort(key=lambda p: -abs(p["impact"]))
        if pts:
            out[r["article_id"]] = pts
    return out


# ── evidence: headlines + tickers for the winning topic ───────────────────────

def topic_evidence(tag: str, window: int, match_count: int = 24, pool: int = 200) -> dict:
    """Pull the topic's articles (up to `pool` for robust ticker stats), keep the
    first `match_count` as display headlines, and aggregate the tickers mentioned
    *within this topic* + the topic's sentiment impact on each."""
    client = get_supabase_client()
    try:
        res = client.schema(SCHEMA).rpc("search_news_by_tags", {
            "tag_filter": [tag],
            "match_count": max(match_count, pool),
            "lookback_hours": window * 24,
            "stream_filter": None,
        }).execute()
        arts = res.data or []
    except Exception as e:                       # noqa: BLE001
        print(f"  (evidence RPC failed: {e})")
        arts = []

    # dedupe by title, keep newest-first order the RPC returns. Collect ALL article
    # ids for ticker stats; keep only the first `match_count` as display headlines.
    seen, headlines, article_ids = set(), [], []
    for a in arts:
        title = (a.get("title") or "").strip()
        if not title or title.lower() in seen:
            continue
        seen.add(title.lower())
        aid = a.get("article_id")
        if aid is not None:
            article_ids.append(aid)
        if len(headlines) < match_count:
            headlines.append({
                "article_id": aid,
                "title": title,
                "source": a.get("source"),
                "url": a.get("url"),
                "slug": a.get("slug"),
                "published_at": a.get("published_at"),
            })

    # story key points explain WHY the trend is happening (news_impact_heads)
    kp_by_article = story_key_points(article_ids)
    for h in headlines:
        h["key_points"] = [p["text"] for p in kp_by_article.get(h["article_id"], [])[:3]]
    # aggregate the highest-impact claims across the topic, deduped by text
    why_seen, why_points = set(), []
    for pts in kp_by_article.values():
        for p in pts:
            k = p["text"].lower()[:80]
            if k in why_seen:
                continue
            why_seen.add(k)
            why_points.append(p)
    why_points.sort(key=lambda p: -abs(p["impact"]))
    why_points = [{"text": p["text"], "impact": round(p["impact"], 2)} for p in why_points[:10]]

    topic_tickers = _topic_tickers(article_ids, window)

    return {"headlines": headlines, "article_ids": article_ids,
            "topic_tickers": topic_tickers, "why_points": why_points}


def _week_ticker_mentions(window: int) -> dict[str, int]:
    """Each ticker's TOTAL mentions across ALL news in the current window (its
    market-wide baseline), from `news_trends_ticker_daily_v`. This is the
    denominator for a ticker's topic *over-index* — a mega-cap mentioned
    everywhere has a huge baseline, so being in the topic barely moves its index."""
    since = span_days(window)[0]
    rows = _fetch_all("news_trends_ticker_daily_v", "ticker, mention_count",
                      since, ["bucket_day", "ticker"])
    out: dict[str, int] = defaultdict(int)
    for r in rows:
        t = str(r.get("ticker") or "").upper().strip()
        if t and not t.isdigit():
            out[t] += int(r.get("mention_count") or 0)
    return out


def _topic_tickers(article_ids: list, window: int, limit: int = 15) -> list[dict]:
    """The tickers *most tied to this trend*, and the topic's sentiment impact on
    each. Ranked by **over-index**, not raw volume: how over-represented a name is
    in the topic's articles vs its baseline share of all news this week
    (`over_index = topic_share ÷ week_share`). This surfaces the names the story is
    unusually about (e.g. gold/energy on an inflation trend) instead of the mega-caps
    that are mentioned everywhere regardless of topic. Mention count is from
    `news_article_tickers`; the baseline from `news_trends_ticker_daily_v`; the impact
    is the mean per-article `sentiment_score` from `ticker_sentiment_heads_v` over the
    SAME articles (how this story hits the name, not its overall weekly sentiment)."""
    if not article_ids:
        return []
    client = get_supabase_client()
    ids = article_ids[:1000]

    freq: dict[str, int] = defaultdict(int)
    try:
        for i in range(0, len(ids), 300):        # chunk the IN() list
            tk = (client.schema(SCHEMA).table("news_article_tickers")
                  .select("ticker").in_("article_id", ids[i:i + 300]).execute().data or [])
            for r in tk:
                t = str(r.get("ticker") or "").upper().strip()
                if t and not t.isdigit():         # drop foreign numeric tickers
                    freq[t] += 1
    except Exception as e:                        # noqa: BLE001
        print(f"  (ticker link failed: {e})")
        return []

    # topic-scoped sentiment impact from the per-article-per-ticker view
    imp_sum: dict[str, float] = defaultdict(float)
    imp_n: dict[str, int] = defaultdict(int)
    try:
        for i in range(0, len(ids), 300):
            rows = (client.schema(SCHEMA).table("ticker_sentiment_heads_v")
                    .select("ticker, sentiment_score")
                    .in_("article_id", ids[i:i + 300]).execute().data or [])
            for r in rows:
                t = str(r.get("ticker") or "").upper().strip()
                s = r.get("sentiment_score")
                if t and not t.isdigit() and s is not None:
                    imp_sum[t] += float(s)
                    imp_n[t] += 1
    except Exception as e:                        # noqa: BLE001
        print(f"  (topic sentiment failed: {e})")

    # Baseline share of all news this week → each ticker's topic over-index.
    week_map = _week_ticker_mentions(window)
    week_total = sum(week_map.values()) or 1
    topic_total = sum(freq.values()) or 1

    rows = []
    for t, n in freq.items():
        # guard the source mismatch (link-count vs view mention_count): a name can't
        # be in more topic articles than it has all-week mentions, so floor base at n.
        base = max(week_map.get(t, 0), n)
        over = round((n / topic_total) / (base / week_total), 2) if base else None
        impact = round(imp_sum[t] / imp_n[t], 3) if imp_n.get(t) else None
        rows.append({"ticker": t, "topic_mentions": n,
                     "week_mentions": week_map.get(t) or None, "over_index": over,
                     "topic_impact": impact, "scored_articles": imp_n.get(t, 0)})

    # Rank by over-index (unusual concentration in THIS trend), floored by a minimum
    # mention count so a 1–2 mention obscure name can't top the board; names below the
    # floor fall to the tail, ordered by raw mentions, so the list stays complete.
    strong = [d for d in rows
              if d["topic_mentions"] >= TICKER_MENTION_FLOOR and d["over_index"] is not None]
    strong.sort(key=lambda d: (-d["over_index"], -d["topic_mentions"]))
    strong_ids = {d["ticker"] for d in strong}
    weak = sorted((d for d in rows if d["ticker"] not in strong_ids),
                  key=lambda d: -d["topic_mentions"])
    return (strong + weak)[:limit]


def co_tags(article_ids: list, topic_key: str, limit: int = 6) -> list[str]:
    """Theme tags that co-occur with the topic in its own articles (from
    news_articles.search_tags). Themes are stored lower-case, tickers upper-case —
    so we keep only the lower-case, non-generic, non-numeric tokens. These become
    the *related tags* the briefing preset subscribes to alongside the topic."""
    if not article_ids:
        return []
    client = get_supabase_client()
    ids, freq = article_ids[:1000], defaultdict(int)
    try:
        for i in range(0, len(ids), 300):
            rows = (client.schema(SCHEMA).table("news_articles")
                    .select("search_tags").in_("id", ids[i:i + 300]).execute().data or [])
            for r in rows:
                for tag in (r.get("search_tags") or []):
                    raw = str(tag or "").strip()
                    if not raw or raw != raw.lower():   # upper = ticker, skip
                        continue
                    if raw.isdigit() or raw == topic_key.lower() or _is_generic(raw):
                        continue
                    freq[raw] += 1
    except Exception as e:                              # noqa: BLE001
        print(f"  (co-tags failed: {e})")
        return []
    return [t for t, _ in sorted(freq.items(), key=lambda kv: -kv[1])[:limit]]


# A topic "clearly" has a screener only when a real screening overlaps its THEME
# (not merely the generic framing default). Below this topical-term overlap we flag
# that a dedicated screening should be created.
MIN_TOPICAL_FOR_CLEAR = 2


def match_screening(label: str, related_tags: list[str], framing: str,
                    tickers: list[str] | None = None) -> dict:
    """Pick the curated screening most connected to the topic, and decide whether it
    *clearly* supports the narrative. `topic_score` counts real topic-term overlap;
    a framing nudge (risk-off→short, opportunity→momentum/thematic) only breaks ties
    for the closest link — it does NOT count as topical support. If no screening clears
    the topical bar, `needs_new_screening` is set and a ready-to-build `suggested`
    screening spec is returned so the user can create one."""
    client = get_supabase_client()
    try:
        rows = (client.schema(SCHEMA).table("market_screenings")
                .select("slug,name,category,description,llm_prompt").execute().data or [])
    except Exception as e:                              # noqa: BLE001
        print(f"  (screenings fetch failed: {e})")
        rows = []
    terms = {w for s in [label, *related_tags] for w in str(s).lower().replace("_", " ").split()
             if len(w) > 2}
    scored = []
    for r in rows:
        slug = r.get("slug") or ""
        if not slug or (r.get("category") or "").lower() == "test" or slug.startswith("test"):
            continue
        text = " ".join(str(r.get(k) or "") for k in ("name", "category", "description", "llm_prompt")).lower()
        topic_score = sum(1 for t in terms if t in text)   # real topical overlap
        score = topic_score
        reasons = [f"matches {topic_score} topic term(s)"] if topic_score else []
        if framing == "risk-off" and "short" in text:
            score += 2
            reasons.append("a short screen fits a risk-off story")
        if framing == "opportunity" and ("momentum" in text or (r.get("category") or "") == "Thematic"):
            score += 1
            reasons.append("a momentum/thematic screen fits an opportunity story")
        scored.append({"slug": slug, "name": r.get("name"), "category": r.get("category"),
                       "score": score, "topic_score": topic_score,
                       "reason": "; ".join(reasons) or "closest available"})
    scored.sort(key=lambda s: (-s["score"], -s["topic_score"]))

    best = scored[0] if scored else {"slug": "", "name": None, "topic_score": 0, "score": 0,
                                     "reason": "no screenings available"}
    thematic_ok = best.get("category") == "Thematic" and best.get("topic_score", 0) >= 1
    clear = best.get("topic_score", 0) >= MIN_TOPICAL_FOR_CLEAR or thematic_ok

    matched = {**best, "is_fallback": not clear}
    if not clear:
        matched["reason"] = (f"no screening clearly covers #{label} — closest is "
                             f"{best.get('name') or 'the gallery'} "
                             f"({'framing fit only' if best.get('topic_score', 0) == 0 else 'weak overlap'})")

    return {
        "matched": matched,
        "candidates": scored[:4],
        "needs_new_screening": not clear,
        "suggested": (suggest_screening(label, related_tags, tickers, framing) if not clear else None),
    }


def suggest_screening(label: str, related_tags: list[str], tickers: list[str] | None,
                      framing: str) -> dict:
    """A ready-to-build screening spec for a topic that has no clear screener yet —
    so the user can create one to back the narrative. Grounded in the topic's own
    tags + the tickers it's moving; the prompt is a seed to refine, not a final scan."""
    tks = [t for t in (tickers or [])][:6]
    theme = label.strip()
    slug = "-".join(theme.lower().split())[:40] + "-radar"
    tag_str = ", ".join([label, *related_tags][:6])
    lean = ("relative weakness / breakdowns and short candidates" if framing == "risk-off"
            else "relative strength / momentum leaders")
    return {
        "slug": slug,
        "name": f"{theme.title()} Radar",
        "category": "Thematic",
        "focus": theme,
        "seed_tickers": tks,
        "tags": [label, *related_tags][:6],
        "description": (f"US stocks most exposed to {theme} — the week's dominant news trend. "
                        f"Surfaces the names moving on {tag_str}."),
        "llm_prompt": (f"Screen liquid US-listed stocks (avg volume > 1M) with clear exposure to "
                       f"{theme} ({tag_str}). Rank by {lean} over the last 1–4 weeks and by news "
                       f"intensity on this theme. Seed/anchor names to consider: {', '.join(tks) or '—'}. "
                       f"Exclude names with no fundamental or supply-chain link to the theme."),
        "how_to_create": "Create it in /protected/screenings (or the screenings admin), then re-run "
                         "this brief — the market-screening CTA will link to it automatically.",
    }


def _utm(content: str, topic_key: str) -> str:
    return (f"utm_source=meta&utm_medium=paid&utm_campaign=trend_{quote_plus(topic_key)}"
            f"&utm_content={content}")


def build_lead_magnets(topic_key: str, label: str, related_tags: list[str],
                       tickers: list[str], framing: str) -> dict:
    """The conversion payload: for each lead magnet, a ready deep-link that lands the
    user on the page pre-configured for THIS topic. Briefings → preset tags + tickers;
    market screening → the matched curated screener."""
    tags = [topic_key.lower()] + [t for t in related_tags if t != topic_key.lower()]
    tags, tks = tags[:5], tickers[:5]
    b_url = (f"{BRAND}/briefings?tags={quote_plus(','.join(tags))}"
             f"&tickers={quote_plus(','.join(tks))}&{_utm('news_briefing', topic_key)}")

    sc = match_screening(label, related_tags, framing, tickers)
    m = sc["matched"]
    s_path = f"/marketscreenings/{m['slug']}" if m.get("slug") else "/marketscreenings"
    s_url = f"{BRAND}{s_path}?{_utm('market_screening', topic_key)}"

    names = ", ".join(tks[:3])
    return {
        "news_briefing": {
            "tags": tags, "tickers": tks,
            "path": f"/briefings?tags={','.join(tags)}&tickers={','.join(tks)}",
            "url": b_url,
            "pitch": (f"A daily briefing on #{label}" + (f" + {names}" if names else "")
                      + " would have put this in your inbox before the open."),
        },
        "market_screening": {
            "matched_slug": m.get("slug"), "matched_name": m.get("name"),
            "match_reason": m.get("reason"), "is_fallback": m.get("is_fallback", False),
            "needs_new_screening": sc["needs_new_screening"],
            "suggested_screening": sc["suggested"],
            "candidates": sc["candidates"],
            "path": s_path, "url": s_url,
            "pitch": (f"The {m.get('name')} screen surfaces the names this story is moving."
                      if m.get("name") else "Browse the screeners that catch these moves."),
        },
    }


# ── the one story the ad should tell ──────────────────────────────────────────

def build_lead_story(winner: dict, why_points: list[dict], topic_tickers: list[dict]) -> dict:
    """Distil the brief into ONE narrative for the ad: the dominant topic + its single
    most prominent scored claim (the driver) + the tickers it's actually moving and the
    direction. This is the story the ad leads with — no downstream synthesis required."""
    driver = why_points[0] if why_points else None
    # split the topic's tickers by how the story is hitting them
    scored = [t for t in topic_tickers if t.get("topic_impact") is not None]
    hurt = sorted([t for t in scored if t["topic_impact"] <= -0.1],
                  key=lambda t: t["topic_impact"])
    helped = sorted([t for t in scored if t["topic_impact"] >= 0.1],
                    key=lambda t: -t["topic_impact"])
    most_affected = sorted(scored, key=lambda t: -abs(t["topic_impact"]))[:3]

    # framing from the driver's sign, tie-broken by the balance of affected names
    if driver and driver["impact"] <= -0.15:
        framing = "risk-off"
    elif driver and driver["impact"] >= 0.15:
        framing = "opportunity"
    else:
        net = sum(t["topic_impact"] for t in scored)
        framing = "risk-off" if net < 0 else "opportunity" if net > 0 else "mixed"

    delta = ("brand-new this week" if winner["isNew"]
             else f"up {winner['deltaPct']*100:.0f}% vs last week" if (winner["deltaPct"] or 0) >= 0
             else f"down {abs(winner['deltaPct']*100):.0f}% vs last week")
    event = (driver["text"].split(" — ")[0].strip() if driver else f"#{winner['label']} is dominating the tape")

    parts = [f"{event}." if not event.endswith((".", "!", "?")) else event,
             f"It's the week's most-discussed market story — {winner['current']} articles, {delta} — and it reads {framing} for stocks."]
    clause = ""
    if hurt:
        clause = "Pressuring " + ", ".join(t["ticker"] for t in hurt[:3])
    if helped:
        lift = ", ".join(t["ticker"] for t in helped[:3])
        clause = (clause + f" while lifting {lift}") if clause else f"Lifting {lift}"
    if clause:
        parts.append(clause + ".")
    narrative = " ".join(parts)

    return {
        "topic": winner["label"],
        "topic_key": winner["key"],
        "week_articles": winner["current"],
        "delta_pct": winner["deltaPct"],
        "framing": framing,
        "driver": ({"text": driver["text"], "impact": driver["impact"]} if driver else None),
        "most_affected": [{"ticker": t["ticker"], "topic_impact": t["topic_impact"],
                           "topic_mentions": t["topic_mentions"]} for t in most_affected],
        "narrative": narrative,
    }


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="Find the week's most talked-about news topic")
    ap.add_argument("--window-days", type=int, default=7, help="current window length (default 7)")
    ap.add_argument("--top", type=int, default=8, help="board size per mode (default 8)")
    ap.add_argument("--evidence", type=int, default=24, help="headline evidence to pull (default 24)")
    ap.add_argument("--topic", help="force a specific tag as the topic (overrides the auto-pick)")
    ap.add_argument("--include-generic", action="store_true",
                    help="allow structural tags (earnings, lawsuit, …) to win the topic pick")
    args = ap.parse_args()
    w = args.window_days

    print(f"\nReading news trends over the last {w} days (vs the prior {w})...")
    tags = build_tag_index(w)
    tickers = build_ticker_index(w)
    if not tags:
        print("No tag trends found — is the news pipeline populated?")
        return 1

    # the single dominant topic: heat over sizable, thematic (non-generic) tags
    def eligible(t):
        return t["current"] >= MIN_CURRENT_FOR_TOPIC and (args.include_generic or not _is_generic(t["key"]))

    pool = [t for t in tags if eligible(t)] or [t for t in tags if t["current"] >= MIN_CURRENT_FOR_TOPIC] or tags
    if args.topic:
        forced = next((t for t in tags if t["key"].lower() == args.topic.lower()
                       or t["label"].lower() == args.topic.lower()), None)
        if not forced:
            print(f"--topic '{args.topic}' not found in this window's tags.")
            return 1
        winner, pick_reason = forced, f"forced via --topic {args.topic}"
    else:
        winner = max(pool, key=_heat)
        pick_reason = "highest heat (volume × acceleration) among thematic tags"
    print(f"Top topic: #{winner['label']}  ({winner['current']} articles this week, "
          f"{'NEW' if winner['isNew'] else f'{winner['deltaPct']*100:+.0f}% vs prior'})  — {pick_reason}")

    ev = topic_evidence(winner["key"], w, args.evidence)

    # tickers mentioned WITHIN the topic + the topic's impact on each (from
    # topic_evidence); annotate with each ticker's overall weekly sentiment/mentions
    # for context (topic-scoped vs. how the name reads market-wide this week).
    week_sent = {t["key"]: t["avgSentiment"] for t in tickers}
    week_cur = {t["key"]: t["current"] for t in tickers}
    topic_tickers = [{
        **tt,
        "week_mentions": week_cur.get(tt["ticker"]),
        "week_sentiment": week_sent.get(tt["ticker"]),
    } for tt in ev["topic_tickers"][:12]]

    boards = {
        "tags": {m: _rank(tags, m, args.top) for m in ("mentions", "growth", "new")},
        "tickers": {m: _rank(tickers, m, args.top) for m in ("mentions", "growth", "new")},
    }

    # angle options for the downstream director
    thematic = [t for t in tags if not _is_generic(t["key"]) and t["current"] >= MIN_CURRENT_FOR_TOPIC]
    biggest = max(thematic, key=lambda t: t["current"], default=winner)
    # fastest-rising needs real volume, else an 11-article blip wins on +1000%
    rising_pool = [t for t in thematic if not t["isNew"] and t["current"] >= 25]
    rising = max(rising_pool or thematic, key=lambda t: (t["deltaPct"] or 0), default=winner)

    def _slim(t):
        return {"key": t["key"], "label": t["label"], "week_articles": t["current"],
                "delta_pct": t["deltaPct"], "is_new": t["isNew"]}

    lead_story = build_lead_story(winner, ev["why_points"], topic_tickers)
    print(f"\nLead story for the ad:\n  {lead_story['narrative']}")

    # conversion linkage: preset deep-links into each lead magnet for THIS topic.
    # Lead the preset with the names the story actually MOVES (most_affected), then
    # fill with the most-mentioned — so the briefing tracks what matters for this trend.
    related_tags = co_tags(ev["article_ids"], winner["key"])
    affected = [a["ticker"] for a in lead_story["most_affected"]]
    magnet_tickers = affected + [t["ticker"] for t in topic_tickers if t["ticker"] not in affected]
    lead_magnets = build_lead_magnets(winner["key"], winner["label"], related_tags,
                                      magnet_tickers, lead_story["framing"])
    print(f"  briefing → {lead_magnets['news_briefing']['url']}")
    ms = lead_magnets["market_screening"]
    print(f"  screener → {ms['url']}  ({ms['matched_name']})")
    if ms["needs_new_screening"]:
        sug = ms["suggested_screening"] or {}
        print(f"  ⚠ NO screener clearly covers #{winner['label']} — "
              f"consider creating “{sug.get('name')}” ({sug.get('category')}) to back this narrative.")

    end = datetime.now(timezone.utc).date()
    brief = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_days": w,
        "window": {"from": span_days(w)[0], "to": _day(end)},
        "pick_reason": pick_reason,
        # THE single story the ad generation uses — everything below is supporting detail
        "lead_story": lead_story,
        # conversion targets: preset deep-links into each lead magnet for this topic
        "lead_magnets": lead_magnets,
        "related_tags": related_tags,
        "top_topic": {
            "key": winner["key"],
            "label": winner["label"],
            "week_articles": winner["current"],
            "prior_articles": winner["previous"],
            "delta_pct": winner["deltaPct"],
            "is_new": winner["isNew"],
            "spark": winner["spark"],
            "heat": round(_heat(winner), 1),
            "why_its_trending": ev["why_points"],   # scored STORY_KEY_POINTS claims
            "tickers_in_play": topic_tickers,
            "headlines": ev["headlines"],
        },
        # alternate angles: the biggest thematic topic and the fastest-rising one
        "biggest_topic": _slim(biggest),
        "fastest_rising_topic": _slim(rising),
        "runner_up_topics": [
            _slim(t) for t in sorted(pool, key=_heat, reverse=True) if t["key"] != winner["key"]
        ][:5],
        "boards": boards,
    }

    out_dir = OUT_ROOT / _day(end)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "trend_brief.json").write_text(json.dumps(brief, indent=2, default=str))
    (out_dir / "trend_brief.md").write_text(_render_md(brief))
    print(f"\n✓ wrote {out_dir}/trend_brief.json")
    print(f"✓ wrote {out_dir}/trend_brief.md")
    return 0


def _pct(v):
    return "NEW" if v is None else f"{v*100:+.0f}%"


def _render_md(b: dict) -> str:
    t = b["top_topic"]
    ls = b.get("lead_story") or {}
    affected = "  ·  ".join(
        f"{a['ticker']} {a['topic_impact']:+.2f}" for a in (ls.get("most_affected") or [])
    ) or "—"
    L = [
        f"# Weekly trend brief — {b['window']['from']} → {b['window']['to']}",
        "",
        "## ⭐ THE STORY (use this for the ad)",
        "",
        f"> {ls.get('narrative', '—')}",
        "",
        f"- **framing:** {ls.get('framing', '—')}  ·  **most affected:** {affected}",
        "",
        "## 🎯 Lead-magnet links (the ad's CTA)",
    ]
    lm = b.get("lead_magnets") or {}
    nb, ms = lm.get("news_briefing") or {}, lm.get("market_screening") or {}
    if nb:
        L += [f"- **News briefing** — preset #{'  #'.join(nb.get('tags', []))}"
              + (f" · {', '.join(nb.get('tickers', []))}" if nb.get("tickers") else ""),
              f"    {nb.get('pitch','')}",
              f"    → {nb.get('url','')}"]
    if ms:
        fb = "  _(fallback)_" if ms.get("is_fallback") else ""
        L += [f"- **Market screening** — {ms.get('matched_name','the gallery')}{fb} "
              f"({ms.get('match_reason','')})",
              f"    {ms.get('pitch','')}",
              f"    → {ms.get('url','')}"]
        if ms.get("needs_new_screening"):
            sug = ms.get("suggested_screening") or {}
            L += ["",
                  f"> ⚠️ **No screener clearly supports #{t['label']} — create one to back this ad.**",
                  f"> Suggested: **{sug.get('name')}** · _{sug.get('category')}_ · slug `{sug.get('slug')}`",
                  f"> {sug.get('description','')}",
                  f"> Seed tickers: {', '.join(sug.get('seed_tickers') or []) or '—'}",
                  f"> Prompt seed: {sug.get('llm_prompt','')}",
                  f"> {sug.get('how_to_create','')}"]
    L += [
        "",
        f"## 🔥 Most talked-about topic: **#{t['label']}**",
        "",
        f"- **{t['week_articles']} articles** this week "
        f"({'brand-new' if t['is_new'] else _pct(t['delta_pct']) + ' vs prior week'})",
        f"- heat score {t['heat']}  ·  daily spark: {t['spark']}",
        "",
        "### Why it's trending (scored story key points)",
    ]
    why = t.get("why_its_trending") or []
    if why:
        for p in why[:8]:
            L.append(f"- {p['text']}  _(impact {p['impact']:+.2f})_")
    else:
        L.append("- (no scored key points found)")
    L += ["", f"### Tickers unusually tied to #{t['label']} (over-index vs the whole week)"]
    if t["tickers_in_play"]:
        for tk in t["tickers_in_play"]:
            imp = tk.get("topic_impact")
            imp_txt = "—" if imp is None else f"{imp:+.2f}"
            over = tk.get("over_index")
            over_txt = "—" if over is None else f"{over:.1f}×"
            wk = tk.get("week_mentions")
            wk_txt = "" if not wk else f"/{wk} all week"
            L.append(f"- **{tk['ticker']}** · {over_txt} over-index · "
                     f"{tk['topic_mentions']} in-topic{wk_txt} · topic impact {imp_txt}")
    else:
        L.append("- (none linked)")
    L += ["", "### Headline evidence"]
    for h in t["headlines"][:12]:
        src = f" — _{h['source']}_" if h.get("source") else ""
        L.append(f"- {h['title']}{src}")
        for kp in (h.get("key_points") or [])[:2]:
            L.append(f"    · {kp}")
    L += ["", "## Alternate angles",
          f"- **biggest thematic topic:** #{b['biggest_topic']['label']} "
          f"({b['biggest_topic']['week_articles']} articles · {_pct(b['biggest_topic']['delta_pct'])})",
          f"- **fastest-rising topic:** #{b['fastest_rising_topic']['label']} "
          f"({b['fastest_rising_topic']['week_articles']} articles · {_pct(b['fastest_rising_topic']['delta_pct'])})",
          "", "## Runner-up topics"]
    for r in b["runner_up_topics"]:
        L.append(f"- **#{r['label']}** · {r['week_articles']} articles · {_pct(r['delta_pct'])}")
    L += ["", "## Trending tickers (mentions)"]
    for it in b["boards"]["tickers"]["mentions"][:8]:
        L.append(f"- {it['label']} · {it['current']} · {_pct(it['deltaPct'])}")
    L.append("")
    return "\n".join(L)


if __name__ == "__main__":
    raise SystemExit(main())
