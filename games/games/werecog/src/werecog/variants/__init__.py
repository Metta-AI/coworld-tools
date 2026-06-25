"""Werewolf/Mafia variants and dependency resolution."""

from __future__ import annotations

from collections.abc import Sequence

from mettagrid.cogame.core import CoGameMissionVariant
from mettagrid.cogame.variants import VariantRegistry
from werecog.variants.full import FullVariant
from werecog.variants.hunt import HuntVariant
from werecog.variants.meetings import MeetingsVariant
from werecog.variants.render import RenderVariant
from werecog.variants.role_action_rewards import RoleActionRewardsVariant
from werecog.variants.roles import RolesVariant
from werecog.variants.survival_rewards import SurvivalRewardsVariant
from werecog.variants.suspicion import SuspicionVariant
from werecog.variants.timing import LongNightVariant, ShortDayVariant, ShortNightVariant
from werecog.variants.voting import VotingVariant
from werecog.variants.win_conditions import WinConditionsVariant

PUBLIC_VARIANT_TYPES: tuple[type[CoGameMissionVariant], ...] = (FullVariant,)
HIDDEN_VARIANT_TYPES: tuple[type[CoGameMissionVariant], ...] = (
    RolesVariant,
    MeetingsVariant,
    SuspicionVariant,
    HuntVariant,
    VotingVariant,
    WinConditionsVariant,
    SurvivalRewardsVariant,
    RoleActionRewardsVariant,
    RenderVariant,
    ShortNightVariant,
    LongNightVariant,
    ShortDayVariant,
)
ALL_VARIANT_TYPES = PUBLIC_VARIANT_TYPES + HIDDEN_VARIANT_TYPES

VARIANTS: tuple[CoGameMissionVariant, ...] = tuple(variant_type() for variant_type in PUBLIC_VARIANT_TYPES)
HIDDEN_VARIANTS: tuple[CoGameMissionVariant, ...] = tuple(variant_type() for variant_type in HIDDEN_VARIANT_TYPES)

_VARIANT_TYPES_BY_NAME = {variant.name: type(variant) for variant in [*VARIANTS, *HIDDEN_VARIANTS]}
HIDDEN_VARIANT_NAMES = frozenset(variant.name for variant in HIDDEN_VARIANTS)
_NON_MECHANIC_VARIANTS = {"full", "short_night", "long_night", "short_day"}
WEREWOLF_MAFIA_INTERFACE_VARIANTS: tuple[str, ...] = ("full",)


def normalize_variant_names(names: Sequence[str]) -> list[str]:
    requested: list[str] = []
    seen: set[str] = set()
    for raw_name in names:
        name = raw_name.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        requested.append(name)
    unknown = [name for name in requested if name not in _VARIANT_TYPES_BY_NAME]
    if unknown:
        available = ", ".join(sorted(_VARIANT_TYPES_BY_NAME))
        raise ValueError(f"Unknown variant {unknown[0]!r}. Available: {available}")
    return requested


def _instantiate_variant(name: str) -> CoGameMissionVariant:
    expected_type = _VARIANT_TYPES_BY_NAME[name]
    return expected_type()  # pyright: ignore[reportCallIssue]


def resolve_variant_selection(names: Sequence[str]) -> VariantRegistry:
    requested = normalize_variant_names(names)
    registry = VariantRegistry([_instantiate_variant(name) for name in requested])
    registry.run_configure(requested)

    unexpected = [variant.name for variant in registry.all() if not isinstance(variant, ALL_VARIANT_TYPES)]
    assert not unexpected, f"Werewolf registry resolved non-local variants: {unexpected}"
    return registry


def parse_variants(names: Sequence[str]) -> list[CoGameMissionVariant]:
    return list(resolve_variant_selection(names).configured())


def variant_dependency_graph(names: Sequence[str]) -> list[tuple[str, str, str]]:
    return resolve_variant_selection(names).build_dependency_graph()


WEREWOLF_MAFIA_MECHANICS: tuple[str, ...] = tuple(
    name
    for name in resolve_variant_selection(WEREWOLF_MAFIA_INTERFACE_VARIANTS).configured_names()
    if name not in _NON_MECHANIC_VARIANTS
)
