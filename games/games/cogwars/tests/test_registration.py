"""Smoke tests: importing ``cogame`` registers the game + variants with cogames."""

from __future__ import annotations

from cogames.game import get_game

import cogame  # noqa: F401 (side-effect import under test)


def test_game_registered_with_cogames() -> None:
    game = get_game("cogwars")
    assert game.name == "cogwars"
    mission_names = [m.name for m in game.missions]
    assert "default" in mission_names


def test_public_variants_exposed() -> None:
    game = get_game("cogwars")
    variant_names = [v.name for v in game.variant_registry.all()]
    for expected in ("easy", "hard", "big_map", "full"):
        assert expected in variant_names, f"missing variant: {expected}"


def test_default_mission_make_env_runs() -> None:
    game = get_game("cogwars")
    mission = game.missions[0]
    env = mission.make_env()
    assert env.game.num_agents == mission.num_cogs
    assert env.game.max_steps > 0
    assert "ore_vein" in env.game.objects
