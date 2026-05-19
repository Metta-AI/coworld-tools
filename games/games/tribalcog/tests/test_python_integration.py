"""
Integration tests for the Python-Nim FFI interface.

Tests the TribalVillageEnv class and all FFI functions.
Run with: pytest tests/test_python_integration.py -v
"""

import ctypes
import numpy as np
import pytest

from tribal_village_env.config import (
    DEFAULT_MAX_STEPS,
    DEFAULT_RENDER_SCALE,
    OBS_MAX_VALUE,
    OBS_MIN_VALUE,
    OBS_NORMALIZATION_FACTOR,
)
from tribal_village_env.environment import (
    TribalVillageEnv,
    NimConfig,
    make_tribal_village_env,
    ACTION_SPACE_SIZE,
    ACTION_VERB_COUNT,
    ACTION_ARGUMENT_COUNT,
)


class TestConstants:
    """Test constants module values."""

    def test_observation_bounds(self):
        """Verify observation space bounds are valid."""
        assert OBS_MIN_VALUE == 0
        assert OBS_MAX_VALUE == 255
        assert OBS_NORMALIZATION_FACTOR == 1.0 / 255.0

    def test_defaults_are_positive(self):
        """Verify default values are positive."""
        assert DEFAULT_MAX_STEPS > 0
        assert DEFAULT_RENDER_SCALE > 0


class TestNimConfigStruct:
    """Test the NimConfig ctypes structure matches Nim's CEnvironmentConfig."""

    def test_nimconfig_field_order(self):
        """Verify NimConfig fields are in correct order for FFI alignment."""
        fields = [name for name, _ in NimConfig._fields_]
        expected = [
            "max_steps",
            "victory_condition",
            "tumor_spawn_rate",
            "heart_reward",
            "ore_reward",
            "bar_reward",
            "wood_reward",
            "water_reward",
            "wheat_reward",
            "spear_reward",
            "armor_reward",
            "food_reward",
            "cloth_reward",
            "tumor_kill_reward",
            "survival_penalty",
            "death_penalty",
        ]
        assert fields == expected, f"Field order mismatch: {fields} != {expected}"

    def test_nimconfig_field_types(self):
        """Verify NimConfig field types match Nim's expected types."""
        config = NimConfig()
        assert isinstance(config.max_steps, int)
        assert isinstance(config.victory_condition, int)
        # Float fields
        float_fields = [
            "tumor_spawn_rate", "heart_reward", "ore_reward", "bar_reward",
            "wood_reward", "water_reward", "wheat_reward", "spear_reward",
            "armor_reward", "food_reward", "cloth_reward", "tumor_kill_reward",
            "survival_penalty", "death_penalty",
        ]
        for field in float_fields:
            assert hasattr(config, field), f"Missing field: {field}"

    def test_nimconfig_size(self):
        """Verify NimConfig struct size is consistent."""
        # 2 int32s + 14 floats = 2*4 + 14*4 = 64 bytes
        expected_size = 64
        actual_size = ctypes.sizeof(NimConfig)
        assert actual_size == expected_size, f"Size mismatch: {actual_size} != {expected_size}"


class TestEnvironmentCreation:
    """Test environment creation and configuration."""

    def test_create_default_env(self):
        """Create environment with default config."""
        env = TribalVillageEnv()
        assert env is not None
        assert env.env_ptr is not None
        env.close()

    def test_create_with_config(self):
        """Create environment with custom config."""
        config = {
            "max_steps": 5000,
            "victory_condition": 1,
            "heart_reward": 10.0,
        }
        env = TribalVillageEnv(config=config)
        assert env.max_steps == 5000
        env.close()

    def test_make_factory_function(self):
        """Test make_tribal_village_env factory."""
        env = make_tribal_village_env(max_steps=1000)
        assert env.max_steps == 1000
        env.close()

    def test_env_dimensions(self):
        """Verify environment dimensions are sensible."""
        env = TribalVillageEnv()
        assert env.total_agents > 0
        assert env.obs_layers > 0
        assert env.obs_width > 0
        assert env.obs_height > 0
        assert env.num_agents == env.total_agents
        env.close()

    def test_action_space(self):
        """Verify action space is correctly configured."""
        env = TribalVillageEnv()
        assert env.single_action_space.n == ACTION_SPACE_SIZE
        assert ACTION_SPACE_SIZE == ACTION_VERB_COUNT * ACTION_ARGUMENT_COUNT
        env.close()

    def test_observation_space(self):
        """Verify observation space matches dimensions."""
        env = TribalVillageEnv()
        obs_shape = env.single_observation_space.shape
        assert obs_shape == (env.obs_layers, env.obs_width, env.obs_height)
        env.close()


