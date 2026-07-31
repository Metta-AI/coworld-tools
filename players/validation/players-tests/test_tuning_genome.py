"""Tests for the Gene / GenomeSpec vector API and the compose glue.

Ported from swgy-crewrift ``packages/swgy-tune/tests/test_knob.py``
(``Knob``/``KnobSpec`` renamed ``Gene``/``GenomeSpec``), plus new cases for
``genome_from_dataclass`` / ``apply_genome``.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

import pytest

from players.player_sdk.tuning import (
    Gene,
    GenomeSpec,
    apply_genome,
    genome_from_dataclass,
)

SPEC = GenomeSpec(
    genes=[
        Gene("speed", low=0.0, high=1.0, default=0.5),
        Gene("bias", low=-2.0, high=2.0, default=0.0),
        Gene("gain", low=1.0, high=10.0, default=4.0),
    ]
)


def test_genome_layout_is_declaration_order():
    assert SPEC.names() == ["speed", "bias", "gain"]
    assert SPEC.bounds() == [(0.0, 1.0), (-2.0, 2.0), (1.0, 10.0)]
    assert SPEC.default_vector() == [0.5, 0.0, 4.0]


def test_to_from_vector_round_trip():
    values = {"speed": 0.2, "bias": 1.5, "gain": 9.0}
    vec = SPEC.to_vector(values)
    assert vec == [0.2, 1.5, 9.0]
    assert SPEC.from_vector(vec) == values


def test_to_vector_fills_missing_with_default_and_ignores_unknown():
    vec = SPEC.to_vector({"bias": 1.0, "unknown": 99.0})
    assert vec == [0.5, 1.0, 4.0]  # speed+gain -> defaults, unknown dropped


def test_clamp_pulls_values_into_bounds():
    clamped = SPEC.clamp([2.0, -5.0, 0.0])
    assert clamped == [1.0, -2.0, 1.0]
    # values already inside bounds are untouched
    assert SPEC.clamp([0.5, 0.0, 4.0]) == [0.5, 0.0, 4.0]


def test_gene_clamp_helper():
    g = Gene("x", low=0.0, high=1.0, default=0.5)
    assert g.clamp(-1.0) == 0.0
    assert g.clamp(2.0) == 1.0
    assert g.clamp(0.3) == 0.3


def test_sample_is_within_bounds_and_seedable():
    rng = random.Random(1234)
    for _ in range(200):
        vec = SPEC.sample(rng)
        for (low, high), v in zip(SPEC.bounds(), vec):
            assert low <= v <= high
    # same seed -> same genome
    assert SPEC.sample(random.Random(7)) == SPEC.sample(random.Random(7))


def test_length_mismatch_rejected():
    with pytest.raises(ValueError, match="length"):
        SPEC.from_vector([0.1, 0.2])
    with pytest.raises(ValueError, match="length"):
        SPEC.clamp([0.1, 0.2, 0.3, 0.4])


def test_validation_empty_duplicate_and_default_out_of_bounds():
    with pytest.raises(ValueError, match="at least one gene"):
        GenomeSpec(genes=[])
    with pytest.raises(ValueError, match="duplicate"):
        GenomeSpec(genes=[Gene("a", 0, 1, 0.5), Gene("a", 0, 1, 0.5)])
    with pytest.raises(ValueError, match="outside"):
        GenomeSpec(genes=[Gene("a", 0.0, 1.0, 2.0)])
    with pytest.raises(ValueError, match="low .* > high"):
        GenomeSpec(genes=[Gene("a", 1.0, 0.0, 0.5)])


@dataclass(frozen=True)
class _DemoParams:
    arrival_radius: float = 12.0  # GA bounds [4, 32]
    stuck_window: int = 12  # GA bounds [4, 40]
    inertia: bool = True
    label: str = "unused"


def test_genome_from_dataclass_reads_defaults_in_bounds_order():
    spec = genome_from_dataclass(
        _DemoParams,
        {"stuck_window": (4, 40), "arrival_radius": (4.0, 32.0), "inertia": (0, 1)},
    )
    assert spec.names() == ["stuck_window", "arrival_radius", "inertia"]
    assert spec.default_vector() == [12.0, 12.0, 1.0]
    with pytest.raises(ValueError, match="no field"):
        genome_from_dataclass(_DemoParams, {"nope": (0, 1)})
    with pytest.raises(ValueError, match="not numeric"):
        genome_from_dataclass(_DemoParams, {"label": (0, 1)})


def test_apply_genome_converts_to_field_types():
    spec = genome_from_dataclass(
        _DemoParams,
        {"arrival_radius": (4.0, 32.0), "stuck_window": (4, 40), "inertia": (0, 1)},
    )
    cfg = apply_genome(_DemoParams(), spec, [17.3, 21.6, 0.2])
    assert cfg.arrival_radius == 17.3
    assert cfg.stuck_window == 22  # rounded to int
    assert cfg.inertia is False  # thresholded at 0.5
    assert cfg.label == "unused"  # untouched field survives
