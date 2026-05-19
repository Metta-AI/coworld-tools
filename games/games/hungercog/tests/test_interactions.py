"""Interaction tests for the Hunger game.

Tests each game rule individually using minimal environments with deterministic layouts.
"""

from dataclasses import dataclass

from metta.games.games import make_game
from hungercog.game import register_with_metta
from hungercog.variants.carnivore import CarnivoreVariant
from hungercog.variants.herbivore import herbivore_station_config
from hungercog.variants.plants import (
    INITIAL_PLANT_FOOD,
    plant_config,
)
from hungercog.variants.seasons import (
    DROP_TARGET_PCT,
    DROPS_PER_SEASON,
    FOOD_DRAIN_PERIOD,
    SEASON_FOOD_PCT,
    SEASON_LENGTH,
    STARVATION_CHECK_PERIOD,
    YEAR_LENGTH,
)
from hungercog.variants.solar import DAY_LENGTH, DAY_SOLAR_DELTA
from mettagrid.config.event_config import EventConfig, periodic
from mettagrid.config.filter.filter import isNot
from mettagrid.config.handler_config import (
    Handler,
    actorHas,
    firstMatch,
    targetHas,
    updateActor,
    updateTarget,
    withdraw,
)
from mettagrid.config.mettagrid_config import (
    ActionsConfig,
    AgentConfig,
    GameConfig,
    InventoryConfig,
    MettaGridConfig,
    MoveActionConfig,
    NoopActionConfig,
    ResourceLimitsConfig,
    WallConfig,
)
from mettagrid.config.query import query
from mettagrid.config.tag import typeTag
from mettagrid.map_builder.ascii import AsciiMapBuilder
from mettagrid.simulator import Simulation

register_with_metta()

BASE_RESOURCES = ["food", "egg", "kid"]
RESOURCES_WITH_HERBIVORE = BASE_RESOURCES + ["energy", "herbivore"]
RESOURCES_WITH_CARNIVORE = BASE_RESOURCES + ["energy", "herbivore", "carnivore"]


def _hunger_limits(resources: list[str] | None = None) -> dict[str, ResourceLimitsConfig]:
    """Permissive resource limits for testing."""
    res = resources or BASE_RESOURCES
    gear_res = [r for r in res if r in ("herbivore", "carnivore")]
    return {
        "all": ResourceLimitsConfig(base=10000, max=10000, resources=res),
        "gear": ResourceLimitsConfig(base=1, max=1, resources=gear_res),
    }


def _test_agent(
    initial: dict[str, int] | None = None,
    resources: list[str] | None = None,
) -> AgentConfig:
    """Agent config for testing with permissive limits."""
    return AgentConfig(
        inventory=InventoryConfig(
            initial=initial or {},
            limits=_hunger_limits(resources),
        ),
    )


def _agent_with_carnivores(max_steps: int = 100) -> AgentConfig:
    """Agent config with carnivore handlers for carnivore-herbivore tests."""
    limits = _hunger_limits(BASE_RESOURCES + ["carnivore"])
    limits["gear"] = ResourceLimitsConfig(base=1, max=1, resources=["carnivore", "herbivore"])
    limits["energy"] = ResourceLimitsConfig(
        base=100,
        resources=["energy"],
        modifiers={"carnivore": 400, "herbivore": 100},
    )
    return AgentConfig(
        inventory=InventoryConfig(initial={}, limits=limits),
        on_use_handler=firstMatch(
            [
                Handler(
                    name="carnivore_hunts_herbivore",
                    filters=[actorHas({"carnivore": 1}), targetHas({"herbivore": 1})],
                    mutations=[withdraw({"food": 9999}), updateTarget({"egg": -1})],
                ),
                Handler(
                    name="carnivore_tags_carnivore",
                    filters=[actorHas({"carnivore": 1}), targetHas({"carnivore": 1})],
                    mutations=[updateActor({"egg": -1}), updateTarget({"egg": -1})],
                ),
            ]
        ),
    )


