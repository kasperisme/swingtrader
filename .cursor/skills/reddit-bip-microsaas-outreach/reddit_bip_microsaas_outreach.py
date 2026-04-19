#!/usr/bin/env python3
"""
Dry-run (default): fetch r/buildinpublic + r/microsaas /new, flag invite-to-share
threads, print draft comments with https://www.newsimpactscreener.com/

Posting: set REDDIT_DRY_RUN=0 and a **user-scoped** token source:
  - **REDDIT_REFRESH_TOKEN** (recommended: no password in .env after one-time OAuth), or
  - **REDDIT_USERNAME** + **REDDIT_PASSWORD** (script app password grant).

Reddit does **not** allow comments with **client_credentials** alone — POST /api/comment
returns USER_REQUIRED ("Please log in to do that."). That is enforced server-side.

Requires: REDDIT_CLIENT_ID, REDDIT_SECRET, optional REDDIT_USER_AGENT in env.

Loads secrets from the first of:
  - REDDIT_ENV_FILE (path to a .env file), or
  - repo code/analytics/.env (walks parents from this script's directory).
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

try:
    from dotenv import load_dotenv as _load_dotenv_lib
except ImportError:
    _load_dotenv_lib = None  # type: ignore[misc, assignment]

SKILL_DIR = Path(__file__).resolve().parent


def _resolve_env_file() -> Path | None:
    explicit = os.environ.get("REDDIT_ENV_FILE", "").strip()
    if explicit:
        p = Path(explicit).expanduser()
        return p if p.is_file() else None
    for d in (SKILL_DIR, *SKILL_DIR.parents):
        candidate = d / "code" / "analytics" / ".env"
        if candidate.is_file():
            return candidate
    return None


def _load_dotenv_file(path: Path) -> None:
    """Minimal KEY=VALUE reader if python-dotenv is not installed."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if not key:
            continue
        val = val.strip().strip("'").strip('"')
        if key not in os.environ:
            os.environ[key] = val


SITE_URL = "https://www.newsimpactscreener.com/"

# Title or selftext; case-insensitive (substring match).
INVITE_PATTERNS: tuple[str, ...] = (
    r"share your project",
    r"share what you'?re building",
    r"show your",
    r"show us your",
    r"showcase",
    r"what are you building",
    r"what are you working on",
    r"drop your",
    r"link your (app|saas|site|tool|startup|project)",
    r"post your (app|saas|site|tool|startup|project)",
    r"roast my",
    r"feedback on (my|our)",
    r"critique my",
    r"tear down",
    r"looking for feedback",
    r"shameless plug",
    r"megathread",
    r"weekly.*(share|show|build|project)",
    r"(share|show).*(saturday|sunday|monday|tuesday|wednesday|thursday|friday|thread)",
)

_COMPILED = tuple(re.compile(p, re.I) for p in INVITE_PATTERNS)


def _load_env() -> None:
    env_path = _resolve_env_file()
    if env_path is None:
        return
    if _load_dotenv_lib is not None:
        _load_dotenv_lib(env_path)
    else:
        _load_dotenv_file(env_path)


def _req(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    data: bytes | None = None,
) -> tuple[int, dict]:
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=45) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body)
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(err)
        except json.JSONDecodeError:
            parsed = {"raw": err[:500]}
        return e.code, parsed


