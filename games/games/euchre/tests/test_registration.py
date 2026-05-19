"""Smoke tests: importing ``cogame_euchre`` registers the game with the framework."""

from __future__ import annotations

import cogame_euchre  # noqa: F401 (side-effect import under test)
from cogame_euchre.framework import get_game


def test_game_registered() -> None:
    game = get_game("euchre")
    assert game.name == "euchre"
    mission_names = [m.name for m in game.missions]
    assert "basic" in mission_names


def test_variant_registry_present() -> None:
    game = get_game("euchre")
    # Euchre ships with no variants in v1; registry should still exist.
    variant_names = [v.name for v in game.variant_registry.all()]
    assert variant_names == []


def test_default_mission_make_env_runs() -> None:
    game = get_game("euchre")
    mission = game.missions[0]
    env = mission.make_env()
    assert env.game.num_agents == mission.num_cogs
    assert env.game.max_steps > 0
    assert "controller" in env.game.objects
