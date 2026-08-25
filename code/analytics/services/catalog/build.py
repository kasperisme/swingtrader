"""Generate an inventory of the `swingtrader` schema, with intent attached.

**Why this exists.** An agent that cannot see what is already in the database
rebuilds it. In one session a peer-relationship finder was written from scratch
— badly, through four failed iterations over raw news co-occurrence — while
`swingtrader.ticker_relationship_edges` sat there with 38k typed, directional,
evidence-backed edges, alongside a `get_relationship_neighborhood()` function
that did the traversal too. The cost was a day; the cause was that nothing in
the repo answered "what is already here?".

A hand-written schema doc would rot within a month: 102 migrations, 83 tables
and views, 851 columns, 51 functions. So this is generated from two sources
that cannot drift from the truth:

* **The live database** — names, columns, types, row estimates, freshness.
  Freshness matters as much as existence: a table nobody has written to since
  March is a different thing from one updated this morning, and the catalog
  should not present them identically.
* **The migration files** — which carry the *intent*. These migrations open with
  a `-- Why:` block explaining what the object is for and what it replaced. That
  prose is the part an agent actually needs, and it is the part introspection
  cannot produce. It is extracted and attached to the object it created.

The output is deliberately two files. `SUPABASE-CATALOG.md` is the full
reference. `index` is one line per object, small enough to paste into a skill so
the common lookup costs no tool call at all — the failure mode being designed
against is not "the agent looked and found nothing", it is "the agent never
looked".
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # code/analytics
from shared.db import get_pg_connection  # noqa: E402

SCHEMA = "swingtrader"
# .../code/analytics/services/catalog/build.py -> parents[2] is code/analytics
ANALYTICS = Path(__file__).resolve().parents[2]
MIGRATIONS = ANALYTICS / "supabase" / "migrations"
OUT_MD = ANALYTICS / "docs" / "SUPABASE-CATALOG.md"
OUT_JSON = ANALYTICS / "docs" / "supabase_catalog.json"

# Domain grouping. An agent looks for a capability ("peer relationships",
# "news scoring"), not an alphabetical list, so objects are bucketed by the
# first prefix that matches. Order matters — the first hit wins.
DOMAINS: list[tuple[str, tuple[str, ...]]] = [
    ("Relationships & graph", ("ticker_relationship", "ticker_pair", "relationship_")),
    ("News: articles & scoring", ("news_article", "news_impact", "news_trends", "news_")),
    ("News: topics & claims", ("topic_", "story_", "claims_")),
    ("Tickers: sentiment & coverage", ("ticker_sentiment", "ticker_coverage", "ticker_")),
    ("Company factor vectors", ("company_vector", "company_")),
    ("Screening & scans", ("scan_", "screen", "market_screening")),
    ("Users, plans & billing", ("user_", "profile", "subscription", "plan", "billing",
                                "lead", "email")),
    ("Ads, attribution & analytics", ("ad_", "attribution", "utm", "campaign", "quote_")),
    ("Agents & jobs", ("agent", "job", "cron", "run_")),
]
OTHER = "Other"

# Columns that indicate when a row last changed, most-preferred first.
FRESH_COLS = ("updated_at", "last_seen_at", "created_at", "published_at",
              "calibrated_at", "fetched_at", "vector_date", "scan_date", "bucket_day")


def _domain(name: str) -> str:
    for label, prefixes in DOMAINS:
        if any(name.startswith(p) for p in prefixes):
            return label
    return OTHER


# ----------------------------------------------------------------------
def _migration_intent() -> dict[str, str]:
    """object name -> the prose explaining why it exists.

    Two passes per migration. The file's leading comment block is the general
    rationale; a comment block sitting immediately above a CREATE is more
    specific and wins. Objects created by a migration with neither get nothing
    rather than a fabricated description — a wrong explanation is worse than
    none, because it will be believed.
    """
    out: dict[str, str] = {}
    if not MIGRATIONS.exists():
        return out
    create_re = re.compile(
        r"CREATE\s+(?:OR\s+REPLACE\s+)?(?:MATERIALIZED\s+)?"
        r"(TABLE|VIEW|FUNCTION)\s+(?:IF\s+NOT\s+EXISTS\s+)?"
        r"(?:swingtrader\.)?([a-zA-Z_][\w]*)", re.I)

    for path in sorted(MIGRATIONS.glob("*.sql")):
        text = path.read_text(errors="ignore")
        lines = text.splitlines()

        header: list[str] = []
        for ln in lines:
            st = ln.strip()
            if st.startswith("--"):
                body = st.lstrip("-").strip()
                if body and not set(body) <= {"-"}:
                    header.append(body)
            elif st:
                break
        file_intent = " ".join(header).strip()

        for m in create_re.finditer(text):
            name = m.group(2).lower()
            # Walk backwards for a comment block directly above this CREATE.
            upto = text[:m.start()].splitlines()
            local: list[str] = []
            for ln in reversed(upto):
                st = ln.strip()
                if st.startswith("--"):
                    body = st.lstrip("-").strip()
                    if body and not set(body) <= {"-"}:
                        local.append(body)
                elif st == "":
                    if local:
                        break
                else:
                    break
            intent = " ".join(reversed(local)).strip() or file_intent
            if intent and (name not in out or len(intent) > len(out[name])):
                out[name] = intent[:600]
    return out


def _introspect() -> dict:
    conn = get_pg_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT c.relname, c.relkind, GREATEST(c.reltuples, 0)::bigint
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s AND c.relkind IN ('r','v','m','p')
        ORDER BY c.relname
    """, (SCHEMA,))
    objects = {r[0]: {"name": r[0], "kind": {"r": "table", "p": "table", "v": "view",
                                             "m": "matview"}[r[1]],
                      "rows_est": int(r[2])} for r in cur.fetchall()}

    cur.execute("""
        SELECT table_name, column_name, data_type
        FROM information_schema.columns WHERE table_schema = %s
        ORDER BY table_name, ordinal_position
    """, (SCHEMA,))
    cols = defaultdict(list)
    for t, c, d in cur.fetchall():
        cols[t].append((c, d))
    for name, o in objects.items():
        o["columns"] = cols.get(name, [])

    # Freshness. Only for real tables — a view's timestamps come from its
    # sources and scanning one can be arbitrarily expensive.
    for name, o in objects.items():
        o["last_row_at"] = None
        if o["kind"] not in ("table", "matview"):
            continue
        colnames = [c for c, _ in o["columns"]]
        pick = next((c for c in FRESH_COLS if c in colnames), None)
        if not pick:
            continue
        try:
            cur.execute("SET LOCAL statement_timeout = '4s'")
            cur.execute(f'SELECT MAX("{pick}")::text FROM {SCHEMA}."{name}"')
            row = cur.fetchone()
            o["last_row_at"] = (row[0][:10] if row and row[0] else None)
            o["fresh_col"] = pick
        except Exception:                                    # noqa: BLE001
            conn.rollback()

    # Enum-ish column VALUES are the vocabulary an agent actually searches with.
    # `find "competitor"` returned nothing while ticker_relationship_edges was
    # sitting there, because "competitor" is a VALUE in rel_type, not a name or
    # a column. Sampling the distinct values of low-cardinality type/status
    # columns makes the schema findable by what it CONTAINS, not only by what it
    # is called — which is the difference between the catalog working and not.
    for name, o in objects.items():
        o["values"] = {}
        if o["kind"] not in ("table", "matview"):
            continue
        for col, dtype in o["columns"]:
            if dtype not in ("text", "character varying", "USER-DEFINED"):
                continue
            if not any(k in col for k in ("type", "kind", "cluster", "status",
                                          "category", "source", "stream", "role",
                                          "label", "mode")):
                continue
            try:
                # DISTINCT over the whole table times out on the big ones —
                # news_impact_heads has 2.4M rows, and its `cluster` column is
                # the single most useful enum in the schema, so losing it to a
                # timeout defeats the point. Scanning a bounded prefix finds
                # every value of a genuinely low-cardinality column while
                # staying fast.
                cur.execute("SET LOCAL statement_timeout = '8s'")
                # Both ends, not just a prefix. Scanning the first 200k rows of
                # news_impact_heads found 11 of its 13 clusters — STORY_KEY_POINTS
                # and ARTICLE_TAGS were added later, so they live only in recent
                # rows and a head-only sample reports them as nonexistent. That is
                # the worst kind of miss: confidently absent.
                #
                # The tail must be taken on the PRIMARY KEY, not the value column:
                # `ORDER BY <value> DESC` has no index behind it and forces a full
                # sort of the whole table, which timed out and returned nothing at
                # all. Ordering on `id` walks the pk index backwards and is instant.
                has_id = any(c == "id" for c, _ in o["columns"])
                tail = (f'  UNION ALL (SELECT "{col}"::text v FROM {SCHEMA}."{name}" '
                        f'   WHERE "{col}" IS NOT NULL ORDER BY id DESC LIMIT 150000)'
                        if has_id else "")
                cur.execute(
                    f'SELECT DISTINCT v FROM ('
                    f'  (SELECT "{col}"::text v FROM {SCHEMA}."{name}" '
                    f'   WHERE "{col}" IS NOT NULL LIMIT 150000)'
                    f'{tail}'
                    f') s LIMIT 40')
                vals = sorted({r[0] for r in cur.fetchall() if r[0]})
                if 1 < len(vals) <= 30:
                    o["values"][col] = vals
            except Exception:                                # noqa: BLE001
                conn.rollback()

    cur.execute("""
        SELECT p.proname,
               pg_get_function_identity_arguments(p.oid),
               pg_get_function_result(p.oid)
        FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = %s ORDER BY p.proname
    """, (SCHEMA,))
    funcs = [{"name": r[0], "args": r[1], "returns": r[2]} for r in cur.fetchall()]
    return {"objects": objects, "functions": funcs}


