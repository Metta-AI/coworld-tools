import numpy as np
from cogames.cli.mission import resolve_mission
from cogames.game import get_game

import overcogged  # noqa: F401
from overcogged.game.game import (
    CHOPPED_MEAT,
    CHOPPED_VEG,
    CLEAN_PLATE,
    DIRTY_PLATE,
    DISH_FRIES,
    DISH_SALAD,
    DISH_SOUP,
    QUEUE_FRIES,
    QUEUE_SALAD,
    QUEUE_SOUP,
    STATIONS,
)


def _basic_env(*, variants: list[str] | None = None, cogs: int = 4):
    game = get_game("overcogged")
    _name, env, _mission = resolve_mission(game, "basic", variants_arg=variants, cogs=cogs)
    return env


def test_basic_mission_uses_line_layout() -> None:
    env = _basic_env()
    hub = env.game.map_builder.instance
    grid = env.game.map_builder.create().build().grid

    assert hub.layout == "default"
    assert hub.stations == STATIONS
    assert hub.station_offsets is not None
    assert env.game.map_builder.width == 23
    assert env.game.map_builder.height == 23
    assert grid[9, 7] == "veg_station"
    assert grid[9, 9] == "meat_station"
    assert grid[9, 11] == "chopping_station"
    assert grid[9, 13] == "cooking_station"
    assert grid[9, 15] == "fryer_station"
    assert grid[11, 15] == "plate_station"
    assert grid[13, 11] == "order_board"
    assert grid[13, 13] == "serving_station"
    assert grid[13, 15] == "wash_station"
    assert np.all(grid[0, 9:14] == "empty")
    assert np.all(grid[-1, 9:14] == "empty")
    assert np.all(grid[9:14, 0] == "empty")
    assert np.all(grid[9:14, -1] == "empty")


def test_default_basic_surface_matches_full_variant() -> None:
    default_env = _basic_env()
    full_env = _basic_env(variants=["full"])

    assert default_env.game.resource_names == full_env.game.resource_names
    assert set(default_env.game.objects) == set(full_env.game.objects)
    assert set(default_env.game.events) == set(full_env.game.events)


def test_tutorial_variant_limits_ticket_mix() -> None:
    env = _basic_env(variants=["tutorial"])
    arrivals = [name for name in env.game.events if name.startswith("ticket_arrival_")]

    assert arrivals
    assert all(name.endswith("_salad") for name in arrivals)
    assert "soup_finish_cook" not in env.game.events
    assert "fries_finish_cook" not in env.game.events


def test_basic_mission_render_config_surfaces_plate_states() -> None:
    env = _basic_env()
    render = env.game.render

    assert list(render.agent_huds) == [DISH_SALAD, DISH_SOUP, DISH_FRIES, CLEAN_PLATE, DIRTY_PLATE]
    assert list(render.object_status["agent"]) == [
        CHOPPED_VEG,
        CHOPPED_MEAT,
        DISH_SALAD,
        DISH_SOUP,
        DISH_FRIES,
        CLEAN_PLATE,
        DIRTY_PLATE,
    ]


def test_basic_mission_render_config_surfaces_order_board_queue_statuses() -> None:
    env = _basic_env()
    render = env.game.render

    assert list(render.object_status["order_board"]) == [QUEUE_SALAD, QUEUE_SOUP, QUEUE_FRIES]
