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
- ``call_meeting`` → navigate to the emergency-button rect, then edge-press A.
"""

from __future__ import annotations

from players.crewrift.richardborg.nav import plan_route, plan_route_via_vents
from players.crewrift.richardborg.perception.entities import VotingState
from players.crewrift.richardborg.types import ActionState, Belief, Command, Intent

INPUT_HEADER = 0x84
CHAT_HEADER = 0x81
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

# Re-root the nav route at the agent's live position at least this often (ticks), so
# the follower never commits to a stale route after drifting off the planned line.
# A* is ~0.2ms (design §12), so frequent replanning is effectively free.
REPLAN_INTERVAL = 8

# Report fires when within ReportRange = 20px (dist² ≤ 400) of a body (sim.nim).
REPORT_RANGE_SQ = 400
# Kill fires within KillRange = 20px (dist² ≤ 400); vent within VentRange = 16px
# (dist² ≤ 256) (sim.nim).
KILL_RANGE_SQ = 400
VENT_RANGE_SQ = 256


def encode_chat(text: str) -> bytes:
    """Encode meeting chat into a Sprite-v1 input-text packet (Voting only).

    ``0x81`` + little-endian ``u16`` length + printable ASCII (non-ASCII dropped).
    """

    payload = text.encode("ascii", errors="ignore")
    return bytes([CHAT_HEADER]) + len(payload).to_bytes(2, "little") + payload


def encode_input(held_mask: int) -> bytes:
    """Encode a held-button bitmask into a Sprite-v1 input packet."""

    return bytes([INPUT_HEADER, held_mask & MASK_BITS])


def _axis_input(delta: int, velocity: int) -> int:
    """Return -1/0/+1 d-pad input for one axis (bang-bang + predictive stop)."""

    if abs(delta) <= ARRIVE_RADIUS:
        return 0
    # If already coasting toward the target and within stopping distance, release
    # so momentum carries us the rest of the way without overshooting.
    if (
        velocity != 0
        and (velocity > 0) == (delta > 0)
        and abs(delta) <= STOP_FACTOR * abs(velocity)
    ):
        return 0
    return 1 if delta > 0 else -1


def _movement_mask(
    self_xy: tuple[int, int], target_xy: tuple[int, int], velocity: tuple[int, int]
) -> int:
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
    preserve_vote_cursor = (
        action_state.current_intent is not None
        and action_state.current_intent.kind == "vote"
        and intent.kind == "vote"
    )
    action_state.current_intent = intent
    action_state.route = []
    action_state.route_cursor = 0
    action_state.route_goal = None
    action_state.route_teleports = {}
    action_state.ticks_since_plan = 0
    action_state.vote_confirmed = False
    action_state.vote_move_attempts = 0
    if not preserve_vote_cursor:
        action_state.vote_cursor_index = None
        action_state.vote_cursor_candidate_count = 0
    action_state.vote_move_hold_ticks = 0
    action_state.vote_move_release_ticks = 0
    action_state.vote_confirm_attempts = 0
    action_state.vote_confirm_any_target = False
    action_state.vote_confirm_hold_ticks = 0
    action_state.vote_confirm_release_ticks = 0
    action_state.chat_sent = False


def _same_execution_intent(left: Intent, right: Intent | None) -> bool:
    if right is None:
        return False
    return (
        left.kind == right.kind
        and left.point == right.point
        and left.target_color == right.target_color
        and left.target_id == right.target_id
        and left.task_index == right.task_index
        and left.text == right.text
    )


def _edge_press(action_state: ActionState, bit: int) -> int:
    """Fire an edge-triggered button once: 0→bit registers; if we held it last
    tick, release first (return 0) so the next tick re-presses (sim.nim freshA)."""

    return 0 if action_state.held_mask & bit else bit


VOTE_CONFIRM_HOLD_TICKS = 3
VOTE_CONFIRM_RELEASE_TICKS = 2
VOTE_CONFIRM_RETRY_PULSES = 2
VOTE_MOVE_HOLD_TICKS = 2
VOTE_MOVE_RELEASE_TICKS = 1


def _navigate_mask(
    belief: Belief,
    action_state: ActionState,
    self_xy: tuple[int, int],
    goal: tuple[int, int],
    *,
    via_vents: bool = False,
) -> int:
    """Follow (replanning if needed) the nav route toward ``goal``; return d-pad mask.

    With ``via_vents`` the route may include vent teleport legs (imposter flee): on
    such a leg the agent walks onto the entry vent's anchor and presses B to vanish
    to the exit, then resumes walking.
    """

    velocity = _velocity(action_state, self_xy)

    # (Re)plan when the goal changes, and also **periodically** (every
    # REPLAN_INTERVAL ticks) re-rooting the route at the agent's live position. A* is
    # ~0.2ms, so this is nearly free, and it keeps the follower from committing to a
    # stale route after it has drifted off the planned line (the residual cause of
    # task-approach wedging — a fresh route from where it actually is routes around
    # the wall it was mashing into).
    action_state.ticks_since_plan += 1
    if (
        action_state.route_goal != goal
        or action_state.ticks_since_plan >= REPLAN_INTERVAL
    ):
        action_state.route_goal = goal
        action_state.route_cursor = 0
        action_state.route_teleports = {}
        action_state.ticks_since_plan = 0
        if belief.nav is None:
            # No nav graph yet: steer straight at the goal.
            action_state.route = [goal]
        elif via_vents:
            route, teleports = plan_route_via_vents(belief.nav, self_xy, goal)
            action_state.route = list(route)
            action_state.route_teleports = dict(teleports)
        else:
            # nav present: an empty route means genuinely unreachable — hold
            # still (a stall the mode can react to) rather than steering at a wall.
            action_state.route = list(plan_route(belief.nav, self_xy, goal))

    if not action_state.route:
        return 0  # unreachable under the nav graph: hold still

    # Advance past any waypoints we have already reached — including a teleport
    # target once the hop has dropped us next to it (so we resume walking onward
    # instead of trying to vent back). A teleport target is unreachable on foot, so
    # before the hop fires we are never within range of it and the cursor halts on
    # it, which is exactly when we press B below.
    while (
        action_state.route_cursor < len(action_state.route) - 1
        and _dist2(self_xy, action_state.route[action_state.route_cursor])
        <= WAYPOINT_RADIUS**2
    ):
        action_state.route_cursor += 1

    cursor = action_state.route_cursor
    if (
        cursor in action_state.route_teleports
        and _dist2(self_xy, action_state.route[cursor]) > WAYPOINT_RADIUS**2
    ):
        return _teleport_mask(belief, action_state, self_xy)

    waypoint = action_state.route[min(cursor, len(action_state.route) - 1)]
    return _movement_mask(self_xy, waypoint, velocity)


def _teleport_mask(
    belief: Belief, action_state: ActionState, self_xy: tuple[int, int]
) -> int:
    """Drive the vent hop at the current cursor: press B in range, else close in.

    The cursor sits on a teleport-target waypoint; the leg before it walked us onto
    the entry vent's anchor. Press B (level-triggered) once we are actually within
    VentRange of that vent's center — otherwise keep steering onto the anchor so the
    press lands. Once the server teleports us next to the exit waypoint, the cursor
    advances and ordinary walking resumes.
    """

    vent_index = action_state.route_teleports[action_state.route_cursor]
    if belief.map is None or not (0 <= vent_index < len(belief.map.vents)):
        return 0
    center = belief.map.vents[vent_index].center
    if _dist2(self_xy, (center.x, center.y)) <= VENT_RANGE_SQ:
        return BTN_B
    entry = action_state.route[action_state.route_cursor - 1]
    return _movement_mask(self_xy, entry, _velocity(action_state, self_xy))


def resolve_action(
    intent: Intent, belief: Belief, action_state: ActionState
) -> Command:
    """Execute an intent into this tick's wire command (design §9)."""

    # Diff against the stored intent; a change discards in-progress execution.
    if not _same_execution_intent(intent, action_state.current_intent):
        _reset_execution(action_state, intent)
    else:
        action_state.current_intent = intent

    self_xy = _self_xy(belief)
    command = _resolve(intent, belief, action_state, self_xy)

    # Record self position for next tick's velocity estimate, and the held mask.
    if self_xy is not None:
        action_state.last_self_x, action_state.last_self_y = self_xy
    action_state.held_mask = command.held_mask
    return command


