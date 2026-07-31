"""Route-order analysis: exact optimal open tours over a distance matrix.

The "did the policy visit its objectives in a sane ORDER?" kernel: with the
handful of objectives an episode hands one agent, Held-Karp is ~2^n·n² — an
exact answer is cheap, and an approximate baseline would make the comparison
arguable.

Deliberately dependency-free: the solver takes a plain distance matrix, and
:func:`pairwise_costs` builds one from any caller-supplied ``cost_fn``
(``NavPlan.cost`` over a nav mesh, euclidean distance, precomputed tables —
whatever the game's notion of travel cost is). This module never imports a
navigation stack.

Origin: extracted from Ron Dahlgren's (swgy) crewrift route autopsy
(``swgy_tools.route.tour``); the mesh-A* pairwise costing became the
injected ``cost_fn`` seam.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Hashable, Sequence

__all__ = ["TourComparison", "optimal_open_tour", "pairwise_costs", "path_cost"]

Point = Hashable
PairCache = dict[tuple, float]


def pairwise_costs(
    points: Sequence[Point],
    cost_fn: Callable[[Point, Point], float],
    cache: PairCache | None = None,
) -> list[list[float]]:
    """Symmetric cost matrix between every pair of ``points``.

    ``cache`` shares costs *across* calls keyed on the (sorted) point pair —
    a corpus run repeats the same few hundred pairs thousands of times, so
    one shared dict turns an O(tours) costing bill into O(pairs). Cache
    hygiene is the caller's: use one cache per (map, cost model).
    """
    n = len(points)
    d = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            key = None
            cost = None
            if cache is not None:
                try:
                    key = (min(points[i], points[j]), max(points[i], points[j]))  # type: ignore[type-var]
                except TypeError:
                    key = (points[i], points[j])
                cost = cache.get(key)
            if cost is None:
                cost = float(cost_fn(points[i], points[j]))
                if cache is not None and key is not None:
                    cache[key] = cost
            d[i][j] = d[j][i] = cost
    return d


def optimal_open_tour(dist: list[list[float]]) -> tuple[list[int], float]:
    """Held-Karp: the cheapest OPEN path from node 0 through every other node.

    Node 0 is the start; the path may end anywhere (no return leg — the
    thing being scored usually doesn't have to go home either). Returns
    ``(order, total_cost)`` where ``order`` lists the non-start node indices
    in visit order. Exact, not greedy.
    """
    n = len(dist)
    if n <= 1:
        return [], 0.0
    targets = list(range(1, n))
    m = len(targets)
    inf = float("inf")

    # best[mask][j] = cost of starting at 0, visiting `mask`, ending at targets[j]
    best = [[inf] * m for _ in range(1 << m)]
    prev = [[-1] * m for _ in range(1 << m)]
    for j in range(m):
        best[1 << j][j] = dist[0][targets[j]]

    for mask in range(1 << m):
        for j in range(m):
            if not mask & (1 << j) or best[mask][j] == inf:
                continue
            base = best[mask][j]
            for k in range(m):
                if mask & (1 << k):
                    continue
                nxt = mask | (1 << k)
                cost = base + dist[targets[j]][targets[k]]
                if cost < best[nxt][k]:
                    best[nxt][k] = cost
                    prev[nxt][k] = j

    full = (1 << m) - 1
    end = min(range(m), key=lambda j: best[full][j])
    total = best[full][end]

    order: list[int] = []
    mask, j = full, end
    while j >= 0:
        order.append(targets[j])
        pj = prev[mask][j]
        mask ^= 1 << j
        j = pj
    order.reverse()
    return order, total


def path_cost(dist: list[list[float]], order: Sequence[int]) -> float:
    """Cost of walking ``0 -> order[0] -> order[1] -> ...`` on the matrix."""
    total, cur = 0.0, 0
    for nxt in order:
        total += dist[cur][nxt]
        cur = nxt
    return total


@dataclass(frozen=True)
class TourComparison:
    """An actual visit order scored against the optimal order of the same
    stops (both starting from matrix node 0)."""

    visited: tuple[int, ...]  # node indices, in the order actually visited
    optimal: tuple[int, ...]  # the same nodes, in the cheapest order
    actual_cost: float
    optimal_cost: float

    @property
    def excess(self) -> float:
        """Extra cost paid purely to ORDER. Cannot be negative."""
        return self.actual_cost - self.optimal_cost

    @property
    def ratio(self) -> float:
        return self.actual_cost / self.optimal_cost if self.optimal_cost > 0 else float("nan")

    @classmethod
    def score(cls, dist: list[list[float]], visited: Sequence[int]) -> "TourComparison":
        """Compare ``visited`` (indices into ``dist``, excluding start 0)
        against the exact optimal order of those same stops."""
        optimal, optimal_cost = optimal_open_tour(dist)
        return cls(
            visited=tuple(visited),
            optimal=tuple(optimal),
            actual_cost=path_cost(dist, visited),
            optimal_cost=optimal_cost,
        )
