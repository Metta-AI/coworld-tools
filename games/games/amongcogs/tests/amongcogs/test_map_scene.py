from __future__ import annotations

from collections import Counter

import pytest

from amongcogs.map_scene import AmongUsShipConfig
from amongcogs.runtime import make_game
from mettagrid.simulator import Simulation

TASK_STATIONS = {
    "wiring_station",
    "navigation_station",
    "admin_station",
    "medbay_station",
    "weapons_station",
    "shields_station",
    "comms_station",
}
VENTS = {
    "cafeteria_vent",
    "admin_vent",
    "weapons_vent",
    "reactor_vent",
    "security_vent",
    "upper_engine_vent",
    "medbay_vent",
    "electrical_vent",
    "lower_engine_vent",
    "navigation_vent",
    "oxygen_vent",
    "shields_vent",
}
MAP_BORDER = 3
CAFETERIA_X_RANGE = range(20 + MAP_BORDER, 34 + MAP_BORDER)
CAFETERIA_Y_RANGE = range(2 + MAP_BORDER, 12 + MAP_BORDER)


def test_among_us_site_uses_custom_ship_scene_and_scaled_spawn_count() -> None:
    env = make_game("amongcogs", num_agents=17, max_steps=120)
    map_builder = env.game.map_builder

    assert map_builder.width == 48
    assert map_builder.height == 32
    assert isinstance(map_builder.instance, AmongUsShipConfig)
    assert map_builder.instance.spawn_count == 17


@pytest.mark.parametrize("num_agents", [12, 30])
def test_among_us_ship_scene_places_expected_stations_and_agent_count(num_agents: int) -> None:
    env = make_game("amongcogs", num_agents=num_agents, max_steps=120)
    sim = Simulation(env, seed=1)
    try:
        counts: Counter[str] = Counter()
        for obj in sim.grid_objects(ignore_types=["wall"]).values():
            counts[obj["type_name"]] += 1

        assert counts["agent"] == num_agents
        assert counts["emergency_button"] == 1
        assert counts["wiring_station"] == 1
        assert counts["reactor_station"] == 2
        assert counts["navigation_station"] == 1
        assert counts["oxygen_station"] == 2
        assert counts["admin_station"] == 1
        assert counts["medbay_station"] == 1
        assert counts["weapons_station"] == 1
        assert counts["shields_station"] == 1
        assert counts["comms_station"] == 1
        assert counts["lights_station"] == 1
        assert counts["security_station"] == 1
        for vent_name in VENTS:
            assert counts[vent_name] == 1
    finally:
        sim.close()


def test_among_us_ship_scene_limits_cafeteria_task_station_clustering() -> None:
    env = make_game("amongcogs", num_agents=12, max_steps=120)
    sim = Simulation(env, seed=1)
    try:
        task_station_positions: list[tuple[str, int, int]] = []
        for obj in sim.grid_objects(ignore_types=["wall", "agent"]).values():
            if obj["type_name"] in TASK_STATIONS:
                type_name = str(obj["type_name"])
                c = int(obj["c"])
                r = int(obj["r"])
                task_station_positions.append((type_name, c, r))

        assert len(task_station_positions) == 7
        in_cafeteria = [
            (type_name, c, r)
            for type_name, c, r in task_station_positions
            if c in CAFETERIA_X_RANGE and r in CAFETERIA_Y_RANGE
        ]
        assert len(in_cafeteria) == 0

        for station_type in TASK_STATIONS:
            assert any(
                type_name == station_type and not (c in CAFETERIA_X_RANGE and r in CAFETERIA_Y_RANGE)
                for type_name, c, r in task_station_positions
            )
    finally:
        sim.close()
