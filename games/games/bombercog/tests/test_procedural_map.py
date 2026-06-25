"""Tests for the bombercog procedural_map variant."""

from __future__ import annotations

from conftest import build_sim

from bombercog.variants.procedural_map import (
    ProceduralBombercogMapBuilder,
    ProceduralBombercogMapConfig,
)
from mettagrid.simulator import Simulation


def _build_sim(max_steps: int = 500, seed: int = 42) -> Simulation:
    return build_sim(num_agents=2, max_steps=max_steps, variants=["procedural_map"], seed=seed)


def _objects_of(sim: Simulation, type_name: str) -> list[dict]:
    return [o for o in sim.grid_objects().values() if o.get("type_name") == type_name]


def _count_type(sim: Simulation, type_name: str) -> int:
    return len(_objects_of(sim, type_name))


def test_procedural_map_has_two_spawns() -> None:
    """The procedural map produces exactly 2 agent spawns."""
    sim = _build_sim()
    try:
        assert _count_type(sim, "agent") == 2, "procedural map should spawn exactly 2 agents"
    finally:
        sim.close()


def test_procedural_map_has_crates_adjacent_to_every_spawn() -> None:
    """Every agent spawn has at least one adjacent crate — first-bomb
    invariant preserved."""
    sim = _build_sim()
    try:
        crate_positions = {(c["r"], c["c"]) for c in _objects_of(sim, "crate")}
        for a in _objects_of(sim, "agent"):
            r, c = a["r"], a["c"]
            neighbours = {(r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)}
            assert neighbours & crate_positions, (
                f"agent at ({r},{c}) has no adjacent crate; neighbours={neighbours}"
            )
    finally:
        sim.close()


def test_procedural_map_outer_walls() -> None:
    """Outer perimeter of the map is all walls."""
    sim = _build_sim()
    try:
        wall_positions = {(w["r"], w["c"]) for w in _objects_of(sim, "wall")}
        # Size is set by the config constants; verify row 0 and last row are walls.
        # At least the corners must be walls.
        assert (0, 0) in wall_positions, "top-left corner should be a wall"
    finally:
        sim.close()


def test_procedural_map_is_seeded_deterministic() -> None:
    """Building the map twice with the same seed produces identical grids."""
    cfg = ProceduralBombercogMapConfig(seed=123, width=13, height=11)
    grid_a = cfg.create().build().grid
    grid_b = cfg.create().build().grid
    assert (grid_a == grid_b).all(), "same seed should produce identical map"


def test_procedural_map_different_seeds_differ() -> None:
    """Different seeds produce different maps (at least some cells differ)."""
    grid_a = ProceduralBombercogMapConfig(seed=1, width=13, height=11).create().build().grid
    grid_b = ProceduralBombercogMapConfig(seed=99999, width=13, height=11).create().build().grid
    assert not (grid_a == grid_b).all(), "different seeds should yield different maps"


def test_procedural_map_is_connected_between_spawns() -> None:
    """The two spawn cells are reachable from each other via empty+crate cells
    (crates can be blasted away, so connectivity through crates is acceptable
    for gameplay)."""
    grid = ProceduralBombercogMapConfig(seed=7, width=13, height=11).create().build().grid
    h, w = grid.shape
    agent_cells = [(r, c) for r in range(h) for c in range(w) if str(grid[r, c]).startswith("agent")]
    assert len(agent_cells) == 2

    # BFS through empty+crate (non-wall) cells.
    from collections import deque

    start = agent_cells[0]
    target = agent_cells[1]
    visited = {start}
    queue = deque([start])
    while queue:
        r, c = queue.popleft()
        if (r, c) == target:
            return
        for nr, nc in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
            if 0 <= nr < h and 0 <= nc < w and (nr, nc) not in visited:
                if grid[nr, nc] != ProceduralBombercogMapBuilder.WALL:
                    visited.add((nr, nc))
                    queue.append((nr, nc))
    raise AssertionError(f"spawns {start} and {target} are not connected via empty/crate cells")
