"""Seasons variant: seasonal food drops that replenish plant objects."""

from __future__ import annotations

from mettagrid.cogame.core import CoGameMissionVariant, Deps
from hungercog.variants.plants import PlantVariant
from mettagrid.config.event_config import EventConfig
from mettagrid.config.handler_config import updateTarget
from mettagrid.config.mettagrid_config import MettaGridConfig
from mettagrid.config.query import query
from mettagrid.config.tag import typeTag

# Season constants (exported for egg, multi_year, tests)
SEASON_LENGTH = 250
YEAR_LENGTH = 1000
FOOD_DRAIN_PERIOD = 10
STARVATION_CHECK_PERIOD = 5
SEASON_FOOD_PCT: dict[str, float] = {
    "summer": 1.50,
    "fall": 0.90,
    "winter": 0.10,
    "spring": 0.90,
}
DROPS_PER_SEASON = 5
DROP_TARGET_PCT = 0.10
PLANT_DENSITY = 0.016
MAP_WIDTH = 88
MAP_HEIGHT = 88


def _drop_timesteps(season_offset: int, num_years: int) -> list[int]:
    """5 evenly-spaced food drop timesteps within a season, across all years."""
    interval = SEASON_LENGTH // DROPS_PER_SEASON
    timesteps: list[int] = []
    for year in range(num_years):
        base = year * YEAR_LENGTH + season_offset
        timesteps.extend(base + i * interval for i in range(DROPS_PER_SEASON))
    return timesteps


def _estimate_num_plants(num_agents: int) -> int:
    """Estimate total plant objects from map params. Used for food balance math."""
    from_buildings = int(MAP_WIDTH * MAP_HEIGHT * PLANT_DENSITY)
    from_hub = num_agents  # roughly 1 hub plant per agent spawn
    return from_buildings + from_hub


class SeasonsVariant(CoGameMissionVariant):
    """Add seasonal food drops that replenish plant objects. Requires plant variant."""

    name: str = "seasons"
    description: str = "Seasonal food drops replenish plant objects (summer/fall/winter/spring)."

    def dependencies(self) -> Deps:
        return Deps(required=[PlantVariant])

    def modify_env(self, mission, env: MettaGridConfig) -> None:
        num_cogs = len(env.game.agents)
        num_plants = _estimate_num_plants(num_cogs)
        max_steps = env.game.max_steps
        num_years = max_steps // YEAR_LENGTH

        drain_per_season = num_cogs * (SEASON_LENGTH // FOOD_DRAIN_PERIOD)
        plant_query = query(typeTag("plant"))
        plants_per_drop = max(1, round(num_plants * DROP_TARGET_PCT))

        for season_name, offset in [
            ("summer", 0),
            ("fall", SEASON_LENGTH),
            ("winter", 2 * SEASON_LENGTH),
            ("spring", 3 * SEASON_LENGTH),
        ]:
            pct = SEASON_FOOD_PCT[season_name]
            total_food = pct * drain_per_season
            food_per_drop = total_food / DROPS_PER_SEASON
            food_per_plant = max(1, round(food_per_drop / plants_per_drop))

            timesteps = _drop_timesteps(offset, num_years)
            env.game.events[f"{season_name}_food_drop"] = EventConfig(
                name=f"{season_name}_food_drop",
                target_query=plant_query,
                timesteps=timesteps,
                mutations=[updateTarget({"food": food_per_plant})],
                max_targets=plants_per_drop,
            )
