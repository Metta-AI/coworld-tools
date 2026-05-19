"""Bombercog variants. Importing this package registers each variant by name."""

from bombercog.variants.chain_reaction import ChainReactionVariant
from bombercog.variants.four_player import FourPlayerVariant
from bombercog.variants.kickable_bombs import KickableBombsVariant
from bombercog.variants.powerups import PowerupsVariant
from bombercog.variants.procedural_map import ProceduralMapVariant

__all__ = [
    "ChainReactionVariant",
    "FourPlayerVariant",
    "KickableBombsVariant",
    "PowerupsVariant",
    "ProceduralMapVariant",
]
