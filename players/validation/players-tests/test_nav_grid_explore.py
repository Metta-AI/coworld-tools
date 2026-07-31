"""Scenario tests for players.player_sdk.nav_grid (explore).

Ported 1:1 from the embedded smoke test of the original ``swgy_explore.py``
(sm-policies SWGY-Nav bundle). The numbered scenario comments and the
``check(label, ...)`` assertion labels are preserved verbatim so failures
map straight back to the origin scenarios.
"""

from __future__ import annotations

from players.player_sdk.nav_grid.core import Coordinate, GridNavState, GridNavView
from players.player_sdk.nav_grid.distance import manhattan as _manhattan
from players.player_sdk.nav_grid.explore import (
    ExploreConfig,
    ExploreState,
    biased_wander,
    frontier_bfs,
    is_stuck,
    note_observed,
    poi_patrol,
    sector_assignment,
    spiral,
)


def check(label: str, cond: bool, detail: str = "") -> None:
    """Assertion helper preserved from the original smoke tests: the label
    pinpoints the failing scenario."""
    assert cond, f"FAIL {label}: {detail}"


def test_explore_smoke_scenarios() -> None:

    def empty_view() -> GridNavView:
        return GridNavView(obs_center=(0, 0))

    # 1. Frontier BFS picks the closest unobserved cell.
    cfg = ExploreConfig(revisit_after_steps=10)
    nav = GridNavState()
    es = ExploreState()
    # Mark a small region as observed.
    for r in range(-1, 2):
        for c in range(-1, 2):
            es.cell_last_seen[(r, c)] = 0
    target = frontier_bfs(es, empty_view(), nav, cfg, step=1)
    check(
        "1 frontier picks unobserved",
        target is not None and _manhattan((0, 0), target) == 2,
        f"got {target}",
    )

    # 2. Frontier returns None when every cell within range is seen.
    # Seed must extend beyond frontier_max_distance, since cells
    # outside cell_last_seen count as unseen.
    cfg = ExploreConfig(revisit_after_steps=100, frontier_max_distance=3)
    nav = GridNavState()
    es = ExploreState()
    for r in range(-10, 11):
        for c in range(-10, 11):
            es.cell_last_seen[(r, c)] = 0
    target = frontier_bfs(es, empty_view(), nav, cfg, step=10)
    check("2 frontier exhausted", target is None, f"got {target}")

    # 3. Frontier respects walls (blocked cells aren't candidates).
    cfg = ExploreConfig(revisit_after_steps=10)
    nav = GridNavState()
    nav.blocked = {(0, 1), (1, 0), (-1, 0)}
    es = ExploreState()
    es.cell_last_seen[(0, 0)] = 0
    target = frontier_bfs(es, empty_view(), nav, cfg, step=1)
    check(
        "3 frontier avoids blocked",
        target is not None and target not in nav.blocked,
        f"got {target} blocked={nav.blocked}",
    )

    # 4. Sector assignment partitions agents by id.
    cfg = ExploreConfig(sector_count=4, revisit_after_steps=10)
    nav = GridNavState()
    es0 = ExploreState()
    es1 = ExploreState()
    sector_assignment(es0, empty_view(), nav, cfg, step=1, agent_id=0)
    sector_assignment(es1, empty_view(), nav, cfg, step=1, agent_id=1)
    check(
        "4 sector assignment differs by id",
        es0.sector_index == 0 and es1.sector_index == 1,
        f"got {es0.sector_index}, {es1.sector_index}",
    )

    # 5. Spiral advances cursor; first target is one of the ring-1 cells.
    cfg = ExploreConfig(spiral_max_radius=3)
    nav = GridNavState()
    es = ExploreState()
    t = spiral(es, empty_view(), nav, cfg, step=1)
    check(
        "5 spiral first target on ring 1",
        t is not None and max(abs(t[0]), abs(t[1])) == 1,
        f"got {t}",
    )

    # 6. Spiral returns distinct cells across calls.
    cfg = ExploreConfig(spiral_max_radius=3)
    nav = GridNavState()
    es = ExploreState()
    seen: set[Coordinate] = set()
    for _ in range(8):
        t = spiral(es, empty_view(), nav, cfg, step=1)
        if t is not None:
            seen.add(t)
    check(
        "6 spiral covers multiple cells",
        len(seen) >= 4,
        f"got {sorted(seen)}",
    )

    # 7. POI patrol picks the oldest stale POI in range.
    cfg = ExploreConfig(poi_stale_threshold=10, poi_max_chase_distance=20)
    nav = GridNavState()
    es = ExploreState()
    pois = [((0, 5), 50), ((0, 10), 30), ((0, 25), 0)]  # last out of range
    target = poi_patrol(es, empty_view(), nav, cfg, step=100, pois=pois)
    # (0, 10) has age 70; (0, 5) has age 50; oldest is (0, 10).
    check(
        "7 poi_patrol picks oldest in range",
        target == (0, 10),
        f"got {target}",
    )

    # 8. POI patrol skips fresh POIs.
    cfg = ExploreConfig(poi_stale_threshold=100)
    nav = GridNavState()
    es = ExploreState()
    pois = [((0, 5), 95), ((0, 10), 99)]
    target = poi_patrol(es, empty_view(), nav, cfg, step=100, pois=pois)
    check("8 poi_patrol skips fresh", target is None, f"got {target}")

    # 9. Biased wander picks a free adjacent cell.
    cfg = ExploreConfig()
    nav = GridNavState()
    es = ExploreState()
    t = biased_wander(es, empty_view(), nav, cfg, step=1)
    check(
        "9 wander returns adjacent",
        t is not None and _manhattan((0, 0), t) == 1,
        f"got {t}",
    )

    # 10. Biased wander honors a strong bias toward east.
    cfg = ExploreConfig(
        wander_bias_vector=(0, 1),
        wander_bias_strength=1.0,
    )
    nav = GridNavState()
    es = ExploreState()
    t = biased_wander(es, empty_view(), nav, cfg, step=1)
    check(
        "10 wander biases east",
        t == (0, 1),
        f"got {t}",
    )

    # 11. Biased wander returns None when all neighbors blocked.
    cfg = ExploreConfig()
    nav = GridNavState()
    nav.blocked = {(-1, 0), (1, 0), (0, -1), (0, 1)}
    es = ExploreState()
    view = empty_view()
    view.blocker_locals = set(nav.blocked)
    t = biased_wander(es, view, nav, cfg, step=1)
    check("11 wander all blocked", t is None, f"got {t}")

    # 12. note_observed bumps last-seen for the visible window.
    cfg = ExploreConfig()
    nav = GridNavState()
    es = ExploreState()
    note_observed(es, empty_view(), nav, step=42)
    check(
        "12 note_observed records center",
        es.cell_last_seen.get((0, 0)) == 42,
        f"got {es.cell_last_seen.get((0, 0))}",
    )
    check(
        "12b note_observed records corner",
        es.cell_last_seen.get((6, 6)) == 42,
        f"got {es.cell_last_seen.get((6, 6))}",
    )

    # 13. is_stuck flips after enough quiet ticks.
    cfg = ExploreConfig(stuck_threshold=3)
    nav = GridNavState()
    es = ExploreState()
    is_stuck(es, nav, cfg, step=0)  # prime
    check("13a not stuck immediately", not is_stuck(es, nav, cfg, step=1))
    check("13b stuck after threshold", is_stuck(es, nav, cfg, step=4))
