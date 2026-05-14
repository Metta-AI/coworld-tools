"""Shared helpers for policy modules.

The Nim bot splits these across ``tasks.nim`` / ``motion.nim`` /
``path.nim`` / ``policy.nim``. We collapse them here because both
the crewmate and imposter policies want the same primitives —
movement intent, A\\* navigation wiring, anti-stuck nudge,
task-tier selection, body-priority ordering.

Key entry points:

- :class:`Policy` — abstract base; each role policy implements
  ``decide()``.
- :func:`best_actionable_task` — the four-tier task selection
  with hysteresis. See its docstring for the full ordering and
  the assignment-evidence semantics added by Phases 1-3 of
  ``CREWMATE_TASK_FIX_PLAN.md``.
- :func:`navigate_to_world_goal` — A\\* over the walk mask
  (`path.py`) when localized; greedy world-delta fallback
  otherwise.
- :func:`anti_stuck_nudge`, :func:`set_world_goal`,
  :func:`world_pos_from_screen` — utilities the policies share.

``decide()`` is the one-method contract. Policies should mutate state
(``Bot.goal``, ``Bot.motion``, ``Bot.tasks.hold_ticks``, etc.) freely and
call ``bot.fired(branch_id)`` exactly once before returning.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from .. import actions
from .. import path as path_mod
from ..geometry import player_world_x, player_world_y
from ..state import Bot, Phase, PlayerSighting, TaskInfo
from ..tuning import (
    ARRIVAL_DEADBAND,
    CENTER_X,
    CENTER_Y,
    CLOSE_DISTANCE,
    JIGGLE_TICKS,
    PATH_REPLAN_INTERVAL,
    PATH_REPLAN_MOVE_THRESHOLD,
    STUCK_TICKS,
    TASK_COMMIT_TICKS,
    TELEPORT_VELOCITY_THRESHOLD,
)

if TYPE_CHECKING:  # pragma: no cover
    from ..data import GameMap


class Policy(ABC):
    """Base class for the three per-phase policies.

    All three policies take a ``game_map`` second argument so they
    can read task world positions, run the A* pathfinder against
    the walk mask, and pass the :class:`~modulabot.data.GameMap`
    on to navigation helpers. The legacy state-obs test harness
    passes ``None`` here; navigation gracefully degrades to
    screen-space greedy steering when ``game_map`` is missing.
    """

    @abstractmethod
    def decide(self, bot: Bot, game_map: "GameMap | None" = None) -> int:
        """Return a BitWorld action index for this frame."""


# ---------------------------------------------------------------------------
# Helpers available to all policies
# ---------------------------------------------------------------------------


def manhattan_from_center(x: int, y: int) -> int:
    return abs(x - CENTER_X) + abs(y - CENTER_Y)


def self_position(bot: Bot) -> tuple[int, int]:
    """Our screen-space position.

    In state-obs mode the state observation advertises our self pin; until
    that's parsed we fall back to screen centre (which is true in first-person
    cameras anyway, but the state-obs path populates ``players`` with a ``self``
    flag so the real value ends up there).
    """
    for player in bot.percep.players:
        if player.is_self:
            return player.x, player.y
    return CENTER_X, CENTER_Y


def world_self_position(bot: Bot) -> tuple[int, int]:
    """Our world-space position, or ``(-1, -1)`` when unknown.

    Prefers the camera-derived world position (``player_world_x/y``)
    when the localizer has a lock; in state-obs mode the observation
    doesn't carry a world camera so we return ``(-1, -1)`` and the
    motion tracker falls back to its state-obs self sighting via
    :func:`self_position`.

    Having real world coordinates here is what unblocks the
    anti-stuck jiggle in pixel mode — the pixel adapter paints
    ``players`` with a self sighting at screen centre every frame,
    so :func:`self_position` reports constant ``(CENTER_X, CENTER_Y)``
    and the motion tracker never observes motion. World coords move
    as the camera follows us, so velocity reflects actual travel.
    """
    if bot.percep.localized:
        return player_world_x(bot.percep), player_world_y(bot.percep)
    return -1, -1


def move_toward(x: int, y: int, deadband: int = ARRIVAL_DEADBAND) -> int:
    """Action that moves us toward a screen-space target.

    Returns :data:`~modulabot.actions.NOOP` when already within
    ``deadband``. The default deadband is :data:`ARRIVAL_DEADBAND`
    (looser than :data:`CLOSE_DISTANCE`) to absorb the per-frame
    momentum the BitWorld sim applies — a bot with no momentum model
    and a tight deadband orbits the target; a looser one converges.
    Policies that need pixel-precise arrival (e.g. the "press A when
    standing on the task rect" check) still use :data:`CLOSE_DISTANCE`
    explicitly at the interaction site.
    """
    dx = x - CENTER_X
    dy = y - CENTER_Y
    return actions.direction_to(dx, dy, deadband=deadband)


def move_away_from(x: int, y: int, deadband: int = CLOSE_DISTANCE) -> int:
    """Inverse of :func:`move_toward` — for fleeing bodies.

    Keeps the tighter :data:`CLOSE_DISTANCE` deadband so fleebody
    doesn't disengage too early while the imposter is still
    recognisably near the corpse.
    """
    dx = CENTER_X - x
    dy = CENTER_Y - y
    return actions.direction_to(dx, dy, deadband=deadband)


def choose_body(bot: Bot):
    """Return the nearest visible body by Manhattan distance, or None."""
    bodies = bot.percep.bodies
    if not bodies:
        return None
    return min(bodies, key=lambda body: manhattan_from_center(body.x, body.y))


def alive_other_players(bot: Bot) -> list[PlayerSighting]:
    """Every visible player that isn't self and is alive."""
    return [
        p for p in bot.percep.players if not p.is_self and p.alive
    ]


def visible_non_teammates(bot: Bot) -> list[PlayerSighting]:
    """Crewmates we haven't confirmed as imposter teammates."""
    return [
        p
        for p in alive_other_players(bot)
        if p.color not in bot.identity.known_imposters
    ]


def lone_non_teammate(bot: Bot) -> PlayerSighting | None:
    """Return the sole visible non-teammate, or None if zero-or-many visible."""
    candidates = visible_non_teammates(bot)
    if len(candidates) == 1:
        return candidates[0]
    return None


def best_actionable_task(bot: Bot) -> TaskInfo | None:
    """Pick the best task to walk toward right now.

    Priority (matches the Nim eight-tier ordering, collapsed where state-obs
    data makes tiers equivalent):

    1. An ``active`` task — we're already on it; press A.
    2. A task with ``icon_visible`` — walk onto it.
    3. A task with ``arrow_visible`` — chase the arrow offscreen.
    4. Otherwise ``None`` — let the policy fall through to patrol.

    Within each tier we take the closest to screen centre. ``active``
    ties prefer ``icon_visible`` over checkout-only (Phase 4.2 of
    CREWMATE_TASK_FIX_PLAN.md).

    **Assignment evidence (Phase 1/2 of the fix plan).** Tier 3 is
    not "every off-screen task on the map"; it's only tasks with a
    matching yellow radar dot at the projected screen-edge position
    (or a previously-latched ``bot.tasks.checkout[i]``). Tier 1 is
    not "any rect intersection"; the pixel adapter further requires
    ``icon_visible or checkout[i]`` before setting ``active=True``.
    These gates are what stop the bot from chasing every task on the
    map indiscriminately.

    **In-flight confirmation gate (Phase 3).** A task with
    ``bot.tasks.confirming_index == idx`` is in the post-hold
    confirmation window; ``_keep`` filters it out so the policy
    doesn't loop back into ``_begin_hold`` while
    ``_check_hold_confirmation`` waits on the server signal.

    **Target hysteresis.** Even with the gates above, perception can
    still flicker (sprite-match miss for one tick, dot momentarily
    absent), so a naive ``min()`` over tiers can flip the chosen
    target frame-to-frame. Each flip invalidates the A\\* path in
    ``set_world_goal``, leaving the crewmate stalled.

    Fix: if we committed to a task on a previous tick and it's still a
    valid unresolved candidate, keep it for at least
    :data:`~modulabot.tuning.TASK_COMMIT_TICKS` ticks before
    reconsidering. Two escape hatches preserve responsiveness:

    - An ``active`` task *other than the committed one* wins
      immediately (we walked onto a free task — don't waste it).
    - A task whose ``icon`` is now visible when the committed target
      is only an arrow wins once the commit window elapses (a closer
      reachable task became visible; finish that first).

    The imposter has an analogous sticky followee via
    :data:`~modulabot.tuning.IMPOSTER_FOLLOW_SWAP_MIN_TICKS`.
    """
    percep = bot.percep
    tasks = bot.tasks

    if not percep.tasks:
        return None

    def _keep(info: TaskInfo) -> bool:
        if info.index < 0:
            return False
        if info.index < len(tasks.resolved) and tasks.resolved[info.index]:
            return False
        # Phase 3: a task with a pending server-side confirmation is
        # "in flight" — we already pressed A for
        # :data:`~modulabot.tuning.TASK_HOLD_TICKS` ticks, released,
        # and are now watching for the server to acknowledge. Don't
        # re-select it; that would clobber ``confirming_via_icon``
        # and restart the timer. ``_check_hold_confirmation`` will
        # either mark it resolved (filtered by the line above) or
        # un-latch it (drops out of tier 3) when it resolves.
        if info.index == tasks.confirming_index:
            return False
        return not (info.index < len(tasks.states) and tasks.states[info.index].value == 3)

    candidates = [info for info in percep.tasks if _keep(info)]
    if not candidates:
        tasks.chosen_index = -1
        tasks.chosen_since_tick = -1
        return None

    def _pick_best(pool: list[TaskInfo]) -> TaskInfo:
        # Actives + icons score on screen position (where the visible
        # sprite sits); arrows score on their clamped edge hint. Callers
        # only pass a non-empty single-tier pool here.
        if pool[0].icon_visible or pool[0].active:
            return min(pool, key=lambda t: manhattan_from_center(t.x, t.y))
        return min(pool, key=lambda t: manhattan_from_center(t.arrow_x, t.arrow_y))

    actives = [info for info in candidates if info.active]
    icons = [info for info in candidates if info.icon_visible]
    arrows = [info for info in candidates if info.arrow_visible]

    # Always take a free active task, even over a committed target
    # — we're standing on it; pressing A costs nothing.
    if actives:
        # Phase 4.2 tiebreak ordering, applied in priority order:
        # (a) the committed task wins so the chosen_since_tick window
        #     doesn't reset gratuitously when we're already going for
        #     it; (b) icon-visible actives outrank checkout-only
        #     actives because the icon is direct server-rendered
        #     evidence of assignment, while checkout is a weaker
        #     "we saw a dot here at some point" inference.
        for info in actives:
            if info.index == tasks.chosen_index:
                return info
        icon_actives = [info for info in actives if info.icon_visible]
        pool = icon_actives if icon_actives else actives
        chosen = _pick_best(pool)
        tasks.chosen_index = chosen.index
        tasks.chosen_since_tick = percep.tick
        return chosen

    # Commit-and-stick path: if we picked a task recently and it's
    # still a valid candidate, keep it until the commit window elapses.
    if tasks.chosen_index >= 0:
        committed = next(
            (info for info in candidates if info.index == tasks.chosen_index),
            None,
        )
        if committed is not None:
            commit_elapsed = percep.tick - tasks.chosen_since_tick
            if commit_elapsed < TASK_COMMIT_TICKS:
                return committed
            # Commit window elapsed. Upgrade from arrow→icon if a
            # visible alternative exists; otherwise stay put so we
            # actually finish what we started.
            if not committed.icon_visible and icons:
                chosen = _pick_best(icons)
                tasks.chosen_index = chosen.index
                tasks.chosen_since_tick = percep.tick
                return chosen
            return committed
        # Committed task vanished from candidates (resolved elsewhere,
        # or map changed) — drop the commit and repick.
        tasks.chosen_index = -1
        tasks.chosen_since_tick = -1

    # Fresh pick: highest tier with content wins, then commit.
    pool = icons if icons else (arrows if arrows else None)
    if pool is None:
        return None
    chosen = _pick_best(pool)
    tasks.chosen_index = chosen.index
    tasks.chosen_since_tick = percep.tick
    return chosen


def update_motion(bot: Bot) -> None:
    """Update velocity / stuck counters from the last-seen self position.

    Uses world coordinates (camera-derived) when the localizer has a
    lock; falls back to screen-space self position otherwise. In pixel
    mode this is the difference between a working anti-stuck jiggle
    and a broken one — the pixel adapter always paints the self
    sighting at screen centre, so screen-space velocity reads as
    ``(0, 0)`` every frame even when the bot is actually moving.
    World coordinates actually shift as the camera follows the bot.

    Teleport guard: when velocity magnitude exceeds
    :data:`~modulabot.tuning.TELEPORT_VELOCITY_THRESHOLD`, the
    measurement is discarded and the counters are left alone. This
    absorbs post-interstitial respawns and localizer re-locks (camera
    can jump by hundreds of pixels between a role-reveal frame and
    the first playing frame).

    Stuck counter only grows during ``Phase.PLAYING``. Voting /
    interstitial frames don't contribute to "am I wedged on a wall?"
    — the sim isn't running player physics during those phases.
    """
    motion = bot.motion

    # Prefer world coords; fall back to screen centre (state-obs mode
    # populates a self sighting there, and the screen centre is a
    # reasonable default when localize has nothing to lock onto).
    world = world_self_position(bot)
    if world != (-1, -1):
        sx, sy = world
        using_world = True
    else:
        sx, sy = self_position(bot)
        using_world = False

    if not motion.prev_self_valid:
        motion.prev_self_x = sx
        motion.prev_self_y = sy
        motion.prev_self_valid = True
        motion.velocity_x = 0
        motion.velocity_y = 0
        return

    vx = sx - motion.prev_self_x
    vy = sy - motion.prev_self_y

    # Teleport guard — a post-interstitial re-spawn or a localizer
    # jump shouldn't confuse the motion tracker. Swallow the sample,
    # reseed prev, leave counters as-is.
    if using_world and (
        abs(vx) > TELEPORT_VELOCITY_THRESHOLD
        or abs(vy) > TELEPORT_VELOCITY_THRESHOLD
    ):
        motion.prev_self_x = sx
        motion.prev_self_y = sy
        motion.velocity_x = 0
        motion.velocity_y = 0
        return

    motion.velocity_x = vx
    motion.velocity_y = vy

    moved = vx != 0 or vy != 0
    if bot.percep.phase == Phase.PLAYING:
        if moved:
            motion.stuck_ticks = 0
        elif bot.goal.has:
            motion.stuck_ticks += 1
    else:
        # Voting / interstitial: don't grow stuck counters while the
        # sim isn't running player physics.
        motion.stuck_ticks = 0

    motion.prev_self_x = sx
    motion.prev_self_y = sy


def anti_stuck_nudge(bot: Bot, intended: int) -> int:
    """If we've been stuck for too long, perpendicular-nudge for N ticks.

    Returns ``intended`` unchanged outside the jiggle window. This is the
    Python equivalent of the Nim ``applyJiggle`` helper, minus the
    pixel-collision complexity (the cogames sim handles that for us).
    """
    motion = bot.motion
    if motion.jiggle_ticks > 0:
        motion.jiggle_ticks -= 1
        return _perpendicular(intended, motion.jiggle_side)
    if motion.stuck_ticks >= STUCK_TICKS:
        motion.jiggle_ticks = JIGGLE_TICKS
        motion.jiggle_side = -motion.jiggle_side
        motion.stuck_ticks = 0
        return _perpendicular(intended, motion.jiggle_side)
    return intended


_PERPENDICULAR_POSITIVE = {
    actions.UP: actions.RIGHT,
    actions.DOWN: actions.LEFT,
    actions.LEFT: actions.UP,
    actions.RIGHT: actions.DOWN,
    actions.UP_A: actions.RIGHT_A,
    actions.DOWN_A: actions.LEFT_A,
    actions.LEFT_A: actions.UP_A,
    actions.RIGHT_A: actions.DOWN_A,
    # Diagonals: clockwise 90° rotation
    actions.UP_LEFT: actions.UP_RIGHT,
    actions.UP_RIGHT: actions.DOWN_RIGHT,
    actions.DOWN_RIGHT: actions.DOWN_LEFT,
    actions.DOWN_LEFT: actions.UP_LEFT,
    actions.UP_LEFT_A: actions.UP_RIGHT_A,
    actions.UP_RIGHT_A: actions.DOWN_RIGHT_A,
    actions.DOWN_RIGHT_A: actions.DOWN_LEFT_A,
    actions.DOWN_LEFT_A: actions.UP_LEFT_A,
}

_PERPENDICULAR_NEGATIVE = {
    actions.UP: actions.LEFT,
    actions.DOWN: actions.RIGHT,
    actions.LEFT: actions.DOWN,
    actions.RIGHT: actions.UP,
    actions.UP_A: actions.LEFT_A,
    actions.DOWN_A: actions.RIGHT_A,
    actions.LEFT_A: actions.DOWN_A,
    actions.RIGHT_A: actions.UP_A,
    # Diagonals: counter-clockwise 90° rotation
    actions.UP_LEFT: actions.DOWN_LEFT,
    actions.UP_RIGHT: actions.UP_LEFT,
    actions.DOWN_RIGHT: actions.UP_RIGHT,
    actions.DOWN_LEFT: actions.DOWN_RIGHT,
    actions.UP_LEFT_A: actions.DOWN_LEFT_A,
    actions.UP_RIGHT_A: actions.UP_LEFT_A,
    actions.DOWN_RIGHT_A: actions.UP_RIGHT_A,
    actions.DOWN_LEFT_A: actions.DOWN_RIGHT_A,
}


def _perpendicular(action: int, side: int) -> int:
    lut = _PERPENDICULAR_POSITIVE if side > 0 else _PERPENDICULAR_NEGATIVE
    return lut.get(action, action)


# ---------------------------------------------------------------------------
# World-space navigation (A* + lookahead waypoint)
# ---------------------------------------------------------------------------


def set_world_goal(
    bot: Bot,
    world_x: int,
    world_y: int,
    *,
    name: str = "",
    index: int = -1,
    screen_x: int | None = None,
    screen_y: int | None = None,
) -> None:
    """Record a world-space navigation target on ``bot.goal``.

    Callers set both the world coords (for :func:`navigate_to_world_goal`
    to pathfind against) and optional screen coords (for the trace /
    debug overlay readout). Changing the target world position
    relative to the cached one invalidates the stored A\\* path so
    the next :func:`navigate_to_world_goal` call re-plans.
    """
    g = bot.goal
    if not g.has_world or g.world_x != world_x or g.world_y != world_y:
        # Goal moved: drop the cached path so we re-plan at the new
        # anchor on the next navigation call.
        g.path = []
        g.has_path_step = False
        g.path_plan_tick = -1
    g.has_world = True
    g.world_x = world_x
    g.world_y = world_y
    g.name = name
    g.index = index
    # Screen coords: default to world coords if not provided so the
    # trace/debug panel has something sensible to display.
    g.has = True
    g.x = screen_x if screen_x is not None else world_x
    g.y = screen_y if screen_y is not None else world_y


def clear_goal(bot: Bot) -> None:
    """Drop the current goal, clearing both screen + world fields and
    the cached path. Callers invoke when the policy falls through to
    patrol / NOOP."""
    g = bot.goal
    g.has = False
    g.has_world = False
    g.has_path_step = False
    g.path = []
    g.path_plan_tick = -1


def _should_replan(bot: Bot) -> bool:
    """True when the cached A* path is stale relative to our position
    or the elapsed ticks cap.

    Re-plan triggers:
    1. No prior plan (first call or post-goal-change invalidation).
    2. Elapsed ticks since last plan >= ``PATH_REPLAN_INTERVAL``.
    3. Player has moved > ``PATH_REPLAN_MOVE_THRESHOLD`` from the plan
       anchor — catches teleports and lets the waypoint re-seat when
       we've covered most of the lookahead distance.
    """
    g = bot.goal
    if g.path_plan_tick < 0 or not g.path:
        return True
    if bot.percep.tick - g.path_plan_tick >= PATH_REPLAN_INTERVAL:
        return True
    swx = player_world_x(bot.percep)
    swy = player_world_y(bot.percep)
    if (
        abs(swx - g.path_plan_self_x) > PATH_REPLAN_MOVE_THRESHOLD
        or abs(swy - g.path_plan_self_y) > PATH_REPLAN_MOVE_THRESHOLD
    ):
        return True
    return False


def navigate_to_world_goal(
    bot: Bot,
    game_map: "GameMap | None",
    *,
    deadband: int = ARRIVAL_DEADBAND,
) -> int:
    """Steer toward ``bot.goal`` (world coords) via A\\* waypoint.

    Contract: ``bot.goal.has_world`` must be True, set via
    :func:`set_world_goal`. If the localizer has no lock or
    ``game_map`` is None, this falls back to screen-space greedy
    steering from the policy's adapter-populated target so callers
    don't have to branch.

    Strategy:

    1. Recompute the A\\* path when :func:`_should_replan` says so
       (goal moved, plan is stale, we drifted far from the anchor).
    2. Advance a lookahead waypoint along the stored path based on
       the bot's *current* position — not just the plan-time anchor.
       This eliminates NOOP gaps where the bot reaches the old
       cached waypoint and idles until the next replan.
    3. Convert the waypoint delta from world -> screen-space and emit
       :func:`~modulabot.actions.direction_to`.
    4. On unreachable (path is empty), fall back to straight-line
       world-delta steering — the wall might open up after a few
       ticks, and the anti-stuck jiggle handles the meantime.

    Returns an action index. Caller is responsible for attaching
    ``bot.fired(...)`` before returning it from :meth:`Policy.decide`.
    """
    g = bot.goal
    percep = bot.percep
    if not g.has_world:
        return actions.NOOP

    # State-obs mode / un-localized pixel mode: no world position to
    # pathfind from. Fall through to greedy screen-space delta.
    if not percep.localized or game_map is None:
        return _greedy_world_delta(bot, g.world_x, g.world_y, deadband)

    if _should_replan(bot):
        new_path = path_mod.find_path(percep, game_map, g.world_x, g.world_y)
        g.path = new_path
        g.path_plan_tick = percep.tick
        g.path_plan_self_x = player_world_x(percep)
        g.path_plan_self_y = player_world_y(percep)
        if not new_path:
            g.has_path_step = False

    # Advance the waypoint along the stored path every tick. This
    # finds the closest point on the path to our current position
    # and looks PATH_LOOKAHEAD steps ahead, so the target stays
    # meaningful as we move rather than going stale between replans.
    if g.path:
        _advance_along_path(bot)

    if g.has_path_step:
        # Waypoint steering uses a tight deadband (the waypoint is
        # usually ~PATH_LOOKAHEAD pixels ahead; we want to emit a
        # direction every frame until we arrive at the goal). The
        # caller's ``deadband`` applies to the *goal*, not the
        # intermediate waypoints — it's consulted only in the
        # fallback path below.
        return _greedy_world_delta(bot, g.path_step_x, g.path_step_y, deadband=2)

    # Unreachable or A\* failed: aim at the goal directly and let the
    # anti-stuck jiggle deal with walls.
    return _greedy_world_delta(bot, g.world_x, g.world_y, deadband)


def _advance_along_path(bot: Bot) -> None:
    """Update the cached waypoint by finding our position on the stored path.

    Scans the stored A\\* path for the closest point to the bot's
    current world position, then looks :data:`~modulabot.path.PATH_LOOKAHEAD`
    steps ahead. This is called every tick so the waypoint tracks our
    progress smoothly — the expensive A\\* is only recomputed on the
    replan cadence but the waypoint never goes stale.
    """
    g = bot.goal
    path = g.path
    if not path:
        g.has_path_step = False
        return

    px = player_world_x(bot.percep)
    py = player_world_y(bot.percep)

    # Find closest point on the stored path.
    best_dist = 1 << 30
    best_idx = 0
    for i, step in enumerate(path):
        d = abs(step.x - px) + abs(step.y - py)
        if d < best_dist:
            best_dist = d
            best_idx = i

    # Look ahead from our closest point.
    lookahead_idx = min(len(path) - 1, best_idx + path_mod.PATH_LOOKAHEAD)
    step = path[lookahead_idx]
    g.has_path_step = True
    g.path_step_x = step.x
    g.path_step_y = step.y


def _greedy_world_delta(
    bot: Bot, target_wx: int, target_wy: int, deadband: int
) -> int:
    """Emit a direction from the world-space delta to ``(target_wx, target_wy)``.

    Works identically in state-obs mode (where ``player_world_*``
    returns the sighting's screen coords + camera offset == 0) and
    in pixel mode (real world coords). Shared helper so
    :func:`navigate_to_world_goal` has one direction-emission path
    for both the waypoint case and the fallback.
    """
    percep = bot.percep
    if percep.localized:
        px, py = player_world_x(percep), player_world_y(percep)
    else:
        # Without a camera lock, treat the screen centre as our
        # "world" position. This degrades cleanly to the old
        # move_toward semantics when callers already threaded
        # screen-space coords through set_world_goal.
        px, py = CENTER_X, CENTER_Y
    dx = target_wx - px
    dy = target_wy - py
    return actions.direction_to(dx, dy, deadband=deadband)


def world_pos_from_screen(percep, screen_x: int, screen_y: int) -> tuple[int, int]:
    """Convert a screen-space coordinate to world space via the current camera.

    Used by policies to translate perception's adapter-populated
    screen positions (e.g. ``body.x / body.y`` on a BodySighting)
    into world coordinates the pathfinder understands. Returns
    ``(-1, -1)`` when the camera isn't locked so callers can fall
    back to screen-space steering.
    """
    if not percep.localized:
        return (-1, -1)
    return (percep.camera_x + screen_x, percep.camera_y + screen_y)
