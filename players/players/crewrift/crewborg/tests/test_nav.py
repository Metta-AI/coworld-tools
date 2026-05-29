"""Nav graph + A* route planning + destination anchors (design §6, §9)."""

from __future__ import annotations

import numpy as np

from players.crewrift.crewborg.map.types import MapData, MapPoint, MapRect, TaskStation, Vent
from players.crewrift.crewborg.nav import (
    _segment_clear,
    build_nav_graph,
    plan_route,
)


def test_partially_blocked_cell_is_still_a_node() -> None:
    # With 1x1 point collision, one blocked pixel must NOT discard the whole cell
    # (the old conservative rule did exactly that). The cell stays routable.
    mask = np.ones((16, 16), dtype=bool)
    mask[0, 0] = False
    graph = build_nav_graph(mask, cell_size=8)
    assert (0, 0) in graph.node_point  # cell survives despite the blocked pixel


def test_fully_blocked_cell_is_not_a_node() -> None:
    mask = np.ones((16, 16), dtype=bool)
    mask[0:8, 0:8] = False  # top-left cell has no walkable pixel
    graph = build_nav_graph(mask, cell_size=8)
    assert (0, 0) not in graph.node_point
    assert (1, 1) in graph.node_point


def test_route_goes_around_a_wall() -> None:
    mask = np.ones((24, 80), dtype=bool)
    mask[8:, 32:40] = False  # vertical wall on the lower rows; gap stays open up top
    graph = build_nav_graph(mask, cell_size=8)

    route = plan_route(graph, (8, 16), (72, 16))
    assert route, "expected a route around the wall"
    assert route[-1] == (72, 16)  # ends exactly on the goal
    assert any(y < 8 for _, y in route)  # detours up through the gap


def test_unreachable_goal_returns_empty() -> None:
    mask = np.ones((24, 48), dtype=bool)
    mask[:, 24:32] = False  # full-height wall splits the map in two
    graph = build_nav_graph(mask, cell_size=8)
    assert plan_route(graph, (8, 12), (40, 12)) == []


def test_clear_shot_collapses_to_a_single_waypoint() -> None:
    mask = np.ones((64, 64), dtype=bool)
    graph = build_nav_graph(mask, cell_size=8)
    assert plan_route(graph, (4, 4), (60, 60)) == [(60, 60)]


def test_smoothed_route_segments_never_cross_a_wall() -> None:
    mask = np.ones((24, 80), dtype=bool)
    mask[8:, 32:40] = False
    graph = build_nav_graph(mask, cell_size=8)

    start = (8, 16)
    route = plan_route(graph, start, (72, 16))
    assert route and route[-1] == (72, 16)
    # Every leg up to (but excluding) the final exact-goal hop is occlusion-free.
    legs = [start] + route
    for a, b in zip(legs[:-2], legs[1:-1]):
        assert _segment_clear(graph.walkability, a, b), f"leg {a}->{b} crosses the wall"


def test_line_of_sight_blocks_a_diagonal_corner_squeeze() -> None:
    mask = np.ones((16, 16), dtype=bool)
    mask[0:8, 8:16] = False  # top-right pixels blocked
    mask[8:16, 0:8] = False  # bottom-left pixels blocked
    graph = build_nav_graph(mask, cell_size=8)
    # (4,4) -> (12,12) grazes the shared corner of the two blocked quadrants.
    assert not _segment_clear(graph.walkability, (4, 4), (12, 12))


# --------------------------------------------------------------------------- #
# Destination anchors                                                         #
# --------------------------------------------------------------------------- #


def _map(tasks=(), vents=(), button=MapRect(x=0, y=0, w=4, h=4), home=MapPoint(x=4, y=4)) -> MapData:
    return MapData(width=48, height=24, tasks=tuple(tasks), vents=tuple(vents), rooms=(), button=button, home=home)


def test_task_anchor_is_a_reachable_walkable_pixel_in_the_rect() -> None:
    # A task rect that straddles a wall: its geometric center sits in the wall, but
    # the anchor must be a walkable, reachable pixel inside the rect.
    mask = np.ones((24, 48), dtype=bool)
    mask[:, 10:14] = False  # wall band through the task rect's center column
    task = TaskStation(name="edge", x=8, y=8, w=8, h=8)  # center (12, 12) — in the wall
    graph = build_nav_graph(mask, map_data=_map(tasks=[task]))

    anchor = graph.task_anchor(0)
    assert anchor is not None
    ax, ay = anchor
    assert 8 <= ax < 16 and 8 <= ay < 16  # inside the rect
    assert mask[ay, ax]  # on a walkable pixel
    assert not (10 <= ax < 14)  # not in the wall band


def test_unreachable_task_has_no_anchor_and_is_reported() -> None:
    mask = np.ones((24, 48), dtype=bool)
    mask[:, 24:32] = False  # wall splits the map; home is on the left
    task = TaskStation(name="far", x=40, y=10, w=4, h=4)  # right of the wall
    graph = build_nav_graph(mask, map_data=_map(tasks=[task], home=MapPoint(x=4, y=12)))

    assert graph.task_anchor(0) is None
    assert any("task[0]" in w for w in graph.unreachable)


def test_vent_anchor_lands_within_reach_of_the_vent_center() -> None:
    mask = np.ones((24, 48), dtype=bool)
    vent = Vent(x=18, y=8, w=8, h=8, group="1", group_index=1)  # center (22, 12)
    graph = build_nav_graph(mask, map_data=_map(vents=[vent]))

    anchor = graph.vent_anchor(0)
    assert anchor is not None
    (ax, ay), (cx, cy) = anchor, (22, 12)
    assert (ax - cx) ** 2 + (ay - cy) ** 2 <= 16**2  # within VentRange of the center
