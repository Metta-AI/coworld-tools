"""Mechanics / interface variants.

``FullVariant`` is the "interface variant" pattern called out in
``cg.game.variant-tree``: a hidden variant that declares required dependencies
and uses the configure phase to read values off them before applying a final
layer of env mutations. Requesting ``full`` alone pulls in ``hard`` and
``big_map`` automatically through the registry's dependency resolution.

TODO(cogame): add your own mechanics variants (recipe tweaks, role changes,
reward shaping, etc.) and consider adding a curriculum/tree layer once the
default game is stable.
"""

from __future__ import annotations

from cogames.core import CoGameMissionVariant, Deps
from cogames.variants import ResolvedDeps
from mettagrid.config.mettagrid_config import MettaGridConfig
from pydantic import PrivateAttr

from cogame.variants.difficulty import HardVariant
from cogame.variants.layout import BigMapVariant


class FullVariant(CoGameMissionVariant):
    """Interface variant. Applies :class:`HardVariant` + :class:`BigMapVariant`
    and caps ``max_steps`` once more on top. Requesting ``full`` alone pulls
    both dependencies in automatically."""

    name: str = "full"
    description: str = "Interface variant: hard + big_map + a final step cap."

    _configured_with_hard: bool = PrivateAttr(default=False)

    def dependencies(self) -> Deps:
        return Deps(required=[HardVariant, BigMapVariant])

    def configure(self, deps: ResolvedDeps) -> None:
        # Demonstrates cross-configuration: read state off a resolved dependency.
        # In real games, prefer using this hook to share derived values (recipe
        # weights, map parameters) between variants in a dependency-aware way.
        hard = deps.required(HardVariant)
        assert isinstance(hard, HardVariant)
        self._configured_with_hard = True

    def modify_env(self, mission, env: MettaGridConfig) -> None:
        # Runs after hard + big_map have already mutated env (topological order
        # puts required deps before their dependents).
        assert self._configured_with_hard, "FullVariant.configure() was not called"
        env.game.max_steps = max(1, env.game.max_steps // 2)
