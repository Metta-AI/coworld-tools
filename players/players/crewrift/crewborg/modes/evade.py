"""Evade mode: leave the scene right after a kill (imposter Flee; design §7.2).

Evade is brief (``EVADE_TICKS``) and **local**: it picks a reachable point just far
enough to leave the body's immediate vicinity (≈ ``EVADE_RADIUS`` px) and emits
``escape`` toward it, then the selector drops back into Pretend. Crucially it does
*not* flee to the globally furthest point — doing so stranded the imposter at a map
edge, away from the crew, where Pretend froze and it never hunted again. Staying
local keeps it near the action so it can re-blend and kill again once the cooldown
clears. The action layer routes via ``plan_route_via_vents``, but for such a short
hop A* won't take a far vent teleport (it isn't cheaper to a nearby goal), so the
move stays local. Before the nav graph exists it steers directly away from the body.
"""

from __future__ import annotations

import math

from players.crewrift.crewborg.types import ActionState, Belief, Intent
from players.player_sdk import EmptyModeParams, Mode, ModeParams

Point = tuple[int, int]

# How far to move off the body — far enough to leave its immediate vicinity, near
# enough to stay among the crew so Pretend/Hunt can re-engage (world px).
EVADE_RADIUS = 128


class EvadeMode(Mode[Belief, ActionState, Intent]):
    name = "evade"
    params_type = EmptyModeParams

    def __init__(self, params: ModeParams | None = None) -> None:
        super().__init__(params)
        # The far getaway point, fixed for the duration of this evade so we keep
        # committing to one escape instead of re-choosing every tick.
        self._goal: Point | None = None

    def decide(self, belief: Belief, action_state: ActionState) -> Intent:
        del action_state
        self_xy = _self_xy(belief)
        if self_xy is None:
            return Intent(kind="idle", reason="no self position")

        threat = _threat_point(belief, self_xy)

        if belief.nav is None:
            # No graph yet: steer straight away from the body (reflect it through us).
            away = (2 * self_xy[0] - threat[0], 2 * self_xy[1] - threat[1])
            if away == self_xy:
                return Intent(kind="idle", reason="nothing to evade")
            return Intent(kind="escape", point=away, reason="moving away from the body")

        if self._goal is None:
            self._goal = _local_escape_point(belief, threat)
        if self._goal is None:
            return Intent(kind="idle", reason="nowhere to flee")
        return Intent(kind="escape", point=self._goal, reason="leaving the body's vicinity")


def _threat_point(belief: Belief, self_xy: Point) -> Point:
    """The point to flee from: the freshest body, or where we stand if none is known."""

    if belief.bodies:
        body = max(belief.bodies.values(), key=lambda b: b.first_seen_tick)
        return body.world_x, body.world_y
    return self_xy


def _local_escape_point(belief: Belief, threat: Point) -> Point | None:
    """The reachable nav node whose distance from ``threat`` is closest to ``EVADE_RADIUS``.

    A point on that ring leaves the body's immediate vicinity without sprinting to a
    far corner — so the imposter stays near the crew and can re-engage after the flee.
    """

    nav = belief.nav
    if nav is None or not nav.node_point:
        return None
    return min(nav.node_point.values(), key=lambda p: abs(math.dist(p, threat) - EVADE_RADIUS))


def _self_xy(belief: Belief) -> Point | None:
    if belief.self_world_x is None or belief.self_world_y is None:
        return None
    return belief.self_world_x, belief.self_world_y
