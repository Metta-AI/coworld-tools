"""Tests for the tribal_village environment."""

import pytest

from tests.conftest import requires_nim_library


class TestNimConfig:
    """Tests for the NimConfig ctypes structure."""

    def test_nim_config_fields(self):
        """NimConfig should have all expected fields with correct types."""
        from tribal_village_env.environment import NimConfig

        config = NimConfig()

        # Check all fields exist and have expected types
        assert hasattr(config, "max_steps")
        assert hasattr(config, "victory_condition")
        assert hasattr(config, "tumor_spawn_rate")
        assert hasattr(config, "heart_reward")
        assert hasattr(config, "ore_reward")
        assert hasattr(config, "bar_reward")
        assert hasattr(config, "wood_reward")
        assert hasattr(config, "water_reward")
        assert hasattr(config, "wheat_reward")
        assert hasattr(config, "spear_reward")
        assert hasattr(config, "armor_reward")
        assert hasattr(config, "food_reward")
        assert hasattr(config, "cloth_reward")
        assert hasattr(config, "tumor_kill_reward")
        assert hasattr(config, "survival_penalty")
        assert hasattr(config, "death_penalty")

    def test_nim_config_default_values(self):
        """NimConfig fields should initialize to zero/default."""
        from tribal_village_env.environment import NimConfig

        config = NimConfig()
        assert config.max_steps == 0
        assert config.victory_condition == 0

    def test_nim_config_assignment(self):
        """NimConfig fields should be assignable."""
        from tribal_village_env.environment import NimConfig

        config = NimConfig(
            max_steps=1000,
            victory_condition=1,
            tumor_spawn_rate=0.5,
            heart_reward=1.0,
        )
        assert config.max_steps == 1000
        assert config.victory_condition == 1
        assert config.tumor_spawn_rate == pytest.approx(0.5)
        assert config.heart_reward == pytest.approx(1.0)


class TestConstants:
    """Tests for environment constants."""

    def test_action_space_constants(self):
        """Action space constants should be defined correctly."""
        from tribal_village_env.environment import (
            ACTION_VERB_COUNT,
            ACTION_ARGUMENT_COUNT,
            ACTION_SPACE_SIZE,
        )

        assert ACTION_VERB_COUNT == 11
        assert ACTION_ARGUMENT_COUNT == 28
        assert ACTION_SPACE_SIZE == 308  # 11 * 28


@requires_nim_library
class TestTribalVillageEnvIntegration:
    """Integration tests requiring the Nim library."""

    def test_env_creation(self):
        """Environment should be creatable with default config."""
        from tribal_village_env.environment import TribalVillageEnv

        env = TribalVillageEnv()
        assert env is not None
        assert env.env_ptr is not None
        env.close()

    def test_env_dimensions(self):
        """Environment should report valid dimensions."""
        from tribal_village_env.environment import TribalVillageEnv

        env = TribalVillageEnv()
        assert env.total_agents > 0
        assert env.obs_layers > 0
        assert env.obs_width > 0
        assert env.obs_height > 0
        env.close()

    def test_env_spaces(self):
        """Environment should have valid observation and action spaces."""
        from tribal_village_env.environment import TribalVillageEnv

        env = TribalVillageEnv()
        assert env.single_observation_space is not None
        assert env.single_action_space is not None
        assert env.single_action_space.n == 308
        env.close()

    def test_env_reset(self):
        """Environment reset should return observations and info."""
        from tribal_village_env.environment import TribalVillageEnv

        env = TribalVillageEnv()
        obs, info = env.reset()

        assert isinstance(obs, dict)
        assert len(obs) == env.num_agents
        assert all(k.startswith("agent_") for k in obs)

        assert isinstance(info, dict)
        assert len(info) == env.num_agents

        env.close()

    def test_env_step(self):
        """Environment step should return valid outputs."""
        from tribal_village_env.environment import TribalVillageEnv

        env = TribalVillageEnv()
        env.reset()

        # Take a step with all zero actions
        actions = {f"agent_{i}": 0 for i in range(env.num_agents)}
        obs, rewards, terminated, truncated, infos = env.step(actions)

        assert isinstance(obs, dict)
        assert isinstance(rewards, dict)
        assert isinstance(terminated, dict)
        assert isinstance(truncated, dict)
        assert isinstance(infos, dict)

        assert len(obs) == env.num_agents
        assert len(rewards) == env.num_agents

        env.close()

    def test_env_multiple_steps(self):
        """Environment should handle multiple steps."""
        from tribal_village_env.environment import TribalVillageEnv

        env = TribalVillageEnv()
        env.reset()

        for step in range(10):
            actions = {f"agent_{i}": 0 for i in range(env.num_agents)}
            obs, rewards, terminated, truncated, infos = env.step(actions)

            assert env.step_count == step + 1

        env.close()

    def test_env_close(self):
        """Environment close should release resources."""
        from tribal_village_env.environment import TribalVillageEnv

        env = TribalVillageEnv()
        assert env.env_ptr is not None

        env.close()
        assert env.env_ptr is None

    def test_env_render_ansi(self):
        """Environment should render to ANSI string."""
        from tribal_village_env.environment import TribalVillageEnv

        env = TribalVillageEnv(config={"render_mode": "ansi"})
        env.reset()

        result = env.render()
        assert isinstance(result, str)

        env.close()

    def test_env_config_application(self):
        """Environment should apply custom config."""
        from tribal_village_env.environment import TribalVillageEnv

        config = {
            "max_steps": 500,
            "tumor_spawn_rate": 0.1,
        }
        env = TribalVillageEnv(config=config)
        assert env.max_steps == 500

        env.close()


