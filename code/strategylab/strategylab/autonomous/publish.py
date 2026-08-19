"""Publish research to Supabase for the public site.

Two rules govern what gets written, both of them consequences of what this lab
measured about its own output:

**A number never travels without its provenance.** Every published strategy row
carries the trial count it was selected from, its deflated Sharpe, its PBO, and
its out-of-sample metrics where they exist. A Sharpe ratio without the number of
configurations behind it is an anecdote, and this lab produced one that read 5.5x
better than the incumbent in-sample and +0.03 out of it.

**Negative results publish too.** Most of what an honest quant lab produces is a
refutation. A site that only shows the wins is a marketing page wearing a lab
coat, so `result_kind` defaults to 'negative' and the leaderboard sorts on the
OUT-OF-SAMPLE column — ranking by in-sample Sharpe would put the most overfitted
strategy on top.

Nothing is published automatically on first sight: a finding must reach
CONFIRMED (two independent replications, zero refutations) before `published`
can be set.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..config import load_env
from .findings import FindingStore, Status

log = logging.getLogger(__name__)


def _slugify(text: str, maxlen: int = 80) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:maxlen] or "untitled"


@dataclass
class PublishResult:
    campaigns: int = 0
    strategies: int = 0
    findings: int = 0
    notes: int = 0
    skipped: list[str] = None
    error: str = ""

    def summary(self) -> str:
        if self.error:
            return f"publish failed: {self.error}"
        return (f"published {self.campaigns} campaigns, {self.strategies} strategies, "
                f"{self.findings} findings, {self.notes} notes"
                + (f" (skipped {len(self.skipped or [])})" if self.skipped else ""))


class ResearchPublisher:
    """Writes the lab's record into Supabase."""

    def __init__(self, schema: str | None = None):
        load_env()
        self.schema = schema or os.environ.get("SUPABASE_SCHEMA", "swingtrader")
        self._conn = None

    # ------------------------------------------------------------------
    def _connect(self):
        if self._conn is not None:
            return self._conn
        import psycopg2
        direct = os.environ.get("SUPABASE_DB_DIRECT_URL")
        if direct:
            self._conn = psycopg2.connect(direct)
            return self._conn
        url = os.environ.get("SUPABASE_URL", "")
        pwd = os.environ.get("SUPABASE_DB_PWD", "")
        host = os.environ.get("SUPABASE_DB_POOLER_HOST", "")
        if not (url and pwd and host):
            raise RuntimeError(
                "need SUPABASE_DB_DIRECT_URL, or SUPABASE_URL + SUPABASE_DB_PWD "
                "+ SUPABASE_DB_POOLER_HOST")
        ref = url.replace("https://", "").split(".")[0]
        self._conn = psycopg2.connect(
            host=host, port=int(os.environ.get("SUPABASE_DB_PORT", 6543)),
            dbname=os.environ.get("SUPABASE_DB_NAME", "postgres"),
            user=f"postgres.{ref}", password=pwd, connect_timeout=20)
        return self._conn

    def ready(self) -> tuple[bool, str]:
        """Check the connection AND that the migration has been applied."""
        try:
            c = self._connect()
            with c.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema=%s AND table_name IN "
                    "('research_campaigns','research_strategies',"
                    "'research_findings','research_notes')", (self.schema,))
                n = cur.fetchone()[0]
            if n < 4:
                return False, (f"only {n}/4 research tables exist in schema "
                               f"'{self.schema}' — apply the migration "
                               "20260819220000_quant_research_lab.sql first")
            return True, ""
        except Exception as exc:
            return False, str(exc)[:200]

    # ------------------------------------------------------------------
    def publish_campaign(self, campaign, cfg, universe_size: int,
                         models: dict | None = None) -> None:
        c = self._connect()
        with c.cursor() as cur:
            cur.execute(f"""
                INSERT INTO {self.schema}.research_campaigns
                  (run_id, started_at, ended_at, protocol_version, universe_size,
                   prefilter, dev_start, dev_end, costs_json, iterations,
                   trials_own, trials_inherited, best_genome_hash, best_reward,
                   best_sharpe, pbo, stop_reason, stop_detail, models_used)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (run_id) DO UPDATE SET
                  ended_at=EXCLUDED.ended_at, iterations=EXCLUDED.iterations,
                  trials_own=EXCLUDED.trials_own, best_reward=EXCLUDED.best_reward,
                  best_sharpe=EXCLUDED.best_sharpe, pbo=EXCLUDED.pbo,
                  stop_reason=EXCLUDED.stop_reason, stop_detail=EXCLUDED.stop_detail
            """, (campaign.run_id, campaign.started, campaign.ended,
                  cfg.protocol_version, universe_size, cfg.prefilter,
                  cfg.splits.dev_start, cfg.splits.dev_end,
                  json.dumps({"commission_bps": cfg.costs.commission_bps,
                              "slippage_bps": cfg.costs.slippage_bps,
                              "spread_bps": cfg.costs.spread_bps,
                              "max_adv_participation": cfg.costs.max_adv_participation}),
                  campaign.iterations, campaign.trials, 0,
                  campaign.best_hash or None, campaign.best_reward,
                  campaign.best_sharpe, campaign.pbo, campaign.stop_reason,
                  campaign.stop_detail, json.dumps(models or {})))
        c.commit()

    def publish_strategy(self, genome, campaign_run_id: str, dev_metrics: dict,
                         fold_metrics: list, trials_considered: int,
                         deflated_sharpe: float, pbo: float | None,
                         gate_passed: bool, gate_failures: list[str],
                         holdout_metrics: dict | None = None,
                         vault_metrics: dict | None = None,
                         changes: str = "") -> None:
        c = self._connect()
        with c.cursor() as cur:
            cur.execute(f"""
                INSERT INTO {self.schema}.research_strategies
                  (genome_hash, campaign_run_id, genome_json, changes_vs_incumbent,
                   dev_metrics, fold_metrics, holdout_metrics, vault_metrics,
                   trials_considered, deflated_sharpe, pbo, gate_passed, gate_failures)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (genome_hash, campaign_run_id) DO UPDATE SET
                  holdout_metrics=COALESCE(EXCLUDED.holdout_metrics,
                                           {self.schema}.research_strategies.holdout_metrics),
                  vault_metrics=COALESCE(EXCLUDED.vault_metrics,
                                         {self.schema}.research_strategies.vault_metrics),
                  deflated_sharpe=EXCLUDED.deflated_sharpe, pbo=EXCLUDED.pbo,
                  gate_passed=EXCLUDED.gate_passed, gate_failures=EXCLUDED.gate_failures
            """, (genome.hash, campaign_run_id, json.dumps(dict(genome)), changes,
                  json.dumps(dev_metrics, default=str),
                  json.dumps(fold_metrics, default=str),
                  json.dumps(holdout_metrics, default=str) if holdout_metrics else None,
                  json.dumps(vault_metrics, default=str) if vault_metrics else None,
                  trials_considered, deflated_sharpe, pbo, gate_passed,
                  gate_failures or []))
        c.commit()

    # ------------------------------------------------------------------
    def publish_findings(self, store: FindingStore, run_id: str = "",
                         only_confirmed: bool = True) -> int:
        """Push findings. By default only CONFIRMED ones become visible.

        An autonomous lab generates candidate findings continuously; publishing
        them on first sight would put a p=0.53 result on a public page. Anything
        below CONFIRMED is written with published=false so it is recorded but
        not shown.
        """
        c = self._connect()
        n = 0
        statuses = ([Status.CONFIRMED] if only_confirmed
                    else [Status.CONFIRMED, Status.REPLICATING, Status.REFUTED,
                          Status.OBSERVED])
        for status in statuses:
            for f in store.by_status(status, limit=200):
                if f is None:
                    continue
                visible = bool(f.credible)
                caveat = self._caveat_for(f)
                with c.cursor() as cur:
                    cur.execute(f"""
                        INSERT INTO {self.schema}.research_findings
                          (slug, claim, status, replications, refutations,
                           evidence_json, caveats, reproduce_command,
                           source_campaign, published, updated_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now())
                        ON CONFLICT (slug) DO UPDATE SET
                          status=EXCLUDED.status, replications=EXCLUDED.replications,
                          refutations=EXCLUDED.refutations,
                          evidence_json=EXCLUDED.evidence_json,
                          caveats=EXCLUDED.caveats, published=EXCLUDED.published,
                          updated_at=now()
                    """, (_slugify(f.claim), f.claim, f.status.value, f.replications,
                          f.refutations, json.dumps(f.evidence, default=str), caveat,
                          self._reproduce_for(f), f.source or run_id, visible))
                n += 1
        c.commit()
        return n

    @staticmethod
    def _caveat_for(f) -> str:
        """The counterweight that travels with the claim."""
        if f.status is Status.REFUTED:
            return ("Refuted: this failed when tested on data that did not produce "
                    "it. Recorded so the attempt is not silently repeated.")
        if f.replications < 2:
            return (f"Seen {f.replications + 1} time(s) and not yet independently "
                    "replicated. Every result this lab produced that looked good on "
                    "first sight failed its first honest replication, so treat this "
                    "as a candidate, not a conclusion.")
        return ("Replicated on data that did not produce it. Still measured on a "
                "survivorship-limited universe with modelled rather than realised "
                "costs — an upper bound, not a live track record.")

    @staticmethod
    def _reproduce_for(f) -> str:
        run = (f.evidence or {}).get("run", "")
        if run:
            return (f"cd code/strategylab && .venv/bin/python -m strategylab.cli "
                    f"compare {run} --limit 800")
        return "cd code/strategylab && .venv/bin/python -m strategylab.cli compare"

    # ------------------------------------------------------------------
    # Markers of this lab's own machine and repo. A published article must
    # contain none of them: a reader cannot run our CLI, does not have our
    # virtualenv, and gains nothing from the name of a regression test. The
    # replication story is the method and the data — not our shell history.
    INTERNAL_PATTERNS = (
        (r"\.venv/", "virtualenv path"),
        (r"\bcd code/", "repo-relative shell step"),
        (r"python -m strategylab", "internal CLI invocation"),
        (r"python /tmp/", "scratch script"),
        (r"\btests?/[\w./]*\.py", "test file reference"),
        (r"::test_\w+", "test id"),
        (r"\b(?:output|code)/[\w./-]+", "repo path"),
        (r"\bservices/[\w./-]+", "internal module path"),
        (r"\bThe repo has\b", "reference to our repo"),
    )

    @classmethod
    def audit_internal_references(cls, text: str) -> list[str]:
        """Every internal reference still present. Empty means safe to publish."""
        found = []
        for pattern, label in cls.INTERNAL_PATTERNS:
            for m in re.finditer(pattern, text):
                found.append(f"{label}: {m.group(0)[:60]}")
        return found

    @classmethod
    def _deinternalise(cls, text: str) -> str:
        """Strip references to this machine, this repo and this test suite.

        A note that says "run `.venv/bin/python -m strategylab.flow.cli stage1`"
        is addressed to whoever is sitting at this laptop. Published, it reads
        as a reproduction recipe while being unusable to everyone who reads it —
        worse than saying nothing, because it looks like it should work.

        What survives is the part that actually travels: what was computed, on
        what data, under what pre-registered rules.
        """
        # 1. Fenced blocks that are internal invocations, with their heading.
        def drop_block(m: re.Match) -> str:
            body = m.group(0)
            if re.search(r"\.venv/|cd code/|python -m strategylab|python /tmp/", body):
                return ""
            return body
        text = re.sub(r"```[a-z]*\n.*?```", drop_block, text, flags=re.S)

        # 2. Standalone command lines outside any fence.
        text = re.sub(r"(?m)^[ \t]*(?:\$ )?(?:cd code/|\.venv/|python -m strategylab|python /tmp/)[^\n]*\n?",
                      "", text)

        # 3. Any remaining sentence that carries an invocation. Dropping the
        # whole sentence rather than the command alone avoids leaving stubs
        # like "Run it with ." behind.
        invocation = re.compile(r"\.venv/|cd code/|python -m strategylab|python /tmp/")
        kept = []
        for para in text.split("\n\n"):
            if invocation.search(para):
                sentences = re.split(r"(?<=[.!?])\s+", para)
                para = " ".join(x for x in sentences if not invocation.search(x)).strip()
                if not para:
                    continue
            kept.append(para)
        text = "\n\n".join(kept)

        # 4. Sentences whose only content is an internal pointer.
        text = re.sub(r"(?m)^Reproduce:.*(?:\n(?!\n).*)*$", "", text)
        text = re.sub(r"The repo has [^.]*\.[ \t]*", "", text)

        # 5. Parentheticals that merely cite a test.
        text = re.sub(r"\s*\(`?tests?/[^)]*`?\)", "", text)
        text = re.sub(r"\s*\(or the [^)]*tests?/[^)]*\)", "", text)

        # 6. Bare paths and flags left in prose.
        text = re.sub(r"`?\b(?:output|code)/[\w./-]*\{([^}]*)\}`?",
                      lambda m: m.group(1).strip(), text)
        text = re.sub(r"`?\b(?:output|code)/[\w./-]*?([\w-]+\.[a-z]{2,5})`?",
                      lambda m: m.group(1), text)
        text = re.sub(r"`--limit (\d+)`", r"an \1-name universe limit", text)
        text = re.sub(r"`?\bservices/[\w./-]+`?", "the pairs module", text)

        # 7. Drop the leading H1. It becomes the note's title and is rendered
        # by the page chrome; leaving it in the body prints the headline twice.
        text = re.sub(r"\A\s*#[ \t]+[^\n]*\n+", "", text)

        # 8. Tidy the holes left behind.
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"(?m)^##+ Reproduce\s*\n+(?=##|\Z)", "", text)
        return text.strip() + "\n"

    @staticmethod
    def _summarise(text: str, limit: int = 320) -> str:
        """The opening sentences of the body, as plain text.

        Rendered as a bare string in listings, so markdown has to come out
        here — an earlier version shipped `**Verdict: nothing survives.**`
        to the site with the asterisks visible. Built up whole sentences at
        a time so it can never end mid-clause, which reads as a bug rather
        than as brevity.
        """
        body: list[str] = []
        for ln in text.splitlines()[1:]:
            ln = ln.strip()
            # A bullet is "* " or "- " with a space; "**Verdict:" is bold
            # text and is usually the most important sentence in the file.
            if (not ln or ln.startswith(("#", "|", "```", ">"))
                    or ln.startswith(("* ", "- ", "---", "+ "))):
                continue
            body.append(ln)
            if sum(len(b) for b in body) > limit * 2:
                break

        plain = " ".join(body)
        plain = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", plain)   # links -> text
        plain = re.sub(r"[*_`]{1,3}", "", plain)                    # emphasis, code
        plain = re.sub(r"\s+", " ", plain).strip()
        if len(plain) <= limit:
            return plain

        out = ""
        for sentence in re.split(r"(?<=[.!?])\s+", plain):
            if out and len(out) + len(sentence) + 1 > limit:
                break
            out = f"{out} {sentence}".strip()
        # A single opening sentence longer than the limit still has to be cut.
        return out if out else plain[:limit].rsplit(" ", 1)[0] + "\u2026"

    def publish_note(self, path: Path, published: bool = False,
                     result_kind: str = "negative", tags: list[str] | None = None,
                     charts: list[str] | None = None) -> str:
        """Publish a long-form write-up from a markdown file."""
        raw = path.read_text()
        # Title and summary come from the RAW file: the transform strips the
        # leading H1 (the page renders the title itself), so reading them back
        # off the cleaned text would fall through to the filename.
        title = next((ln.lstrip("# ").strip() for ln in raw.splitlines()
                      if ln.startswith("# ")), path.stem)
        summary = self._summarise(raw)
        text = self._deinternalise(raw)
        slug = _slugify(title)

        # Hard gate. If the transform missed something, the note is stored as a
        # draft regardless of what the caller asked for — a live article citing
        # our virtualenv is worse than a late one.
        leftovers = self.audit_internal_references(text)
        if leftovers and published:
            log.warning("%s: not publishing live — internal references remain: %s",
                        slug, "; ".join(leftovers[:5]))
            published = False

        c = self._connect()
        with c.cursor() as cur:
            cur.execute(f"""
                INSERT INTO {self.schema}.research_notes
                  (slug, title, summary, body_md, result_kind, tags, charts,
                   published, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s, now())
                ON CONFLICT (slug) DO UPDATE SET
                  title=EXCLUDED.title, summary=EXCLUDED.summary,
                  body_md=EXCLUDED.body_md, result_kind=EXCLUDED.result_kind,
                  tags=EXCLUDED.tags, charts=EXCLUDED.charts,
                  -- Not published: re-running the publisher refreshes content,
                  -- it does not take a live article down or put a draft up.
                  updated_at=now()
            """, (slug, title, summary, text, result_kind, tags or [],
                  json.dumps(charts or []), published))
        c.commit()
        return slug

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
