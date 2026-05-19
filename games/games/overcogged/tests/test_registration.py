from cogames.game import get_game

import overcogged  # noqa: F401


def test_overcogged_registers_standalone_game_module() -> None:
    game = get_game("overcogged")
    full_variant = game.variant_registry.get("full")

    assert game.__class__.__name__ == "OvercookedCoGame"
    assert game.__class__.__module__ == "overcogged.game.game"
    assert [mission.name for mission in game.missions] == ["basic", "classic"]
    assert full_variant is not None
    assert full_variant.name == "full"