# ----------------------------------------------------------------------
def build_catalog(write: bool = True) -> dict:
    intent = _migration_intent()
    data = _introspect()
    objs, funcs = data["objects"], data["functions"]
    for o in objs.values():
        o["intent"] = intent.get(o["name"], "")
        o["domain"] = _domain(o["name"])
    for f in funcs:
        f["intent"] = intent.get(f["name"], "")
        f["domain"] = _domain(f["name"])

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    grouped: dict[str, list] = defaultdict(list)
    for o in objs.values():
        grouped[o["domain"]].append(o)

    md = [f"# Supabase `swingtrader` catalog", "",
          f"Generated {generated} by `python -m services.catalog.build`. "
          f"**Do not hand-edit** — regenerate instead.", "",
          f"{len(objs)} tables/views, {sum(len(o['columns']) for o in objs.values())} "
          f"columns, {len(funcs)} functions.", "",
          "`rows` is a planner estimate, not a count. `fresh` is the newest row's "
          "timestamp — an object with an old date is likely abandoned, and that is "
          "as important to know as whether it exists.", ""]

    order = [d for d, _ in DOMAINS] + [OTHER]
    for dom in order:
        items = sorted(grouped.get(dom, []), key=lambda o: -o["rows_est"])
        if not items:
            continue
        md += [f"## {dom}", ""]
        for o in items:
            head = f"### `{o['name']}` ({o['kind']})"
            # A view has no reltuples, so "~0 rows" would read as "empty" when
            # it means "not applicable" — a distinction that decides whether an
            # agent bothers to look at it.
            bits = ([f"~{o['rows_est']:,} rows"] if o["kind"] != "view"
                    else ["view — row count n/a"])
            if o.get("last_row_at"):
                bits.append(f"fresh to {o['last_row_at']}")
            md += [head, "", f"*{', '.join(bits)}*", ""]
            if o["intent"]:
                md += [o["intent"], ""]
            md += ["| column | type |", "|---|---|"]
            md += [f"| `{c}` | {d} |" for c, d in o["columns"]]
            md += [""]
            for col, vals in (o.get("values") or {}).items():
                md += [f"`{col}` values: " + ", ".join(f"`{v}`" for v in vals), ""]

    md += ["## Functions", "",
           "Callable via PostgREST `.rpc(name, {...})` or directly in SQL.", "",
           "| function | arguments | returns |", "|---|---|---|"]
    for f in funcs:
        md += [f"| `{f['name']}` | `{f['args'] or ''}` | {f['returns']} |"]
    md += [""]

    # The compact index — one line per object, for pasting into the skill.
    idx = [f"# swingtrader schema index (generated {generated})", ""]
    for dom in order:
        items = sorted(grouped.get(dom, []),
                       key=lambda o: (o["kind"] == "view", -o["rows_est"]))
        if not items:
            continue
        idx.append(f"## {dom}")
        for o in items:
            desc = (o["intent"].split(". ")[0][:110]) if o["intent"] else ""
            fresh = f" @{o['last_row_at']}" if o.get("last_row_at") else ""
            size = "" if o["kind"] == "view" else f", ~{o['rows_est']:,}{fresh}"
            idx.append(f"- `{o['name']}` ({o['kind']}{size}) {desc}")
        idx.append("")
    idx.append("## Functions")
    for f in funcs:
        idx.append(f"- `{f['name']}({f['args'] or ''})`")

    payload = {"generated": generated, "objects": list(objs.values()),
               "functions": funcs, "index": "\n".join(idx)}
    if write:
        OUT_MD.parent.mkdir(parents=True, exist_ok=True)
        OUT_MD.write_text("\n".join(md))
        OUT_JSON.write_text(json.dumps(payload, indent=1, default=str))
        (OUT_MD.parent / "supabase_index.md").write_text("\n".join(idx))
    return payload


