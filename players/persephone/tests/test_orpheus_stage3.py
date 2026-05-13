"""Unit tests for Orpheus Stage 3 spatial reasoning."""

from __future__ import annotations

import numpy as np

from orpheus import belief_update
from orpheus.belief_state import BeliefState
from orpheus.occupancy_grid import (
    ROOM_A_FLOOR_COLORS,
    WALL_COLOR,
    CellState,
    OccupancyGrid,
)
from orpheus.pathfinding import a_star
from orpheus.perception.types import (
    FramePerception,
    MinimapDot,
    OverworldPerception,
    Position,
    RoleRevealPerception,
    Room,
    View,
)


def _frame(view: View, **kwargs) -> FramePerception:
    """Build a FramePerception with the supplied populated view payload."""
    return FramePerception(view=view, **kwargs)


def _apply(
    belief_state: BeliefState,
    perception: FramePerception,
    previous_view: View | None = None,
) -> None:
    """Apply perception using the current belief view by default."""
    belief_update.apply(
        belief_state,
        perception,
        belief_state.view if previous_view is None else previous_view,
    )


def _footprint_cells(
    grid: OccupancyGrid,
    position: tuple[int, int],
) -> list[tuple[int, int]]:
    top_left_x = position[0] - 3
    top_left_y = position[1] - 3
    gx, gy = grid.world_to_grid(top_left_x, top_left_y)
    return [
        (cell_x, cell_y)
        for cell_y in range(gy, gy + 4)
        for cell_x in range(gx, gx + 4)
    ]


def test_occupancy_grid_construction_marks_borders() -> None:
    """OccupancyGrid initializes borders as confirmed WALL cells."""
    grid = OccupancyGrid((100, 100), resolution=2)

    assert grid.cells.shape == (50, 50)
    assert grid.viewport_confirmed.shape == (50, 50)
    assert grid.get(0, 0) == CellState.WALL
    assert grid.get(49, 0) == CellState.WALL
    assert grid.get(0, 49) == CellState.WALL
    assert grid.get(49, 49) == CellState.WALL
    assert bool(grid.viewport_confirmed[0, 0]) is True
    assert bool(grid.viewport_confirmed[49, 49]) is True
    assert grid.get(25, 25) == CellState.UNKNOWN
    assert bool(grid.viewport_confirmed[25, 25]) is False


def test_mark_wall_and_mark_free_basics() -> None:
    """Single-cell marking handles state and viewport provenance."""
    grid = OccupancyGrid((40, 40), resolution=2)

    grid.mark_wall(3, 3)
    assert grid.get(3, 3) == CellState.WALL
    assert bool(grid.viewport_confirmed[3, 3]) is False

    grid.mark_free(4, 4, viewport_confirmed=True)
    assert grid.get(4, 4) == CellState.FREE
    assert bool(grid.viewport_confirmed[4, 4]) is True

    grid.mark_wall(4, 4, viewport_confirmed=True)
    assert grid.get(4, 4) == CellState.WALL
    assert bool(grid.viewport_confirmed[4, 4]) is True


def test_provenance_preserves_viewport_confirmed_cells() -> None:
    """Minimap-tier writes cannot overwrite viewport-confirmed terrain."""
    grid = OccupancyGrid((40, 40), resolution=2)

    grid.mark_free(5, 5, viewport_confirmed=True)
    grid.mark_wall(5, 5, viewport_confirmed=False)

    assert grid.get(5, 5) == CellState.FREE
    assert bool(grid.viewport_confirmed[5, 5]) is True


def test_world_to_grid_round_trip() -> None:
    """World and grid coordinates round-trip at resolution 2."""
    grid = OccupancyGrid((100, 100), resolution=2)

    grid_coord = grid.world_to_grid(10, 10)

    assert grid_coord == (5, 5)
    assert grid.grid_to_world(*grid_coord) == (10, 10)


