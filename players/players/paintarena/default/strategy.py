"""Pure decision logic for the Paint Arena default policy.

Paint Arena is fully observable and deterministic, so the policy is a pure
function of the current observation — no memory, no model, no randomness. This
module is import-clean (no I/O, no websockets) so it can be unit-tested and
reused by any transport.

Strategy ("defensible coverage"): every tick, walk one step toward the nearest
tile that is not already ours, breaking ties toward the tile that is *farthest*
from the opponent. Because painting is last-writer-wins, tiles deep in our own
half are safe (the opponent cannot cheaply re-flip them) while frontier tiles
are contested. Preferring near-and-safe tiles makes the policy flood-fill its
own Voronoi half first (full board coverage, no wasted oscillation) and only
contest the shared frontier once its safe territory is claimed. This cleanly
beats the bundled sweep painter and never collapses into the degenerate
flip-the-same-tile oscillation that a naive "chase the opponent" rule suffers.
"""

from __future__ import annotations

from pydantic import BaseModel

MOVES = ("up", "down", "left", "right", "stay")


class Observation(BaseModel):
    """One game tick as seen by a player slot (extra fields ignored)."""

    width: int
    height: int
    positions: list[list[int]]
    tile_owners: list[int]
    tick: int
    max_ticks: int


def _step_toward(x: int, y: int, tx: int, ty: int) -> str:
    """Greedy one-step move that reduces Manhattan distance to (tx, ty)."""
    dx = tx - x
    dy = ty - y
    if abs(dx) >= abs(dy):
        if dx > 0:
            return "right"
        if dx < 0:
            return "left"
    if dy > 0:
        return "down"
    if dy < 0:
        return "up"
    if dx > 0:
        return "right"
    if dx < 0:
        return "left"
    return "stay"


def choose_move(obs: Observation, slot: int) -> str:
    """Pick the next move for ``slot``. Always returns a legal move string."""
    width, height = obs.width, obs.height
    owners = obs.tile_owners
    mx, my = obs.positions[slot]
    ox, oy = obs.positions[1 - slot]

    best: tuple[int, int] | None = None
    best_key: tuple[int, int, int] | None = None
    for ty in range(height):
        row = ty * width
        for tx in range(width):
            if owners[row + tx] == slot:
                continue
            dist_me = abs(tx - mx) + abs(ty - my)
            dist_opp = abs(tx - ox) + abs(ty - oy)
            # nearest first; among equals prefer farthest-from-opponent (safest),
            # then a stable index for determinism.
            key = (dist_me, -dist_opp, row + tx)
            if best_key is None or key < best_key:
                best_key, best = key, (tx, ty)

    if best is None:  # we already own the whole board
        return "stay"
    return _step_toward(mx, my, best[0], best[1])
