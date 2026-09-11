"""The three FMP reads behind one company_ceos row.

    profile                            -> who the CEO is (the same field the quote page prints)
    key-executives                     -> their title, birth year, pay, and the rest of the team
    governance-executive-compensation  -> the SEC proxy pay history

The profile is the authority on WHO. key-executives often lists several
people with "CEO" in the title (co-CEOs, CEOs of a subsidiary), and the quote
page shows the profile's name — so the link has to lead to that person, not to
whoever key-executives happens to list first.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

import requests

from services.ceos import names

BASE = "https://financialmodelingprep.com/stable"


class RateLimiter:
    """A shared minimum interval between calls, across worker threads."""

    def __init__(self, per_minute: int):
        self.interval = 60.0 / max(1, per_minute)
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            at = max(now, self._next)
            self._next = at + self.interval
        delay = at - time.monotonic()
        if delay > 0:
            time.sleep(delay)


class FmpError(RuntimeError):
    pass


class FmpQuotaError(FmpError):
    """The plan's bandwidth/call quota is spent. Retrying cannot help, and every
    further call only digs deeper, so the run stops rather than backing off."""


class Fmp:
    def __init__(self, per_minute: int = 600):
        self.key = os.environ["APIKEY"]
        self.limiter = RateLimiter(per_minute)
        self.session = requests.Session()

    def get(self, path: str, **params: Any) -> list[dict]:
        for attempt in range(4):
            self.limiter.wait()
            try:
                r = self.session.get(f"{BASE}/{path}", params={**params, "apikey": self.key}, timeout=30)
            except requests.RequestException as e:
                if attempt == 3:
                    raise FmpError(f"{path}: {e}") from e
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 429 and "limit reach" in r.text.lower():
                raise FmpQuotaError(f"{path}: {r.text.strip()[:160]}")
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(5 * (attempt + 1))
                continue
            if r.status_code != 200:
                raise FmpError(f"{path} {r.status_code}: {r.text[:200]}")
            data = r.json()
            if isinstance(data, dict):
                # FMP reports plan/limit errors as a 200 with an object body.
                raise FmpError(f"{path}: {str(data)[:200]}")
            return data or []
        raise FmpError(f"{path}: gave up after retries")


def _int(v: Any) -> int | None:
    try:
        return int(round(float(v))) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _pick_ceo(executives: list[dict], ceo_name: str) -> dict | None:
    by_name = [e for e in executives if e.get("name") and names.same_person(e["name"], ceo_name)]
    if by_name:
        titled = [e for e in by_name if names.is_ceo_title(e.get("title"))]
        return (titled or by_name)[0]
    return None


def _comp_rows(rows: list[dict], ceo_name: str) -> list[dict]:
    """The CEO's own proxy rows, one per year, newest first.

    `nameAndPosition` is a single free-text field ("Jen-Hsun Huang President
    and CEO"), so the name is recovered by position: the surname must appear
    and the first token must be a compatible given name.
    """
    sur = names.surname(ceo_name)
    giv = names.given(ceo_name)
    if not sur:
        return []

    by_year: dict[int, dict] = {}
    for r in rows:
        toks = names.name_tokens(r.get("nameAndPosition") or "")
        if sur not in toks:
            continue
        first = next((t for t in toks if len(t) > 1 and t not in names.HONORIFICS), None)
        if giv and first and first != sur and not (first.startswith(giv[:3]) or giv.startswith(first[:3])):
            continue
        year = _int(r.get("year"))
        if year is None:
            continue
        row = {
            "year": year,
            "salary": _int(r.get("salary")),
            "bonus": _int(r.get("bonus")),
            "stock_award": _int(r.get("stockAward")),
            "option_award": _int(r.get("optionAward")),
            "incentive": _int(r.get("incentivePlanCompensation")),
            "other": _int(r.get("allOtherCompensation")),
            "total": _int(r.get("total")),
            "filing_date": r.get("filingDate"),
            "link": r.get("link"),
            "name_and_position": r.get("nameAndPosition"),
        }
        prev = by_year.get(year)
        # A year appears in up to three consecutive proxies; the newest filing
        # carries any restatement.
        if prev is None or (row["filing_date"] or "") > (prev["filing_date"] or ""):
            by_year[year] = row
    return [by_year[y] for y in sorted(by_year, reverse=True)]


def fetch_company(fmp: Fmp, symbol: str) -> dict | None:
    """Everything for one symbol, or None when FMP names no CEO.

    Raises FmpError on transport/plan failures so the caller can tell "no CEO"
    (delete the row) apart from "could not ask" (leave the row alone).
    """
    profile = fmp.get("profile", symbol=symbol)
    if not profile:
        return None
    p = profile[0]
    raw = (p.get("ceo") or "").strip()
    ceo = names.clean_name(raw)
    if not ceo:
        return None

    executives = fmp.get("key-executives", symbol=symbol)
    comp = fmp.get("governance-executive-compensation", symbol=symbol)

    me = _pick_ceo(executives, ceo) or {}
    since = me.get("titleSince")

    team = []
    for e in executives:
        if not e.get("name") or e is me or not e.get("active", True):
            continue
        team.append({
            "name": names.clean_name(e["name"]) or e["name"],
            "title": e.get("title"),
            "pay": _int(e.get("pay")),
            "currency_pay": e.get("currencyPay"),
            "year_born": _int(e.get("yearBorn")),
        })

    return {
        "symbol": symbol,
        "company_name": p.get("companyName"),
        "exchange": p.get("exchange"),
        "sector": p.get("sector") or None,
        "industry": p.get("industry") or None,
        "country": p.get("country") or None,
        "market_cap": _int(p.get("marketCap")),
        "ceo_name_raw": raw,
        "ceo_name": ceo,
        "ceo_title": me.get("title"),
        "year_born": _int(me.get("yearBorn")),
        "title_since": str(since) if since else None,
        "pay": _int(me.get("pay")),
        "currency_pay": me.get("currencyPay"),
        "compensation": _comp_rows(comp, ceo),
        "executives": team,
    }