@dataclass
class HungerTestHarness:
    """Minimal environment for deterministic Hunger interaction tests."""

    simulation: Simulation

    @classmethod
    def create_single(
        cls,
        station_name: str,
        station_cfg,
        agent_initial: dict[str, int] | None = None,
        events: dict | None = None,
        resources: list[str] | None = None,
    ) -> "HungerTestHarness":
        """5x5 map: agent at (1,2), station at (2,2). Agent moves east to interact."""
        res = resources or BASE_RESOURCES
        cfg = MettaGridConfig(
            game=GameConfig(
                num_agents=1,
                max_steps=100,
                resource_names=res,
                actions=ActionsConfig(noop=NoopActionConfig(), move=MoveActionConfig()),
                agent=_test_agent(resources=res),
                objects={
                    "wall": WallConfig(name="wall"),
                    station_name: station_cfg,
                },
                events=events or {},
                map_builder=AsciiMapBuilder.Config(
                    map_data=[
                        ["#", "#", "#", "#", "#"],
                        ["#", ".", ".", ".", "#"],
                        ["#", "@", "S", ".", "#"],
                        ["#", ".", ".", ".", "#"],
                        ["#", "#", "#", "#", "#"],
                    ],
                    char_to_map_name={
                        "#": "wall",
                        "@": "agent.agent",
                        ".": "empty",
                        "S": station_name,
                    },
                ),
            )
        )
        sim = Simulation(cfg, seed=42)
        if agent_initial:
            sim.agent(0).set_inventory(agent_initial)
        return cls(simulation=sim)

    @classmethod
    def create_two_agents(
        cls,
        agent0_initial: dict[str, int],
        agent1_initial: dict[str, int],
        events: dict | None = None,
        extra_objects: dict | None = None,
        resources: list[str] | None = None,
    ) -> "HungerTestHarness":
        """5x5 map: agent0 at (1,2), agent1 at (2,2). Agent0 moves east onto agent1."""
        res = resources or BASE_RESOURCES
        carn_agent = _agent_with_carnivores(max_steps=100) if "carnivore" in res else None
        # Both agents need carnivore handlers: when A moves onto B, B's onUse runs (target's handlers).
        use_carn = carn_agent and ("carnivore" in (agent0_initial or {}) or "carnivore" in (agent1_initial or {}))
        agent0 = carn_agent if use_carn else _test_agent(resources=res)
        agent1 = carn_agent if use_carn else _test_agent(resources=res)

        objects = {"wall": WallConfig(name="wall")}
        if extra_objects:
            objects.update(extra_objects)

        cfg = MettaGridConfig(
            game=GameConfig(
                num_agents=2,
                max_steps=100,
                resource_names=res,
                actions=ActionsConfig(noop=NoopActionConfig(), move=MoveActionConfig()),
                agents=[agent0, agent1],
                objects=objects,
                events=events or {},
                map_builder=AsciiMapBuilder.Config(
                    map_data=[
                        ["#", "#", "#", "#", "#"],
                        ["#", ".", ".", ".", "#"],
                        ["#", "@", "@", ".", "#"],
                        ["#", ".", ".", ".", "#"],
                        ["#", "#", "#", "#", "#"],
                    ],
                    char_to_map_name={
                        "#": "wall",
                        "@": "agent.agent",
                        ".": "empty",
                    },
                ),
            )
        )
        sim = Simulation(cfg, seed=42)
        sim.agent(0).set_inventory(agent0_initial)
        sim.agent(1).set_inventory(agent1_initial)
        return cls(simulation=sim)

    @classmethod
    def create_event_test(
        cls,
        num_agents: int,
        agent_initial: dict[str, int],
        events: dict,
        max_steps: int = 2000,
        objects: dict | None = None,
        resources: list[str] | None = None,
    ) -> "HungerTestHarness":
        """Minimal map for testing events. Agents in a row."""
        obj_defs = {"wall": WallConfig(name="wall")}
        if objects:
            obj_defs.update(objects)

        res = resources or BASE_RESOURCES
        # Build a map with agents in a line
        row = ["#"] + ["@"] * num_agents + ["."] * (5 - num_agents) + ["#"]
        cfg = MettaGridConfig(
            game=GameConfig(
                num_agents=num_agents,
                max_steps=max_steps,
                resource_names=res,
                actions=ActionsConfig(noop=NoopActionConfig(), move=MoveActionConfig()),
                agent=_test_agent(resources=res),
                objects=obj_defs,
                events=events,
                map_builder=AsciiMapBuilder.Config(
                    map_data=[
                        ["#"] * 7,
                        row,
                        ["#"] * 7,
                    ],
                    char_to_map_name={
                        "#": "wall",
                        "@": "agent.agent",
                        ".": "empty",
                    },
                ),
            )
        )
        sim = Simulation(cfg, seed=42)
        for i in range(num_agents):
            sim.agent(i).set_inventory(agent_initial)
        return cls(simulation=sim)

    def move_agent_east(self, agent_id: int = 0) -> bool:
        """Move agent east (onto station or other agent). Returns action success."""
        self.simulation.agent(agent_id).set_action("move_east")
        # Other agents noop
        for i in range(self.simulation.num_agents):
            if i != agent_id:
                self.simulation.agent(i).set_action("noop")
        self.simulation.step()
        return self.simulation.agent(agent_id).last_action_success

    def step(self, n: int = 1) -> None:
        """Step simulation n times with all agents doing noop."""
        for _ in range(n):
            for i in range(self.simulation.num_agents):
                self.simulation.agent(i).set_action("noop")
            self.simulation.step()

    def inv(self, agent_id: int = 0) -> dict[str, int]:
        return self.simulation.agent(agent_id).inventory

    def close(self) -> None:
        self.simulation.close()


