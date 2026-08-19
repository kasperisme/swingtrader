"""Universe construction.

Two independent decisions, kept separate on purpose:

  * **Membership** — which tickers could ever be traded. Resolved once and
    cached. Includes delisted names, because a universe built only from names
    that still trade today is the single largest source of fabricated alpha in
    retail backtesting.
  * **Eligibility** — which of those may be traded on a given day. Resolved
    per-bar inside the backtest from the price panel itself (price, dollar
    volume, history length), so it is point-in-time by construction: a name
    becomes eligible the day it first satisfies the filter, not the day the
    universe file was written.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ..config import meta_cache_dir
from . import fmp

log = logging.getLogger(__name__)


class UniverseBuilder:
    def __init__(self, cache_dir: Path | None = None):
        self.dir = Path(cache_dir or meta_cache_dir())
        self.dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------ cache --
    def _load(self, name: str):
        p = self.dir / f"{name}.json"
        if p.exists():
            try:
                return json.loads(p.read_text())
            except Exception:
                return None
        return None

    def _store(self, name: str, payload) -> None:
        (self.dir / f"{name}.json").write_text(json.dumps(payload))

    # ------------------------------------------------------- membership --
    def listed(self, refresh: bool = False) -> list[dict]:
        cached = None if refresh else self._load("listed")
        if cached is not None:
            return cached
        rows: list[dict] = []
        for exch in ("NYSE", "NASDAQ"):
            try:
                rows.extend(fmp.exchange_symbols(exch))
            except Exception as exc:
                log.warning("exchange listing %s failed: %s", exch, exc)
        out = [{"symbol": r.get("symbol"), "sector": r.get("sector"),
                "industry": r.get("industry"), "exchange": r.get("exchangeShortName") or exch,
                "companyName": r.get("companyName"),
                "market_cap": r.get("marketCap"), "volume": r.get("volume"),
                "price": r.get("price"), "delisted_date": None}
               for r in rows if r.get("symbol")]
        self._store("listed", out)
        return out

    def delisted(self, refresh: bool = False) -> list[dict]:
        cached = None if refresh else self._load("delisted")
        if cached is not None:
            return cached
        try:
            rows = fmp.delisted_companies()
        except Exception as exc:
            log.warning("delisted feed unavailable (%s) — universe will be "
                        "survivorship-biased", exc)
            rows = []
        out = [{"symbol": r.get("symbol"), "sector": None, "industry": None,
                "exchange": r.get("exchange"), "delisted_date": r.get("delistedDate")}
               for r in rows if r.get("symbol")
               and (r.get("exchange") or "").upper() in {"NYSE", "NASDAQ", "AMEX"}]
        self._store("delisted", out)
        return out

    def sp500(self, refresh: bool = False) -> list[str]:
        cached = None if refresh else self._load("sp500")
        if cached is not None:
            return cached
        try:
            rows = fmp.sp500_constituents()
        except Exception as exc:
            log.warning("sp500 constituents unavailable: %s", exc)
            rows = []
        out = sorted({r.get("symbol") for r in rows if r.get("symbol")})
        self._store("sp500", out)
        return out

    def sectors(self, symbols: list[str], refresh: bool = False) -> dict[str, str]:
        """symbol -> sector. Treated as static: sector migration is rare enough
        that the residual look-ahead is negligible next to its cost to fix."""
        cached = self._load("sectors") or {}
        missing = [s for s in symbols if s not in cached]
        if missing and (refresh or len(missing) > 0):
            for i in range(0, len(missing), 500):
                try:
                    for row in fmp.profiles(missing[i:i + 500]):
                        if row.get("symbol"):
                            cached[row["symbol"]] = row.get("sector") or "Unknown"
                except Exception as exc:
                    log.warning("profile batch failed: %s", exc)
                    break
            self._store("sectors", cached)
        return {s: cached.get(s, "Unknown") for s in symbols}

    # ------------------------------------------------------------ build --
    def membership(self, source: str = "nyse_nasdaq", include_delisted: bool = True,
                   refresh: bool = False) -> list[dict]:
        """The full candidate set for a genome's `universe.source`."""
        rows = self.listed(refresh=refresh)
        if source == "sp500":
            keep = set(self.sp500(refresh=refresh))
            rows = [r for r in rows if r["symbol"] in keep]
        elif source == "liquid_mid_large":
            # Ranked by today's dollar volume, so membership carries a mild
            # look-ahead. Kept as an option because it is the cheapest universe
            # to sync; `nyse_nasdaq` is the unbiased default.
            def dv(r):
                try:
                    return float(r.get("price") or 0) * float(r.get("volume") or 0)
                except (TypeError, ValueError):
                    return 0.0
            rows = [r for r in rows if (r.get("market_cap") or 0) >= 1e9]
            rows = sorted(rows, key=dv, reverse=True)[:1500]
        if include_delisted:
            live = {r["symbol"] for r in rows}
            rows = rows + [r for r in self.delisted(refresh=refresh)
                           if r["symbol"] not in live]
        # Drop the obvious non-common-stock tickers: warrants, units, rights.
        out = [r for r in rows if r["symbol"] and not any(
            r["symbol"].endswith(sfx) for sfx in (".WS", ".U", ".RT", "-WT", "-UN", "-RT"))]
        seen, dedup = set(), []
        for r in out:
            if r["symbol"] in seen:
                continue
            seen.add(r["symbol"])
            dedup.append(r)
        return dedup

    def symbols(self, source: str = "nyse_nasdaq", include_delisted: bool = True,
                refresh: bool = False) -> list[str]:
        return sorted(r["symbol"] for r in self.membership(source, include_delisted, refresh))

    def coverage_report(self) -> dict:
        listed, delisted = self.listed(), self.delisted()
        # Roughly 6% of US listings delist per year; over a ten-year window a
        # complete universe should carry thousands of dead tickers. Anything
        # far short of that means the correction is partial, and the report
        # says so rather than implying the backtest is clean.
        adequate = len(delisted) >= 0.25 * len(listed)
        notes = [
            "Per-day eligibility (price, dollar volume, history length) is computed "
            "from the price panel itself, so it is point-in-time by construction.",
        ]
        if adequate:
            notes.append("Delisted names are included, so companies that failed are in "
                         "the universe.")
        else:
            notes.append(
                f"WARNING: only {len(delisted)} delisted tickers are available on this "
                "FMP plan (the feed is page-capped), against "
                f"{len(listed)} live listings. The universe is therefore still largely "
                "SURVIVORSHIP-BIASED: results are optimistic by roughly 1-4% CAGR on "
                "long-only US equity momentum. Treat absolute returns as an upper bound; "
                "relative comparisons between genomes remain valid because every genome "
                "sees the same universe.")
        notes.append("Historical index membership is not available on this plan, so "
                     "`universe.source=sp500` uses TODAY's members and is additionally "
                     "biased — prefer nyse_nasdaq for evaluation.")
        return {
            "listed": len(listed),
            "delisted": len(delisted),
            "survivorship_corrected": adequate,
            "note": " ".join(notes),
        }