def _resolve(
    intent: Intent,
    belief: Belief,
    action_state: ActionState,
    self_xy: tuple[int, int] | None,
) -> Command:
    if intent.kind in ("idle", "loiter"):
        return Command(held_mask=0)

    # Meeting intents don't depend on world position.
    if intent.kind == "vote":
        return _resolve_vote(intent, belief, action_state)
    if intent.kind == "chat":
        return _resolve_chat(intent, action_state)

    # World-relative intents need our position; hold still until the camera is up.
    if self_xy is None:
        return Command(held_mask=0)

    if intent.kind == "navigate_to":
        if intent.point is None:
            return Command(held_mask=0)
        return Command(
            held_mask=_navigate_mask(belief, action_state, self_xy, intent.point)
        )

    if intent.kind == "escape":
        if intent.point is None:
            return Command(held_mask=0)
        # Flee toward the point, vanishing through a vent when one lies on the route.
        return Command(
            held_mask=_navigate_mask(
                belief, action_state, self_xy, intent.point, via_vents=True
            )
        )

    if intent.kind == "complete_task":
        return _resolve_complete_task(intent, belief, action_state, self_xy)

    if intent.kind == "report":
        return _resolve_report(intent, belief, action_state, self_xy)

    if intent.kind == "call_meeting":
        return _resolve_call_meeting(belief, action_state, self_xy)

    if intent.kind == "flee_from":
        return _resolve_flee(intent, belief, action_state, self_xy)

    if intent.kind == "kill":
        return _resolve_kill(intent, belief, action_state, self_xy)

    if intent.kind == "vent":
        return _resolve_vent(intent, belief, action_state, self_xy)

    return Command(held_mask=0)