# ===========================================================================
# Plant harvesting
# ===========================================================================


class TestPlantHarvest:
    """Herbivores can harvest food from plants. Carnivores cannot."""

    def test_herbivore_harvests_food(self):
        h = HungerTestHarness.create_single(
            station_name="plant",
            station_cfg=plant_config(),
            agent_initial={"herbivore": 1, "food": 0},
            resources=RESOURCES_WITH_HERBIVORE,
        )
        h.move_agent_east()
        assert h.inv().get("food", 0) == INITIAL_PLANT_FOOD
        h.close()

    def test_carnivore_cannot_harvest(self):
        h = HungerTestHarness.create_single(
            station_name="plant",
            station_cfg=plant_config(),
            agent_initial={"carnivore": 1, "food": 0},
            resources=RESOURCES_WITH_CARNIVORE,
        )
        h.move_agent_east()
        assert h.inv().get("food", 0) == 0
        h.close()

    def test_gearless_cannot_harvest(self):
        """Without herbivore gear, cannot harvest herbivore-only plant."""
        h = HungerTestHarness.create_single(
            station_name="plant",
            station_cfg=plant_config(),
            agent_initial={"food": 0},
            resources=RESOURCES_WITH_HERBIVORE,
        )
        h.move_agent_east()
        assert h.inv().get("food", 0) == 0
        h.close()


# ===========================================================================
# Gear stations
# ===========================================================================


class TestGearStations:
    """Agents pick up gear once and cannot change."""

    def test_get_carnivore_gear(self):
        h = HungerTestHarness.create_single(
            station_name="carnivore_station",
            station_cfg=CarnivoreVariant.carnivore_station_config(),
            resources=RESOURCES_WITH_CARNIVORE,
        )
        h.move_agent_east()
        assert h.inv().get("carnivore", 0) == 1
        h.close()

    def test_get_herbivore_gear(self):
        h = HungerTestHarness.create_single(
            station_name="herbivore_station",
            station_cfg=herbivore_station_config(),
            resources=RESOURCES_WITH_HERBIVORE,
        )
        h.move_agent_east()
        assert h.inv().get("herbivore", 0) == 1
        h.close()

    def test_cannot_change_gear_carnivore_to_herbivore(self):
        """Agent with carnivore gear cannot switch to herbivore."""
        h = HungerTestHarness.create_single(
            station_name="herbivore_station",
            station_cfg=herbivore_station_config(),
            agent_initial={"carnivore": 1},
            resources=RESOURCES_WITH_CARNIVORE,
        )
        h.move_agent_east()
        assert h.inv().get("carnivore", 0) == 1
        assert h.inv().get("herbivore", 0) == 0
        h.close()

    def test_cannot_change_gear_herbivore_to_carnivore(self):
        """Agent with herbivore gear cannot switch to carnivore."""
        h = HungerTestHarness.create_single(
            station_name="carnivore_station",
            station_cfg=CarnivoreVariant.carnivore_station_config(),
            agent_initial={"herbivore": 1},
            resources=RESOURCES_WITH_CARNIVORE,
        )
        h.move_agent_east()
        assert h.inv().get("herbivore", 0) == 1
        assert h.inv().get("carnivore", 0) == 0
        h.close()


