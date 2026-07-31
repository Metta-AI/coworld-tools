"""Opt-in tuning utilities: typed kwarg configs and GA genome vectors.

Two independent, dependency-free halves plus glue:

- :mod:`.knobs` — string-kwarg → frozen-dataclass config pipeline
  (:func:`build`, :class:`Knobs`, :func:`split_prefixed`, :func:`by_role`).
- :mod:`.genome` — named numeric parameters ⇄ flat GA vector
  (:class:`Gene`, :class:`GenomeSpec`).
- :mod:`.compose` — connect the two (:func:`genome_from_dataclass`,
  :func:`apply_genome`).

This subpackage is not re-exported from ``players.player_sdk`` — import it
explicitly: ``from players.player_sdk.tuning import Knobs, build``.

Origin: extracted from Ron Dahlgren's (swgy) agent libraries (sm-policies
``swgy_knobs.py``; swgy-crewrift ``swgy_tune.knob``).
"""

from .compose import apply_genome, genome_from_dataclass
from .genome import Gene, GenomeSpec
from .knobs import (
    KnobCoercionError,
    Knobs,
    RoleKnob,
    UnknownKnobError,
    build,
    by_role,
    coerce_kwargs,
    coerce_value,
    parse_role_knob,
    split_prefixed,
)

__all__ = [
    "Gene",
    "GenomeSpec",
    "KnobCoercionError",
    "Knobs",
    "RoleKnob",
    "UnknownKnobError",
    "apply_genome",
    "build",
    "by_role",
    "coerce_kwargs",
    "coerce_value",
    "genome_from_dataclass",
    "parse_role_knob",
    "split_prefixed",
]