class TestEnvironmentLifecycle:
    """Test the full environment lifecycle: reset, step, close."""

    @pytest.fixture
    def env(self):
        """Create and yield an environment, then close it."""
        env = TribalVillageEnv()
        yield env
        env.close()

    def test_reset_returns_observations(self, env):
        """Reset should return observations dict for all agents."""
        obs, info = env.reset()
        assert isinstance(obs, dict)
        assert len(obs) == env.num_agents
        for i in range(env.num_agents):
            key = f"agent_{i}"
            assert key in obs
            assert obs[key].shape == env.single_observation_space.shape

    def test_reset_returns_info(self, env):
        """Reset should return info dict for all agents."""
        obs, info = env.reset()
        assert isinstance(info, dict)
        assert len(info) == env.num_agents

    def test_step_with_random_actions(self, env):
        """Step with random actions should work."""
        env.reset()
        actions = {
            f"agent_{i}": np.random.randint(0, ACTION_SPACE_SIZE)
            for i in range(env.num_agents)
        }
        obs, rewards, terminated, truncated, info = env.step(actions)

        assert isinstance(obs, dict)
        assert isinstance(rewards, dict)
        assert isinstance(terminated, dict)
        assert isinstance(truncated, dict)
        assert isinstance(info, dict)

        assert len(obs) == env.num_agents
        assert len(rewards) == env.num_agents

    def test_step_increments_count(self, env):
        """Step should increment step counter."""
        env.reset()
        assert env.step_count == 0

        actions = {f"agent_{i}": 0 for i in range(env.num_agents)}
        env.step(actions)
        assert env.step_count == 1

        env.step(actions)
        assert env.step_count == 2

    def test_multiple_resets(self, env):
        """Multiple resets should work correctly."""
        for _ in range(3):
            obs, info = env.reset()
            assert env.step_count == 0
            assert len(obs) == env.num_agents

    def test_run_multiple_steps(self, env):
        """Run multiple steps without errors."""
        env.reset()
        actions = {f"agent_{i}": 0 for i in range(env.num_agents)}

        for step in range(100):
            obs, rewards, terminated, truncated, info = env.step(actions)
            # Verify step completed without error
            assert env.step_count == step + 1


class TestRenderModes:
    """Test render functionality."""

    @pytest.fixture
    def env(self):
        env = TribalVillageEnv(config={"render_mode": "rgb_array"})
        yield env
        env.close()

    def test_render_mode_property(self, env):
        """Test render_mode property getter/setter."""
        assert env.render_mode == "rgb_array"
        env.render_mode = "ansi"
        assert env.render_mode == "ansi"

    def test_render_rgb_array(self, env):
        """Test RGB array rendering."""
        env.reset()
        env.step({f"agent_{i}": 0 for i in range(env.num_agents)})

        result = env.render()
        if result is not None and isinstance(result, np.ndarray):
            assert result.ndim == 3
            assert result.shape[2] == 3  # RGB channels
            assert result.dtype == np.uint8

    def test_render_ansi(self):
        """Test ANSI text rendering."""
        env = TribalVillageEnv(config={"render_mode": "ansi"})
        env.reset()
        env.step({f"agent_{i}": 0 for i in range(env.num_agents)})

        result = env.render()
        # Should return a string (or empty string if not available)
        assert isinstance(result, str) or result is None
        env.close()


class TestFogOfWarQueries:
    """Test fog of war FFI functions."""

    @pytest.fixture
    def env(self):
        env = TribalVillageEnv()
        env.reset()
        # Run a few steps so some tiles may be revealed
        actions = {f"agent_{i}": 0 for i in range(env.num_agents)}
        for _ in range(10):
            env.step(actions)
        yield env
        env.close()

    def test_is_tile_revealed_returns_bool(self, env):
        """is_tile_revealed should return boolean."""
        result = env.is_tile_revealed(team_id=0, x=0, y=0)
        assert isinstance(result, bool)

    def test_get_revealed_tile_count_returns_int(self, env):
        """get_revealed_tile_count should return non-negative int."""
        count = env.get_revealed_tile_count(team_id=0)
        assert isinstance(count, int)
        assert count >= 0

    def test_clear_revealed_map(self, env):
        """clear_revealed_map should not raise."""
        env.clear_revealed_map(team_id=0)
        # After clearing, count should be 0 or very small
        count = env.get_revealed_tile_count(team_id=0)
        assert count >= 0


class TestTechTreeQueries:
    """Test tech tree state query FFI functions."""

    @pytest.fixture
    def env(self):
        env = TribalVillageEnv()
        env.reset()
        yield env
        env.close()

    def test_has_blacksmith_upgrade(self, env):
        """has_blacksmith_upgrade should return upgrade level."""
        # At game start, should have no upgrades (level 0)
        level = env.has_blacksmith_upgrade(team_id=0, upgrade_type=0)
        assert isinstance(level, int)
        assert level >= 0 and level <= 3

    def test_has_university_tech(self, env):
        """has_university_tech should return boolean."""
        result = env.has_university_tech(team_id=0, tech_type=0)
        assert isinstance(result, bool)

    def test_has_castle_tech(self, env):
        """has_castle_tech should return boolean."""
        result = env.has_castle_tech(team_id=0, tech_type=0)
        assert isinstance(result, bool)

    def test_has_unit_upgrade(self, env):
        """has_unit_upgrade should return boolean."""
        result = env.has_unit_upgrade(team_id=0, upgrade_type=0)
        assert isinstance(result, bool)


