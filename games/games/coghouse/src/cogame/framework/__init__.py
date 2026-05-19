"""Local replica of the cogames framework: mission, variant, and registry
base classes. Keeps ``cogame`` free of a runtime ``cogames``
dependency while preserving the same lifecycle + API surface.
"""

from __future__ import annotations

from cogame.framework.core import (
    CoGameMission,
    CoGameMissionVariant,
    Deps,
)
from cogame.framework.registry import CoGame, get_game, register_game
from cogame.framework.variants import (
    ResolvedDeps,
    VariantRegistry,
    format_variant_catalog,
)

__all__ = [
    "CoGame",
    "CoGameMission",
    "CoGameMissionVariant",
    "Deps",
    "ResolvedDeps",
    "VariantRegistry",
    "format_variant_catalog",
    "get_game",
    "register_game",
]