def get_token_readonly(client_id: str, secret: str, ua: str) -> str:
    auth = base64.b64encode(f"{client_id}:{secret}".encode()).decode()
    payload = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
    status, j = _req(
        "POST",
        "https://www.reddit.com/api/v1/access_token",
        headers={
            "User-Agent": ua,
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data=payload,
    )
    if status != 200:
        raise RuntimeError(f"token (read) failed HTTP {status}: {j}")
    tok = j.get("access_token")
    if not tok:
        raise RuntimeError(f"no access_token in response: {j}")
    return str(tok)


def get_token_user(client_id: str, secret: str, ua: str, user: str, password: str) -> str:
    auth = base64.b64encode(f"{client_id}:{secret}".encode()).decode()
    payload = urllib.parse.urlencode(
        {
            "grant_type": "password",
            "username": user,
            "password": password,
        }
    ).encode()
    status, j = _req(
        "POST",
        "https://www.reddit.com/api/v1/access_token",
        headers={
            "User-Agent": ua,
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data=payload,
    )
    if status != 200:
        raise RuntimeError(f"token (user) failed HTTP {status}: {j}")
    tok = j.get("access_token")
    if not tok:
        raise RuntimeError(f"no access_token in response: {j}")
    return str(tok)


def get_token_refresh(client_id: str, secret: str, ua: str, refresh_token: str) -> str:
    auth = base64.b64encode(f"{client_id}:{secret}".encode()).decode()
    payload = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
    ).encode()
    status, j = _req(
        "POST",
        "https://www.reddit.com/api/v1/access_token",
        headers={
            "User-Agent": ua,
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data=payload,
    )
    if status != 200:
        raise RuntimeError(f"token (refresh) failed HTTP {status}: {j}")
    tok = j.get("access_token")
    if not tok:
        raise RuntimeError(f"no access_token in response: {j}")
    return str(tok)


def resolve_user_write_token(client_id: str, secret: str, ua: str) -> str:
    """Bearer token that can act as a Reddit user (comments, etc.)."""
    refresh = os.environ.get("REDDIT_REFRESH_TOKEN", "").strip()
    if refresh:
        return get_token_refresh(client_id, secret, ua, refresh)
    user = os.environ.get("REDDIT_USERNAME", "").strip()
    pw = os.environ.get("REDDIT_PASSWORD", "").strip()
    if user and pw:
        return get_token_user(client_id, secret, ua, user, pw)
    print(
        "Cannot post comments: Reddit requires a user-scoped OAuth access token.\n"
        "  • Application-only tokens (client_id + REDDIT_SECRET via grant_type=client_credentials)\n"
        "    can read public listings, but POST /api/comment returns USER_REQUIRED.\n"
        "  • Set REDDIT_REFRESH_TOKEN (from one-time browser OAuth), or\n"
        "    REDDIT_USERNAME + REDDIT_PASSWORD for a script app password grant.\n",
        file=sys.stderr,
        flush=True,
    )
    raise SystemExit(1)


def fetch_new(token: str, ua: str, limit: int = 75) -> list[dict]:
    q = urllib.parse.urlencode({"limit": str(limit), "raw_json": "1"})
    url = f"https://oauth.reddit.com/r/buildinpublic+microsaas/new.json?{q}"
    status, j = _req(
        "GET",
        url,
        headers={"User-Agent": ua, "Authorization": f"bearer {token}"},
    )
    if status != 200:
        raise RuntimeError(f"listing failed HTTP {status}: {j}")
    children = j.get("data", {}).get("children", [])
    out: list[dict] = []
    for c in children:
        if not isinstance(c, dict) or c.get("kind") != "t3":
            continue
        d = c.get("data")
        if isinstance(d, dict):
            out.append(d)
    return out


def matches_invite(post: dict) -> bool:
    title = post.get("title") or ""
    body = post.get("selftext") or ""
    blob = f"{title}\n{body}"
    return any(p.search(blob) for p in _COMPILED)


def draft_comment() -> str:
    return (
        "If you’re tying **headlines to tickers/themes** while you ship, we built "
        f"[News Impact Screener]({SITE_URL}) for that—might save you some rabbit holes. "
        "Good luck with the build."
    )


def post_comment(token: str, ua: str, thing_id: str, text: str) -> dict:
    payload = urllib.parse.urlencode(
        {"api_type": "json", "thing_id": thing_id, "text": text}
    ).encode()
    status, j = _req(
        "POST",
        "https://oauth.reddit.com/api/comment",
        headers={
            "User-Agent": ua,
            "Authorization": f"bearer {token}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data=payload,
    )
    if status != 200:
        raise RuntimeError(f"comment failed HTTP {status}: {j}")
    errs = []
    if isinstance(j, dict):
        js = j.get("json")
        if isinstance(js, dict):
            errs = js.get("errors") or []
    if errs:
        raise RuntimeError(f"comment rejected: {errs}")
    return j


def main() -> int:
    _load_env()
    client_id = os.environ.get("REDDIT_CLIENT_ID", "").strip()
    secret = os.environ.get("REDDIT_SECRET", "").strip()
    ua = os.environ.get(
        "REDDIT_USER_AGENT",
        "NewsImpactScreenerOutreach/1.0 (by /u/KingGinger29)",
    ).strip()
    dry = os.environ.get("REDDIT_DRY_RUN", "1").strip().lower() in (
        "1",
        "true",
        "yes",
    )

    if not client_id or not secret:
        print(
            "Missing REDDIT_CLIENT_ID or REDDIT_SECRET. "
            "Set them in env or in code/analytics/.env (or set REDDIT_ENV_FILE).",
            file=sys.stderr,
        )
        return 1

    print("Fetching OAuth token (read-only)…")
    ro_token = get_token_readonly(client_id, secret, ua)
    posts = fetch_new(ro_token, ua)
    print(f"Loaded {len(posts)} posts from r/buildinpublic+microsaas /new\n")

    candidates = [p for p in posts if matches_invite(p)]
    if not candidates:
        print("No invite-to-share style matches in this window (heuristics are strict).")
        return 0

    max_age_h = float(os.environ.get("REDDIT_MAX_POST_AGE_HOURS", "72"))
    now = time.time()

    for p in candidates:
        created = float(p.get("created_utc") or 0)
        age_h = (now - created) / 3600.0
        if age_h > max_age_h:
            continue
        sub = p.get("subreddit") or "?"
        pid = p.get("name") or ""
        title = (p.get("title") or "").replace("\n", " ")[:120]
        permalink = p.get("permalink") or ""
        link = f"https://www.reddit.com{permalink}" if permalink else ""
        print(f"[{sub}] age={age_h:.1f}h")
        print(f"  {title}")
        print(f"  {link}")
        print(f"  thing_id={pid}")
        print("  --- draft comment ---")
        print(draft_comment())
        print()

    if dry:
        print("REDDIT_DRY_RUN is on: no comments posted. Set REDDIT_DRY_RUN=0 to enable POST.")
        return 0

    print("Posting comments (user-scoped token)…", flush=True)
    uw_token = resolve_user_write_token(client_id, secret, ua)
    for p in candidates:
        created = float(p.get("created_utc") or 0)
        age_h = (now - created) / 3600.0
        if age_h > max_age_h:
            continue
        pid = p.get("name") or ""
        if not pid.startswith("t3_"):
            continue
        try:
            resp = post_comment(uw_token, ua, pid, draft_comment())
            print("posted:", pid, json.dumps(resp)[:200])
        except RuntimeError as e:
            print("error:", pid, e, file=sys.stderr)
        time.sleep(float(os.environ.get("REDDIT_COMMENT_SLEEP_SEC", "8")))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
