"""Diplomacog mission and variant export surface."""

from collections.abc import Sequence

from diplomacog.game import DiplomacyGame, make_diplomacog_mission
from diplomacog.variants import (
    DIPLOMACY_INTERFACE_VARIANTS,
    VARIANTS,
    diplomacy_mechanics,
    normalize_variant_names,
    parse_variants,
    resolve_variant_selection,
)

DiplomacogGame = DiplomacyGame


def make_diplomacog_env(
    *,
    num_agents: int = 24,
    max_steps: int = 400,
    variants: Sequence[str] = (),
):
    mission = make_diplomacog_mission(num_agents=num_agents, max_steps=max_steps)
    if variants:
        mission = mission.with_variants(list(variants))
    return mission.make_env()


__all__ = [
    "DiplomacogGame",
    "DiplomacyGame",
    "DIPLOMACY_INTERFACE_VARIANTS",
    "VARIANTS",
    "diplomacy_mechanics",
    "make_diplomacog_env",
    "make_diplomacog_mission",
    "normalize_variant_names",
    "parse_variants",
    "resolve_variant_selection",
]
