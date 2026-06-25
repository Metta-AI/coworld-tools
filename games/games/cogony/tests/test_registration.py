"""Smoke tests: importing ``cogame`` registers the game + variants with cogames."""

from __future__ import annotations

from mettagrid.cogame.game import get_game

import cogony  # noqa: F401 (side-effect import under test)


def test_game_registered_with_cogames() -> None:
    game = get_game("cogony")
    assert game.name == "cogony"
    mission_names = [m.name for m in game.missions]
    assert "cogony" in mission_names


def test_cogony_variant_registered() -> None:
    game = get_game("cogony")
    variant_names = [v.name for v in game.variant_registry.all()]
    assert "cogony" in variant_names


def test_default_mission_make_env_runs() -> None:
    game = get_game("cogony")
    mission = game.missions[0]
    env = mission.make_env()
    assert env.game.num_agents == mission.num_cogs
    assert env.game.max_steps > 0
