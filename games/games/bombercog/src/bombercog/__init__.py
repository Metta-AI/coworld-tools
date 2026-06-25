"""bombercog: Bomberman-style multi-agent deathmatch on MettaGrid."""

from bombercog.game import BombercogMission
from bombercog.variants import (
    ChainReactionVariant,
    FourPlayerVariant,
    KickableBombsVariant,
    PowerupsVariant,
    ProceduralMapVariant,
)

__all__ = [
    "BombercogMission",
    "ChainReactionVariant",
    "FourPlayerVariant",
    "KickableBombsVariant",
    "PowerupsVariant",
    "ProceduralMapVariant",
]