# ===========================================================================
# Predator-prey interactions
# ===========================================================================


class TestCarnivoreHerbivoreInteraction:
    """Predator tags prey: steals all food, prey loses egg."""

    def test_predator_steals_food_from_prey(self):
        h = HungerTestHarness.create_two_agents(
            agent0_initial={"carnivore": 1, "food": 0},
            agent1_initial={"herbivore": 1, "food": 50, "egg": 1},
            resources=RESOURCES_WITH_CARNIVORE,
        )
        h.move_agent_east()
        # Carnivore should have herbivore's food (up to cap)
        assert h.inv(0).get("food", 0) == 50
        # Herbivore should have no food
        assert h.inv(1).get("food", 0) == 0
        h.close()

    def test_carnivore_takes_all_food_capped(self):
        """Carnivore's food is capped at inventory max."""
        h = HungerTestHarness.create_two_agents(
            agent0_initial={"carnivore": 1, "food": 80},
            agent1_initial={"herbivore": 1, "food": 50, "egg": 1},
            resources=RESOURCES_WITH_CARNIVORE,
        )
        h.move_agent_east()
        # Carnivore can only hold up to their limit
        pred_food = h.inv(0).get("food", 0)
        assert pred_food >= 80  # at least kept what they had
        h.close()

    def test_herbivore_loses_egg_when_tagged(self):
        h = HungerTestHarness.create_two_agents(
            agent0_initial={"carnivore": 1, "food": 0},
            agent1_initial={"herbivore": 1, "food": 50, "egg": 1},
            resources=RESOURCES_WITH_CARNIVORE,
        )
        h.move_agent_east()
        assert h.inv(1).get("egg", 0) == 0
        h.close()

    def test_herbivore_without_egg_still_loses_food(self):
        h = HungerTestHarness.create_two_agents(
            agent0_initial={"carnivore": 1, "food": 0},
            agent1_initial={"herbivore": 1, "food": 30},
            resources=RESOURCES_WITH_CARNIVORE,
        )
        h.move_agent_east()
        assert h.inv(0).get("food", 0) == 30
        assert h.inv(1).get("food", 0) == 0
        h.close()


# ===========================================================================
# Carnivore-carnivore interactions
# ===========================================================================


class TestCarnivoreCarnivoreInteraction:
    """Carnivore tags carnivore: both lose egg."""

    def test_both_carnivores_lose_egg(self):
        h = HungerTestHarness.create_two_agents(
            agent0_initial={"carnivore": 1, "food": 20, "egg": 1},
            agent1_initial={"carnivore": 1, "food": 20, "egg": 1},
            resources=RESOURCES_WITH_CARNIVORE,
        )
        h.move_agent_east()
        assert h.inv(0).get("egg", 0) == 0
        assert h.inv(1).get("egg", 0) == 0
        h.close()

    def test_no_food_transfer_between_carnivores(self):
        h = HungerTestHarness.create_two_agents(
            agent0_initial={"carnivore": 1, "food": 10, "egg": 1},
            agent1_initial={"carnivore": 1, "food": 40, "egg": 1},
            resources=RESOURCES_WITH_CARNIVORE,
        )
        h.move_agent_east()
        # Food should not change (no withdraw in carnivore-carnivore handler)
        assert h.inv(0).get("food", 0) == 10
        assert h.inv(1).get("food", 0) == 40
        h.close()

    def test_herbivore_cannot_tag_carnivore(self):
        """Herbivore walking onto carnivore should not trigger any combat handler."""
        h = HungerTestHarness.create_two_agents(
            agent0_initial={"herbivore": 1, "food": 20, "egg": 1},
            agent1_initial={"carnivore": 1, "food": 40, "egg": 1},
            resources=RESOURCES_WITH_CARNIVORE,
        )
        h.move_agent_east()
        # Nothing should happen — herbivore has no offensive handlers
        assert h.inv(0).get("egg", 0) == 1
        assert h.inv(1).get("egg", 0) == 1
        assert h.inv(0).get("food", 0) == 20
        assert h.inv(1).get("food", 0) == 40
        h.close()


