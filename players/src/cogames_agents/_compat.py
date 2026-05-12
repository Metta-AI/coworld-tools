"""Compatibility helpers for historical import paths."""

from __future__ import annotations

import sys
from importlib import import_module
from types import ModuleType


def alias_module(alias: str, target: str) -> ModuleType:
    """Map an old module name to a canonical module object."""
    module = import_module(target)
    sys.modules[alias] = module
    return module
