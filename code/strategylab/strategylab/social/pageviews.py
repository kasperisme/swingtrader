"""Wikimedia pageviews — the free, deep-history attention series.

Chosen over Google Trends for the first pass for one reason that matters more
than coverage: **Google Trends is normalised, rebased per query, and revised.**
The number you fetch today for 2019 is not the number you would have seen in
2019, the scale depends on which other queries were in the request, and Google
resamples. Every one of those is a way to manufacture a backtest that could not
have been traded. Pageviews are raw daily counts of a fixed article, never
rebased and never revised, which makes them the only free attention source that
is honestly backtestable.

What they cost in exchange:

* **Attention, not purchase.** A pageview is someone reading about a thing. The
  thesis needs someone *buying* it. This is the widest crack in the chain and
  L2 is what tests it.
* **Article-title drift.** Pages get renamed and merged; `Celsius_Holdings`
  starts in 2024-02 because the article was created then, not because the
  company did. `probe()` measures history depth so a name with a short series is
  excluded rather than silently truncating the panel.
* **Bot and spike contamination.** `all-access/user` already excludes known
  crawlers. A residual spike filter is deliberately NOT applied here: clipping
  the spikes would remove exactly the events the thesis is about.
"""

from __future__ import annotations

import gzip
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import CACHE_ROOT

log = logging.getLogger(__name__)

API = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
       "en.wikipedia/all-access/user/{article}/daily/{start}/{end}")
UA = "swingtrader-strategylab/0.1 (research; k.rasmussen92@gmail.com)"

# The API's own floor. Anything before this returns empty rather than an error.
EARLIEST = "20150701"


