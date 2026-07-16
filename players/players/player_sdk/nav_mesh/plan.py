"""The result of routing: :class:`NavPlan`.

Origin: extracted from Ron Dahlgren's (swgy) agent libraries
(swgy-crewrift; original module ``swgy_base.nav.plan``).

A leaf value module (imports nothing from ``nav``). ``NavPlan`` is frozen and
holds only tuples/ints/floats, so a policy can compute it **once** and cache it
across many ticks -- following never mutates the plan, only the follower's
cursor advances (see ``follow.NavState``).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NavPlan:
    """An ordered route through the nav-mesh, start node to goal node."""

    nodes: tuple[int, ...]
    """Node ids in travel order; ``nodes[0]`` is the start, ``nodes[-1]`` the goal."""

    waypoints: tuple[tuple[int, int], ...]
    """Map-pixel ``(x, y)`` for each node in ``nodes`` (parallel arrays)."""

    cost: float
    """Total path cost under ``NavParams.diagonal_bias``: summed blended
    edge metrics (Euclidean length at bias 0, Chebyshev travel-time at bias 1)
    plus any teleport surcharge and avoidance penalties. At bias 1 this reads
    as travel time (px of the slower axis, i.e. ~ticks at the engine's
    per-axis terminal speed), so two routes/goals can be ranked by *time to
    reach*."""

    goal: int
    """The goal node id (``== nodes[-1]``)."""

    def __len__(self) -> int:
        return len(self.nodes)

    def __bool__(self) -> bool:
        return len(self.nodes) > 0

    def first(self, n: int) -> tuple[tuple[int, int], ...]:
        """The first ``n`` waypoint coordinates (for a step-limited preview)."""
        return self.waypoints[:n]

    def remaining(self, cursor: int) -> tuple[tuple[int, int], ...]:
        """Waypoint coordinates from ``cursor`` onward."""
        return self.waypoints[cursor:]
