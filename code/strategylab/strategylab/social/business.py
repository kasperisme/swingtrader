"""What the company actually is — the input a thesis has to be specific about.

Stage 2 generates growth theses without seeing the news, so that it cannot
paraphrase the consensus and manufacture a gap. But blind cannot mean ignorant:
a model given only a ticker produces "international expansion will drive
margins", which the saturation metric cannot score because it is not an
assertion about anything. The generator therefore sees the *business* and not
the *coverage*.

The load-bearing field is **segment revenue**, because it supplies materiality —
the quantity whose absence killed the L2 panel test. Crocs' own brand is 82% of
revenue and HEYDUDE is 18%, so a thesis about Crocs-brand demand moves the P&L
and a thesis about HEYDUDE moves a fifth of it. The panel regression that
averaged over 115 tickers treated a Big Mac claim about McDonald's (one menu
item, franchise-fee revenue) as the same kind of observation, and averaging over
materiality is how a real effect averages to zero.

Everything here is point-in-time by fiscal year as reported, so a thesis
generated for an earlier date can be given the mix that was known then.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..config import CACHE_ROOT
from ..data import fmp

log = logging.getLogger(__name__)

_V4 = "https://financialmodelingprep.com/api/v4"
_V3 = "https://financialmodelingprep.com/api/v3"


@dataclass
class Segment:
    name: str
    revenue: float
    share: float                     # of that year's total
    yoy: float | None = None         # growth vs the prior fiscal year


@dataclass
class BusinessProfile:
    ticker: str
    company: str = ""
    industry: str = ""
    sector: str = ""
    description: str = ""
    market_cap: float | None = None
    fiscal_year: str = ""
    revenue: float | None = None
    revenue_yoy: float | None = None
    gross_margin: float | None = None
    operating_margin: float | None = None
    product_segments: list[Segment] = field(default_factory=list)
    geographic_segments: list[Segment] = field(default_factory=list)
    brands: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def brief(self) -> str:
        """The compact rendering handed to the generator.

        Deliberately terse and numeric. A long narrative description would leak
        the very framing the blind-generation rule exists to exclude — vendor
        profile text is written from the same press the narrative comes from.
        """
        lines = [f"{self.ticker} — {self.company}",
                 f"industry: {self.industry} / {self.sector}"]
        if self.market_cap:
            lines.append(f"market cap: ${self.market_cap/1e9:.1f}bn")
        if self.revenue:
            g = f", {self.revenue_yoy:+.1%} YoY" if self.revenue_yoy is not None else ""
            lines.append(f"FY{self.fiscal_year} revenue: ${self.revenue/1e9:.2f}bn{g}")
        if self.gross_margin is not None:
            lines.append(f"gross margin {self.gross_margin:.1%}, "
                         f"operating margin {self.operating_margin:.1%}")
        if self.product_segments:
            lines.append("revenue by product/brand:")
            for s in self.product_segments:
                g = f"  ({s.yoy:+.1%} YoY)" if s.yoy is not None else ""
                lines.append(f"  - {s.name}: ${s.revenue/1e9:.2f}bn "
                             f"= {s.share:.0%} of revenue{g}")
        if self.geographic_segments:
            lines.append("revenue by geography: " + ", ".join(
                f"{s.name} {s.share:.0%}" for s in self.geographic_segments))
        if self.brands:
            lines.append("known brands/products: " + ", ".join(self.brands[:20]))
        return "\n".join(lines)


def _segments(symbol: str, kind: str) -> list[list[Segment]]:
    """Per-fiscal-year segment breakdowns, newest first.

    FMP returns `[{'2025-12-31': {name: revenue, ...}}, ...]`, one object per
    year with the date as the key. The shape changes between years for the same
    company — Crocs reported by sales channel in 2021 and by brand from 2022 —
    so year-over-year growth is only computed for names present in both.
    """
    url = f"{_V4}/revenue-{kind}-segmentation"
    try:
        rows = fmp._get(url, {"symbol": symbol, "structure": "flat",
                              "period": "annual"}) or []
    except Exception as exc:                                  # noqa: BLE001
        log.debug("%s segmentation unavailable for %s: %s", kind, symbol, exc)
        return []
    years = []
    for row in rows:
        if not isinstance(row, dict) or not row:
            continue
        date = next(iter(row))
        data = row[date]
        if not isinstance(data, dict) or not data:
            continue
        total = sum(v for v in data.values() if isinstance(v, (int, float)) and v > 0)
        if total <= 0:
            continue
        segs = [Segment(name=k, revenue=float(v), share=float(v) / total)
                for k, v in sorted(data.items(), key=lambda kv: -kv[1])
                if isinstance(v, (int, float)) and v > 0]
        years.append((date, segs))
    years.sort(key=lambda x: x[0], reverse=True)

    out = []
    for i, (_date, segs) in enumerate(years):
        if i + 1 < len(years):
            prior = {s.name: s.revenue for s in years[i + 1][1]}
            for s in segs:
                p = prior.get(s.name)
                s.yoy = (s.revenue / p - 1.0) if p else None
        out.append(segs)
    return out


class BusinessStore:
    """Disk-cached business profiles."""

    def __init__(self, cache_dir: Path | None = None):
        self.dir = Path(cache_dir or (CACHE_ROOT / "business"))
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, ticker: str) -> Path:
        return self.dir / f"{ticker.replace('/', '_').replace('.', '-')}.json"

    def load(self, ticker: str) -> BusinessProfile | None:
        p = self._path(ticker)
        if not p.exists():
            return None
        try:
            d = json.loads(p.read_text())
        except Exception:                                     # noqa: BLE001
            return None
        for k in ("product_segments", "geographic_segments"):
            d[k] = [Segment(**s) for s in d.get(k, [])]
        return BusinessProfile(**d)

    def build(self, ticker: str, brands: list[str] | None = None) -> BusinessProfile:
        prof = {}
        try:
            rows = fmp._get(f"{_V3}/profile/{ticker}") or []
            prof = rows[0] if rows else {}
        except Exception as exc:                              # noqa: BLE001
            log.debug("profile unavailable for %s: %s", ticker, exc)

        inc = []
        try:
            inc = fmp._get(f"{_V3}/income-statement/{ticker}",
                           {"period": "annual", "limit": 3}) or []
        except Exception as exc:                              # noqa: BLE001
            log.debug("income statement unavailable for %s: %s", ticker, exc)

        rev = revyoy = gm = om = None
        fy = ""
        if inc:
            cur = inc[0]
            fy = str(cur.get("calendarYear") or cur.get("date", ""))[:4]
            rev = float(cur.get("revenue") or 0) or None
            if len(inc) > 1 and rev:
                prior = float(inc[1].get("revenue") or 0)
                revyoy = (rev / prior - 1.0) if prior else None
            if rev:
                gm = float(cur.get("grossProfit") or 0) / rev
                om = float(cur.get("operatingIncome") or 0) / rev

        prod = _segments(ticker, "product")
        geo = _segments(ticker, "geographic")
        bp = BusinessProfile(
            ticker=ticker, company=prof.get("companyName") or ticker,
            industry=prof.get("industry") or "", sector=prof.get("sector") or "",
            description=(prof.get("description") or "")[:900],
            market_cap=float(prof.get("mktCap") or 0) or None,
            fiscal_year=fy, revenue=rev, revenue_yoy=revyoy,
            gross_margin=gm, operating_margin=om,
            product_segments=prod[0] if prod else [],
            geographic_segments=geo[0] if geo else [],
            brands=list(brands or []))
        self._path(ticker).write_text(json.dumps(bp.to_dict(), indent=1, default=str))
        return bp

    def ensure(self, ticker: str, brands: list[str] | None = None) -> BusinessProfile:
        got = self.load(ticker)
        if got is None:
            return self.build(ticker, brands)
        if brands and not got.brands:
            got.brands = list(brands)
        return got