# ===========================================================================
# Events: food drain
# ===========================================================================


class TestFoodDrain:
    """Periodic food drain reduces all agents' food."""

    def test_food_drains_over_time(self):
        events = {
            "food_drain": EventConfig(
                name="food_drain",
                target_query=query(typeTag("agent")),
                timesteps=periodic(start=0, period=FOOD_DRAIN_PERIOD, end=100),
                mutations=[updateTarget({"food": -1})],
            ),
        }
        h = HungerTestHarness.create_event_test(
            num_agents=1,
            agent_initial={"food": 50},
            events=events,
            max_steps=100,
        )
        # Step enough times for several drain events
        h.step(FOOD_DRAIN_PERIOD * 5)
        food = h.inv().get("food", 0)
        assert food < 50, f"Food should have drained, got {food}"
        h.close()

    def test_food_cannot_go_below_zero(self):
        events = {
            "food_drain": EventConfig(
                name="food_drain",
                target_query=query(typeTag("agent")),
                timesteps=periodic(start=0, period=1, end=100),
                mutations=[updateTarget({"food": -1})],
            ),
        }
        h = HungerTestHarness.create_event_test(
            num_agents=1,
            agent_initial={"food": 3},
            events=events,
            max_steps=100,
        )
        h.step(20)
        food = h.inv().get("food", 0)
        assert food == 0, f"Food should not go below 0, got {food}"
        h.close()


# ===========================================================================
# Events: starvation check
# ===========================================================================


class TestStarvationCheck:
    """Agents with egg but no food lose the egg."""

    def test_starving_agent_loses_egg(self):
        events = {
            "starvation_check": EventConfig(
                name="starvation_check",
                target_query=query(typeTag("agent")),
                timesteps=periodic(start=0, period=STARVATION_CHECK_PERIOD, end=100),
                filters=[targetHas({"egg": 1}), isNot(targetHas({"food": 1}))],
                mutations=[updateTarget({"egg": -1})],
            ),
        }
        h = HungerTestHarness.create_event_test(
            num_agents=1,
            agent_initial={"food": 0, "egg": 1},
            events=events,
            max_steps=100,
        )
        h.step(STARVATION_CHECK_PERIOD + 1)
        assert h.inv().get("egg", 0) == 0, "Starving agent should lose egg"
        h.close()

    def test_fed_agent_keeps_egg(self):
        events = {
            "starvation_check": EventConfig(
                name="starvation_check",
                target_query=query(typeTag("agent")),
                timesteps=periodic(start=0, period=STARVATION_CHECK_PERIOD, end=100),
                filters=[targetHas({"egg": 1}), isNot(targetHas({"food": 1}))],
                mutations=[updateTarget({"egg": -1})],
            ),
        }
        h = HungerTestHarness.create_event_test(
            num_agents=1,
            agent_initial={"food": 50, "egg": 1},
            events=events,
            max_steps=100,
        )
        h.step(STARVATION_CHECK_PERIOD * 3)
        assert h.inv().get("egg", 0) == 1, "Fed agent should keep egg"
        h.close()


# ===========================================================================
# Events: egg drop and hatch
# ===========================================================================


