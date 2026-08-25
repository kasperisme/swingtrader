"""The pinned momentum universe.

The screen itself is `prefilter.minervini` — eight criteria, unmodified, and
deliberately not tuned. What this module adds is the pinning: a manifest that
records the spec, the symbol list, the date range and a fingerprint of the
eligibility mask, so a study run months apart is provably run on the same
universe.

That is not bureaucracy. The single largest source of incomparable results in
this project was universe drift: the same incumbent genome scored Sharpe 0.464
and then 0.22 across a restart, and a third of the gap was the cached symbol
set having grown underneath the `--limit` flag.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import OUTPUT_ROOT
from ..prefilter import minervini, stage2

log = logging.getLogger(__name__)

SCREENS = {
    "minervini": lambda bank, spec: minervini(bank, rs_min=spec.rs_min),
    "minervini_strict": lambda bank, spec: minervini(bank, rs_min=80.0,
                                                     name="minervini_strict"),
    "stage2": lambda bank, spec: stage2(bank),
}


@dataclass
class UniverseSpec:
    """Frozen. Changing any field changes the fingerprint and invalidates
    comparisons with anything pinned under the old one."""

    screen: str = "minervini"
    rs_min: float = 70.0
    # Tradability floors applied ON TOP of the screen. The template says nothing
    # about whether an order can be filled.
    min_price: float = 5.0
    min_adv_usd: float = 5e6
    min_bars: int = 252
    version: str = "1.0.0"

    def key(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)


@dataclass
class MomentumUniverse:
    mask: np.ndarray                       # (n_days, n_symbols) bool, point-in-time
    symbols: list[str]
    dates: np.ndarray
    spec: UniverseSpec
    funnel: dict = field(default_factory=dict)
    fingerprint: str = ""

    # ---------------------------------------------------------------------
    @property
    def per_day(self) -> np.ndarray:
        return self.mask.sum(axis=1)

    def stats(self) -> dict:
        live = self.per_day[self.per_day > 0]
        return {
            "sessions": int(len(self.dates)),
            "symbols": int(len(self.symbols)),
            "name_days_qualified": int(self.mask.sum()),
            "median_names_per_day": int(np.median(live)) if live.size else 0,
            "min_names_per_day": int(live.min()) if live.size else 0,
            "max_names_per_day": int(live.max()) if live.size else 0,
            "ever_qualified": int(self.mask.any(axis=0).sum()),
            "first_session": str(self.dates[0]), "last_session": str(self.dates[-1]),
        }

    def summary(self) -> str:
        s = self.stats()
        rows = [f"Momentum universe '{self.spec.screen}' v{self.spec.version}  "
                f"[{self.fingerprint[:12]}]"]
        for k, v in self.funnel.items():
            rows.append(f"   {k:<38} {v:,}" if isinstance(v, int) else f"   {k:<38} {v}")
        rows.append(f"   {'names qualified per day (median)':<38} {s['median_names_per_day']:,}")
        rows.append(f"   {'                        (min-max)':<38} "
                    f"{s['min_names_per_day']}-{s['max_names_per_day']}")
        rows.append(f"   {'distinct names ever qualified':<38} {s['ever_qualified']:,}")
        return "\n".join(rows)

    # ---------------------------------------------------------------------
    def manifest(self) -> dict:
        return {"spec": asdict(self.spec), "fingerprint": self.fingerprint,
                "stats": self.stats(), "symbols": list(self.symbols)}

    def save(self, path: Path | None = None) -> Path:
        d = Path(path or (OUTPUT_ROOT / "momentum"))
        d.mkdir(parents=True, exist_ok=True)
        (d / "universe.json").write_text(json.dumps(self.manifest(), indent=2))
        np.savez_compressed(d / "universe_mask.npz", mask=self.mask,
                            dates=self.dates.astype("datetime64[D]"))
        return d / "universe.json"

    def verify(self, panel) -> dict:
        """Is this pin still valid for `panel`?

        Returns a report rather than raising, because the caller usually wants
        to say WHY a study cannot be compared to an earlier one, not just fail.
        """
        same_syms = list(panel.symbols) == list(self.symbols)
        same_dates = (len(panel.dates) == len(self.dates)
                      and bool(np.array_equal(np.asarray(panel.dates, dtype="datetime64[D]"),
                                              np.asarray(self.dates, dtype="datetime64[D]"))))
        return {"valid": bool(same_syms and same_dates),
                "symbols_match": same_syms, "dates_match": same_dates,
                "pinned_symbols": len(self.symbols), "panel_symbols": len(panel.symbols),
                "note": ("A pin is only meaningful against the panel it was built on. "
                         "A mismatch means results are not comparable to anything "
                         "pinned earlier — which is the failure this exists to catch.")}


def _fingerprint(spec: UniverseSpec, symbols: list[str], dates, mask: np.ndarray) -> str:
    h = hashlib.sha256()
    h.update(spec.key().encode())
    h.update("|".join(symbols).encode())
    h.update(np.asarray(dates, dtype="datetime64[D]").tobytes())
    h.update(np.packbits(mask).tobytes())
    return h.hexdigest()


def pin_universe(panel, bank, spec: UniverseSpec | None = None) -> MomentumUniverse:
    """Apply the screen plus the tradability floors and fingerprint the result."""
    spec = spec or UniverseSpec()
    if spec.screen not in SCREENS:
        raise ValueError(f"unknown screen {spec.screen!r}; have {sorted(SCREENS)}")

    res = SCREENS[spec.screen](bank, spec)
    mask = res.mask.copy()
    funnel = dict(res.funnel)

    close = panel.close
    adv = bank.get("dollar_volume_20d")
    mask &= close > spec.min_price
    funnel[f"+ price > ${spec.min_price:g}"] = int(mask.sum())
    mask &= np.greater_equal(adv, spec.min_adv_usd,
                             out=np.zeros(mask.shape, dtype=bool), where=np.isfinite(adv))
    funnel[f"+ ADV >= ${spec.min_adv_usd/1e6:g}M"] = int(mask.sum())
    mask &= bank.get("bars_available") >= spec.min_bars
    funnel[f"+ >= {spec.min_bars} bars of history"] = int(mask.sum())

    fp = _fingerprint(spec, list(panel.symbols), panel.dates, mask)
    return MomentumUniverse(mask=mask, symbols=list(panel.symbols), dates=panel.dates,
                            spec=spec, funnel=funnel, fingerprint=fp)


def load_universe(path: Path | None = None) -> tuple[dict, np.ndarray]:
    d = Path(path or (OUTPUT_ROOT / "momentum"))
    manifest = json.loads((d / "universe.json").read_text())
    z = np.load(d / "universe_mask.npz")
    return manifest, z["mask"]
