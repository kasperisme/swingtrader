"""Attach the files a write-up was computed from.

A research note that says "Artifacts: output/flow/stage1/{...}" is citing a
directory on one laptop. That reads as evidence and is not: nobody outside this
machine can open it. Either the file is downloadable or the note should say why
it is not.

Both halves matter for replication. The pre-registration record is the whole
basis for calling a result pre-registered — without it, a reader has only my
word that the hypotheses were fixed before the data was seen. The price panel,
by contrast, is derived from a licensed vendor feed and is not mine to
redistribute; that is a fact a replicator needs stated plainly, along with what
they would need to rebuild it themselves.
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
from dataclasses import dataclass
from pathlib import Path

from ..config import OUTPUT_ROOT

log = logging.getLogger(__name__)

# Files above this are not worth pushing through a public bucket; they are
# almost always raw data panels, which are also the ones most likely to be
# vendor-licensed.
MAX_PUBLISH_BYTES = 8 * 1024 * 1024


@dataclass
class Artifact:
    name: str
    description: str
    path: Path | None = None
    available: bool = True
    reason: str = ""
    sort: int = 0


VENDOR_DATA_REASON = (
    "Not redistributable — this panel is built from licensed Financial Modeling "
    "Prep data, so the derived results are publishable but the underlying price "
    "and fundamental history is not. Rebuild it with an FMP key using the sync "
    "commands in the strategylab README; the pre-registration and results files "
    "here pin down exactly what was computed from it."
)

# Artifacts for the write-ups that reference files. Keyed by note slug.
NOTE_ARTIFACTS: dict[str, list[Artifact]] = {
    "stage-1-result-flow-inertia-momentum": [
        Artifact(
            "preregistration.json",
            "The hypotheses, thresholds and pass/fail rules, fixed before the "
            "panel was built. This is what makes the result pre-registered "
            "rather than a story told afterwards.",
            OUTPUT_ROOT / "flow" / "stage1" / "preregistration.json", sort=10),
        Artifact(
            "stage1.json",
            "Every computed statistic behind the write-up: coefficients, "
            "t-statistics, p-values and bucket sorts for the full T0-T5 "
            "falsification battery.",
            OUTPUT_ROOT / "flow" / "stage1" / "stage1.json", sort=20),
        Artifact(
            "panel.csv.gz",
            "The 129-cross-section stock-month panel the tests were run on "
            "(111,695 rows).",
            None, available=False, reason=VENDOR_DATA_REASON, sort=30),
    ],
}


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


class ArtifactPublisher:
    def __init__(self, publisher, chart_publisher):
        self.pub = publisher
        self.cp = chart_publisher      # reuses the bucket + upload path

    def publish_for_note(self, note_slug: str) -> list[str]:
        items = NOTE_ARTIFACTS.get(note_slug, [])
        written = []
        for a in items:
            url = storage_path = sha = None
            nbytes = None
            available = a.available
            reason = a.reason

            if available:
                if a.path is None or not a.path.exists():
                    available, reason = False, (
                        "Not found on the machine that produced this run — the "
                        "result stands on the statistics reported in the note.")
                elif a.path.stat().st_size > MAX_PUBLISH_BYTES:
                    available, reason = False, (
                        f"Too large to host here "
                        f"({a.path.stat().st_size / 1e6:.0f} MB).")
                else:
                    storage_path = f"artifacts/{note_slug}/{a.name}"
                    ct = mimetypes.guess_type(a.name)[0] or "application/json"
                    st = self.cp._storage()
                    st.upload(path=storage_path, file=a.path.read_bytes(),
                              file_options={"content-type": ct, "upsert": "true",
                                            "cache-control": "public, max-age=3600"})
                    url = st.get_public_url(storage_path)
                    nbytes, sha = a.path.stat().st_size, _sha256(a.path)

            conn = self.pub._connect()
            with conn.cursor() as cur:
                cur.execute(f"""
                    INSERT INTO {self.pub.schema}.research_artifacts
                      (note_slug, name, description, available, reason,
                       public_url, storage_path, bytes, sha256, sort_order,
                       updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now())
                    ON CONFLICT (note_slug, name) DO UPDATE SET
                      description=EXCLUDED.description,
                      available=EXCLUDED.available, reason=EXCLUDED.reason,
                      public_url=EXCLUDED.public_url,
                      storage_path=EXCLUDED.storage_path, bytes=EXCLUDED.bytes,
                      sha256=EXCLUDED.sha256, updated_at=now()
                """, (note_slug, a.name, a.description, available, reason or None,
                      url, storage_path, nbytes, sha, a.sort))
            conn.commit()
            written.append(f"{'ok ' if available else 'n/a'} {a.name}")
        return written
