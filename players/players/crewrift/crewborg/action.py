"""Action layer: resolve symbolic intents into wire payloads (design §9, §12).

All Sprite-v1 transport mechanics and movement control live here.
``resolve_action`` is **stateful across ticks** via ``ActionState``: it diffs the
incoming intent against the stored one, discarding in-progress execution (the nav
route, button state) when the intent changes and continuing it when unchanged.

Movement controller (design §12 default): **bang-bang** d-pad toward the target
with a **release-near-target deadband** and a **predictive stop** — release an
axis when the remaining distance is within the estimated momentum stopping
distance, so the agent coasts to rest on the target instead of overshooting.

Composite intents sequence navigate-then-interact over one "move toward a world
point" routine that follows the baked nav route (design §9):

- ``navigate_to`` → follow the route to the point.
- ``complete_task`` → navigate to the task rect, then hold A with no d-pad
  (movement suppressed — any d-pad input resets the 72-tick task progress).
"""

from __future__ import annotations

from players.crewrift.crewborg.nav import plan_route
from players.crewrift.crewborg.types import ActionState, Belief, Command, Intent

INPUT_HEADER = 0x84
MASK_BITS = 0x7F

# Button bit assignments (AGENTS.md §2 / design §3.3).
BTN_UP = 0x01
BTN_DOWN = 0x02
BTN_LEFT = 0x04
BTN_RIGHT = 0x08
BTN_A = 0x20
BTN_B = 0x40

# Movement-controller tuning (design §12). Distances are world pixels.
ARRIVE_RADIUS = 4  # within this of an axis target ⇒ that axis has arrived
WAYPOINT_RADIUS = 8  # within this of a route waypoint ⇒ advance to the next
# Momentum stopping distance ≈ v·fr/(1-fr) with fr = 144/256; ≈ 1.29·v. Release
# the axis a bit before that so friction brings us to rest on the target.
STOP_FACTOR = 1.3


def encode_input(held_mask: int) -> bytes:
    """Encode a held-button bitmask into a Sprite-v1 input packet."""

    return bytes([INPUT_HEADER, held_mask & MASK_BITS])


def _axis_input(delta: int, velocity: int) -> int:
    """Return -1/0/+1 d-pad input for one axis (bang-bang + predictive stop)."""

    if abs(delta) <= ARRIVE_RADIUS:
        return 0
    # If already coasting toward the target and within stopping distance, release
    # so momentum carries us the rest of the way without overshooting.
    if velocity != 0 and (velocity > 0) == (delta > 0) and abs(delta) <= STOP_FACTOR * abs(velocity):
        return 0
    return 1 if delta > 0 else -1


def _movement_mask(self_xy: tuple[int, int], target_xy: tuple[int, int], velocity: tuple[int, int]) -> int:
    """Held d-pad mask to drive from ``self_xy`` toward ``target_xy``."""

    ix = _axis_input(target_xy[0] - self_xy[0], velocity[0])
    iy = _axis_input(target_xy[1] - self_xy[1], velocity[1])
    mask = 0
    if ix < 0:
        mask |= BTN_LEFT
    elif ix > 0:
        mask |= BTN_RIGHT
    if iy < 0:
        mask |= BTN_UP
    elif iy > 0:
        mask |= BTN_DOWN
    return mask


def _dist2(a: tuple[int, int], b: tuple[int, int]) -> int:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def _self_xy(belief: Belief) -> tuple[int, int] | None:
    if belief.self_world_x is None or belief.self_world_y is None:
        return None
    return belief.self_world_x, belief.self_world_y


def _velocity(action_state: ActionState, self_xy: tuple[int, int]) -> tuple[int, int]:
    if action_state.last_self_x is None or action_state.last_self_y is None:
        return 0, 0
    return self_xy[0] - action_state.last_self_x, self_xy[1] - action_state.last_self_y


def _reset_execution(action_state: ActionState, intent: Intent) -> None:
    action_state.current_intent = intent
    action_state.route = []
    action_state.route_cursor = 0
    action_state.route_goal = None


def _navigate_mask(
    belief: Belief, action_state: ActionState, self_xy: tuple[int, int], goal: tuple[int, int]
) -> int:
    """Follow (replanning if needed) the nav route toward ``goal``; return d-pad mask."""

    velocity = _velocity(action_state, self_xy)

    # (Re)plan when we have no route or the goal changed.
    if not action_state.route or action_state.route_goal != goal:
        action_state.route_goal = goal
        action_state.route_cursor = 0
        route: list[tuple[int, int]] = []
        if belief.nav is not None:
            route = list(plan_route(belief.nav, self_xy, goal))
        # No graph or no path: steer straight at the goal.
        action_state.route = route if route else [goal]

    # Advance past any waypoints we have already reached.
    while (
        action_state.route_cursor < len(action_state.route) - 1
        and _dist2(self_xy, action_state.route[action_state.route_cursor]) <= WAYPOINT_RADIUS**2
    ):
        action_state.route_cursor += 1

    waypoint = action_state.route[min(action_state.route_cursor, len(action_state.route) - 1)]
    return _movement_mask(self_xy, waypoint, velocity)


def resolve_action(intent: Intent, belief: Belief, action_state: ActionState) -> Command:
    """Execute an intent into this tick's wire command (design §9)."""

    # Diff against the stored intent; a change discards in-progress execution.
    if intent != action_state.current_intent:
        _reset_execution(action_state, intent)

    self_xy = _self_xy(belief)
    command = _resolve(intent, belief, action_state, self_xy)

    # Record self position for next tick's velocity estimate, and the held mask.
    if self_xy is not None:
        action_state.last_self_x, action_state.last_self_y = self_xy
    action_state.held_mask = command.held_mask
    return command


def _resolve(
    intent: Intent, belief: Belief, action_state: ActionState, self_xy: tuple[int, int] | None
) -> Command:
    if intent.kind in ("idle", "loiter"):
        return Command(held_mask=0)

    # World-relative intents need our position; hold still until the camera is up.
    if self_xy is None:
        return Command(held_mask=0)

    if intent.kind == "navigate_to":
        if intent.point is None:
            return Command(held_mask=0)
        return Command(held_mask=_navigate_mask(belief, action_state, self_xy, intent.point))

    if intent.kind == "complete_task":
        return _resolve_complete_task(intent, belief, action_state, self_xy)

    # Other intent kinds (report/vote/chat/kill/vent) are wired in P3/P4.
    return Command(held_mask=0)


def _resolve_complete_task(
    intent: Intent, belief: Belief, action_state: ActionState, self_xy: tuple[int, int]
) -> Command:
    if intent.task_index is None or belief.map is None or intent.task_index >= len(belief.map.tasks):
        return Command(held_mask=0)
    task = belief.map.tasks[intent.task_index]
    inside = task.x <= self_xy[0] < task.x + task.w and task.y <= self_xy[1] < task.y + task.h
    if inside:
        # On the station: hold A with no d-pad (any d-pad resets task progress);
        # residual momentum settles via friction while progress accrues.
        return Command(held_mask=BTN_A)
    # Otherwise drive onto the station's center.
    center = (task.center.x, task.center.y)
    return Command(held_mask=_navigate_mask(belief, action_state, self_xy, center))
