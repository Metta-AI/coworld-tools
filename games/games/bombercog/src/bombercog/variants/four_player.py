"""Four-player variant: 4-agent deathmatch on a larger 13x11 map."""

from __future__ import annotations

from bombercog._framework import CoGameMissionVariant
from mettagrid.config.mettagrid_config import MettaGridConfig
from mettagrid.map_builder.ascii import AsciiMapBuilder

# 13x11 map with four corner spawns. Each spawn has an adjacent crate so
# every agent has a meaningful target for their first bomb. Layout is
# symmetric across both axes so no corner is disadvantaged.
MAP_13x11: list[list[str]] = [
    list("#############"),
    list("#@C.......C@#"),
    list("#C.........C#"),
    list("#.C..C.C..C.#"),
    list("#....C.C....#"),
    list("#..C.C.C.C..#"),
    list("#....C.C....#"),
    list("#.C..C.C..C.#"),
    list("#C.........C#"),
    list("#@C.......C@#"),
    list("#############"),
]

NUM_PLAYERS = 4


class FourPlayerVariant(CoGameMissionVariant):
    """Replace the 2-agent 11x9 map with a 4-agent 13x11 map.

    The variant swaps ``env.game.map_builder`` to a map with four corner
    spawns and adjusts ``num_agents`` and the ``agents`` list to match.
    Caller can either pass ``num_agents=4`` explicitly (e.g. via the
    recipe) or leave the default — the variant enforces 4 regardless.
    """

    name: str = "four_player"
    description: str = "4-agent deathmatch on a larger map."

    def modify_env(self, mission, env: MettaGridConfig) -> None:
        env.game.map_builder = AsciiMapBuilder.Config(
            map_data=[list(row) for row in MAP_13x11],
            char_to_map_name={
                "#": "wall",
                ".": "empty",
                "@": "agent.agent",
                "C": "crate",
            },
        )

        # Scale agent list up or down to NUM_PLAYERS. Use the first agent's
        # config as the template so all 4 agents have identical setup.
        if not env.game.agents:
            return
        template = env.game.agents[0].model_copy(deep=True)
        env.game.agents = [template.model_copy(deep=True) for _ in range(NUM_PLAYERS)]
        env.game.num_agents = NUM_PLAYERS