def staleness() -> str | None:
    """Warn when migrations have landed since the catalog was generated.

    A generated doc solves rot only if someone regenerates it. Nobody will
    remember to, so the tool that reads it checks and says so — the warning
    costs nothing and appears exactly when it is relevant.
    """
    if not OUT_JSON.exists():
        return "catalog has never been generated"
    try:
        gen = json.loads(OUT_JSON.read_text()).get("generated", "")
        newest = max((f.stat().st_mtime for f in MIGRATIONS.glob("*.sql")), default=0)
        newest_day = datetime.fromtimestamp(newest, timezone.utc).strftime("%Y-%m-%d")
    except Exception:                                        # noqa: BLE001
        return None
    if newest_day > gen:
        return (f"STALE: newest migration is {newest_day}, catalog generated {gen}. "
                f"Run `python -m services.catalog.build`.")
    return None


# Words an agent reaches for that appear nowhere in the schema, or that appear
# in the WRONG place. Each maps to a list, because one intent can legitimately
# reach several objects and picking one for the reader hides the alternative.
#
# The supply-chain entry is the reason this is a list. `ticker_relationship_edges`
# is not a peer/competitor table — it is the full inter-company relationship
# graph, and the VALUE CHAIN is the majority of it: supplier + customer + partner
# = 46% of 38k edges, against competitor at 42% and ownership at 12%. Routing
# "supply chain" only to news_impact_heads' SUPPLY_CHAIN_EXPOSURE cluster sent
# the reader to a per-article RISK SCORE when they asked who supplies whom.
# Both objects are real and they answer different questions:
#   ticker_relationship_edges       -> structure: who is related to whom
#   news_impact_heads SUPPLY_CHAIN_ -> scoring: how much is this article about
#     EXPOSURE                         supply-chain risk
ALIASES: dict[str, list[str]] = {
    # the relationship graph, in every vocabulary it gets asked for
    "peer": ["relationship"], "peers": ["relationship"], "rival": ["relationship"],
    "related": ["relationship"], "graph": ["relationship"],
    "network": ["relationship"], "neighbour": ["relationship"],
    "neighbor": ["relationship"], "competitor": ["relationship"],
    "supplier": ["relationship"], "supply chain": ["relationship", "supply_chain"],
    "vendor": ["relationship"], "customer": ["relationship"],
    "partner": ["relationship"], "counterparty": ["relationship"],
    "value chain": ["relationship"], "upstream": ["relationship"],
    "downstream": ["relationship"], "owns": ["relationship"],
    "ownership": ["relationship"], "subsidiary": ["relationship"],
    "parent company": ["relationship"], "acquirer": ["relationship"],
    "acquisition": ["relationship"], "m&a": ["relationship"],
    "brand": ["relationship"],
    # news scoring + claims
    "narrative": ["story_key_points"], "claim": ["story_key_points"],
    "claims": ["story_key_points"], "key points": ["story_key_points"],
    "consensus": ["growth_profile"], "what the market thinks": ["growth_profile"],
    "growth": ["growth_profile"], "valuation": ["valuation_positioning"],
    # retrieval + aggregates
    "semantic": ["embedding"], "similarity": ["embedding"],
    "vector search": ["embedding"], "trend": ["news_trends"],
    "trending": ["news_trends"],
    # prices / pairs
    "cointegration": ["ticker_pair"], "spread": ["ticker_pair"],
    "pairs": ["ticker_pair"], "hedge ratio": ["ticker_pair"],
    "earnings surprise": ["surprise"], "attention": ["coverage"],
}