@requires_nim_library
class TestTribalVillageEnvQueries:
    """Tests for environment query methods."""

    def test_fog_of_war_queries(self):
        """Fog of war query methods should work."""
        from tribal_village_env.environment import TribalVillageEnv

        env = TribalVillageEnv()
        env.reset()

        # These should not raise
        revealed = env.is_tile_revealed(0, 5, 5)
        assert isinstance(revealed, bool)

        count = env.get_revealed_tile_count(0)
        assert isinstance(count, int)
        assert count >= 0

        env.close()

    def test_tech_tree_queries(self):
        """Tech tree query methods should work."""
        from tribal_village_env.environment import TribalVillageEnv

        env = TribalVillageEnv()
        env.reset()

        # Blacksmith upgrades (0-4)
        level = env.has_blacksmith_upgrade(0, 0)
        assert isinstance(level, int)
        assert level >= 0

        # University techs
        has_tech = env.has_university_tech(0, 0)
        assert isinstance(has_tech, bool)

        # Castle techs
        has_castle = env.has_castle_tech(0, 0)
        assert isinstance(has_castle, bool)

        # Unit upgrades
        has_unit = env.has_unit_upgrade(0, 0)
        assert isinstance(has_unit, bool)

        env.close()

    def test_threat_map_queries(self):
        """Threat map query methods should work."""
        from tribal_village_env.environment import TribalVillageEnv

        env = TribalVillageEnv()
        env.reset()

        has_threats = env.has_known_threats(0)
        assert isinstance(has_threats, bool)

        x, y, strength = env.get_nearest_threat(0)
        assert isinstance(x, int)
        assert isinstance(y, int)
        assert isinstance(strength, int)

        count = env.get_threats_in_range(0, 10)
        assert isinstance(count, int)
        assert count >= 0

        threat = env.get_threat_at(0, 5, 5)
        assert isinstance(threat, int)
        assert threat >= 0

        env.close()


class TestMakeTribalVillageEnv:
    """Tests for the factory function."""

    @requires_nim_library
    def test_factory_default(self):
        """Factory should create environment with defaults."""
        from tribal_village_env.environment import make_tribal_village_env

        env = make_tribal_village_env()
        assert env is not None
        env.close()

    @requires_nim_library
    def test_factory_with_config(self):
        """Factory should accept config dict."""
        from tribal_village_env.environment import make_tribal_village_env

        env = make_tribal_village_env(config={"max_steps": 100})
        assert env.max_steps == 100
        env.close()

    @requires_nim_library
    def test_factory_with_kwargs(self):
        """Factory should accept kwargs."""
        from tribal_village_env.environment import make_tribal_village_env

        env = make_tribal_village_env(max_steps=200)
        assert env.max_steps == 200
        env.close()
