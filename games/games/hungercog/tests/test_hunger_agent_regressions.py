from hungercog.agent.hunger_agent.entity_map import Entity, EntityMap
from hungercog.agent.hunger_agent.navigator import Navigator
from hungercog.game import make_game


def test_hunger_mission_enables_local_position_tokens() -> None:
    env = make_game("hungercog", num_agents=2, max_steps=50)
    assert env.game.obs.global_obs.local_position is True


def test_reach_adjacent_avoids_blocked_adjacent_goal_cells() -> None:
    nav = Navigator()
    entity_map = EntityMap()

    # Target object at (2, 0). Its north-adjacent cell (1, 0) is blocked by a structure.
    entity_map.entities[(2, 0)] = Entity(type="plant")
    entity_map.entities[(1, 0)] = Entity(type="predator_station")
    entity_map.explored = {(r, c) for r in range(-2, 5) for c in range(-3, 4)}

    goals = nav._goal_cells((2, 0), entity_map, adj=True)
    assert (1, 0) not in goals


def test_egg_events_include_first_year_only_for_partial_second_year() -> None:
    env = make_game("hungercog", num_agents=40, max_steps=1800, variants=["plant", "seasons", "kids"])

    assert env.game.events["egg_drop"].timesteps == [250]
    assert env.game.events["egg_hatch"].timesteps == [750]


def test_hunger_site_scales_hub_spawn_count_with_num_agents() -> None:
    env = make_game("hungercog", num_agents=120, max_steps=250)

    assert env.game.map_builder.instance.hub.spawn_count == 120


def test_default_hunger_map_builds_enough_spawn_points() -> None:
    env = make_game("hungercog", num_agents=40, max_steps=250)

    game_map = env.game.map_builder.create().build_for_num_agents(env.game.num_agents)

    assert (game_map.grid == "agent.agent").sum() == 40
