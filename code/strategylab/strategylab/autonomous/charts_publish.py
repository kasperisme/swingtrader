"""Upload research charts to Supabase Storage and catalogue them.

The images are the part of this record most likely to be read without the
surrounding text — someone screenshots the equity curve, not the paragraph
explaining that the search picked it out of 743 configurations. So every chart
is registered with three things the picture cannot carry by itself:

  sample_window      whether it is drawn on data the search optimised over
  trials_considered  how many configurations the plotted thing was selected from
  caption            what the axes mean, written by code that knows

`perf_equity` on the dev window is the specific chart this guards against. It
slopes up and to the right in every single run, because that is what it was
selected to do. Publishing it unlabelled would be the most dishonest thing in
the whole lab.
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
import os
import re
from dataclasses import dataclass
from pathlib import Path

from ..config import OUTPUT_ROOT, load_env

log = logging.getLogger(__name__)

DEFAULT_BUCKET = "research"

# Charts plus the small result/pre-registration files a write-up cites. Raw data
# panels are deliberately absent: they are large and usually vendor-licensed.
ALLOWED_MIME = ["image/png", "image/svg+xml", "application/json", "text/plain",
                "text/csv", "text/markdown"]


@dataclass(frozen=True)
class ChartKind:
    kind: str
    title: str
    caption: str
    sample_window: str
    sort: int


# Keyed on the filename the chart writers emit (strategylab/charts.py).
REGISTRY: dict[str, ChartKind] = {
    "perf_equity": ChartKind(
        "equity", "Equity curve",
        "Cumulative return of the selected strategy against buy-and-hold. Drawn "
        "on the development window — the same data the search optimised over, so "
        "this curve is an upper bound and not a forecast. The out-of-sample "
        "number is the one that counts.",
        "dev", 10),
    "perf_folds": ChartKind(
        "folds", "Performance by walk-forward fold",
        "Per-fold Sharpe across purged walk-forward splits. The question this "
        "answers is whether the edge survives in more than one regime, or "
        "whether a single lucky fold is carrying the median.",
        "dev", 20),
    "perf_trades": ChartKind(
        "trades", "Trade outcome distribution",
        "Distribution of per-trade R-multiples and the cumulative contribution "
        "of each. A long right tail carried by a handful of trades means the "
        "result depends on rare events and the Sharpe understates the risk.",
        "dev", 30),
    "perf_sides": ChartKind(
        "sides", "Long and short sleeves separately",
        "Each side's contribution. A short sleeve that does not pay for itself "
        "after borrow costs is complexity without return.",
        "dev", 40),
    "perf_exposure": ChartKind(
        "exposure", "Capital deployment over time",
        "Gross exposure through the backtest. Long flat stretches mean the "
        "headline Sharpe is computed over fewer bets than the date range "
        "suggests.",
        "dev", 50),
    "search_reward": ChartKind(
        "search_reward", "Does the search learn?",
        "Best-so-far reward against iteration. A rising line shows the optimiser "
        "is finding better configurations on the development window; it says "
        "nothing about whether those configurations generalise.",
        "n/a", 60),
    "search_sources": ChartKind(
        "search_sources", "Where proposals came from",
        "Proposal counts by origin (LLM, TPE, restart) beside which origin "
        "produced the winners — the credit-assignment view of the search.",
        "n/a", 70),
    "search_operators": ChartKind(
        "search_operators", "Which kinds of change paid off?",
        "Mutation operators ranked by improvement over parent. This is what the "
        "bandit uses to allocate its next proposals.",
        "n/a", 80),
}

# Flow-investigation charts: falsification tests, not strategy performance.
FLOW_REGISTRY: dict[str, ChartKind] = {
    "flow_coefficients": ChartKind(
        "diagnostic", "Flow-inertia coefficients",
        "Estimated persistence of the flow forcing function per name. The "
        "strategy hypothesis requires this to be reliably positive.",
        "n/a", 10),
    "flow_rho_distribution": ChartKind(
        "diagnostic", "Distribution of flow persistence",
        "Cross-sectional distribution of the AR(1) inertia estimate. Centred "
        "near zero means there is no persistent forcing function to trade.",
        "n/a", 20),
    "flow_momentum_by_rho": ChartKind(
        "diagnostic", "Momentum profits sorted on flow persistence",
        "Falsification test T1: momentum should concentrate in high-persistence "
        "names. If it does not, the inertia mechanism is not the driver.",
        "n/a", 30),
    "flow_event_time": ChartKind(
        "diagnostic", "Returns in event time after a forcing event",
        "Falsification test T2: returns should be positive over the flow "
        "half-life and fade after it.",
        "n/a", 40),
    "flow_impact_law": ChartKind(
        "diagnostic", "Square-root impact law fit",
        "Realised move against the square root of scaled flow. A strong "
        "in-sample fit here was circular — the forward-looking version of the "
        "same regression was insignificant.",
        "n/a", 50),
    "flow_proxy_comparison": ChartKind(
        "diagnostic", "Signed-volume proxy against mechanical flow",
        "Falsification test T5: the Tier-1 proxy and the Tier-2 ETF-derived "
        "flow should agree. Disagreement means the proxy measures something "
        "else, most likely volatility clustering.",
        "n/a", 60),
    "tier2_rho": ChartKind(
        "diagnostic", "Persistence of arbitrage-induced trading",
        "Weekly AR(1) of ETF creation/redemption flow attributed to each stock.",
        "n/a", 70),
}


def _slug(*parts: str) -> str:
    s = "-".join(p for p in parts if p)
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:90]


def png_size(p: Path) -> tuple[int | None, int | None]:
    """Width and height straight out of the PNG header.

    These end up as width/height attributes on the <img>. Without them a
    lazy-loaded image collapses to zero height, never scrolls into view, and
    therefore never loads — seven figures rendered as a 0px region. Reading the
    IHDR chunk avoids a Pillow dependency for 8 bytes of data.
    """
    try:
        head = p.read_bytes()[:24]
        if head[:8] != b"\x89PNG\r\n\x1a\n":
            return None, None
        return (int.from_bytes(head[16:20], "big"),
                int.from_bytes(head[20:24], "big"))
    except Exception:
        return None, None


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


class ChartPublisher:
    """Uploads chart images and registers them against the research record."""

    def __init__(self, publisher, bucket: str | None = None):
        load_env()
        self.pub = publisher          # a ResearchPublisher (owns the pg conn)
        self.bucket = bucket or os.environ.get("RESEARCH_BUCKET", DEFAULT_BUCKET)
        self._client = None

    def _storage(self):
        if self._client is None:
            from supabase import create_client
            url = os.environ["SUPABASE_URL"]
            key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ["SUPABASE_KEY"]
            self._client = create_client(url, key)
        return self._client.storage.from_(self.bucket)

    def ensure_bucket(self) -> tuple[bool, str]:
        """Create the public bucket if it is missing."""
        from supabase import create_client
        url = os.environ["SUPABASE_URL"]
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ["SUPABASE_KEY"]
        client = create_client(url, key)
        try:
            existing = {b.name for b in client.storage.list_buckets()}
        except Exception as exc:
            return False, f"cannot list buckets: {str(exc)[:160]}"
        if self.bucket in existing:
            return True, f"bucket '{self.bucket}' exists"
        try:
            client.storage.create_bucket(
                self.bucket, options={"public": True,
                                      "allowed_mime_types": ALLOWED_MIME,
                                      "file_size_limit": 10 * 1024 * 1024})
            return True, f"created public bucket '{self.bucket}'"
        except Exception as exc:
            return False, (f"cannot create bucket '{self.bucket}': {str(exc)[:160]}"
                           " — create it by hand in the dashboard (public, image/png)")

    # ------------------------------------------------------------------
    def upload(self, path: Path, object_key: str) -> str:
        st = self._storage()
        ct = mimetypes.guess_type(path.name)[0] or "image/png"
        st.upload(path=object_key, file=path.read_bytes(),
                  file_options={"content-type": ct, "upsert": "true",
                                "cache-control": "public, max-age=3600"})
        return st.get_public_url(object_key)

    def register(self, *, slug: str, title: str, caption: str, kind: str,
                 sample_window: str, storage_path: str, public_url: str,
                 nbytes: int, sha: str, campaign_run_id: str | None = None,
                 genome_hash: str | None = None, note_slug: str | None = None,
                 trials_considered: int | None = None, sort_order: int = 0,
                 published: bool = False, width: int | None = None,
                 height: int | None = None) -> None:
        conn = self.pub._connect()
        with conn.cursor() as cur:
            cur.execute(f"""
                INSERT INTO {self.pub.schema}.research_charts
                  (slug, title, caption, kind, sample_window, storage_path,
                   public_url, bytes, sha256, campaign_run_id, genome_hash,
                   note_slug, trials_considered, sort_order, published,
                   width, height, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now())
                ON CONFLICT (slug) DO UPDATE SET
                  title=EXCLUDED.title, caption=EXCLUDED.caption,
                  public_url=EXCLUDED.public_url, bytes=EXCLUDED.bytes,
                  sha256=EXCLUDED.sha256, trials_considered=EXCLUDED.trials_considered,
                  -- published is deliberately NOT overwritten: re-uploading an
                  -- image is a mechanical act, publishing is a human decision,
                  -- and a re-run silently unpublished seven live figures.
                  width=EXCLUDED.width,
                  height=EXCLUDED.height, updated_at=now()
            """, (slug, title, caption, kind, sample_window, storage_path,
                  public_url, nbytes, sha, campaign_run_id, genome_hash,
                  note_slug, trials_considered, sort_order, published,
                  width, height))
        conn.commit()

    # ------------------------------------------------------------------
    def publish_run_charts(self, run_dir: Path, trials: int | None = None,
                           genome_hash: str | None = None,
                           published: bool = False) -> list[str]:
        """Publish output/runs/<run>/charts/*.png for one campaign."""
        run_id = run_dir.name
        charts = sorted((run_dir / "charts").glob("*.png"))
        out = []
        for p in charts:
            meta = REGISTRY.get(p.stem)
            if meta is None:
                log.warning("no caption registered for %s — skipping rather than "
                            "publishing an unlabelled chart", p)
                continue
            key = f"runs/{run_id}/{p.name}"
            w, h = png_size(p)
            url = self.upload(p, key)
            slug = _slug(run_id, p.stem)
            self.register(slug=slug, title=f"{run_id} — {meta.title}",
                          caption=meta.caption, kind=meta.kind,
                          sample_window=meta.sample_window, storage_path=key,
                          public_url=url, nbytes=p.stat().st_size, sha=_sha256(p),
                          campaign_run_id=run_id, genome_hash=genome_hash,
                          trials_considered=trials, sort_order=meta.sort,
                          published=published, width=w, height=h)
            out.append(slug)
        return out

    def publish_flow_charts(self, note_slug: str | None = None,
                            published: bool = False) -> list[str]:
        """Publish the flow-inertia investigation figures."""
        out = []
        for root in ((OUTPUT_ROOT / "flow" / "charted"),
                     (OUTPUT_ROOT / "flow" / "tier2")):
            for p in sorted(root.glob("*.png")):
                meta = FLOW_REGISTRY.get(p.stem)
                if meta is None:
                    log.warning("no caption registered for %s — skipping", p)
                    continue
                key = f"flow/{p.name}"
                w, h = png_size(p)
                url = self.upload(p, key)
                slug = _slug("flow", p.stem)
                self.register(slug=slug, title=meta.title, caption=meta.caption,
                              kind=meta.kind, sample_window=meta.sample_window,
                              storage_path=key, public_url=url,
                              nbytes=p.stat().st_size, sha=_sha256(p),
                              note_slug=note_slug, sort_order=meta.sort,
                              published=published, width=w, height=h)
                out.append(slug)
        return out