def find(term: str, limit: int = 12) -> list[dict]:
    """Search names, intent prose, column names and column VALUES.

    Intent-first: an agent asks for "peer relationships", not for a table name,
    so a hit in the migration's rationale ranks above a hit in a column, and a
    hit in a column value (rel_type = 'competitor') counts too.
    """
    if not OUT_JSON.exists():
        build_catalog()
    cat = json.loads(OUT_JSON.read_text())
    t = term.lower().strip()
    terms = {t}
    for k, vs in ALIASES.items():
        if k in t:
            terms.update(vs)

    # Auxiliary tables — traceability, queues, run logs. They legitimately match
    # the same words as the object they hang off, and they were outranking it:
    # every relationship query returned `ticker_relationship_edge_evidence`
    # above `ticker_relationship_edges`. The evidence table is bigger, so size
    # cannot break the tie; naming it as auxiliary can.
    AUX = ("_evidence", "_jobs", "_runs", "_log", "_logs", "_queue", "_audit",
           "_history", "_traceability_v", "_dry_days")

    hits = []
    for o in cat["objects"]:
        score, matched = 0, None
        name = o["name"].lower()
        for q in terms:
            if q == name:
                score += 16
            elif q in name:
                score += 10
            if q in (o.get("intent") or "").lower():
                score += 6
            score += 2 * sum(1 for c, _ in o["columns"] if q in c.lower())
            for col, vals in (o.get("values") or {}).items():
                low = [v.lower() for v in vals]
                if q in low:                       # exact value: rel_type = 'supplier'
                    score += 8
                    matched = f"{col} = {q}"
                elif any(q in v for v in low):     # substring: 'relationship' in
                    score += 2                     # 'TICKER_RELATIONSHIPS' — weak,
                                                   # and it was beating the real answer
        if any(name.endswith(a) for a in AUX):
            score -= 5
        # An empty table is almost always a scaffold that was never filled or a
        # feature that was abandoned. `embedding` returned the empty
        # news_embedding_daily_cluster_centroids above news_article_embeddings
        # and its 1.8M live rows. The catalog already treats freshness as
        # first-class; ranking has to as well, or it points at the dead one.
        if o["kind"] in ("table", "matview") and o["rows_est"] == 0:
            score -= 4
        if score > 0:
            hits.append((score, o["rows_est"], {**o, **({"matched_value": matched}
                                                        if matched else {})}))
    # Plumbing: trigger bodies, materialization refreshers, internal exec
    # helpers. They match the same words as the thing they maintain and are
    # never the answer to "where does X live" — `narrative` returned
    # touch_narrative_prefs_updated_at() ahead of every table.
    PLUMBING = ("touch_", "refresh_", "exec_", "trg_", "_updated_at")
    for f in cat["functions"]:
        fname = f["name"].lower()
        score = sum(16 if q == fname else 10 if q in fname else 0 for q in terms)
        score += sum(6 for q in terms if q in (f.get("intent") or "").lower())
        if any(fname.startswith(p_) or fname.endswith(p_) for p_ in PLUMBING):
            score -= 8
        if score > 0:
            hits.append((score, 0, {"name": f["name"] + "()", "kind": "function",
                                    "rows_est": 0, "intent": f.get("intent", ""),
                                    "columns": []}))
    hits.sort(key=lambda x: (-x[0], -x[1]))
    return [h for _, _, h in hits[:limit]]


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "check":
        msg = staleness()
        print(msg or "catalog is current")
        raise SystemExit(1 if msg else 0)
    if len(sys.argv) > 2 and sys.argv[1] == "find":
        warn = staleness()
        if warn:
            print(f"  !! {warn}\n")
        for o in find(" ".join(sys.argv[2:])):
            mv = f"  [{o['matched_value']}]" if o.get("matched_value") else ""
            print(f"  {o['kind']:<9} {o['name']:<44} {(o.get('intent') or '')[:80]}{mv}")
    else:
        p = build_catalog()
        print(f"wrote {OUT_MD}")
        print(f"wrote {OUT_JSON}")
        print(f"wrote {OUT_MD.parent / 'supabase_index.md'}")
        print(f"{len(p['objects'])} objects, {len(p['functions'])} functions")