def _resolve_complete_task(
    intent: Intent, belief: Belief, action_state: ActionState, self_xy: tuple[int, int]
) -> Command:
    if (
        intent.task_index is None
        or belief.map is None
        or intent.task_index >= len(belief.map.tasks)
    ):
        return Command(held_mask=0)
    task = belief.map.tasks[intent.task_index]
    inside = (
        task.x <= self_xy[0] < task.x + task.w
        and task.y <= self_xy[1] < task.y + task.h
    )
    if inside:
        # On the station: hold A with no d-pad (any d-pad resets task progress);
        # residual momentum settles via friction while progress accrues.
        return Command(held_mask=BTN_A)
    # Otherwise drive onto the station's baked anchor (a reachable pixel inside the
    # rect), falling back to the geometric center before the nav graph exists.
    anchor = (
        belief.nav.task_anchor(intent.task_index) if belief.nav is not None else None
    )
    goal = anchor if anchor is not None else (task.center.x, task.center.y)
    return Command(held_mask=_navigate_mask(belief, action_state, self_xy, goal))


def _resolve_report(
    intent: Intent, belief: Belief, action_state: ActionState, self_xy: tuple[int, int]
) -> Command:
    body = belief.bodies.get(intent.target_id) if intent.target_id is not None else None
    if body is None:
        return Command(held_mask=0)
    body_xy = (body.world_x, body.world_y)
    if _dist2(self_xy, body_xy) <= REPORT_RANGE_SQ:
        # In range: a fresh A press reports the body (sim.nim tryReport).
        return Command(held_mask=_edge_press(action_state, BTN_A))
    return Command(held_mask=_navigate_mask(belief, action_state, self_xy, body_xy))


def _resolve_call_meeting(
    belief: Belief, action_state: ActionState, self_xy: tuple[int, int]
) -> Command:
    if belief.map is None:
        return Command(held_mask=0)
    button = belief.map.button
    if (
        button.x <= self_xy[0] < button.x + button.w
        and button.y <= self_xy[1] < button.y + button.h
    ):
        # In the button rect: a fresh A press calls the meeting if the server still
        # allows this player to call one.
        press = _edge_press(action_state, BTN_A)
        if press:
            action_state.last_call_meeting_attempt_tick = belief.last_tick
        return Command(held_mask=press)

    anchor = belief.nav.button_anchor if belief.nav is not None else None
    goal = anchor if anchor is not None else (button.center.x, button.center.y)
    return Command(held_mask=_navigate_mask(belief, action_state, self_xy, goal))


