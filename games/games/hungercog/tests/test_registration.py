import hungercog  # noqa: F401
from mettagrid.cogame.game import get_game


def test_hungercog_registers_standalone_game_module() -> None:
    game = get_game("hungercog")
    full_variant = game.variant_registry.get("full")

    assert game.__class__.__name__ == "HungerCogGame"
    assert game.__class__.__module__ == "hungercog.game"
    assert [mission.name for mission in game.missions] == ["hungercog"]
    assert full_variant is not None
    assert full_variant.name == "full"
