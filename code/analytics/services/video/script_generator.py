from __future__ import annotations

import json
import logging
import os

import httpx

from .config import OLLAMA_BASE_URL, OLLAMA_TIKTOK_MODEL

log = logging.getLogger(__name__)

# Spoken blocks in voiceover order
SCRIPT_BLOCKS = [
    "hook",
    "market_regime",
    "signal",
    "why_it_matters",
    "what_to_watch",
    "contrarian",
    "cta",
]


def _score_tier(score: float) -> str:
    """Translate a -1..+1 news impact score into human language."""
    abs_s = abs(score)
    if abs_s >= 0.6:
        tier = "strong"
    elif abs_s >= 0.3:
        tier = "moderate"
    elif abs_s >= 0.1:
        tier = "mild"
    else:
        return "neutral"
    direction = "bullish" if score > 0 else "bearish"
    return f"{tier} {direction}"


def build_tiktok_prompt(
    summary: dict,
    articles: list[dict],
    tickers_map: dict[int, list[str]],
    date_str: str,
) -> str:
    top_5 = articles[:5]

    articles_block = ""
    for i, a in enumerate(top_5, 1):
        title = a.get("title", "Untitled")[:80]
        tickers = tickers_map.get(a["id"], [])
        ticker_str = ", ".join(tickers[:3]) if tickers else ""
        articles_block += f"\n{i}. {title}"
        if ticker_str:
            articles_block += f" [{ticker_str}]"

    cluster_block = ""
    for c in summary["cluster_ranking"][:5]:
        tier = _score_tier(c["score"])
        cluster_block += f"\n  - {c['label']}: {tier} ({c['article_count']} articles)"

    dims_block = ""
    for d in summary["top_dimensions"][:5]:
        tier = _score_tier(d["avg_score"])
        dims_block += f"\n  - {d['label']}: {tier}"

    all_tickers: list[str] = []
    for tlist in tickers_map.values():
        for t in tlist:
            if t not in all_tickers:
                all_tickers.append(t)
    ticker_str = ", ".join(all_tickers[:8])

    prompt = f"""You are writing a TikTok script for a pre-market stock analysis channel. Date: {date_str}.
The video is 75-90 seconds. Voiceover only — no on-screen prompts.

## DATA
Top stories:
{articles_block}

Cluster momentum (news impact scores, -1.0 to +1.0):
{cluster_block}

Key dimensions:
{dims_block}

Tickers mentioned: {ticker_str or 'none'}

## THE 7-BLOCK STRUCTURE
Each block maps to one slide. Write each one according to its purpose.

### Block 1 — hook (5-10 words, spoken first ~3 sec)
The make-or-break opener. 80% of viewers decide here.
Pick the single most extreme or contrarian signal from the data.
Formula options:
  - Lead with the most extreme score: "One sector is getting smoked this morning."
  - Name the tension: "Two clusters are moving in opposite directions — here's why."
  - Drop a ticker cold: "Nvidia is sitting on a level that matters today."
  - Contrarian frame: "Everyone's watching the Fed. Wrong thing to watch."
NEVER: "Good morning traders", "Hey everyone", "Today we're breaking down", "The market is moving", greetings.
Fragments OK. State, don't introduce.

### Block 2 — market_regime (15-20 words, ~7 sec)
One sentence only. SPY or QQQ direction. Uptrend, downtrend, distribution, follow-through, chop.
Infer from the cluster momentum data — if macro/sector clusters are mostly bullish, call it.
Example: "Market is in a confirmed uptrend, day four of follow-through on above-average volume."

Also output:
- market_regime_label: 2-4 words for display (e.g. "UPTREND DAY 4", "UNDER PRESSURE", "DISTRIBUTION", "MIXED SIGNALS")
- regime_direction: "bullish", "bearish", or "neutral"

### Block 3 — signal (50-65 words, ~25 sec)
The meat. 2-4 sentences.
- Name the specific cluster or dimension that is the lead story
- Name 1-2 tickers with a specific, concrete observation (not vague)
- State direction and magnitude with the actual score if useful
- Vague = skip. Specific ticker + pattern + score = high shareability.
Example: "Supply chain exposure is taking a hit — score dropped to minus 0.6 after three logistics misses this week. That puts $FDX and $UPS on the watch list. Both are near key support after failing to reclaim their 50-day."

### Block 4 — why_it_matters (25-35 words, ~13 sec)
One to two sentences connecting the signal to something bigger.
Volume confirmation, institutional footprint, earnings proximity, macro catalyst.
Use the news impact scores and factor dimensions to justify.
Example: "This isn't just noise — earnings revision scores for this cluster dropped four weeks running, which historically precedes a sector breakdown."

### Block 5 — what_to_watch (25-35 words, ~13 sec)
Concrete action framing — not advice, just the specific trigger.
A price level, volume threshold, earnings date, or confirmation signal.
Example: "Watch for $FDX to either reclaim 240 on volume, or break the 232 level that's held since July. One of those happens today."

### Block 6 — contrarian (15-25 words, ~10 sec)
One sentence only. What invalidates the thesis.
This is the trust-builder — signals you're analytical, not promotional. Engagement spikes when you give people something to argue about.
Example: "That said — if CPI comes in soft this week, the rate-sensitive names flip, and this whole setup inverts."

### Block 7 — cta (15-20 words, ~10 sec)
One ask only — never both follow + comment.
Rotate between:
  - Follower-growth: "Follow @newsimpactscrnr for tomorrow's setup before the market opens."
  - Engagement: "Comment your watchlist — let's see who's watching the same names."
Mention @newsimpactscrnr exactly once.

## TONE RULES (apply to all blocks)
- Sound like a sharp friend who trades, not a financial influencer
- The data above uses human labels (e.g. "strong bullish", "moderate bearish") — use those exact phrases
- NEVER cite raw numbers from the scoring system (no "0.45", "-0.6", "+0.32", etc.) — these are meaningless to viewers
- Describe momentum in plain language: "building headwinds", "clear tailwind", "turning bearish", "near neutral", "under pressure"
- Name specific tickers and describe what the news means for them — not the score, but the real-world implication
- Short sentences. Fragments hit harder than clauses.
- Banned: "let's dive in", "breaking down", "at the end of the day", "it's important to note",
  "don't sleep on", "stay tuned", "massive", "game-changing", "you need to know", "make sure to",
  "could potentially", "might want to consider"
- No hedging. State it flat or don't say it.

## OUTPUT
JSON only — no markdown, no commentary.
{{
  "hook": "5-10 word opener",
  "market_regime": "one sentence on market direction",
  "market_regime_label": "2-4 word display label (ALL CAPS)",
  "regime_direction": "bullish|bearish|neutral",
  "signal": "2-4 sentences with tickers and specific observations",
  "why_it_matters": "1-2 sentences on institutional/volume/earnings context",
  "what_to_watch": "one sentence with specific level or trigger",
  "contrarian": "one sentence invalidating the thesis",
  "cta": "one sentence, mention @newsimpactscrnr",
  "hashtags": ["#stockmarket", "#premarket", "#trading", ...]
}}"""

    return prompt


