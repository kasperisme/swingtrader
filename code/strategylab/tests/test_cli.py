"""The CLI surface must stay wired — a broken subcommand is invisible until use."""

import pytest

from strategylab.cli import build_parser


ALL_COMMANDS = ["data", "baseline", "backtest", "investigate", "search",
                "finalize", "signals", "report", "space", "compare"]


def test_every_subcommand_parses_and_has_a_handler():
    ap = build_parser()
    for cmd in ALL_COMMANDS:
        argv = ["data", "status"] if cmd == "data" else [cmd]
        args = ap.parse_args(argv)
        assert callable(args.func), cmd


def test_space_command_prints_the_whole_space(capsys):
    from strategylab.cli import cmd_space
    from strategylab.genome import SPACE

    class A:
        json = False
    cmd_space(A())
    out = capsys.readouterr().out
    for key in SPACE:
        assert key in out, f"{key} missing from `strategylab space`"


def test_search_defaults_are_sane():
    args = build_parser().parse_args(["search"])
    assert args.iterations > 0 and args.batch > 0
    assert args.no_llm is False


def test_unknown_command_exits():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["nonsense"])


def test_compare_subcommand_is_wired():
    ap = build_parser()
    args = ap.parse_args(["compare", "evolve2", "evolve3"])
    assert callable(args.func)
    assert args.runs == ["evolve2", "evolve3"]
    assert args.no_factors is False


def test_compare_accepts_a_genome_file():
    args = build_parser().parse_args(["compare", "--genome", "x/strategy.json"])
    assert args.genome == "x/strategy.json"
    assert args.runs == []


def test_search_accepts_seed_arguments():
    args = build_parser().parse_args(["search", "--seed-from", "evolve3"])
    assert args.seed_from == "evolve3"
    assert args.seed_genome is None
