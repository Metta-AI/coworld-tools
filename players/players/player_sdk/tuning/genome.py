"""Gene declaration framework: tunable parameters <-> a flat GA genome vector.

The model: a policy declares a :class:`GenomeSpec` of :class:`Gene` entries.
The spec maps the genes to and from a flat float vector (the GA *genome*) in a
stable order, and validates candidate values against each gene's bounds. A
genetic-algorithm harness consumes only this vector view, so it stays decoupled
from the policy internals.

The vector order is the declaration order of ``GenomeSpec.genes`` and is the
sole genome contract: index ``i`` is always ``genes[i]``.

Origin: extracted from Ron Dahlgren's (swgy) agent libraries (swgy-crewrift,
package ``swgy-tune``). Original names ``Knob``/``KnobSpec``; renamed here to
avoid colliding with the string-kwarg :class:`~players.player_sdk.tuning.Knobs`
mixin that shares this package. See :mod:`players.player_sdk.tuning.compose`
for the glue that connects the two.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Gene:
    """One tunable parameter: a name, inclusive ``[low, high]`` bounds, a default.

    ``default`` must lie within the bounds; :class:`GenomeSpec` validates this.
    """

    name: str
    low: float
    high: float
    default: float

    def clamp(self, value: float) -> float:
        """Return ``value`` clamped into the inclusive ``[low, high]`` range."""
        return min(self.high, max(self.low, value))


@dataclass
class GenomeSpec:
    """An ordered set of genes <-> a flat parameter vector for a GA harness.

    The order of :attr:`genes` defines the genome layout and never changes for a
    given spec, so vectors produced by :meth:`to_vector` / :meth:`sample` /
    :meth:`default_vector` are all mutually compatible.
    """

    genes: list[Gene] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.genes:
            raise ValueError("GenomeSpec needs at least one gene")
        names = [g.name for g in self.genes]
        if len(set(names)) != len(names):
            dupes = sorted({n for n in names if names.count(n) > 1})
            raise ValueError(f"duplicate gene names: {dupes}")
        for g in self.genes:
            if g.low > g.high:
                raise ValueError(f"gene {g.name!r}: low {g.low} > high {g.high}")
            if not (g.low <= g.default <= g.high):
                raise ValueError(
                    f"gene {g.name!r}: default {g.default} outside [{g.low}, {g.high}]"
                )

    def names(self) -> list[str]:
        """Gene names in genome order."""
        return [g.name for g in self.genes]

    def bounds(self) -> list[tuple[float, float]]:
        """``(low, high)`` per gene, in genome order."""
        return [(g.low, g.high) for g in self.genes]

    def default_vector(self) -> list[float]:
        """Each gene's default, in genome order."""
        return [g.default for g in self.genes]

    def to_vector(self, values: Mapping[str, float]) -> list[float]:
        """Project a ``{name: value}`` mapping onto the genome vector.

        Missing names fall back to the gene's ``default``; keys that match no
        gene are ignored. Values are taken as-is (not clamped) so callers can
        detect out-of-range candidates via :meth:`clamp`.
        """
        return [float(values.get(g.name, g.default)) for g in self.genes]

    def from_vector(self, vec: Sequence[float]) -> dict[str, float]:
        """Inverse of :meth:`to_vector`: a genome vector -> ``{name: value}``."""
        self._check_len(vec)
        return {g.name: float(v) for g, v in zip(self.genes, vec)}

    def clamp(self, vec: Sequence[float]) -> list[float]:
        """Clamp each genome element into its gene's bounds."""
        self._check_len(vec)
        return [g.clamp(float(v)) for g, v in zip(self.genes, vec)]

    def sample(self, rng: random.Random) -> list[float]:
        """Draw a genome uniformly at random within the bounds.

        Takes an explicit :class:`random.Random` so sampling is seedable and
        reproducible.
        """
        return [rng.uniform(g.low, g.high) for g in self.genes]

    def _check_len(self, vec: Sequence[float]) -> None:
        if len(vec) != len(self.genes):
            raise ValueError(f"vector length {len(vec)} != gene count {len(self.genes)}")
