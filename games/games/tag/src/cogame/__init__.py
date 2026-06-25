"""cogame: template for a new MettaGrid game built on the cogames framework.

Importing this package:

1. loads ``cogame.game`` as a side effect, which calls
   :func:`cogames.game.register_game` so the game appears to
   :func:`cogames.game.get_game` after import.

TODO(cogame): rename to match your package name in ``pyproject.toml``, then
rename every ``cogame.*`` import accordingly.
"""

from __future__ import annotations

import cogame.game as _game  # noqa: F401  (side effect: register_game)
from cogame.game import MyCoGame, MyMission  # noqa: E402
from cogame.variants import (  # noqa: E402
    ALL_VARIANT_TYPES,
    HIDDEN_VARIANT_TYPES,
    PUBLIC_VARIANT_TYPES,
    BigMapVariant,
    EasyVariant,
    FullVariant,
    HardVariant,
    parse_variants,
    resolve_variant_selection,
)

__all__ = [
    "ALL_VARIANT_TYPES",
    "BigMapVariant",
    "EasyVariant",
    "FullVariant",
    "HIDDEN_VARIANT_TYPES",
    "HardVariant",
    "MyCoGame",
    "MyMission",
    "PUBLIC_VARIANT_TYPES",
    "parse_variants",
    "resolve_variant_selection",
]
