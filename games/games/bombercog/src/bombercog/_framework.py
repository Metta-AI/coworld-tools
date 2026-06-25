"""Minimal Mission / Variant framework for the standalone bombercog package.

This is a behaviour-preserving port of the tiny slice of ``cogames.core`` that
bombercog actually uses: a pydantic-backed mission base class with a
``with_variants`` / ``make_env`` flow, plus an auto-registered variant base
class with a ``modify_env`` hook. Keeping it inline lets the package install
cleanly from PyPI without the cogames -> mettagrid pin clash.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, ClassVar

from pydantic import Field, PrivateAttr
from typing_extensions import Self

from mettagrid.base_config import Config
from mettagrid.config.mettagrid_config import MettaGridConfig
from mettagrid.map_builder.map_builder import AnyMapBuilderConfig


class CoGameMissionVariant(Config):
    """Base class for mission variants.

    Subclasses set a class-level ``name`` (and optional ``description``) and
    override ``modify_env`` to mutate the env config after ``make_base_env``.
    Subclasses are auto-registered by ``name`` via ``__init_subclass__``.
    """

    name: str
    description: str = Field(default="")

    _registry: ClassVar[dict[str, type["CoGameMissionVariant"]]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        name_val = cls.__dict__.get("name")
        if isinstance(name_val, str) and name_val:
            CoGameMissionVariant._registry[name_val] = cls

    def modify_env(self, mission: "CoGameMission", env: MettaGridConfig) -> None:
        """Hook: mutate ``env`` after the base env is built. Default: no-op."""


class CoGameMission(Config):
    """Base class for bombercog mission configurations."""

    name: str
    description: str = ""
    map_builder: AnyMapBuilderConfig
    num_cogs: int | None = None
    min_cogs: int = Field(default=1, ge=1)
    max_cogs: int = Field(default=1000, ge=1)
    default_variant: str | None = None
    max_steps: int = Field(default=10000)

    _variants: dict[str, CoGameMissionVariant] = PrivateAttr(default_factory=dict)

    def with_variants(self, variants: Sequence[str | CoGameMissionVariant]) -> Self:
        copy = self.model_copy(deep=True)
        for v in variants:
            if isinstance(v, CoGameMissionVariant):
                copy._variants[v.name] = v.model_copy(deep=True)
                continue
            variant_cls = CoGameMissionVariant._registry.get(v)
            if variant_cls is None:
                raise ValueError(
                    f"Unknown variant '{v}'. Known: {sorted(CoGameMissionVariant._registry)}"
                )
            copy._variants[v] = variant_cls()
        return copy

    def make_base_env(self) -> MettaGridConfig:
        raise NotImplementedError

    def make_env(self) -> MettaGridConfig:
        env = self.make_base_env()
        for variant in self._variants.values():
            variant.modify_env(self, env)
        env.label = self.name
        for variant_name in self._variants:
            env.label = f"{env.label}.{variant_name}"
        return env
