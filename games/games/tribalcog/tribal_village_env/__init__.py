"""Python package exports for Tribal Village."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "TribalVillageEnv": ("tribal_village_env.environment", "TribalVillageEnv"),
    "make_tribal_village_env": (
        "tribal_village_env.environment",
        "make_tribal_village_env",
    ),
    "ensure_nim_binary_current": (
        "tribal_village_env.build",
        "ensure_nim_binary_current",
    ),
    "ensure_nim_library_current": (
        "tribal_village_env.build",
        "ensure_nim_library_current",
    ),
    "Config": ("tribal_village_env.config", "Config"),
    "EnvironmentConfig": ("tribal_village_env.config", "EnvironmentConfig"),
    "RewardConfig": ("tribal_village_env.config", "RewardConfig"),
    "PPOConfig": ("tribal_village_env.config", "PPOConfig"),
    "PolicyConfig": ("tribal_village_env.config", "PolicyConfig"),
    "TrainingConfig": ("tribal_village_env.config", "TrainingConfig"),
    "play": ("tribal_village_env.recipe", "play"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    try:
        module_name, attr_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