def test_update_from_viewport_marks_wall_pixel() -> None:
    """Viewport scanning maps color-5 wall pixels into world grid cells."""
    grid = OccupancyGrid((100, 100), resolution=2)
    frame = np.zeros((128, 128), dtype=np.uint8)
    frame[49, 40] = WALL_COLOR

    grid.update_from_viewport((50, 50), frame, Room.UNDERWORLD)

    gx, gy = grid.world_to_grid(40, 40)
    assert grid.get(gx, gy) == CellState.WALL
    assert bool(grid.viewport_confirmed[gy, gx]) is True


def test_viewport_wall_mapping_feeds_a_star_detour() -> None:
    """A* avoids walls discovered from viewport pixels."""
    grid = OccupancyGrid((100, 100), resolution=2)
    frame = np.full((128, 128), ROOM_A_FLOOR_COLORS[0], dtype=np.uint8)
    wall_world_x = 40
    gap_world_y = 50

    for world_y in range(10, 90):
        if abs(world_y - gap_world_y) <= 2:
            continue
        frame[world_y + 9, wall_world_x] = WALL_COLOR

    grid.update_from_viewport((50, 50), frame, Room.UNDERWORLD)

    path = a_star(grid, (20, 50), (80, 50), expansion=0)

    assert path is not None
    wall_gx = grid.world_to_grid(wall_world_x, gap_world_y)[0]
    gap_gys = {
        grid.world_to_grid(wall_world_x, y)[1]
        for y in range(gap_world_y - 2, gap_world_y + 3)
    }
    crossed_cells = [grid.world_to_grid(x, y) for x, y in path]
    assert any(gx == wall_gx and gy in gap_gys for gx, gy in crossed_cells)
    assert all(gx != wall_gx or gy in gap_gys for gx, gy in crossed_cells)


def test_update_from_minimap_preserves_viewport_confirmed_free() -> None:
    """Minimap obstacle hints do not overwrite confirmed FREE cells."""
    grid = OccupancyGrid((100, 100), resolution=2)
    gx, gy = grid.world_to_grid(50, 50)
    grid.mark_free(gx, gy, viewport_confirmed=True)
    dot = MinimapDot(
        color=WALL_COLOR,
        minimap_x=10,
        minimap_y=10,
        world_x=50,
        world_y=50,
        is_self=False,
    )

    grid.update_from_minimap([dot], (100, 100))

    assert grid.get(gx, gy) == CellState.FREE
    assert bool(grid.viewport_confirmed[gy, gx]) is True


def test_update_from_movement_marks_player_footprint_free() -> None:
    """Movement confirmation marks the centered 7x7 footprint as FREE."""
    grid = OccupancyGrid((100, 100), resolution=2)

    grid.update_from_movement((50, 50))

    for gx, gy in _footprint_cells(grid, (50, 50)):
        assert grid.get(gx, gy) == CellState.FREE
        assert bool(grid.viewport_confirmed[gy, gx]) is True


def test_a_star_finds_straight_path_on_empty_grid() -> None:
    """A* finds a monotonic path through unknown open space."""
    grid = OccupancyGrid((100, 100), resolution=2)

    path = a_star(grid, (10, 10), (50, 50))

    assert path is not None
    assert path
    xs = [point[0] for point in path]
    ys = [point[1] for point in path]
    assert all(a <= b for a, b in zip(xs, xs[1:]))
    assert all(a <= b for a, b in zip(ys, ys[1:]))
    assert abs(path[-1][0] - 50) <= 2
    assert abs(path[-1][1] - 50) <= 2


def test_a_star_avoids_walls() -> None:
    """A* detours through a gap instead of crossing known walls."""
    grid = OccupancyGrid((100, 100), resolution=2)
    wall_x = 15
    gap_y = 12
    for gy in range(1, grid.grid_h - 1):
        if gy != gap_y:
            grid.mark_wall(wall_x, gy, viewport_confirmed=True)

    path = a_star(grid, (10, 10), (50, 10), expansion=0)

    assert path is not None
    crossed_cells = [grid.world_to_grid(x, y) for x, y in path]
    assert (wall_x, gap_y) in crossed_cells
    assert all(
        gx != wall_x or gy == gap_y
        for gx, gy in crossed_cells
    )


