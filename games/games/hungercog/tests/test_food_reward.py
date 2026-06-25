"""Test food variant reward behavior.

Verifies that the food reward gives 1/max_steps per tick when the agent
has food >= 1, and 0 when the agent has no food. This behavior is the same
before and after the per_tick -> on_tick StatsMutation conversion.
"""

from hungercog.variants.food import FoodVariant
from mettagrid.config.action_config import ActionsConfig, NoopActionConfig
from mettagrid.config.mettagrid_config import (
    AgentConfig,
    GameConfig,
    InventoryConfig,
    MettaGridConfig,
    ResourceLimitsConfig,
    WallConfig,
)
from mettagrid.config.render_config import RenderConfig
from mettagrid.map_builder.ascii import AsciiMapBuilder
from mettagrid.simulator import Simulation


def _make_food_sim(max_steps: int = 100, initial_food: int = 20) -> Simulation:
    """Create a minimal 1-agent simulation with the food variant applied."""
    cfg = MettaGridConfig(
        game=GameConfig(
            num_agents=1,
            max_steps=max_steps,
            resource_names=[],
            actions=ActionsConfig(noop=NoopActionConfig()),
            agents=[
                AgentConfig(
                    inventory=InventoryConfig(
                        limits={"gear": ResourceLimitsConfig(base=1, max=1, resources=[])},
                    ),
                    rewards={},
                ),
            ],
            objects={"wall": WallConfig()},
            render=RenderConfig(object_status={"agent": {}}),
            map_builder=AsciiMapBuilder.Config(
                map_data=[
                    ["#", "#", "#"],
                    ["#", "@", "#"],
                    ["#", "#", "#"],
                ],
                char_to_map_name={"#": "wall", "@": "agent.agent"},
            ),
        )
    )

    FoodVariant().modify_env(None, cfg)

    sim = Simulation(cfg, seed=42)
    sim.agent(0).set_inventory({"food": initial_food})
    return sim


class TestFoodReward:
    """Test food reward accumulation: 1/max_steps per tick when food >= 1."""

    def test_food_reward_accumulates_while_fed(self):
        """Agent with food gets reward every tick."""
        max_steps = 100
        sim = _make_food_sim(max_steps=max_steps, initial_food=5)
        agent = sim.agent(0)
        weight = 1.0 / max_steps

        for _ in range(10):
            agent.set_action("noop")
            sim.step()

        expected = 10 * weight
        assert abs(agent.episode_reward - expected) < 0.001, (
            f"10 fed ticks: expected ~{expected}, got {agent.episode_reward}"
        )

    def test_food_reward_zero_when_no_food(self):
        """Agent with 0 food gets no reward."""
        sim = _make_food_sim(max_steps=100, initial_food=0)
        agent = sim.agent(0)

        for _ in range(10):
            agent.set_action("noop")
            sim.step()

        assert abs(agent.episode_reward) < 0.001, f"0 food should give 0 reward, got {agent.episode_reward}"

    def test_food_reward_stops_when_food_runs_out(self):
        """Reward stops accumulating once food drops to 0.

        We simulate food depletion by setting inventory to 0 mid-episode.
        """
        max_steps = 100
        sim = _make_food_sim(max_steps=max_steps, initial_food=5)
        agent = sim.agent(0)
        weight = 1.0 / max_steps

        # 5 ticks with food
        for _ in range(5):
            agent.set_action("noop")
            sim.step()

        reward_while_fed = agent.episode_reward
        expected_fed = 5 * weight
        assert abs(reward_while_fed - expected_fed) < 0.001, (
            f"5 fed ticks: expected ~{expected_fed}, got {reward_while_fed}"
        )

        # Remove all food
        agent.set_inventory({"food": 0})

        # 5 more ticks without food
        for _ in range(5):
            agent.set_action("noop")
            sim.step()

        reward_after = agent.episode_reward
        assert abs(reward_after - reward_while_fed) < 0.001, (
            f"Reward should not increase without food: was {reward_while_fed}, now {reward_after}"
        )
