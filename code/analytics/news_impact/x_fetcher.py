"""
X (Twitter) fetcher for stock-related posts.

Uses the official X Python SDK (xdk) with app-only Bearer Token authentication.
Searches recent posts by cashtag (e.g. $AAPL) for a list of tickers.

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

# tweet_fields to request from the API
_TWEET_FIELDS = "created_at,author_id,public_metrics"

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
        self.bearer_token = os.environ.get("X_BEARER_TOKEN", "")
        if not self.bearer_token:
            raise RuntimeError("X_BEARER_TOKEN must be set in .env to use --x-news")

    def _build_query(self, tickers: list[str]) -> str:
        """
        Build an X search query for the given tickers.

        Searches cashtags ($AAPL OR $MSFT …) excluding retweets and replies
        to focus on original content.
        """
        cashtags = " OR ".join(f"${t}" for t in tickers[:10])  # X query max ~512 chars
        return f"({cashtags}) -is:retweet -is:reply lang:en"

    def fetch_stock_posts(
        self,
        tickers: list[str],
        max_results: int = 50,
    ) -> list[dict]:
        """
        Search recent X posts mentioning the given stock tickers.

        Parameters
        ----------
        tickers     : list of ticker symbols (e.g. ["AAPL", "MSFT"])
        max_results : max posts to return across all tickers (up to 100 per API page)

        Returns
        -------
        List of dicts with keys: symbol, title, text, url, published_at,
        publisher, public_metrics.  Empty list on failure or missing token.
        """
        from xdk import Client  # imported here so the module loads without xdk installed

        if not tickers:
            return []

        client = Client(bearer_token=self.bearer_token)
        query = self._build_query(tickers)
        # API max per page is 100; clamp to that
        per_page = min(max_results, 100)

        results: list[dict] = []
        try:
            for page in client.posts.search_recent(
                query=query,
                max_results=per_page,
                tweet_fields=_TWEET_FIELDS,
            ):
                if not page.data:
                    break
                for post in page.data:
                    metrics = getattr(post, "public_metrics", None) or {}
                    likes = metrics.get("like_count", 0) if isinstance(metrics, dict) else getattr(metrics, "like_count", 0)
                    if likes < _MIN_LIKES:
                        continue

                    text = (post.text or "").strip()
                    if not text:
                        continue

                    # Detect which ticker(s) this post mentions
                    symbol = _detect_symbol(text, tickers)
                    post_id = str(post.id)
                    url = _POST_URL.format(post_id=post_id)
                    published_at = _normalize_x_created_at(
                        getattr(post, "created_at", None)
                    )

                    # Use first 120 chars as title proxy
                    title = text[:120].replace("\n", " ")
                    if len(text) > 120:
                        title += "…"

                    if isinstance(metrics, dict):
                        metrics_dict = metrics
                    else:
                        metrics_dict = {
                            "like_count": getattr(metrics, "like_count", 0),
                            "retweet_count": getattr(metrics, "retweet_count", 0),
                            "reply_count": getattr(metrics, "reply_count", 0),
                            "quote_count": getattr(metrics, "quote_count", 0),
                        }

                    results.append({
                        "symbol": symbol,
                        "title": title,
                        "text": text,
                        "url": url,
                        "published_at": published_at,
                        "publisher": f"@{getattr(post, 'author_id', 'x_user')}",
                        "public_metrics": metrics_dict,
                        "post_id": post_id,
                    })

                if len(results) >= max_results:
                    break

        except Exception as exc:
            logger.warning("[XFetcher] search_recent failed: %s", exc)
            return []

        return results[:max_results]


def _detect_symbol(text: str, tickers: list[str]) -> str:
    """Return the first ticker from ``tickers`` mentioned as a cashtag in ``text``."""
    text_upper = text.upper()
    for ticker in tickers:
        if f"${ticker}" in text_upper:
            return ticker
    return tickers[0] if tickers else ""
