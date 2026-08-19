import random

from strategylab.genome import (DEFAULTS, SPACE, Genome, default_genome, random_genome,
                                space_spec)


def test_space_and_defaults_agree():
    assert set(SPACE) == set(DEFAULTS)
    assert len(space_spec()) == len(SPACE)


def test_genome_is_always_complete_and_in_bounds():
    rng = random.Random(0)
    for _ in range(50):
        g = random_genome(rng)
        assert set(g) == set(SPACE)
        for k, dim in SPACE.items():
            assert dim.clip(g[k]) == g[k], k


def test_out_of_range_values_are_clipped_not_fatal():
    g = default_genome().patched({"pf.max_positions": 10_000, "gates.rs_rank_min": -50,
                                  "entry.type": "nonsense", "unknown.key": 1})
    assert g["pf.max_positions"] == SPACE["pf.max_positions"].hi
    assert g["gates.rs_rank_min"] == SPACE["gates.rs_rank_min"].lo
    assert g["entry.type"] in SPACE["entry.type"].options
    assert "unknown.key" not in g


def test_repair_enforces_invariants():
    g = default_genome().patched({"gates.adr_min": 5.0, "gates.adr_max": 3.5})
    assert g["gates.adr_max"] > g["gates.adr_min"]
    g = default_genome().patched({"pf.max_positions": 4, "pf.max_sector_positions": 12})
    assert g["pf.max_sector_positions"] <= g["pf.max_positions"]


def test_hash_is_stable_and_discriminating():
    a, b = default_genome(), default_genome()
    assert a.hash == b.hash
    # A change below the rounding floor must not create a "new" configuration,
    # or the deflated-Sharpe trial count silently inflates.
    assert a.patched({"pf.risk_pct": a["pf.risk_pct"] + 1e-9}).hash == a.hash
    assert a.patched({"pf.risk_pct": a["pf.risk_pct"] + 0.5}).hash != a.hash


def test_complexity_ignores_inactive_knobs():
    on = default_genome().patched({"gates.use_fundamentals": True})
    off = default_genome().patched({"gates.use_fundamentals": False})
    assert on.complexity() > off.complexity()


def test_unit_roundtrip():
    for k, dim in SPACE.items():
        for u in (0.0, 0.37, 1.0):
            v = dim.from_unit(u)
            assert abs(dim.unit(v) - u) < 0.51  # ints/cats quantise


def test_from_unit_never_escapes_its_bounds():
    """Log-scaled dims round-trip through exp(log(...)) and can land a hair
    outside the range at the endpoints. A value clipped later, rather than
    here, would change a genome's hash after it was recorded."""
    for k, dim in SPACE.items():
        if not hasattr(dim, "from_unit"):
            continue
        for u in (0.0, 1e-12, 0.5, 1 - 1e-12, 1.0):
            v = dim.from_unit(u)
            assert dim.clip(v) == v, f"{k} at u={u} produced out-of-range {v!r}"
