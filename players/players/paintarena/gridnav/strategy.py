"""Paint Arena policy demonstrating the shared player_sdk libraries.

A worked example of composing three opt-in SDK modules on the simplest real
coworld protocol:

- ``player_sdk.nav_grid`` — the cost-shaped A* pathfinder. The opponent is
  classified as a *stranger* through ``GridNavConfig.stranger_tag_ids``, so
  its repulsion field bends our paths away from contested space with zero
  bespoke avoidance code.
- ``player_sdk.worldmodel.targets`` — a sticky target with progress-based
  invalidation, so we don't oscillate between two equally-near tiles.
- ``player_sdk.worldmodel.select`` — filter-relaxation target choice: prefer
  safe unpainted tiles (far half from the opponent), relax to any unpainted
  tile when no safe one is left.

Frame notes: Paint Arena positions are ``[x, y]``; ``nav_grid`` thinks in
``(row, col)`` — converted at this module's boundary. Paint Arena is fully
observable with absolute coordinates, so instead of dead-reckoning we feed
engine-truth positions straight into ``GridNavState.position`` each tick (the
``nav_grid`` README documents this mode). Direction mapping back to the wire:
north/south/east/west -> up/down/right/left.

Import-clean (no I/O, no websockets) so it is unit-testable and reusable by
any transport, mirroring ``players/paintarena/default/strategy.py``.
"""

from __future__ import annotations

from pydantic import BaseModel

from players.player_sdk.nav_grid import (
    GridNavConfig,
    GridNavState,
    manhattan,
    next_move,
    observe,
    record_step,
)
from players.player_sdk.worldmodel.select import select_with_relaxation
from players.player_sdk.worldmodel.targets import (
    TargetConfig,
    TargetState,
    check_arrival,
    clear_target,
    set_target,
    update_target_progress,
)

MOVES = ("up", "down", "left", "right", "stay")

# The one tag this game needs: "an opposing painter stands here".
TAG_OPPONENT = 1

# nav_grid direction names -> Paint Arena wire moves. nav_grid rows grow
# south; Paint Arena y grows down — same orientation, direct mapping.
_WIRE_MOVE = {"north": "up", "south": "down", "west": "left", "east": "right"}

Cell = tuple[int, int]  # (row, col)


class Observation(BaseModel):
    """One game tick as seen by a player slot (extra fields ignored)."""

    width: int
    height: int
    positions: list[list[int]]
    tile_owners: list[int]
    tick: int
    max_ticks: int


class GridNavPolicy:
    """Stateful per-episode policy: call it once per observation."""

    def __init__(self) -> None:
        cfg = GridNavConfig(
            stranger_tag_ids=frozenset({TAG_OPPONENT}),
            # Bend paths away from the opponent: a soft field, not a wall.
            stranger_repulsion=120.0,
            stranger_spacing=3,
        )
        self.nav = GridNavState(config=cfg)
        self.target = TargetState()
        self.target_cfg = TargetConfig()

    def choose_move(self, obs: Observation, slot: int) -> str:
        me = _to_cell(obs.positions[slot])
        opponents = [
            _to_cell(p) for i, p in enumerate(obs.positions) if i != slot
        ]

        # Fully observable game: feed engine truth instead of dead-reckoning.
        self.nav.position = me
        self.nav.visited.add(me)

        # Classify the opponent into the per-tick view (obs coords ARE
        # absolute here, so obs_center = our own absolute cell).
        frozen_tags = {cell: frozenset({TAG_OPPONENT}) for cell in opponents}
        view = observe(self.nav, frozen_tags, obs_center=me)

        goal = self._pick_tile(obs, slot, me, opponents)
        if goal is None:
            return "stay"  # board fully ours

        direction = next_move(self.nav, view, goal, use_tabu=False)
        record_step(self.nav)
        if direction is None:
            # No path within budget (transient, e.g. we stand on the goal
            # while it repaints). Step greedily instead of idling.
            return _greedy_step(me, goal)
        return _WIRE_MOVE.get(direction, "stay")

    def _pick_tile(
        self, obs: Observation, slot: int, me: Cell, opponents: list[Cell]
    ) -> Cell | None:
        unpainted = [
            (y, x)
            for y in range(obs.height)
            for x in range(obs.width)
            if obs.tile_owners[y * obs.width + x] != slot
        ]
        if not unpainted:
            clear_target(self.target)
            return None

        # Sticky target: keep the current commitment while it's valid,
        # making progress, and still unpainted.
        current = self.target.target
        if current is not None:
            still_unpainted = current in set(unpainted)
            arrived = check_arrival(self.target, me, manhattan, threshold=0)
            progressing = update_target_progress(
                self.target, me, obs.tick, manhattan, self.target_cfg
            )
            if arrived or not still_unpainted or not progressing:
                clear_target(self.target)
            else:
                return current

        def dist_to_nearest_opponent(cell: Cell) -> int:
            return min((manhattan(cell, o) for o in opponents), default=99)

        def score(cell: Cell) -> tuple[int, int]:
            # Lower wins: near me first, then deeper into my half.
            return (manhattan(me, cell), -dist_to_nearest_opponent(cell))

        def safe(cell: Cell) -> bool:
            # Prefer tiles at least as close to me as to any opponent.
            return manhattan(me, cell) <= dist_to_nearest_opponent(cell)

        choice = select_with_relaxation(unpainted, score, filters=[safe])
        if choice is not None:
            set_target(self.target, choice, me, obs.tick, manhattan, kind="tile")
        return choice


def _to_cell(xy: list[int]) -> Cell:
    return (xy[1], xy[0])  # [x, y] -> (row, col)


def _greedy_step(me: Cell, goal: Cell) -> str:
    dr, dc = goal[0] - me[0], goal[1] - me[1]
    if abs(dr) >= abs(dc):
        if dr > 0:
            return "down"
        if dr < 0:
            return "up"
    if dc > 0:
        return "right"
    if dc < 0:
        return "left"
    return "stay"