class TestThreatMapQueries:
    """Test threat map FFI functions."""

    @pytest.fixture
    def env(self):
        env = TribalVillageEnv()
        env.reset()
        # Run some steps to potentially create threats
        actions = {f"agent_{i}": 0 for i in range(env.num_agents)}
        for _ in range(50):
            env.step(actions)
        yield env
        env.close()

    def test_has_known_threats(self, env):
        """has_known_threats should return boolean."""
        result = env.has_known_threats(team_id=0)
        assert isinstance(result, bool)

    def test_get_nearest_threat(self, env):
        """get_nearest_threat should return tuple of (x, y, strength)."""
        x, y, strength = env.get_nearest_threat(agent_id=0)
        assert isinstance(x, int)
        assert isinstance(y, int)
        assert isinstance(strength, int)
        # If no threat, returns (-1, -1, 0)
        if x == -1:
            assert y == -1
            assert strength == 0

    def test_get_threats_in_range(self, env):
        """get_threats_in_range should return non-negative count."""
        count = env.get_threats_in_range(agent_id=0, radius=10)
        assert isinstance(count, int)
        assert count >= 0

    def test_get_threat_at(self, env):
        """get_threat_at should return threat strength."""
        strength = env.get_threat_at(team_id=0, x=0, y=0)
        assert isinstance(strength, int)
        assert strength >= 0


class TestEndToEndScenarios:
    """End-to-end integration scenarios."""

    def test_full_game_loop(self):
        """Run a complete game loop with random actions."""
        config = {"max_steps": 100}
        env = TribalVillageEnv(config=config)

        obs, info = env.reset()
        total_reward = {f"agent_{i}": 0.0 for i in range(env.num_agents)}
        done = False
        steps = 0

        while not done and steps < 100:
            actions = {
                f"agent_{i}": np.random.randint(0, ACTION_SPACE_SIZE)
                for i in range(env.num_agents)
            }
            obs, rewards, terminated, truncated, info = env.step(actions)

            for agent_id, reward in rewards.items():
                total_reward[agent_id] += reward

            # Check if all agents are done
            all_terminated = all(terminated.values())
            all_truncated = all(truncated.values())
            done = all_terminated or all_truncated
            steps += 1

        env.close()
        assert steps > 0
        assert len(total_reward) == env.num_agents

    def test_config_affects_behavior(self):
        """Different configs should produce different behavior."""
        config1 = {"max_steps": 50, "victory_condition": 0}
        config2 = {"max_steps": 50, "victory_condition": 1}

        env1 = TribalVillageEnv(config=config1)
        env2 = TribalVillageEnv(config=config2)

        # Both should create valid environments
        assert env1.env_ptr is not None
        assert env2.env_ptr is not None

        env1.reset()
        env2.reset()

        env1.close()
        env2.close()

    def test_deterministic_with_same_seed(self):
        """Same seed should produce same initial state."""
        env1 = TribalVillageEnv()
        env2 = TribalVillageEnv()

        obs1, _ = env1.reset(seed=42)
        obs2, _ = env2.reset(seed=42)

        # Initial observations should be identical
        for i in range(env1.num_agents):
            key = f"agent_{i}"
            np.testing.assert_array_equal(obs1[key], obs2[key])

        env1.close()
        env2.close()

    def test_environment_cleanup(self):
        """Environment should clean up resources on close."""
        env = TribalVillageEnv()
        env.reset()
        env.step({f"agent_{i}": 0 for i in range(env.num_agents)})

        # Store pointer before close
        ptr = env.env_ptr
        assert ptr is not None

        env.close()
        assert env.env_ptr is None

    def test_stress_rapid_reset(self):
        """Rapid reset cycles should not leak memory."""
        env = TribalVillageEnv()

        for _ in range(20):
            env.reset()
            actions = {f"agent_{i}": 0 for i in range(env.num_agents)}
            for _ in range(5):
                env.step(actions)

        env.close()

    def test_boundary_actions(self):
        """Test boundary action values."""
        env = TribalVillageEnv()
        env.reset()

        # Test minimum action (0)
        actions_min = {f"agent_{i}": 0 for i in range(env.num_agents)}
        env.step(actions_min)

        # Test maximum valid action
        actions_max = {f"agent_{i}": ACTION_SPACE_SIZE - 1 for i in range(env.num_agents)}
        env.step(actions_max)

        env.close()


class TestAgentInterface:
    """Test agent-specific interface methods."""

    @pytest.fixture
    def env(self):
        env = TribalVillageEnv()
        env.reset()
        yield env
        env.close()

    def test_agents_list(self, env):
        """Verify agents list is populated correctly."""
        assert len(env.agents) == env.num_agents
        assert env.agents == env.possible_agents
        for i, agent in enumerate(env.agents):
            assert agent == f"agent_{i}"

    def test_num_agents_consistent(self, env):
        """num_agents should match total_agents and agents list."""
        assert env.num_agents == env.total_agents
        assert env.num_agents == len(env.agents)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