class PageviewStore:
    """Disk-cached daily pageviews, one gzipped CSV per article."""

    def __init__(self, cache_dir: Path | None = None):
        self.dir = Path(cache_dir or (CACHE_ROOT / "pageviews"))
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, article: str) -> Path:
        safe = urllib.parse.quote(article, safe="").replace("%", "_")[:120]
        return self.dir / f"{safe}.csv.gz"

    # ---------------------------------------------------------- fetch ----
    def fetch(self, article: str, start: str = EARLIEST,
              end: str | None = None) -> pd.DataFrame:
        end = end or pd.Timestamp.today().strftime("%Y%m%d")
        url = API.format(article=urllib.parse.quote(article.replace(" ", "_"), safe=""),
                         start=start, end=end)
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=45) as fh:
                    items = json.load(fh).get("items", [])
                break
            except urllib.error.HTTPError as exc:
                if exc.code == 404:                 # no such article
                    return pd.DataFrame(columns=["date", "views"])
                if attempt == 2:
                    raise
                time.sleep(2 * (attempt + 1))
            except Exception:                        # noqa: BLE001
                if attempt == 2:
                    raise
                time.sleep(2 * (attempt + 1))
        else:
            return pd.DataFrame(columns=["date", "views"])
        if not items:
            return pd.DataFrame(columns=["date", "views"])
        df = pd.DataFrame({"date": [pd.Timestamp(i["timestamp"][:8]) for i in items],
                           "views": [int(i["views"]) for i in items]})
        return df.sort_values("date").reset_index(drop=True)

    def save(self, article: str, df: pd.DataFrame) -> None:
        df.to_csv(self._path(article), index=False, compression="gzip")

    def load(self, article: str) -> pd.DataFrame | None:
        p = self._path(article)
        if not p.exists():
            return None
        try:
            df = pd.read_csv(p, parse_dates=["date"])
        except Exception:                            # noqa: BLE001
            return None
        return df if len(df) else None

    def ensure(self, articles: list[str], force: bool = False,
               workers: int = 8, progress_every: int = 250) -> dict:
        """Download anything missing, concurrently.

        Serial fetching runs at roughly one article a second — an hour for a
        few thousand pages, which is long enough that nobody re-runs it after a
        failure. The Wikimedia REST API has no published hard rate limit and
        asks only for a descriptive User-Agent and courteous concurrency, so a
        small pool is used rather than a sleep. Each article is written as soon
        as it lands, so an interrupted run keeps everything it fetched.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        todo = [a for a in articles if force or not self._path(a).exists()]
        stats = {"requested": len(articles), "fetched": 0, "empty": 0, "errors": 0,
                 "skipped": len(articles) - len(todo)}
        if not todo:
            return stats

        def one(article: str):
            try:
                df = self.fetch(article)
                self.save(article, df)
                return article, len(df), None
            except Exception as exc:                        # noqa: BLE001
                return article, 0, exc

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(one, a) for a in todo]
            for n, fut in enumerate(as_completed(futures), 1):
                article, rows, err = fut.result()
                if err is not None:
                    stats["errors"] += 1
                    log.debug("pageviews %s failed: %s", article, err)
                elif rows == 0:
                    stats["empty"] += 1
                else:
                    stats["fetched"] += 1
                if progress_every and n % progress_every == 0:
                    log.info("pageviews %d/%d", n, len(todo))
        return stats

    # ---------------------------------------------------------- probe ----
    def probe(self, article: str) -> dict:
        """History depth and volume — the two things that decide whether an
        article is usable. A page created last year cannot support a study that
        starts in 2015, and a page averaging four views a day is noise."""
        df = self.load(article)
        if df is None or df.empty:
            return {"article": article, "usable": False, "reason": "no data"}
        v = df["views"].to_numpy()
        return {"article": article, "obs": int(len(df)),
                "first": str(df["date"].iloc[0].date()),
                "last": str(df["date"].iloc[-1].date()),
                "median": float(np.median(v)), "max": int(v.max()),
                "usable": bool(len(df) >= 730 and np.median(v) >= 30)}

    # ---------------------------------------------------------- panel ----
    def panel(self, articles: list[str], start: str, end: str) -> pd.DataFrame:
        """Calendar-daily (date x article) view matrix.

        Missing days are zero-filled ONLY inside an article's own observed span;
        outside it they stay NaN. A page that did not exist yet must not look
        like a page nobody read — the first is unknown, the second is a
        measurement, and averaging them together is how a signal gets invented.
        """
        idx = pd.date_range(start, end, freq="D")
        cols: dict[str, pd.Series] = {}
        for a in articles:
            df = self.load(a)
            if df is None or df.empty:
                continue
            s = df.set_index("date")["views"].reindex(idx)
            lo, hi = df["date"].iloc[0], df["date"].iloc[-1]
            inside = (idx >= lo) & (idx <= hi)
            s[inside] = s[inside].fillna(0.0)
            cols[a] = s
        return pd.DataFrame(cols, index=idx)


def attention_growth(views: pd.DataFrame, window: int = 90,
                     baseline: int = 365, min_base: float = 20.0) -> pd.DataFrame:
    """Log growth of recent attention over its own trailing baseline.

    Three choices, each guarding a specific way this could go wrong:

    * **Ratio to the article's OWN baseline**, not a cross-sectional z-score.
      Wikipedia traffic differs by three orders of magnitude between a mega-cap
      brand and a niche one; a cross-sectional comparison would sort by fame.
    * **Log**, so a doubling counts the same whether it starts from 100 or
      100,000 — the thesis is about *acceleration*, not level.
    * **A baseline floor.** Below `min_base` daily views the ratio is dominated
      by integer noise and produces enormous spurious growth readings; those are
      returned as NaN rather than as the largest values in the panel, which is
      where they would otherwise sort.

    Everything is trailing and closed at t, so the value on day t uses only days
    <= t.
    """
    recent = views.rolling(window, min_periods=max(10, window // 3)).mean()
    base = views.rolling(baseline, min_periods=max(60, baseline // 4)).mean()
    ok = base >= min_base
    with np.errstate(invalid="ignore", divide="ignore"):
        g = np.log(recent / base)
    return g.where(ok & np.isfinite(g))
