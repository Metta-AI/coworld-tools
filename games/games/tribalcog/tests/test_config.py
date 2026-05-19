"""Tests for the config module."""

import math

import pytest

from tribal_village_env.config import (
    EnvironmentConfig,
    PolicyConfig,
    PPOConfig,
    RewardConfig,
    TrainingConfig,
)


class TestConfig:
    """Tests for the base Config class."""

    def test_override_simple(self):
        """Test simple field override."""
        env = EnvironmentConfig()
        env.override("max_steps", 5000)
        assert env.max_steps == 5000

    def test_override_nested(self):
        """Test nested field override using dot notation."""
        env = EnvironmentConfig()
        env.override("rewards.heart", 2.0)
        assert env.rewards.heart == 2.0

    def test_override_invalid_field(self):
        """Test that overriding invalid field raises ValueError."""
        env = EnvironmentConfig()
        with pytest.raises(ValueError, match="not found"):
            env.override("invalid_field", 123)

    def test_update_multiple(self):
        """Test batch update of multiple fields."""
        env = EnvironmentConfig()
        env.update({
            "max_steps": 3000,
            "render_scale": 2,
            "rewards.heart": 1.5,
        })
        assert env.max_steps == 3000
        assert env.render_scale == 2
        assert env.rewards.heart == 1.5


class TestRewardConfig:
    """Tests for RewardConfig."""

    def test_defaults_are_nan(self):
        """Test that default reward values are NaN."""
        rewards = RewardConfig()
        assert math.isnan(rewards.heart)
        assert math.isnan(rewards.ore)
        assert math.isnan(rewards.death_penalty)

    def test_set_reward_value(self):
        """Test setting a reward value."""
        rewards = RewardConfig(heart=1.5, ore=0.5)
        assert rewards.heart == 1.5
        assert rewards.ore == 0.5


class TestEnvironmentConfig:
    """Tests for EnvironmentConfig."""

    def test_default_values(self):
        """Test that default values are set correctly."""
        env = EnvironmentConfig()
        assert env.max_steps == 10_000
        assert env.render_mode == "rgb_array"
        assert env.render_scale == 4

    def test_custom_values(self):
        """Test creating config with custom values."""
        env = EnvironmentConfig(max_steps=5000, render_mode="ansi")
        assert env.max_steps == 5000
        assert env.render_mode == "ansi"

    def test_render_mode_validation(self):
        """Test that invalid render mode raises ValueError."""
        with pytest.raises(ValueError, match="render_mode must be one of"):
            EnvironmentConfig(render_mode="invalid")

    def test_to_legacy_dict(self):
        """Test conversion to legacy dictionary format."""
        env = EnvironmentConfig(max_steps=5000, render_mode="ansi")
        env.rewards.heart = 1.5
        legacy = env.to_legacy_dict()

        assert legacy["max_steps"] == 5000
        assert legacy["render_mode"] == "ansi"
        assert legacy["heart_reward"] == 1.5

    def test_from_legacy_dict(self):
        """Test creation from legacy dictionary format."""
        legacy = {
            "max_steps": 3000,
            "heart_reward": 2.0,
            "render_mode": "ansi",
        }
        env = EnvironmentConfig.from_legacy_dict(legacy)

        assert env.max_steps == 3000
        assert env.rewards.heart == 2.0
        assert env.render_mode == "ansi"

    def test_legacy_roundtrip(self):
        """Test that legacy dict conversion is reversible."""
        original = EnvironmentConfig(max_steps=7500, render_scale=2)
        original.rewards.ore = 0.5

        legacy = original.to_legacy_dict()
        restored = EnvironmentConfig.from_legacy_dict(legacy)

        assert restored.max_steps == original.max_steps
        assert restored.render_scale == original.render_scale
        assert restored.rewards.ore == original.rewards.ore


class TestPPOConfig:
    """Tests for PPOConfig."""

    def test_default_values(self):
        """Test that PPO defaults match expected values."""
        ppo = PPOConfig()
        assert ppo.learning_rate == 0.0005
        assert ppo.gamma == 0.995
        assert ppo.clip_coef == 0.2

    def test_validation_learning_rate(self):
        """Test that learning_rate must be positive."""
        with pytest.raises(ValueError):
            PPOConfig(learning_rate=0)

    def test_validation_gamma_bounds(self):
        """Test that gamma must be in [0, 1]."""
        with pytest.raises(ValueError):
            PPOConfig(gamma=1.5)
        with pytest.raises(ValueError):
            PPOConfig(gamma=-0.1)


class TestTrainingConfig:
    """Tests for TrainingConfig."""

    def test_nested_configs(self):
        """Test that nested configs are created correctly."""
        train = TrainingConfig()
        assert isinstance(train.ppo, PPOConfig)
        assert isinstance(train.policy, PolicyConfig)
        assert isinstance(train.env, EnvironmentConfig)

    def test_nested_override(self):
        """Test overriding nested config values."""
        train = TrainingConfig()
        train.override("ppo.learning_rate", 0.001)
        train.override("env.max_steps", 2000)

        assert train.ppo.learning_rate == 0.001
        assert train.env.max_steps == 2000

    def test_serialization(self):
        """Test that config can be serialized to JSON."""
        train = TrainingConfig()
        json_str = train.model_dump_json()

        # Should contain expected fields
        assert "ppo" in json_str
        assert "learning_rate" in json_str
        assert "max_steps" in json_str


class TestPolicyConfig:
    """Tests for PolicyConfig."""

    def test_default_hidden_size(self):
        """Test that default hidden size is 256."""
        policy = PolicyConfig()
        assert policy.hidden_size == 256

    def test_custom_class_path(self):
        """Test setting custom class path."""
        policy = PolicyConfig(class_path="my.custom.Policy")
        assert policy.class_path == "my.custom.Policy"


class TestExtraFieldsForbidden:
    """Tests that extra fields are forbidden."""

    def test_environment_config_extra(self):
        """Test that EnvironmentConfig rejects extra fields."""
        with pytest.raises(ValueError, match="Extra inputs are not permitted"):
            EnvironmentConfig(unknown_field=123)

    def test_ppo_config_extra(self):
        """Test that PPOConfig rejects extra fields."""
        with pytest.raises(ValueError, match="Extra inputs are not permitted"):
            PPOConfig(invalid_param=0.5)