def _resolve_vote(intent: Intent, belief: Belief, action_state: ActionState) -> Command:
    """Drive the vote cursor onto the chosen cell and confirm it, exactly once.

    ``intent.target_color`` is the player to eject (design §7.1); ``None`` ⇒ skip.
    A targeted vote whose target can't be resolved (grid not up yet, or the target
    has died) falls back to skip so we still vote and avoid the no-vote penalty
    (design §12). The cursor steps with edge-triggered presses. If perception never
    observes the target after a full cycle, confirm the current selection to avoid a
    no-vote penalty.
    """

    voting = belief.voting
    self_slot = next(
        (
            candidate.slot
            for candidate in voting.candidates
            if candidate.color == voting.self_marker_color
        ),
        None,
    )
    if action_state.vote_confirmed or any(
        dot.voter == self_slot for dot in voting.dots
    ):
        action_state.vote_confirmed = True
        return Command(held_mask=0)

    target_index = _vote_target_index(intent, voting)
    if target_index is None:
        return Command(held_mask=0)
    _initialize_vote_cursor(action_state, voting)
    if action_state.vote_confirm_any_target:
        if _vote_confirm_retry_exhausted(action_state):
            action_state.vote_confirm_attempts = 0
            return _vote_cursor_step(action_state, voting)
        if _vote_move_in_progress(action_state):
            return _continue_vote_cursor_step(action_state)
        return _confirm_vote(action_state)
    if _vote_confirm_retry_exhausted(action_state):
        action_state.vote_confirm_attempts = 0
        action_state.vote_confirm_any_target = True
        return _vote_cursor_step(action_state, voting)
    if action_state.vote_cursor_index == target_index:
        if _vote_move_in_progress(action_state):
            return _continue_vote_cursor_step(action_state)
        return _confirm_vote(action_state)
    return _vote_cursor_step(action_state, voting)


def _vote_target_index(intent: Intent, voting: VotingState) -> int | None:
    candidates = voting.candidates
    if not candidates:
        return None
    if intent.target_color is not None:
        target_slot = next(
            (c.slot for c in candidates if c.color == intent.target_color and c.alive),
            None,
        )
        if target_slot is not None:
            return target_slot
    return len(candidates)


def _initialize_vote_cursor(action_state: ActionState, voting: VotingState) -> None:
    candidate_count = len(voting.candidates)
    if (
        action_state.vote_cursor_index is not None
        and action_state.vote_cursor_candidate_count == candidate_count
    ):
        return
    cursor_index: int | None
    if voting.skip_cursor_present:
        cursor_index = candidate_count
    else:
        # The rendered cursor can be misread as a candidate cell. Crewrift starts
        # voting on the first live candidate, so initialize from the game invariant
        # and then track our own cursor moves.
        cursor_index = next(
            (candidate.slot for candidate in voting.candidates if candidate.alive),
            None,
        )
    action_state.vote_cursor_index = cursor_index
    action_state.vote_cursor_candidate_count = candidate_count


def _next_vote_cursor(cursor_index: int, voting: VotingState) -> int:
    candidate_count = len(voting.candidates)
    total_positions = candidate_count + 1
    alive_slots = {candidate.slot for candidate in voting.candidates if candidate.alive}
    for _ in range(total_positions):
        cursor_index = (cursor_index + 1 + total_positions) % total_positions
        if cursor_index == candidate_count or cursor_index in alive_slots:
            break
    return cursor_index


def _confirm_vote(action_state: ActionState) -> Command:
    if action_state.vote_confirm_hold_ticks > 0:
        action_state.vote_confirm_hold_ticks -= 1
        if action_state.vote_confirm_hold_ticks == 0:
            action_state.vote_confirm_release_ticks = VOTE_CONFIRM_RELEASE_TICKS
        return Command(held_mask=BTN_A)
    if action_state.vote_confirm_release_ticks > 0:
        action_state.vote_confirm_release_ticks -= 1
        return Command(held_mask=0)
    action_state.vote_confirm_attempts += 1
    action_state.vote_confirm_hold_ticks = VOTE_CONFIRM_HOLD_TICKS - 1
    return Command(held_mask=BTN_A)


def _vote_confirm_retry_exhausted(action_state: ActionState) -> bool:
    return (
        action_state.vote_confirm_attempts >= VOTE_CONFIRM_RETRY_PULSES
        and action_state.vote_confirm_hold_ticks == 0
        and action_state.vote_confirm_release_ticks == 0
    )


