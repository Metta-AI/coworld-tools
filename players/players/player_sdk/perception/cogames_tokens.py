"""cogames_tokens.py — generic MettaGrid/cogames token-stream parsing.

Single-pass token decoder that turns one tick's raw token stream into a
structured :class:`Perception` snapshot. Policy-agnostic: knows nothing
about roles, goals, or planning.

Origin: extracted from Ron Dahlgren's (swgy) agent libraries (sm-policies
scripted stack; original module name ``swgy_perception.py``, which also
superseded its near-duplicate ``mas_perception.py``).

**No mettagrid import.** The original consumed a
``mettagrid.simulator.interface.AgentObservation``; the parser only ever
touched ``obs.tokens[*].feature.name`` / ``.feature.normalization`` /
``.location`` / ``.value``, so that surface is expressed here as structural
:class:`~typing.Protocol` types. A real mettagrid ``AgentObservation``
satisfies :class:`ObservationLike` unchanged, and so does any hand-rolled
object with the same attributes — which keeps ``players.player_sdk`` free
of engine imports (see ``validation/players-tests/test_sdk_core_grid_free.py``).

Token conventions this parser encodes (cross-checked against the cogames
reference docs in the original stack):

- Tag tokens use the ``tag`` feature; multiple tags on one cell emit
  multiple tokens at the same location.
- ``inv:*`` features are emitted at the agent's center cell only.
- ``team:<resource>`` features are GLOBAL (location is None) and represent
  team-pooled inventory. They share the ``team:`` prefix with the
  categorical team *tags* (``team:cogs`` etc.) but live in a different
  namespace.
- ``last_action_move`` is global (location is None); never filter by
  center.
- ``aoe_mask`` is per-cell; value 1 = friendly AOE.
- Powered features (``inv:carbon:p1`` etc.) extend numeric range;
  reconstruct the count via the feature's ``normalization`` factor.
- Schema flags (``has_lp_features`` and similar) are not reliable runtime
  guarantees, so this parser only consumes features it actually finds.

Item/element vocabularies are game-specific and deliberately absent:
``Perception.inventory`` / ``team_resources`` are keyed by whatever names
the env's features carry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Protocol, Sequence, runtime_checkable

Coordinate = tuple[int, int]

__all__ = [
    "Coordinate",
    "FeatureLike",
    "ObservationLike",
    "Perception",
    "TagIndex",
    "TokenLike",
    "parse_observation",
]


@runtime_checkable
class FeatureLike(Protocol):
    """The feature descriptor attached to each observation token."""

    @property
    def name(self) -> str: ...

    @property
    def normalization(self) -> float: ...


@runtime_checkable
class TokenLike(Protocol):
    """One observation token: a feature reading at a location (or global)."""

    @property
    def feature(self) -> FeatureLike: ...

    @property
    def location(self) -> Coordinate | None: ...

    @property
    def value(self) -> int: ...


@runtime_checkable
class ObservationLike(Protocol):
    """The per-tick observation container: just a token sequence."""

    @property
    def tokens(self) -> Sequence[TokenLike]: ...


@dataclass
class Perception:
    """Structured snapshot of one observation tick."""

    tags_by_location: dict[Coordinate, set[int]] = field(default_factory=dict)
    inventory: dict[str, int] = field(default_factory=dict)
    team_resources: dict[str, int] = field(default_factory=dict)
    aoe_by_location: dict[Coordinate, int] = field(default_factory=dict)
    in_friendly_aoe: bool = False
    move_succeeded: bool = False
    has_move_token: bool = False
    own_team_tag_ids: frozenset[int] = frozenset()
    last_reward: float = 0.0
    episode_completion_pct: int = 0


class TagIndex:
    """Resolves tag names against the env vocabulary once.

    Tag IDs vary per mission, so we always resolve by name. ``ids_for_names``
    silently drops names that don't exist in this mission, which lets
    callers declare optional tags (``type:chest`` etc.) without
    conditional code.
    """

    def __init__(self, tag_names: Iterable[str]):
        names = list(tag_names)
        self._name_to_id: dict[str, int] = {name: idx for idx, name in enumerate(names)}
        self._team_tag_ids = frozenset(
            idx for idx, name in enumerate(names) if name.startswith("team:")
        )

    @property
    def team_tag_ids(self) -> frozenset[int]:
        return self._team_tag_ids

    def get(self, name: str) -> int | None:
        return self._name_to_id.get(name)

    def has(self, name: str) -> bool:
        return name in self._name_to_id

    def require(self, name: str) -> int:
        idx = self._name_to_id.get(name)
        if idx is None:
            raise KeyError(f"Required tag {name!r} not in env vocabulary")
        return idx

    def ids_for_names(self, names: Iterable[str]) -> frozenset[int]:
        return frozenset(
            self._name_to_id[name] for name in names if name in self._name_to_id
        )


def parse_observation(
    obs: ObservationLike,
    center: Coordinate,
    team_tag_ids: frozenset[int],
) -> Perception:
    """Single-pass token decoder.

    Inventory and team-resource amounts are reconstructed from base + ``:p1``
    powered tokens using each feature's ``normalization`` as the scale base.
    """
    perception = Perception()

    for token in obs.tokens:
        feature_name = token.feature.name
        location = token.location
        value = token.value

        if feature_name == "tag":
            if location is None:
                continue
            perception.tags_by_location.setdefault(location, set()).add(int(value))
            continue

        if feature_name == "aoe_mask":
            if location is None:
                continue
            perception.aoe_by_location[location] = int(value)
            if location == center and int(value) == 1:
                perception.in_friendly_aoe = True
            continue

        if feature_name == "last_action_move":
            perception.has_move_token = True
            perception.move_succeeded = bool(value)
            continue

        if feature_name == "last_reward" and location is None:
            perception.last_reward = float(value) / max(
                float(token.feature.normalization), 1.0
            )
            continue

        if feature_name == "episode_completion_pct" and location is None:
            perception.episode_completion_pct = int(value)
            continue

        if feature_name.startswith("inv:") and location == center:
            _accumulate_powered(
                feature_name[4:], value, token.feature.normalization, perception.inventory
            )
            continue

        if feature_name.startswith("team:") and location is None:
            _accumulate_powered(
                feature_name[5:],
                value,
                token.feature.normalization,
                perception.team_resources,
            )

    perception.own_team_tag_ids = frozenset(
        perception.tags_by_location.get(center, set()) & team_tag_ids
    )
    return perception


def _accumulate_powered(
    suffix: str, value: int, normalization: float, target: dict[str, int]
) -> None:
    """Reconstruct a count from a base / ``:p1`` / ``:p2`` token."""
    if not suffix or value <= 0:
        return
    item_name, sep, power_str = suffix.rpartition(":p")
    if sep and item_name and power_str.isdigit():
        scale = max(int(normalization), 1) ** int(power_str)
    else:
        item_name = suffix
        scale = 1
    target[item_name] = target.get(item_name, 0) + int(value) * scale
