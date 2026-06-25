"""Integration hook for CoGames."""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = ["register_cli", "TribalVillagePufferPolicy"]

_EXPORTED_ATTR_MODULES = {
    "register_cli": ("tribal_village_env.cogames.cli", "register_cli"),
    "TribalVillagePufferPolicy": ("tribal_village_env.cogames.policy", "TribalVillagePufferPolicy"),
}


def __getattr__(name: str) -> Any:
    if name not in _EXPORTED_ATTR_MODULES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = _EXPORTED_ATTR_MODULES[name]
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value
