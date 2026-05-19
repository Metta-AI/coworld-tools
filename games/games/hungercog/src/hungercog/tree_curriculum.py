from __future__ import annotations

from pydantic import Field

from hungercog.variants import VARIANTS
from metta.rl.curriculum.tree_curriculum import (
    TreeTaskGenerator,
)

_NON_MECHANIC_VARIANTS = {"full", "multi_year_5", "multi_year_10"}
HUNGER_MECHANICS = tuple(variant.name for variant in VARIANTS if variant.name not in _NON_MECHANIC_VARIANTS)


class HungerTreeTaskGenerator(TreeTaskGenerator):
    class Config(TreeTaskGenerator.Config):
        game: str = "hungercog"
        mechanics: list[str] = Field(default_factory=lambda: list(HUNGER_MECHANICS))
        max_steps: int = Field(default=250, ge=1)
        # Keep interface fixed to full hunger mechanics by default.
        interface_variants: list[str] | None = Field(default_factory=lambda: list(HUNGER_MECHANICS))
