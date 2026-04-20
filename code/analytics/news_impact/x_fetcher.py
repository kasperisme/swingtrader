"""
X (Twitter) fetcher for stock-related posts.

Uses the official X Python SDK (xdk) with app-only Bearer Token authentication.
Searches recent posts by cashtag (e.g. $AAPL) for a list of tickers.
Can optionally restrict search to specific X accounts.

Environment variable required:
  X_BEARER_TOKEN  — app-only bearer token from the X developer portal
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Minimum engagement threshold — posts below this are likely noise
_MIN_LIKES = 5


# X post URL template
_POST_URL = "https://x.com/i/web/status/{post_id}"


def _normalize_x_created_at(raw: Optional[str]) -> Optional[str]:
    """Convert X ISO-8601 created_at (UTC) to UTC ISO-8601 string."""
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).isoformat(timespec="seconds")
    except Exception:
        return str(raw)


class XFetcher:
    """
    Fetches recent X posts mentioning stock cashtags via the X API.

    Usage::

        fetcher = XFetcher()
        posts = fetcher.fetch_stock_posts(["AAPL", "MSFT"], max_results=20)
        for post in posts:
            print(post["title"], post["text"])
    """

    def __init__(self) -> None:
        import urllib.parse

        raw_token = os.environ.get("X_BEARER_TOKEN", "")
        if not raw_token:
            raise RuntimeError("X_BEARER_TOKEN must be set in .env to use --x-news")
        # URL-decode the token if it's encoded (as it often is in .env files)
        self.bearer_token = urllib.parse.unquote(raw_token)

    def _build_query(
        self, tickers: Optional[list[str]] = None, accounts: Optional[list[str]] = None
    ) -> str:
        """
        Build an X search query for the given tickers and/or accounts.

        At least one of ``tickers`` or ``accounts`` must be provided.
        Excludes retweets and replies to focus on original content.
        """
        parts: list[str] = []

        if tickers:
            parts.append("(" + " OR ".join(f"${t}" for t in tickers[:10]) + ")")

        if accounts:
            clean_accounts = [acc.lstrip("@") for acc in accounts]
            account_query = " OR ".join(f"from:{acc}" for acc in clean_accounts[:10])
            if len(clean_accounts) > 1:
                parts.append("(" + account_query + ")")
            else:
                parts.append(account_query)

        if not parts:
            raise ValueError("At least one of tickers or accounts is required")

        return " ".join(parts)

    def fetch_stock_posts(
        self,
        tickers: Optional[list[str]] = None,
        max_results: int = 50,
        accounts: Optional[list[str]] = None,
    ) -> list[dict]:
        """
        Search all X posts (full archive) mentioning the given stock tickers and/or accounts.

        Parameters
        ----------
        tickers     : list of ticker symbols (e.g. ["AAPL", "MSFT"]), or None if only filtering by account
        max_results : max posts to return across all tickers (up to 100 per API page)
        accounts    : list of X account names (e.g. ["realDonaldTrump", "elonmusk"])

        At least one of ``tickers`` or ``accounts`` must be provided.

        Returns
        -------
        List of dicts with keys: symbol, title, text, url, published_at,
        publisher, public_metrics.  Empty list on failure or missing token.
        """
        from xdk import (
            Client,
        )  # imported here so the module loads without xdk installed

        if not tickers and not accounts:
            return []

        client = Client(bearer_token=self.bearer_token)
        query = self._build_query(tickers=tickers, accounts=accounts)
        # search_recent: min 10, max 100
        per_page = max(10, min(max_results, 100))

        results: list[dict] = []
        try:
            for page in client.posts.search_recent(
                query=query,
                max_results=per_page,
                tweet_fields=["created_at", "author_id"],
                expansions=["author_id"],
                user_fields=["username"],
            ):
                if not page.data:
                    break

                # Build id→username lookup from expanded users
                users_by_id: dict[str, str] = {}
                includes = getattr(page, "includes", None)
                if includes:
                    raw_users = (
                        includes.get("users", []) if isinstance(includes, dict)
                        else getattr(includes, "users", None) or []
                    )
                    for user in raw_users:
                        uid = str(user.get("id") if isinstance(user, dict) else user.id)
                        uname = (user.get("username") if isinstance(user, dict) else user.username) or ""
                        users_by_id[uid] = uname

                for post in page.data:
                    # SDK may return dicts or objects depending on version
                    if isinstance(post, dict):
                        text = (post.get("text") or "").strip()
                        post_id = str(post.get("id") or "")
                        created_at = post.get("created_at")
                        author_id = str(post.get("author_id") or "")
                    else:
                        text = (post.text or "").strip()
                        post_id = str(post.id)
                        created_at = getattr(post, "created_at", None)
                        author_id = str(getattr(post, "author_id", "") or "")

                    if not text:
                        continue

                    symbol = _detect_symbol(text, tickers)
                    url = _POST_URL.format(post_id=post_id)
                    published_at = _normalize_x_created_at(created_at)
                    username = users_by_id.get(author_id, author_id or "x_user")

                    title = text[:120].replace("\n", " ")
                    if len(text) > 120:
                        title += "…"

                    results.append(
                        {
                            "symbol": symbol,
                            "title": title,
                            "text": text,
                            "url": url,
                            "published_at": published_at,
                            "publisher": f"@{username}",
                            "post_id": post_id,
                        }
                    )

                break

        except Exception as exc:
            exc_msg = str(exc)
            if "402" in exc_msg:
                print(
                    f"[XFetcher] search_recent failed: 402 Payment Required — "
                    f"X API credits exhausted. Returning {len(results)} post(s) already fetched."
                )
            elif "429" in exc_msg:
                print(
                    f"[XFetcher] search_recent rate-limited (429). "
                    f"Returning {len(results)} post(s) already fetched."
                )
            else:
                print(
                    f"[XFetcher] search_recent failed: {exc!r}. "
                    f"Returning {len(results)} post(s) already fetched."
                )

        return results[:max_results]


def _detect_symbol(text: str, tickers: Optional[list[str]] = None) -> str:
    """Return the first ticker from ``tickers`` mentioned as a cashtag in ``text``, or empty string."""
    if not tickers:
        return ""
    text_upper = text.upper()
    for ticker in tickers:
        if f"${ticker}" in text_upper:
            return ticker
    return tickers[0]
