"""deadlock.py — Generic convergence-resource deadlock recovery.

Origin: extracted from Ron Dahlgren's (swgy) agent libraries
(sm-policies scripted stack; original module name ``swgy_deadlock.py``).

Pattern: when several agents converge on a central resource (hub, depot,
station, lander, beacon, ...) but the resource cannot currently produce
the thing they're waiting for, they pile up and block other agents that
*can* feed the resource — classic deadlock.

This module provides:

* ``update_deadlock_state``: detect "I've been adjacent to ``anchor`` for
  ``wait_max_ticks`` while ``can_progress`` is False" → arm a backoff
  target and a cooldown window.
* ``pick_backoff_cell``: deterministic, asymmetric scatter — back off
  along the sign of (my_pos - anchor) by ``backoff_distance`` cells. Two
  agents on opposite sides of the anchor naturally scatter to opposite
  quadrants without coordination.
* The caller computes ``can_progress`` themselves. The mission-specific
  predicate (e.g. "min hub stock <= threshold") stays out of the
  fundamentals so this module is reusable for any "stalled at central
  resource" pattern.
"""

from __future__ import annotations

from dataclasses import dataclass

Coordinate = tuple[int, int]


@dataclass
class DeadlockConfig:
    wait_max_ticks: int = 25       # ticks adjacent before deadlock fires
    min_anchor_distance: int = 1   # Manhattan gate for "adjacent"
                                   # (env is 4-connected; only Manhattan<=1
                                   # cells can fire a bump on this tick).
    backoff_distance: int = 4      # cells to scatter from anchor
    retry_cooldown: int = 30       # ticks of refusal before retargeting


@dataclass
class DeadlockState:
    at_resource_since_step: int | None = None
    cooldown_until_step: int = 0
    backoff_target: Coordinate | None = None


def update_deadlock_state(
    state: DeadlockState,
    anchor: Coordinate | None,
    can_progress: bool,
    my_pos: Coordinate,
    step: int,
    cfg: DeadlockConfig,
) -> bool:
    """Maintain anchor-adjacency tracking and cooldown.

    Returns True if the anchor is currently OFF-LIMITS (we're inside a
    cooldown window after a deadlock recovery back-off).

    Detection requires BOTH:
    * Manhattan(my_pos, anchor) <= ``min_anchor_distance``  AND
    * we've been adjacent for >= ``wait_max_ticks`` ticks  AND
    * ``can_progress`` is False (caller-supplied — e.g. "no stock to
      craft now", "no slot free", "queue is at capacity").

    On detection, ``backoff_target`` is set via ``pick_backoff_cell``
    and ``cooldown_until_step`` is set to ``step + retry_cooldown``.
    The caller is expected to navigate toward ``state.backoff_target``
    (or simply route around the anchor) until ``step >=
    state.cooldown_until_step``.

    Adjacency tracking resets when the agent steps away from the
    anchor's neighborhood.
    """
    if anchor is None:
        state.at_resource_since_step = None
        return step < state.cooldown_until_step

    # Env is 4-connected; bump-adjacency is Manhattan<=1, not Chebyshev.
    # Diagonals (Cheb=1, Manhattan=2) cannot fire a bump on this tick
    # and shouldn't count as "at the resource" for deadlock purposes.
    manh = abs(my_pos[0] - anchor[0]) + abs(my_pos[1] - anchor[1])
    adjacent = manh <= cfg.min_anchor_distance

    if not adjacent:
        state.at_resource_since_step = None
    else:
        if state.at_resource_since_step is None:
            state.at_resource_since_step = step
        elapsed = step - state.at_resource_since_step
        if elapsed >= cfg.wait_max_ticks and not can_progress:
            backoff = pick_backoff_cell(anchor, my_pos, cfg.backoff_distance)
            if backoff is not None:
                state.backoff_target = backoff
                state.cooldown_until_step = step + cfg.retry_cooldown
                state.at_resource_since_step = None

    return step < state.cooldown_until_step


def pick_backoff_cell(
    anchor: Coordinate,
    my_pos: Coordinate,
    distance: int,
) -> Coordinate | None:
    """Pick a backoff cell ``distance`` cells from ``anchor`` along the
    direction biased by our own position relative to ``anchor``.

    Asymmetric and deterministic: an agent NW of the anchor backs off
    further NW; an agent E of the anchor backs off further E. Multiple
    stalled agents end up scattering naturally without any
    cross-communication.

    Returns None if ``distance <= 0``. If ``my_pos == anchor`` (agent
    is literally on the anchor), pick the SE corner as a deterministic
    default — better than not backing off at all.
    """
    if distance <= 0:
        return None
    dr = my_pos[0] - anchor[0]
    dc = my_pos[1] - anchor[1]
    if dr == 0 and dc == 0:
        return (anchor[0] + distance, anchor[1] + distance)
    sr = (dr > 0) - (dr < 0)
    sc = (dc > 0) - (dc < 0)
    return (anchor[0] + sr * distance, anchor[1] + sc * distance)
