"""Layout variants — swap the map and adjust agent count.

Demonstrates replacing ``env.game.map_builder`` and scaling ``num_agents`` in
lockstep. Use this pattern to ship alternative arenas that still run against
the same core mechanics.

TODO(cogame): design your own maps and add more layout variants as needed.
"""

from __future__ import annotations

from mettagrid.config.mettagrid_config import MettaGridConfig
from mettagrid.map_builder.ascii import AsciiMapBuilder

from cogame.framework import CoGameMissionVariant

# A larger 13x13 map with four corner spawns and four ore veins.
BIG_MAP: list[list[str]] = [
    list("#############"),
    list("#@.........@#"),
    list("#...#...#...#"),
    list("#..#V...V#..#"),
    list("#...#...#...#"),
    list("#.....V.....#"),
    list("#...........#"),
    list("#.....V.....#"),
    list("#...#...#...#"),
    list("#..#V...V#..#"),
    list("#...#...#...#"),
    list("#@.........@#"),
    list("#############"),
]

BIG_MAP_NUM_AGENTS = 4


class BigMapVariant(CoGameMissionVariant):
    """Swap to a 13x13 four-corner map and scale the agent list to 4.

    Mirrors the :class:`bombercog.variants.four_player.FourPlayerVariant`
    pattern: replace the map builder, then duplicate the first agent's config
    up to the new target count.
    """

    name: str = "big_map"
    description: str = "13x13 map with 4 corner spawns."

    def modify_env(self, mission, env: MettaGridConfig) -> None:
        env.game.map_builder = AsciiMapBuilder.Config(
            map_data=[list(row) for row in BIG_MAP],
            char_to_map_name={
                "#": "wall",
                ".": "empty",
                "@": "agent.agent",
                "V": "ore_vein",
            },
        )

        if not env.game.agents:
            return
        template = env.game.agents[0].model_copy(deep=True)
        env.game.agents = [template.model_copy(deep=True) for _ in range(BIG_MAP_NUM_AGENTS)]
        env.game.num_agents = BIG_MAP_NUM_AGENTS
