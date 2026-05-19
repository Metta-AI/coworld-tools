"""Self-documenting configuration with Pydantic validation.

This module provides typed, validated configuration classes for the Tribal Village
environment. Based on the mettascope pattern with type hints, field descriptors,
validation constraints, auto-generated help/docs, and deterministic serialization.

Usage:
    # Create environment config
    env_config = EnvironmentConfig(max_steps=5000, render_mode="ansi")

    # Override nested values using dot notation
    env_config.override("rewards.heart", 1.5)

    # Convert to dict for compatibility
    config_dict = env_config.model_dump()

    # Serialize for reproducibility
    config_json = env_config.model_dump_json()
"""

from __future__ import annotations

import math
import types
from typing import Any, ClassVar, NoReturn, Self, Union, get_args, get_origin

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator


def reward_legacy_field_name(field_name: str) -> str:
    return field_name if field_name.endswith("_penalty") else f"{field_name}_reward"


class Config(BaseModel):
    """Base configuration class with override support and validation.

    This class extends Pydantic's BaseModel to provide:
    - Strict field validation (extra="forbid")
    - Dot-notation path overrides (config.override("nested.field", value))
    - Batch updates (config.update({"a.b": 1, "c.d": 2}))
    - Auto-initialization of None Config fields
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    def override(self, key: str, value: Any) -> Self:
        """Override a value in the config using dot-notation path.

        Examples:
            config.override("max_steps", 1000)
            config.override("rewards.heart", 1.5)
            config.override("ppo.learning_rate", 0.0001)
        """
        key_path = key.split(".")

        def fail(error: str) -> NoReturn:
            raise ValueError(
                f"Override failed. Full config:\n{self.model_dump_json(indent=2)}\n"
                f"Override {key} failed: {error}"
            )

        inner_cfg: Config | dict[str, Any] = self
        traversed_path: list[str] = []
        i = 0

        while i < len(key_path) - 1:
            key_part = key_path[i]

            if isinstance(inner_cfg, dict):
                if key_part in inner_cfg:
                    inner_cfg = inner_cfg[key_part]
                    traversed_path.append(key_part)
                    i += 1
                    continue

                remaining_path = ".".join(key_path[i:])
                if remaining_path in inner_cfg or i == len(key_path) - 2:
                    inner_cfg[remaining_path] = value
                    return self

                fail(f"key {key} not found in dict at path {'.'.join(traversed_path)}")

            if not hasattr(inner_cfg, key_part):
                failed_path = ".".join(traversed_path + [key_part])
                fail(f"key {failed_path} not found")

            next_inner_cfg = getattr(inner_cfg, key_part)
            if next_inner_cfg is None:
                field = type(inner_cfg).model_fields.get(key_part)
                if field is not None:
                    field_type = field.annotation
                    if get_origin(field_type) is Union or isinstance(field_type, types.UnionType):
                        non_none_types = [
                            arg for arg in get_args(field_type) if arg is not type(None)
                        ]
                        if len(non_none_types) == 1:
                            field_type = non_none_types[0]
                    if isinstance(field_type, type) and issubclass(field_type, Config):
                        try:
                            next_inner_cfg = field_type()
                            setattr(inner_cfg, key_part, next_inner_cfg)
                        except (TypeError, ValueError):
                            next_inner_cfg = None
                if next_inner_cfg is None:
                    failed_path = ".".join(traversed_path + [key_part])
                    fail(f"Cannot auto-initialize None field {failed_path}")

            if not isinstance(next_inner_cfg, (Config, dict)):
                failed_path = ".".join(traversed_path + [key_part])
                fail(f"key {failed_path} is not a Config object")

            inner_cfg = next_inner_cfg
            traversed_path.append(key_part)
            i += 1

        if isinstance(inner_cfg, Config) and not hasattr(inner_cfg, key_path[-1]):
            fail(f"key {key} not found")

        if isinstance(inner_cfg, dict):
            final_key = key_path[-1]
            remaining = ".".join(key_path[i:])
            target_key = remaining if final_key not in inner_cfg and remaining in inner_cfg else final_key
            inner_cfg[target_key] = value
            return self

        cls = type(inner_cfg)
        field = cls.model_fields.get(key_path[-1])
        if field is None:
            fail(f"key {key} is not a valid field")

        value = TypeAdapter(field.annotation).validate_python(value)
        setattr(inner_cfg, key_path[-1], value)

        return self

    def update(self, updates: dict[str, Any]) -> Self:
        """Apply multiple overrides to the config."""
        for key, value in updates.items():
            self.override(key, value)
        return self


class RewardConfig(Config):
    """Configuration for reward parameters.

    Rewards are applied when the corresponding events occur in the game.
    Penalties are negative rewards applied on certain conditions.
    Use math.nan for rewards that should be inherited from defaults.
    """

    heart: float = Field(
        default=math.nan,
        description="Reward for collecting a heart (healing item)",
    )
    ore: float = Field(
        default=math.nan,
        description="Reward for collecting ore resource",
    )
    bar: float = Field(
        default=math.nan,
        description="Reward for creating a metal bar from ore",
    )
    wood: float = Field(
        default=math.nan,
        description="Reward for collecting wood resource",
    )
    water: float = Field(
        default=math.nan,
        description="Reward for collecting water resource",
    )
    wheat: float = Field(
        default=math.nan,
        description="Reward for harvesting wheat",
    )
    spear: float = Field(
        default=math.nan,
        description="Reward for crafting a spear weapon",
    )
    armor: float = Field(
        default=math.nan,
        description="Reward for crafting armor",
    )
    food: float = Field(
        default=math.nan,
        description="Reward for producing food",
    )
    cloth: float = Field(
        default=math.nan,
        description="Reward for producing cloth",
    )
    tumor_kill: float = Field(
        default=math.nan,
        description="Reward for killing a tumor enemy",
    )
    survival_penalty: float = Field(
        default=math.nan,
        description="Penalty applied each step for agent survival",
    )
    death_penalty: float = Field(
        default=math.nan,
        description="Penalty applied when an agent dies",
    )

class EnvironmentConfig(Config):
    """Configuration for the Tribal Village environment.

    This configuration controls the simulation parameters, rendering,
    and reward structure for the environment.
    """

    # Core simulation parameters
    max_steps: int = Field(
        default=10_000,
        ge=1,
        description="Maximum number of simulation steps per episode",
    )
    victory_condition: int = Field(
        default=0,
        ge=0,
        description="Victory condition type (0=survival, others TBD)",
    )
    tumor_spawn_rate: float = Field(
        default=math.nan,
        description="Rate at which tumor enemies spawn (per step probability)",
    )

    # AI control mode
    ai_mode: str = Field(
        default="external",
        description="AI mode: 'external' (Python controls), 'builtin' (scripted AI), 'hybrid' (scripted + Python override)",
    )

    # Rendering parameters
    render_mode: str = Field(
        default="rgb_array",
        description="Render mode: 'rgb_array', 'ansi', or 'human'",
    )
    render_scale: int = Field(
        default=4,
        ge=1,
        description="Scale factor for rendered output",
    )
    ansi_buffer_size: int = Field(
        default=1_000_000,
        ge=1000,
        description="Buffer size for ANSI rendering output",
    )

    # Reward configuration
    rewards: RewardConfig = Field(
        default_factory=RewardConfig,
        description="Reward parameters for various game events",
    )

    @field_validator("ai_mode")
    @classmethod
    def validate_ai_mode(cls, v: str) -> str:
        valid_modes = {"external", "builtin", "hybrid"}
        if v not in valid_modes:
            raise ValueError(f"ai_mode must be one of {valid_modes}, got '{v}'")
        return v

    @field_validator("render_mode")
    @classmethod
    def validate_render_mode(cls, v: str) -> str:
        valid_modes = {"rgb_array", "ansi", "human"}
        if v not in valid_modes:
            raise ValueError(f"render_mode must be one of {valid_modes}, got '{v}'")
        return v

    def to_legacy_dict(self) -> dict[str, Any]:
        """Convert to legacy dictionary format for backward compatibility."""
        result: dict[str, Any] = {
            "max_steps": self.max_steps,
            "victory_condition": self.victory_condition,
            "ai_mode": self.ai_mode,
            "render_mode": self.render_mode,
            "render_scale": self.render_scale,
        }

        if not math.isnan(self.tumor_spawn_rate):
            result["tumor_spawn_rate"] = self.tumor_spawn_rate

        for field_name in RewardConfig.model_fields:
            value = getattr(self.rewards, field_name)
            if not math.isnan(value):
                result[reward_legacy_field_name(field_name)] = value

        return result

    @classmethod
    def from_legacy_dict(cls, config: dict[str, Any]) -> EnvironmentConfig:
        """Create config from legacy dictionary format."""
        reward_kwargs = {
            field_name: config.get(reward_legacy_field_name(field_name), math.nan)
            for field_name in RewardConfig.model_fields
        }
        rewards = RewardConfig(**reward_kwargs)

        return cls(
            max_steps=config.get("max_steps", 10_000),
            victory_condition=config.get("victory_condition", 0),
            tumor_spawn_rate=config.get("tumor_spawn_rate", math.nan),
            ai_mode=config.get("ai_mode", "external"),
            render_mode=config.get("render_mode", "rgb_array"),
            render_scale=config.get("render_scale", 4),
            ansi_buffer_size=config.get("ansi_buffer_size", 1_000_000),
            rewards=rewards,
        )


class PPOConfig(Config):
    """Configuration for PPO (Proximal Policy Optimization) hyperparameters.

    These parameters control the PPO training algorithm behavior.
    """

    learning_rate: float = Field(
        default=0.0005,
        gt=0,
        description="Learning rate for the optimizer",
    )
    bptt_horizon: int = Field(
        default=64,
        ge=1,
        description="Backpropagation through time horizon for RNN training",
    )
    adam_eps: float = Field(
        default=1e-8,
        gt=0,
        description="Epsilon for Adam optimizer numerical stability",
    )
    adam_beta1: float = Field(
        default=0.95,
        ge=0,
        le=1,
        description="Adam optimizer beta1 (momentum)",
    )
    adam_beta2: float = Field(
        default=0.999,
        ge=0,
        le=1,
        description="Adam optimizer beta2 (RMSprop)",
    )
    gamma: float = Field(
        default=0.995,
        ge=0,
        le=1,
        description="Discount factor for future rewards",
    )
    gae_lambda: float = Field(
        default=0.90,
        ge=0,
        le=1,
        description="Lambda for Generalized Advantage Estimation",
    )
    update_epochs: int = Field(
        default=1,
        ge=1,
        description="Number of epochs per PPO update",
    )
    clip_coef: float = Field(
        default=0.2,
        ge=0,
        description="PPO clipping coefficient",
    )
    vf_coef: float = Field(
        default=2.0,
        ge=0,
        description="Value function loss coefficient",
    )
    vf_clip_coef: float = Field(
        default=0.2,
        ge=0,
        description="Value function clipping coefficient",
    )
    max_grad_norm: float = Field(
        default=1.5,
        gt=0,
        description="Maximum gradient norm for clipping",
    )
    ent_coef: float = Field(
        default=0.01,
        ge=0,
        description="Entropy coefficient for exploration",
    )
    max_minibatch_size: int = Field(
        default=32768,
        ge=1,
        description="Maximum minibatch size",
    )
    vtrace_rho_clip: float = Field(
        default=1.0,
        ge=0,
        description="V-trace rho clipping coefficient",
    )
    vtrace_c_clip: float = Field(
        default=1.0,
        ge=0,
        description="V-trace c clipping coefficient",
    )
    prio_alpha: float = Field(
        default=0.8,
        ge=0,
        le=1,
        description="Priority exponent for prioritized replay",
    )
    prio_beta0: float = Field(
        default=0.2,
        ge=0,
        le=1,
        description="Initial importance sampling exponent",
    )


class PolicyConfig(Config):
    """Configuration for policy network architecture."""

    hidden_size: int = Field(
        default=256,
        ge=1,
        description="Hidden layer size for policy network",
    )
    class_path: str | None = Field(
        default=None,
        description="Full class path for custom policy implementation",
    )


class TrainingConfig(Config):
    """Configuration for training loop parameters.

    This configuration controls the training process including
    environment count, batch sizes, and checkpoint intervals.
    """

    # Environment parameters
    max_steps: int = Field(
        default=1_000,
        ge=1,
        description="Maximum training steps per episode",
    )
    num_envs: int = Field(
        default=64,
        ge=1,
        description="Number of parallel environments",
    )
    checkpoint_interval: int = Field(
        default=200,
        ge=1,
        description="Steps between checkpoints",
    )

    # Batch parameters
    batch_size: int | None = Field(
        default=None,
        ge=1,
        description="Batch size for training (None = auto)",
    )
    minibatch_size: int | None = Field(
        default=None,
        ge=1,
        description="Minibatch size for PPO updates (None = auto)",
    )

    # Vector env parameters
    vector_num_envs: int | None = Field(
        default=None,
        ge=1,
        description="Number of vectorized environments (None = auto)",
    )
    vector_num_workers: int | None = Field(
        default=None,
        ge=1,
        description="Number of worker processes (None = auto based on CPU cores)",
    )
    vector_batch_size: int | None = Field(
        default=None,
        ge=1,
        description="Batch size for vectorized env (None = num_envs)",
    )

    # Nested configurations
    ppo: PPOConfig = Field(
        default_factory=PPOConfig,
        description="PPO hyperparameters",
    )
    policy: PolicyConfig = Field(
        default_factory=PolicyConfig,
        description="Policy network configuration",
    )
    env: EnvironmentConfig = Field(
        default_factory=EnvironmentConfig,
        description="Environment configuration",
    )


# Observation space constants
OBS_MIN_VALUE: int = 0
OBS_MAX_VALUE: int = 255
OBS_NORMALIZATION_FACTOR: float = 1.0 / OBS_MAX_VALUE

# CLI defaults
DEFAULT_ANSI_STEPS: int = 128
DEFAULT_PROFILE_STEPS: int = 512

# Environment defaults (from EnvironmentConfig field defaults)
DEFAULT_MAX_STEPS: int = EnvironmentConfig.model_fields["max_steps"].default
DEFAULT_RENDER_SCALE: int = EnvironmentConfig.model_fields["render_scale"].default
DEFAULT_ANSI_BUFFER_SIZE: int = EnvironmentConfig.model_fields["ansi_buffer_size"].default

# Training defaults (from TrainingConfig field defaults)
DEFAULT_TRAIN_MAX_STEPS: int = TrainingConfig.model_fields["max_steps"].default
DEFAULT_NUM_ENVS: int = TrainingConfig.model_fields["num_envs"].default
DEFAULT_CHECKPOINT_INTERVAL: int = TrainingConfig.model_fields["checkpoint_interval"].default

# PPO hyperparameters (from PPOConfig field defaults)
DEFAULT_LEARNING_RATE: float = PPOConfig.model_fields["learning_rate"].default
DEFAULT_BPTT_HORIZON: int = PPOConfig.model_fields["bptt_horizon"].default
DEFAULT_ADAM_EPS: float = PPOConfig.model_fields["adam_eps"].default
DEFAULT_GAMMA: float = PPOConfig.model_fields["gamma"].default
DEFAULT_GAE_LAMBDA: float = PPOConfig.model_fields["gae_lambda"].default
DEFAULT_UPDATE_EPOCHS: int = PPOConfig.model_fields["update_epochs"].default
DEFAULT_CLIP_COEF: float = PPOConfig.model_fields["clip_coef"].default
DEFAULT_VF_COEF: float = PPOConfig.model_fields["vf_coef"].default
DEFAULT_VF_CLIP_COEF: float = PPOConfig.model_fields["vf_clip_coef"].default
DEFAULT_MAX_GRAD_NORM: float = PPOConfig.model_fields["max_grad_norm"].default
DEFAULT_ENT_COEF: float = PPOConfig.model_fields["ent_coef"].default
DEFAULT_ADAM_BETA1: float = PPOConfig.model_fields["adam_beta1"].default
DEFAULT_ADAM_BETA2: float = PPOConfig.model_fields["adam_beta2"].default
DEFAULT_MAX_MINIBATCH_SIZE: int = PPOConfig.model_fields["max_minibatch_size"].default
DEFAULT_VTRACE_RHO_CLIP: float = PPOConfig.model_fields["vtrace_rho_clip"].default
DEFAULT_VTRACE_C_CLIP: float = PPOConfig.model_fields["vtrace_c_clip"].default
DEFAULT_PRIO_ALPHA: float = PPOConfig.model_fields["prio_alpha"].default
DEFAULT_PRIO_BETA0: float = PPOConfig.model_fields["prio_beta0"].default

# Policy defaults (from PolicyConfig field defaults)
DEFAULT_HIDDEN_SIZE: int = PolicyConfig.model_fields["hidden_size"].default


__all__ = [
    "Config",
    "RewardConfig",
    "EnvironmentConfig",
    "PPOConfig",
    "PolicyConfig",
    "TrainingConfig",
    "OBS_MIN_VALUE",
    "OBS_MAX_VALUE",
    "OBS_NORMALIZATION_FACTOR",
    "DEFAULT_ANSI_STEPS",
    "DEFAULT_PROFILE_STEPS",
    "DEFAULT_MAX_STEPS",
    "DEFAULT_RENDER_SCALE",
    "DEFAULT_ANSI_BUFFER_SIZE",
    "DEFAULT_TRAIN_MAX_STEPS",
    "DEFAULT_NUM_ENVS",
    "DEFAULT_CHECKPOINT_INTERVAL",
    "DEFAULT_LEARNING_RATE",
    "DEFAULT_BPTT_HORIZON",
    "DEFAULT_ADAM_EPS",
    "DEFAULT_GAMMA",
    "DEFAULT_GAE_LAMBDA",
    "DEFAULT_UPDATE_EPOCHS",
    "DEFAULT_CLIP_COEF",
    "DEFAULT_VF_COEF",
    "DEFAULT_VF_CLIP_COEF",
    "DEFAULT_MAX_GRAD_NORM",
    "DEFAULT_ENT_COEF",
    "DEFAULT_ADAM_BETA1",
    "DEFAULT_ADAM_BETA2",
    "DEFAULT_MAX_MINIBATCH_SIZE",
    "DEFAULT_VTRACE_RHO_CLIP",
    "DEFAULT_VTRACE_C_CLIP",
    "DEFAULT_PRIO_ALPHA",
    "DEFAULT_PRIO_BETA0",
    "DEFAULT_HIDDEN_SIZE",
]