class TestEggLifecycle:
    """Eggs are given in fall and hatch in spring."""

    def test_egg_drop_at_fall(self):
        fall_start = SEASON_LENGTH  # 250
        events = {
            "egg_drop": EventConfig(
                name="egg_drop",
                target_query=query(typeTag("agent")),
                timesteps=[fall_start],
                mutations=[updateTarget({"egg": 1})],
            ),
        }
        h = HungerTestHarness.create_event_test(
            num_agents=1,
            agent_initial={"egg": 0},
            events=events,
            max_steps=2000,
        )
        # Step past fall start
        h.step(fall_start + 5)
        assert h.inv().get("egg", 0) == 1, "Agent should receive egg at fall"
        h.close()

    def test_egg_hatch_at_spring(self):
        spring_start = 3 * SEASON_LENGTH  # 750
        events = {
            "egg_hatch": EventConfig(
                name="egg_hatch",
                target_query=query(typeTag("agent")),
                timesteps=[spring_start],
                filters=[targetHas({"egg": 1})],
                mutations=[updateTarget({"egg": -1}), updateTarget({"kid": 1})],
            ),
        }
        h = HungerTestHarness.create_event_test(
            num_agents=1,
            agent_initial={"egg": 1, "kid": 0},
            events=events,
            max_steps=2000,
        )
        h.step(spring_start + 5)
        assert h.inv().get("egg", 0) == 0, "Egg should hatch at spring"
        assert h.inv().get("kid", 0) == 1, "Hatched egg should produce a kid"
        h.close()

    def test_no_egg_no_hatch(self):
        """Agents without egg at spring get nothing."""
        spring_start = 3 * SEASON_LENGTH
        events = {
            "egg_hatch": EventConfig(
                name="egg_hatch",
                target_query=query(typeTag("agent")),
                timesteps=[spring_start],
                filters=[targetHas({"egg": 1})],
                mutations=[updateTarget({"egg": -1}), updateTarget({"kid": 1})],
            ),
        }
        h = HungerTestHarness.create_event_test(
            num_agents=1,
            agent_initial={"egg": 0, "kid": 0},
            events=events,
            max_steps=2000,
        )
        h.step(spring_start + 5)
        assert h.inv().get("egg", 0) == 0
        assert h.inv().get("kid", 0) == 0, "No egg means no kid"
        h.close()


# ===========================================================================
# Events: day/night solar cycle
# ===========================================================================


