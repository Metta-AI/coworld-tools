"""Procedural map variant for bombercog.

Generates a fresh 2-player map per episode using a deterministic seed.
The layout is a perimeter-walled room with scattered interior pillars
(indestructible walls) and destructible crates, with two agent spawns
placed at a maximally-separated pair of open cells.
"""

from __future__ import annotations

import random
from collections import deque
from typing import Optional

import numpy as np
from bombercog._framework import CoGameMissionVariant
from mettagrid.config.mettagrid_config import MettaGridConfig
from mettagrid.map_builder.map_builder import GameMap, MapBuilder, MapBuilderConfig

# Default generation parameters. Width/height must be >=7 to fit the
# spawn-validation invariants (adjacent-crate check).
WIDTH = 13
HEIGHT = 11
PILLAR_DENSITY = 0.08   # fraction of interior cells that become indestructible walls
CRATE_DENSITY = 0.40    # fraction of remaining open cells that become crates


class ProceduralBombercogMapConfig(MapBuilderConfig["ProceduralBombercogMapBuilder"]):
    width: int = WIDTH
    height: int = HEIGHT
    pillar_density: float = PILLAR_DENSITY
    crate_density: float = CRATE_DENSITY
    seed: Optional[int] = None


class ProceduralBombercogMapBuilder(MapBuilder[ProceduralBombercogMapConfig]):
    WALL = "wall"
    EMPTY = "empty"
    CRATE = "crate"
    AGENT = "agent.agent"

    def __init__(self, config: ProceduralBombercogMapConfig) -> None:
        super().__init__(config)
        self._rng = random.Random(config.seed)

    def build(self) -> GameMap:
        w = self.config.width
        h = self.config.height
        # Use a string dtype wide enough to hold "agent.agent" (11 chars).
        grid = np.full((h, w), self.EMPTY, dtype="U12")

        # Outer walls.
        grid[0, :] = self.WALL
        grid[h - 1, :] = self.WALL
        grid[:, 0] = self.WALL
        grid[:, w - 1] = self.WALL

        # Scatter indestructible interior pillars.
        interior_cells = [(r, c) for r in range(1, h - 1) for c in range(1, w - 1)]
        pillar_count = int(len(interior_cells) * self.config.pillar_density)
        for r, c in self._rng.sample(interior_cells, pillar_count):
            grid[r, c] = self.WALL

        # Two spawns at maximum graph distance (BFS diameter approximation).
        open_cells = [(r, c) for r, c in interior_cells if grid[r, c] == self.EMPTY]
        if len(open_cells) < 2:
            raise ValueError("procedural map has too few open cells for 2 spawns")
        far_end_a = _farthest(grid, self._rng.choice(open_cells))
        far_end_b = _farthest(grid, far_end_a)
        spawn_a, spawn_b = far_end_a, far_end_b

        # Sprinkle crates on remaining open cells.
        remaining = [
            (r, c)
            for r, c in open_cells
            if (r, c) != spawn_a and (r, c) != spawn_b
        ]
        crate_count = int(len(remaining) * self.config.crate_density)
        for r, c in self._rng.sample(remaining, crate_count):
            grid[r, c] = self.CRATE

        # Ensure each spawn has at least one adjacent crate for a meaningful
        # first bomb. If not, convert an adjacent empty cell into a crate.
        for r, c in (spawn_a, spawn_b):
            if not _adjacent_is(grid, r, c, self.CRATE):
                for nr, nc in _neighbors(grid, r, c):
                    if grid[nr, nc] == self.EMPTY:
                        grid[nr, nc] = self.CRATE
                        break

        grid[spawn_a] = self.AGENT
        grid[spawn_b] = self.AGENT

        return GameMap(grid)


def _neighbors(grid: np.ndarray, r: int, c: int) -> list[tuple[int, int]]:
    h, w = grid.shape
    return [(nr, nc) for nr, nc in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1))
            if 0 <= nr < h and 0 <= nc < w]


def _adjacent_is(grid: np.ndarray, r: int, c: int, value: str) -> bool:
    return any(grid[nr, nc] == value for nr, nc in _neighbors(grid, r, c))


def _farthest(grid: np.ndarray, start: tuple[int, int]) -> tuple[int, int]:
    """BFS from ``start`` across EMPTY cells; return the farthest EMPTY cell."""
    visited = {start}
    queue = deque([start])
    last = start
    while queue:
        cur = queue.popleft()
        last = cur
        for nr, nc in _neighbors(grid, cur[0], cur[1]):
            if (nr, nc) in visited:
                continue
            if grid[nr, nc] != ProceduralBombercogMapBuilder.EMPTY:
                continue
            visited.add((nr, nc))
            queue.append((nr, nc))
    return last


class ProceduralMapVariant(CoGameMissionVariant):
    """Replace the fixed ASCII map with a procedurally generated one.

    Each episode gets a fresh layout from the seeded RNG, varying pillar
    positions, crate density, and spawn locations. Useful for training
    diversity.
    """

    name: str = "procedural_map"
    description: str = "Procedurally generated 2-player arena."

    def modify_env(self, mission, env: MettaGridConfig) -> None:
        env.game.map_builder = ProceduralBombercogMapConfig()
