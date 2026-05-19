"""cogame-euchre: a 4-player trick-taking card game on MettaGrid.

Importing this package loads :mod:`cogame_euchre.game` as a side effect,
which calls :func:`cogame_euchre.framework.register_game` so the game is
discoverable by name via :func:`cogame_euchre.framework.get_game`.
"""

from __future__ import annotations

import cogame_euchre.game as _game  # noqa: F401  (side effect: register_game)
from cogame_euchre.game import EuchreCoGame, EuchreMission
from cogame_euchre.variants import (
    ALL_VARIANT_TYPES,
    HIDDEN_VARIANT_TYPES,
    PUBLIC_VARIANT_TYPES,
    parse_variants,
    resolve_variant_selection,
)

__all__ = [
    "ALL_VARIANT_TYPES",
    "EuchreCoGame",
    "EuchreMission",
    "HIDDEN_VARIANT_TYPES",
    "PUBLIC_VARIANT_TYPES",
    "parse_variants",
    "resolve_variant_selection",
]
