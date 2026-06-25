"""Shared test helpers for bombercog.

Exposes ``build_sim`` — a thin wrapper around ``BombercogMission.create``,
``with_variants``, and ``make_env`` — so tests read the same as the monorepo
versions that used the ``make_game('bombercog', ...)`` dispatcher.
"""

from __future__ import annotations

from collections.abc import Sequence

from mettagrid.simulator import Simulation

from bombercog.game import BombercogMission

# Side-effect import: registers every variant by name on the framework registry.
import bombercog.variants  # noqa: F401


def build_sim(
    num_agents: int = 2,
    max_steps: int = 500,
    variants: Sequence[str] | None = None,
    seed: int = 42,
) -> Simulation:
    """Build a ``Simulation`` for a ``bombercog`` episode.

    Args:
        num_agents: Number of agents to spawn (overrides the mission's default).
        max_steps: Episode step cap (overrides the mission's default).
        variants: Optional variant names to apply.
        seed: Simulator seed.
    """
    mission = BombercogMission.create(num_agents, max_steps)
    if variants:
        mission = mission.with_variants(list(variants))
    env = mission.make_env()
    # Honour the caller's explicit max_steps even when a variant bumped it.
    env.game.max_steps = max_steps
    return Simulation(env, seed=seed)
