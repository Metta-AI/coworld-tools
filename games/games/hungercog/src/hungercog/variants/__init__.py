"""Hunger game variants."""

from hungercog.variants.carnivore import CarnivoreVariant
from hungercog.variants.digest import DigestVariant
from hungercog.variants.energy import EnergyVariant
from hungercog.variants.food import FoodVariant
from hungercog.variants.full import FullVariant
from hungercog.variants.herbivore import HerbivoreVariant
from hungercog.variants.kids import KidsVariant
from hungercog.variants.multi_year import MultiYear5Variant, MultiYear10Variant
from hungercog.variants.plants import PlantVariant
from hungercog.variants.seasons import SeasonsVariant
from hungercog.variants.solar import SolarVariant

VARIANTS = [
    DigestVariant(),
    EnergyVariant(),
    FoodVariant(),
    FullVariant(),
    KidsVariant(),
    PlantVariant(),
    HerbivoreVariant(),
    SeasonsVariant(),
    SolarVariant(),
    CarnivoreVariant(),
    MultiYear5Variant(),
    MultiYear10Variant(),
]