def _vote_move_in_progress(action_state: ActionState) -> bool:
    return (
        action_state.vote_move_hold_ticks > 0
        or action_state.vote_move_release_ticks > 0
    )


def _continue_vote_cursor_step(action_state: ActionState) -> Command:
    if action_state.vote_move_hold_ticks > 0:
        action_state.vote_move_hold_ticks -= 1
        if action_state.vote_move_hold_ticks == 0:
            action_state.vote_move_release_ticks = VOTE_MOVE_RELEASE_TICKS
        return Command(held_mask=BTN_RIGHT)
    if action_state.vote_move_release_ticks > 0:
        action_state.vote_move_release_ticks -= 1
        return Command(held_mask=0)
    return Command(held_mask=0)


def _vote_cursor_step(action_state: ActionState, voting: VotingState) -> Command:
    if _vote_move_in_progress(action_state):
        return _continue_vote_cursor_step(action_state)
    action_state.vote_move_attempts += 1
    if action_state.vote_cursor_index is not None:
        action_state.vote_cursor_index = _next_vote_cursor(
            action_state.vote_cursor_index, voting
        )
    action_state.vote_move_hold_ticks = VOTE_MOVE_HOLD_TICKS - 1
    return Command(held_mask=BTN_RIGHT)


def _resolve_chat(intent: Intent, action_state: ActionState) -> Command:
    if action_state.chat_sent or not intent.text:
        return Command(held_mask=0)
    action_state.chat_sent = True
    return Command(held_mask=0, chat=intent.text)


def _resolve_flee(
    intent: Intent, belief: Belief, action_state: ActionState, self_xy: tuple[int, int]
) -> Command:
    threat = (
        belief.roster.get(intent.target_color)
        if intent.target_color is not None
        else None
    )
    if threat is None:
        return Command(held_mask=0)
    # Steer directly away from the threat: reflect its position through ours.
    away = (2 * self_xy[0] - threat.world_x, 2 * self_xy[1] - threat.world_y)
    if away == self_xy:  # co-located: no flee direction
        return Command(held_mask=0)
    return Command(
        held_mask=_movement_mask(self_xy, away, _velocity(action_state, self_xy))
    )


def _resolve_kill(
    intent: Intent, belief: Belief, action_state: ActionState, self_xy: tuple[int, int]
) -> Command:
    target = (
        belief.roster.get(intent.target_color)
        if intent.target_color is not None
        else None
    )
    if target is None:
        return Command(held_mask=0)
    target_xy = (target.world_x, target.world_y)
    if _dist2(self_xy, target_xy) <= KILL_RANGE_SQ:
        # In range: a fresh A press kills (sim.nim tryKill). Caveat: if a body is
        # adjacent, the server reports it instead — Hunt avoids that case.
        return Command(held_mask=_edge_press(action_state, BTN_A))
    return Command(held_mask=_navigate_mask(belief, action_state, self_xy, target_xy))


def _resolve_vent(
    intent: Intent, belief: Belief, action_state: ActionState, self_xy: tuple[int, int]
) -> Command:
    index = _select_vent_index(belief, intent.target_id, self_xy)
    if index is None:
        return Command(held_mask=0)
    assert belief.map is not None
    vent = belief.map.vents[index]
    center_xy = (vent.center.x, vent.center.y)
    # Vent fires within VentRange of the vent center (sim.nim tryVent), so the trigger
    # gate stays on the center; navigation aims at the baked anchor (a reachable pixel
    # within range), falling back to the center before the nav graph exists.
    if _dist2(self_xy, center_xy) <= VENT_RANGE_SQ:
        return Command(held_mask=BTN_B)  # B is level-triggered
    anchor = belief.nav.vent_anchor(index) if belief.nav is not None else None
    goal = anchor if anchor is not None else center_xy
    return Command(held_mask=_navigate_mask(belief, action_state, self_xy, goal))


def _select_vent_index(
    belief: Belief, target_id: int | None, self_xy: tuple[int, int]
) -> int | None:
    if belief.map is None or not belief.map.vents:
        return None
    vents = belief.map.vents
    if target_id is not None and 0 <= target_id < len(vents):
        return target_id
    # Default: the nearest vent by center distance.
    return min(
        range(len(vents)),
        key=lambda i: _dist2(self_xy, (vents[i].center.x, vents[i].center.y)),
    )
