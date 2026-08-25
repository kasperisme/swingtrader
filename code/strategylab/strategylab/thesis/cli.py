"""Thesis-lab CLI.

    python -m strategylab.thesis.cli list                 # registered theses
    python -m strategylab.thesis.cli show SOCIAL-ARB-1    # the chain + verdicts
    python -m strategylab.thesis.cli register SOCIAL-ARB-1
    python -m strategylab.thesis.cli data SOCIAL-ARB-1    # what each link needs

`show` prints the chain in TEST order, not causal order, because the question a
reader has is "what runs next and what would kill it", and prints the lab-wide
trial count under the verdict so no t-statistic is read without the number of
draws it was selected from.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from ..config import OUTPUT_ROOT
from .registry import ThesisRegistry
from .theses import ALL
from .thesis import BLOCKED, FAILS, HOLDS, PENDING, link_bar

log = logging.getLogger(__name__)

DB = OUTPUT_ROOT / "runs" / "thesis.db"
DISCOVER_DB = OUTPUT_ROOT / "runs" / "discover.db"

MARK = {HOLDS: "[x]", FAILS: "[!]", PENDING: "[ ]", BLOCKED: "[~]",
        "INCONCLUSIVE": "[?]", "SKIPPED": "[-]"}


def _reg() -> ThesisRegistry:
    return ThesisRegistry(DB)


def cmd_list(args) -> int:
    reg = _reg()
    known = {t["id"]: t for t in reg.theses()}
    print(f"\n{'thesis':<16}{'verdict':<14}{'links':<8}title")
    print("-" * 78)
    for tid, th in ALL.items():
        row = known.get(tid, {})
        v = row.get("verdict", "unregistered")
        print(f"{tid:<16}{v:<14}{len(th.links):<8}{th.title[:44]}")
    lab = reg.lab_trials(DISCOVER_DB)
    print(f"\nlab-wide measurements: {lab['total']} "
          f"({lab['thesis_arms']} thesis arms + {lab['discover_hypotheses']} "
          f"discovery hypotheses)")
    return 0


def cmd_show(args) -> int:
    th = ALL.get(args.thesis)
    if th is None:
        print(f"unknown thesis {args.thesis!r}; known: {', '.join(ALL)}")
        return 2
    reg = _reg()
    results = reg.results(th.id)
    arms = reg.arms_run(th.id)
    lab = reg.lab_trials(DISCOVER_DB)

    print("\n" + "=" * 78)
    print(f"{th.id} — {th.title}")
    print("=" * 78)
    print(f"\n{th.mechanism}\n")
    if th.source:
        print(f"anchor: {th.source}\n")

    print("chain, in TEST order (cheapest and most-likely-to-fail first):\n")
    for ln in th.test_order():
        r = results.get(ln.id)
        v = r.verdict if r else PENDING
        bar = link_bar(ln, arms)
        tag = "PIVOTAL" if ln.pivotal else ""
        print(f"  {MARK.get(v, '[ ]')} {ln.id}  {v:<13}{ln.cost:<7}{tag:<9}"
              f"bar |t|>{bar:.2f}  "
              f"{'prereg' if ln.preregistered else 'exploratory'}")
        print(f"        claim  {ln.claim}")
        print(f"        null   {ln.null}")
        print(f"        kill   {ln.kill}")
        if r and r.n_obs:
            print(f"        result effect {r.effect:+.4f}  t {r.t_stat:+.2f}  "
                  f"n {r.n_obs}  placebo t {r.placebo_t:+.2f}")
        if r and r.note:
            print(f"        note   {r.note}")
        print()

    verdict, reason = th.verdict(results)
    print("-" * 78)
    print(f"VERDICT: {verdict} — {reason}")
    print(f"arms run inside this thesis: {arms}")
    print(f"lab-wide measurements: {lab['total']}")
    if th.notes:
        print(f"\nnote: {th.notes}")
    print("=" * 78 + "\n")
    return 0


def cmd_register(args) -> int:
    th = ALL.get(args.thesis)
    if th is None:
        print(f"unknown thesis {args.thesis!r}")
        return 2
    reg = _reg()
    reg.register(th)
    print(f"registered {th.id} with {len(th.links)} links (pre-registration is "
          f"append-only; re-running this does not reset anything)")
    return 0


def cmd_data(args) -> int:
    th = ALL.get(args.thesis)
    if th is None:
        print(f"unknown thesis {args.thesis!r}")
        return 2
    print(f"\n{th.id} data requirements\n")
    for d, links in sorted(th.data_requirements().items(),
                           key=lambda kv: -len(kv[1])):
        print(f"  {d:<24} needed by {', '.join(links)}")
    print("\nA link whose data is missing returns BLOCKED, which is a data "
          "problem and not a result — the verdict machinery keeps them apart.\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="strategylab.thesis")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="registered theses and their verdicts").set_defaults(
        func=cmd_list)
    for name, fn, helptext in (("show", cmd_show, "the chain, in test order"),
                               ("register", cmd_register, "pre-register a thesis"),
                               ("data", cmd_data, "what each link needs")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("thesis")
        p.set_defaults(func=fn)

    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