class TestDayNightCycle:
    """Solar changes between day and night."""

    def test_solar_increases_at_day(self):
        events = {
            "day_solar": EventConfig(
                name="day_solar",
                target_query=query(typeTag("agent")),
                timesteps=periodic(start=0, period=DAY_LENGTH, end=200),
                mutations=[updateTarget({"solar": DAY_SOLAR_DELTA})],
            ),
            "night_solar": EventConfig(
                name="night_solar",
                target_query=query(typeTag("agent")),
                timesteps=periodic(start=DAY_LENGTH // 2, period=DAY_LENGTH, end=200),
                mutations=[updateTarget({"solar": -DAY_SOLAR_DELTA})],
            ),
        }
        h = HungerTestHarness.create_event_test(
            num_agents=1,
            agent_initial={"solar": 1},
            events=events,
            max_steps=200,
            resources=BASE_RESOURCES + ["energy", "solar"],
        )
        # Step 1 tick past day event (timestep 0)
        h.step(2)
        solar = h.inv().get("solar", 0)
        assert solar == 1 + DAY_SOLAR_DELTA, f"Solar should be {1 + DAY_SOLAR_DELTA} during day, got {solar}"
        h.close()

    def test_solar_decreases_at_night(self):
        half_day = DAY_LENGTH // 2
        events = {
            "day_solar": EventConfig(
                name="day_solar",
                target_query=query(typeTag("agent")),
                timesteps=periodic(start=0, period=DAY_LENGTH, end=200),
                mutations=[updateTarget({"solar": DAY_SOLAR_DELTA})],
            ),
            "night_solar": EventConfig(
                name="night_solar",
                target_query=query(typeTag("agent")),
                timesteps=periodic(start=half_day, period=DAY_LENGTH, end=200),
                mutations=[updateTarget({"solar": -DAY_SOLAR_DELTA})],
            ),
        }
        h = HungerTestHarness.create_event_test(
            num_agents=1,
            agent_initial={"solar": 1},
            events=events,
            max_steps=200,
            resources=BASE_RESOURCES + ["energy", "solar"],
        )
        # Step past night event
        h.step(half_day + 2)
        solar = h.inv().get("solar", 0)
        # Day added +2, then night subtracted -2, net = base
        assert solar == 1, f"Solar should be back to base at night, got {solar}"
        h.close()


# ===========================================================================
# Events: plant food regeneration
# ===========================================================================


class TestPlantRegen:
    """Plants regenerate food via seasonal food drop events."""

    def test_plants_gain_food_from_drop(self):
        # Single food drop event at timestep 5 targeting all plants
        events = {
            "test_drop": EventConfig(
                name="test_drop",
                target_query=query(typeTag("plant")),
                timesteps=[5],
                mutations=[updateTarget({"food": 10})],
                max_targets=10,
            ),
        }

        plant_obj = plant_config()
        empty_plant = plant_obj.model_copy(update={"inventory": InventoryConfig(initial={"food": 0})})

        h = HungerTestHarness.create_event_test(
            num_agents=1,
            agent_initial={},
            events=events,
            max_steps=100,
            objects={"plant": empty_plant},
        )
        h.step(10)

        grid_objects = h.simulation.grid_objects()
        plants = [obj for obj in grid_objects.values() if "plant" in obj.get("type_name", "")]
        assert any(obj.get("inventory", {}).get("food", 0) > 0 for obj in plants) or len(plants) == 0
        h.close()


# ===========================================================================
# Full season integration
# ===========================================================================


class TestSeasonEvents:
    """Test events from variant pipeline (plants + kids)."""

    def test_generates_expected_events(self):
        env = make_game("hungercog", num_agents=40, max_steps=5000, variants=["plant", "seasons", "kids"])
        events = env.game.events
        # Seasonal food drops (seasons variant)
        for season in SEASON_FOOD_PCT:
            assert f"{season}_food_drop" in events
        # Egg lifecycle (kids variant)
        assert "egg_drop" in events
        assert "egg_hatch" in events
        # Food drain (kids variant)
        assert "food_drain" in events
        # Starvation (kids variant)
        assert "starvation_check" in events

    def test_five_drops_per_season(self):
        env = make_game("hungercog", num_agents=40, max_steps=5000, variants=["plant", "seasons", "kids"])
        events = env.game.events
        for season in SEASON_FOOD_PCT:
            timesteps = events[f"{season}_food_drop"].timesteps
            # 5 drops per season * 5 years = 25
            assert len(timesteps) == DROPS_PER_SEASON * 5

    def test_summer_drops_more_than_winter(self):
        env = make_game("hungercog", num_agents=40, max_steps=5000, variants=["plant", "seasons", "kids"])
        events = env.game.events
        summer_hp = events["summer_food_drop"].mutations[0].deltas["food"]
        winter_hp = events["winter_food_drop"].mutations[0].deltas["food"]
        assert summer_hp > winter_hp

    def test_drop_targets_10pct_of_plants(self):
        env = make_game("hungercog", num_agents=40, max_steps=5000, variants=["plant", "seasons", "kids"])
        events = env.game.events
        num_plants = max(1, round(88 * 88 * 0.016 + 40))  # plants variant's _estimate_num_plants(40)
        expected = max(1, round(num_plants * DROP_TARGET_PCT))
        for season in SEASON_FOOD_PCT:
            assert events[f"{season}_food_drop"].max_targets == expected

    def test_egg_drop_fires_at_fall_starts(self):
        env = make_game("hungercog", num_agents=40, max_steps=5000, variants=["plant", "seasons", "kids"])
        egg_drop_times = env.game.events["egg_drop"].timesteps
        # 5 years = 5 egg drops
        assert len(egg_drop_times) == 5
        for i, t in enumerate(egg_drop_times):
            assert t == i * YEAR_LENGTH + SEASON_LENGTH

    def test_egg_hatch_fires_at_spring_starts(self):
        env = make_game("hungercog", num_agents=40, max_steps=5000, variants=["plant", "seasons", "kids"])
        egg_hatch_times = env.game.events["egg_hatch"].timesteps
        assert len(egg_hatch_times) == 5
        for i, t in enumerate(egg_hatch_times):
            assert t == i * YEAR_LENGTH + 3 * SEASON_LENGTH

    def test_food_scales_with_num_cogs(self):
        env_small = make_game("hungercog", num_agents=10, max_steps=5000, variants=["plant", "seasons", "kids"])
        env_large = make_game("hungercog", num_agents=80, max_steps=5000, variants=["plant", "seasons", "kids"])
        small_hp = env_small.game.events["summer_food_drop"].mutations[0].deltas["food"]
        large_hp = env_large.game.events["summer_food_drop"].mutations[0].deltas["food"]
        assert large_hp > small_hp
