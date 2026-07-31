"""Glue between the two halves of this package.

:mod:`.knobs` turns string kwargs into typed frozen dataclass configs;
:mod:`.genome` maps named numeric parameters to and from a flat GA vector.
This module composes them into one pipeline::

    GA vector  ⇄  {name: float}  ⇄  typed frozen config dataclass

Typical use: a config dataclass documents tunable-range suggestions as
``# GA bounds [lo, hi]`` comments (see ``nav_mesh/params.py``); a tuning
harness picks the fields it wants to search, builds a :class:`~.genome.GenomeSpec`
with :func:`genome_from_dataclass`, and turns each candidate vector back into a
config with :func:`apply_genome`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import MISSING, fields, is_dataclass, replace
from typing import Any, get_type_hints

from .genome import Gene, GenomeSpec

__all__ = ["apply_genome", "genome_from_dataclass"]


def genome_from_dataclass(
    cls: type, bounds: Mapping[str, tuple[float, float]]
) -> GenomeSpec:
    """Build a :class:`GenomeSpec` from a dataclass's numeric fields.

    ``bounds`` maps field names to inclusive ``(low, high)`` search ranges;
    its iteration order defines the genome layout. Each named field must
    exist on *cls* and have a numeric (``int``/``float``/``bool``) default,
    which becomes the gene's default.
    """
    if not is_dataclass(cls):
        raise TypeError(f"{cls!r} is not a dataclass")
    by_name = {f.name: f for f in fields(cls)}
    genes: list[Gene] = []
    for name, (low, high) in bounds.items():
        f = by_name.get(name)
        if f is None:
            raise ValueError(f"{cls.__name__} has no field {name!r}")
        if f.default is not MISSING:
            default: Any = f.default
        elif f.default_factory is not MISSING:  # type: ignore[misc]
            default = f.default_factory()  # type: ignore[misc]
        else:
            raise ValueError(f"{cls.__name__}.{name} has no default to seed the gene")
        if not isinstance(default, (int, float)):
            raise ValueError(
                f"{cls.__name__}.{name} default {default!r} is not numeric"
            )
        genes.append(Gene(name=name, low=float(low), high=float(high), default=float(default)))
    return GenomeSpec(genes)


def apply_genome(cfg: Any, spec: GenomeSpec, vec: Sequence[float]) -> Any:
    """Overlay a genome vector onto a config instance.

    Returns ``dataclasses.replace(cfg, ...)`` with each gene's value written
    to its field, converted to the field's declared type: ``int`` fields are
    rounded, ``bool`` fields threshold at 0.5, everything else stays float.
    Fields not covered by *spec* keep their current values.
    """
    if not is_dataclass(cfg):
        raise TypeError(f"{cfg!r} is not a dataclass instance")
    try:
        hints = get_type_hints(type(cfg))
    except Exception:
        hints = {}
    converted: dict[str, Any] = {}
    for name, value in spec.from_vector(vec).items():
        target = hints.get(name)
        if target is bool:
            converted[name] = value >= 0.5
        elif target is int:
            converted[name] = round(value)
        else:
            converted[name] = value
    return replace(cfg, **converted)
