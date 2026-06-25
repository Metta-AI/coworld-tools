"""Full variant: digest, seasons, carnivore, herbivore combined."""

from __future__ import annotations

from mettagrid.cogame.core import CoGameMissionVariant, Deps
from hungercog.variants.carnivore import CarnivoreVariant
from hungercog.variants.digest import DigestVariant
from hungercog.variants.herbivore import HerbivoreVariant
from hungercog.variants.kids import KidsVariant
from hungercog.variants.multi_year import MultiYear5Variant


class FullVariant(CoGameMissionVariant):
    """All core mechanics: digest, seasons, carnivore, herbivore."""

    name: str = "full"
    description: str = "Digest, seasons, carnivore, herbivore."

    def dependencies(self) -> Deps:
        return Deps(required=[DigestVariant, MultiYear5Variant, CarnivoreVariant, HerbivoreVariant, KidsVariant])