async def generate_script(
    summary: dict,
    articles: list[dict],
    tickers_map: dict[int, list[str]],
    date_str: str,
) -> dict:
    prompt = build_tiktok_prompt(summary, articles, tickers_map, date_str)

    payload = {
        "model": OLLAMA_TIKTOK_MODEL,
        "stream": False,
        "think": False,
        "options": {"num_predict": 1024},
        "format": "json",
        "messages": [
            {
                "role": "system",
                "content": (
                    "You write TikTok scripts for a pre-market stock news channel. "
                    "You sound like a trader, not a content creator. "
                    "You use specific data, not hype. "
                    "You output only valid JSON. No markdown. No commentary."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    }

    url = f"{OLLAMA_BASE_URL}/api/chat"
    log.info("Calling Ollama for TikTok script, model=%s", OLLAMA_TIKTOK_MODEL)

    async with httpx.AsyncClient() as client:
        r = await client.post(url, json=payload, timeout=120.0)

    if r.status_code != 200:
        raise RuntimeError(f"Ollama returned HTTP {r.status_code}: {r.text[:200]}")

    raw = r.json()["message"]["content"].strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        script = json.loads(raw)
    except json.JSONDecodeError:
        log.error("Failed to parse Ollama JSON response:\n%s", raw[:500])
        raise

    required = set(SCRIPT_BLOCKS) | {"hashtags", "market_regime_label", "regime_direction"}
    missing = required - script.keys()
    if missing:
        raise ValueError(f"Script missing keys: {missing}")

    full_text = " ".join(script.get(b, "") for b in SCRIPT_BLOCKS)
    log.info("Script generated: %d words", len(full_text.split()))
    return script