def test_a_star_returns_none_when_goal_unreachable() -> None:
    """A* reports no path when the goal is fully enclosed."""
    grid = OccupancyGrid((100, 100), resolution=2)
    goal_gx, goal_gy = grid.world_to_grid(50, 50)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            grid.mark_wall(
                goal_gx + dx,
                goal_gy + dy,
                viewport_confirmed=True,
            )

    assert a_star(grid, (10, 10), (50, 50), expansion=0) is None


def test_a_star_configuration_space_expansion_blocks_narrow_corridor() -> None:
    """Expansion rejects a corridor that only fits a point-sized agent."""
    grid = OccupancyGrid((80, 80), resolution=2)
    corridor_y = 10
    for gx in range(1, grid.grid_w - 1):
        grid.mark_wall(gx, corridor_y - 1, viewport_confirmed=True)
        grid.mark_wall(gx, corridor_y + 1, viewport_confirmed=True)

    start = (10, corridor_y * grid.resolution)
    goal = (60, corridor_y * grid.resolution)

    assert a_star(grid, start, goal, expansion=0) is not None
    assert a_star(grid, start, goal, expansion=2) is None


def test_a_star_prefers_diagonal_steps() -> None:
    """A* uses diagonal moves instead of cardinal-only routing."""
    grid = OccupancyGrid((100, 100), resolution=2)

    path = a_star(grid, (10, 10), (30, 30), expansion=0)

    assert path is not None
    assert len(path) <= 13


def test_belief_update_initializes_occupancy_grid_on_role_reveal() -> None:
    """RoleReveal creates the room occupancy grid once room_size is known."""
    belief_state = BeliefState()
    role_reveal = RoleRevealPerception(
        role="Hades",
        team="Shades",
        room="Underworld",
        room_size=100,
    )

    _apply(
        belief_state,
        _frame(View.ROLE_REVEAL, role_reveal=role_reveal),
    )

    assert isinstance(belief_state.occupancy_grid, OccupancyGrid)
    assert belief_state.occupancy_grid.cells.shape == (50, 50)


def test_belief_update_grid_updates_fire_on_overworld_position_change() -> None:
    """Overworld position changes confirm the new movement footprint."""
    grid = OccupancyGrid((100, 100), resolution=2)
    belief_state = BeliefState(
        room=Room.UNDERWORLD,
        room_size=(100, 100),
        occupancy_grid=grid,
    )

    _apply(
        belief_state,
        _frame(
            View.PLAYING,
            overworld=OverworldPerception(
                self_position=Position(Room.UNDERWORLD, 20, 20),
                room=Room.UNDERWORLD,
            ),
        ),
        previous_view=View.PLAYING,
    )
    _apply(
        belief_state,
        _frame(
            View.PLAYING,
            overworld=OverworldPerception(
                self_position=Position(Room.UNDERWORLD, 28, 28),
                room=Room.UNDERWORLD,
            ),
        ),
        previous_view=View.PLAYING,
    )

    for gx, gy in _footprint_cells(grid, (28, 28)):
        assert grid.get(gx, gy) == CellState.FREE
        assert bool(grid.viewport_confirmed[gy, gx]) is True


def test_belief_update_integrates_raw_pixels_into_grid() -> None:
    """Belief update forwards raw overworld pixels into viewport mapping."""
    belief_state = BeliefState()
    role_reveal = RoleRevealPerception(
        role="Hades",
        team="Shades",
        room="Underworld",
        room_size=100,
    )
    _apply(
        belief_state,
        _frame(View.ROLE_REVEAL, role_reveal=role_reveal),
    )
    frame = np.zeros((128, 128), dtype=np.uint8)
    frame[49, 40] = WALL_COLOR

    _apply(
        belief_state,
        _frame(
            View.PLAYING,
            overworld=OverworldPerception(
                self_position=Position(Room.UNDERWORLD, 50, 50),
                room=Room.UNDERWORLD,
            ),
            raw_pixels=frame,
        ),
        previous_view=View.PLAYING,
    )

    assert belief_state.occupancy_grid is not None
    gx, gy = belief_state.occupancy_grid.world_to_grid(40, 40)
    assert belief_state.occupancy_grid.get(gx, gy) == CellState.WALL
    assert bool(belief_state.occupancy_grid.viewport_confirmed[gy, gx]) is True
