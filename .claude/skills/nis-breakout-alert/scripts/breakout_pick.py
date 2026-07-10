"""Pick the single best fresh breakout from the latest screening-agent result.

Reads the most recent ``user_screening_results`` row for the breakout screening,
no-ops on skipped / not-triggered runs, parses + ranks the CONFIRMED breakouts,
applies per-ticker dedup (don't re-alert a ticker within DEDUP_HOURS), and prints
the chosen candidate as JSON for the skill to render + post.

Usage (run from code/analytics):
    python ../../.claude/skills/nis-breakout-alert/scripts/breakout_pick.py
    python ... breakout_pick.py --result-id <uuid>          # test a specific run
    python ... breakout_pick.py --mark-posted LQDA --result-id <uuid>

Output JSON:
    {"action":"post","candidate":{...},"alt_candidates":[...],"summary":..., ...}
    {"action":"none","reason":"market closed / not triggered / already alerted"}
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path


def _find_analytics() -> Path:
    """Locate code/analytics so `shared` imports regardless of cwd."""
    marker = Path("services") / "screener" / "technical.py"
    candidates = [Path.cwd(), *Path.cwd().parents]
    for p in Path(__file__).resolve().parents:
        candidates.append(p / "code" / "analytics")
    for c in candidates:
        if (c / marker).exists():
            return c
    sys.exit("could not locate code/analytics")


_ANALYTICS_ROOT = _find_analytics()
sys.path.insert(0, str(_ANALYTICS_ROOT))

from shared.db import get_supabase_client  # noqa: E402

SCREENING_ID = "a884970e-dc2f-45c8-8e91-9d0504bebf12"
DEDUP_HOURS = 18  # don't re-alert the same ticker within this window

STATE_PATH = _ANALYTICS_ROOT / "output" / "breakout_alert" / "posted.json"

# "...CONFIRMED breakout on daily+1h —" / "on daily —" / "on 1h —"
_CONF_ON_RE = re.compile(r"breakout on (daily\+1h|daily|1h)\b")
# "daily=CONFIRMED (409.15 vs long entry 409.06, vol 1.86x)"
_FRAME_RE = re.compile(
    r"(daily|1h)=(CONFIRMED|in-band|no)\s*\(([\d.]+)\s*vs long entry\s*([\d.]+),\s*vol\s*([\d.]+)x\)"
)


def _parse_findings(kf: str):
    frames = {}
    for tf, state, price, entry, vol in _FRAME_RE.findall(kf):
        frames[tf] = {
            "state": state,
            "price": float(price),
            "entry": float(entry),
            "vol": float(vol),
        }
    m = _CONF_ON_RE.search(kf)
    return frames, (m.group(1) if m else None)


def _rank_key(c: dict):
    """Strongest first: dual-timeframe > daily-confirmed > higher volume."""
    dual = 1 if c["confirmed_on"] == "daily+1h" else 0
    daily_conf = 1 if c.get("daily", {}).get("state") == "CONFIRMED" else 0
    return (dual, daily_conf, c["max_vol"])


def _load_state() -> dict:
    if STATE_PATH.is_file():
        try:
            return json.loads(STATE_PATH.read_text())
        except Exception:
            return {}
    return {}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))


def _latest_row(client, result_id: str | None):
    q = (
        client.schema("swingtrader")
        .table("user_screening_results")
        .select("id,created_at,status,triggered,summary,data_used")
    )
    if result_id:
        q = q.eq("id", result_id)
    else:
        q = q.eq("screening_id", SCREENING_ID).order("created_at", desc=True)
    r = q.limit(1).execute()
    return r.data[0] if r.data else None


def cmd_pick(args) -> int:
    client = get_supabase_client()
    row = _latest_row(client, args.result_id)
    if not row:
        print(json.dumps({"action": "none", "reason": "no screening results found"}))
        return 0

    if row.get("status") != "done" or not row.get("triggered"):
        print(json.dumps({
            "action": "none",
            "reason": f"status={row.get('status')} triggered={row.get('triggered')} "
                      f"({(row.get('summary') or '')[:80]})",
            "result_id": row["id"],
        }))
        return 0

    du = row["data_used"]
    if isinstance(du, str):
        du = json.loads(du)

    candidates = []
    for v in du.get("verdicts", []):
        if not v.get("triggered_for_ticker"):
            continue
        frames, confirmed_on = _parse_findings(v.get("key_findings", ""))
        if not confirmed_on:
            continue
        candidates.append({
            "ticker": v["ticker"],
            "confirmed_on": confirmed_on,
            "daily": frames.get("daily"),
            "1h": frames.get("1h"),
            "max_vol": max((f["vol"] for f in frames.values()), default=0.0),
            "key_findings": v.get("key_findings", ""),
        })

    if not candidates:
        print(json.dumps({"action": "none", "reason": "triggered but no parseable breakouts",
                          "result_id": row["id"]}))
        return 0

    candidates.sort(key=_rank_key, reverse=True)
    featured = candidates[0]  # the single most-significant breakout = the headline

    # Dedup is keyed on the HEADLINE ticker: one roundup reel per *new* #1 breakout.
    # The board can shuffle hour-to-hour, but we only re-post when the headline changes
    # (or DEDUP_HOURS elapses), so the feed isn't spammed with near-identical reels.
    state = _load_state()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=DEDUP_HOURS)
    last = state.get(featured["ticker"], {}).get("at")
    if last and datetime.fromisoformat(last) > cutoff:
        print(json.dumps({
            "action": "none",
            "reason": f"headline {featured['ticker']} already alerted within {DEDUP_HOURS}h "
                      f"({len(candidates)} breakouts on the board)",
            "result_id": row["id"],
        }))
        return 0

    print(json.dumps({
        "action": "post",
        "result_id": row["id"],
        "created_at": row["created_at"],
        "summary": row.get("summary") or "",
        "triggered_count": du.get("triggered_count"),
        "featured": featured,            # the highlighted #1
        "board": candidates,             # ALL breakouts, ranked, for the board reel
    }, indent=2))
    return 0


def cmd_mark(args) -> int:
    state = _load_state()
    state[args.mark_posted.upper()] = {
        "at": datetime.now(timezone.utc).isoformat(),
        "result_id": args.result_id or "",
    }
    _save_state(state)
    print(f"marked {args.mark_posted.upper()} posted")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--result-id", help="inspect a specific result row (testing)")
    p.add_argument("--mark-posted", help="record TICKER as alerted (dedup)")
    args = p.parse_args(argv)
    return cmd_mark(args) if args.mark_posted else cmd_pick(args)


if __name__ == "__main__":
    raise SystemExit(main())
