"""Pixel-observation perception pipeline.

The orchestrator the cogames tournament path actually uses. Given a
frame, a :class:`~modulabot.data.ReferenceData` bundle (sprites,
font, game map), a :class:`~modulabot.localize.Localizer`, and a
:class:`~modulabot.state.Bot`, fills in every field of
``bot.percep`` and the rest of the sub-records that the policy
layer reads. One call per tick, before the policies dispatch.

Phase detection & flow:

1. **Interstitial gate** via
   :func:`~modulabot.frame.looks_like_interstitial` (≥30% black
   pixels). On a hit, every actor scan is skipped — body / ghost
   sprites have enough black outline to false-positive on a black
   screen otherwise.
2. **Voting parse** on interstitial frames via
   :func:`modulabot.voting.parse_voting_screen`. If it validates,
   ``phase = VOTING`` and ``bot.voting.*`` is populated. Otherwise
   ``phase = INTERSTITIAL`` (role reveal, game over, etc.) and we
   emit minimal state.
3. **Playing** (non-interstitial): :func:`~modulabot.actors.scan_all`
   + :func:`~modulabot.localize.Localizer.update_location`. The
   scanners go first so the localizer's ignore mask knows about
   dynamic pixels.
4. **Adapter layer** (:func:`_populate_policy_state` →
   :func:`_populate_tasks_from_camera`): derive
   ``bot.percep.players`` / ``bot.percep.bodies`` /
   ``bot.percep.tasks`` from the pixel matches so the existing
   state-obs-era policies work unchanged. Task population is
   the heart of the crewmate-task fix work
   (`CREWMATE_TASK_FIX_PLAN.md`):

   - Strict icon match → ``icon_visible`` (server-rendered, =
     assignment).
   - Server-accurate radar-dot projection (:func:`_projected_radar_dot`)
     → ``arrow_visible`` for off-screen tasks, with the
     ``bot.tasks.checkout[i]`` latch surviving momentary dot loss
     (Phase 1).
   - Composite ``active = active_rect AND (icon_visible OR
     checkout[i])`` (Phase 2).
   - Per-task icon-miss counter incremented when the inspection
     rect is fully on-screen with margin AND no strict match AND
     no fuzzy ``maybe_matches_sprite`` match — once it hits
     :data:`~modulabot.tuning.ICON_MISS_THRESHOLD` we latch
     ``resolved[i] = True, checkout[i] = False``, pruning the
     task from the candidate set for the rest of the round
     (Phase 6).

The pipeline does not mutate reference data and does not
persist any state outside ``bot``; safe to call on a fresh bot
every tick.
"""

from __future__ import annotations

import numpy as np

from .. import voting
from ..actors import scan_all
from ..data import (
    MAP_HEIGHT,
    MAP_WIDTH,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    SPRITE_SIZE,
    GameMap,
    ReferenceData,
    Sprite,
    TaskStation,
)
from ..frame import looks_like_interstitial
from ..geometry import (
    PLAYER_SCREEN_X,
    PLAYER_SCREEN_Y,
    SPRITE_DRAW_OFF_X,
    SPRITE_DRAW_OFF_Y,
    player_world_x,
    player_world_y,
)
from ..localize import Localizer
from ..state import (
    BodySighting,
    Bot,
    Phase,
    PlayerSighting,
    Role,
    TaskInfo,
    TaskState,
)
from ..sprite_match import maybe_matches_sprite
from ..tuning import (
    ICON_MISS_THRESHOLD,
    RADAR_MATCH_TOLERANCE,
    TASK_CLEAR_SCREEN_MARGIN,
    TASK_ICON_EXPECTED_SEARCH_RADIUS,
    TASK_ICON_INSPECT_SIZE,
)


def update_from_pixel_observation(
    bot: Bot,
    reference_data: ReferenceData,
    localizer: Localizer,
    observation: np.ndarray,
    tick: int,
) -> None:
    """Run the full pixel pipeline for one frame.

    ``observation`` may be any of the shapes
    :func:`~modulabot.perception.pixel_obs.update_from_pixel_obs`
    accepted — we reuse the unpacker so stacked / packed formats
    work. ``tick`` is the bot's current frame tick (used as
    ``start_tick`` seed for new voting meetings).
    """
    frame = _latest_pixel_frame(observation)
    percep = bot.percep

    # Phase 0 reset: clear pixel-match lists so leftover matches from
    # the previous frame don't leak into this one's policy decisions.
    percep.interstitial_text = ""
    percep.players = []
    percep.bodies = []
    percep.tasks = []
    percep.radar_target = None

    percep.interstitial = looks_like_interstitial(frame)

    if percep.interstitial:
        _handle_interstitial(bot, reference_data, frame, tick)
        return

    percep.phase = Phase.PLAYING
    # Actor scans must run before the localizer so the ignore mask
    # reflects this frame's dynamic pixels.
    scan_all(bot, reference_data.sprites, frame, reference_data.map)
    localizer.update_location(bot, reference_data.sprites, frame)

    _populate_policy_state(
        bot, reference_data.map, frame, reference_data.sprites.task
    )


# ---------------------------------------------------------------------------
# Interstitial handling
# ---------------------------------------------------------------------------


def _handle_interstitial(
    bot: Bot,
    reference_data: ReferenceData,
    frame: np.ndarray,
    tick: int,
) -> None:
    """Distinguish voting interstitials from everything else.

    Voting parser is strict (every slot colour must match its slot
    index), so a false positive during a role-reveal splash is very
    unlikely. On voting, ``bot.voting.active`` is set and
    ``phase = VOTING``; everything else lands on ``phase = INTERSTITIAL``
    with voting state cleared so the next meeting starts fresh.
    """
    if voting.parse_voting_screen(
        bot,
        reference_data.sprites,
        reference_data.font,
        frame,
        tick,
    ):
        bot.percep.phase = Phase.VOTING
        _populate_voting_players(bot)
        return

    bot.percep.phase = Phase.INTERSTITIAL
    # A non-voting interstitial means "something changed" — role
    # reveal, game over, round transition. Reset the voting cache so
    # leftover slots / chat from the previous meeting don't linger.
    if bot.voting.active:
        voting.clear_voting_state(bot)


# ---------------------------------------------------------------------------
# Adapter layer: pixel matches → policy-facing state
# ---------------------------------------------------------------------------


def _populate_policy_state(
    bot: Bot, game_map: GameMap, frame: np.ndarray, task_sprite: Sprite
) -> None:
    """Derive :class:`~modulabot.state.PlayerSighting` /
    :class:`~modulabot.state.BodySighting` / :class:`~modulabot.state.TaskInfo`
    lists from the pixel match results.

    Populated lists live at ``bot.percep.players`` / ``bodies`` /
    ``tasks``. Consumed by the state-obs-era policies in
    :mod:`modulabot.policies`. Kept deliberately shallow — the pixel
    pipeline doesn't need to know anything about the policy layer's
    task-tier priority, goal selection, or chat queue; it just
    translates perception into the vocabulary those policies expect.

    ``frame`` and ``task_sprite`` are threaded through so
    :func:`_populate_tasks_from_camera` can run the Phase 6
    icon-miss negative-evidence pass (``maybe_matches_sprite``
    requires the raw frame).
    """
    percep = bot.percep

    # Self sighting at screen centre (always painted since the player
    # sprite is centred; colour may be UNKNOWN if update_self_color
    # hasn't resolved it yet).
    percep.players.append(
        PlayerSighting(
            slot=-1,
            x=PLAYER_SCREEN_X,
            y=PLAYER_SCREEN_Y,
            color=bot.identity.self_color,
            alive=not bot.is_ghost,
            is_self=True,
        )
    )

    # Other visible crewmates.
    for match in percep.visible_crewmates:
        percep.players.append(
            PlayerSighting(
                slot=-1,
                x=match.x + SPRITE_DRAW_OFF_X,
                y=match.y + SPRITE_DRAW_OFF_Y,
                color=match.color_index,
                alive=True,
                is_self=False,
                is_imposter_known=(
                    match.color_index in bot.identity.known_imposters
                ),
            )
        )

    # Bodies (pixel matches are in sprite-anchor coordinates; the
    # policy-facing BodySighting wants a centre-ish point, so offset
    # by the sprite draw origin).
    for match in percep.visible_bodies:
        percep.bodies.append(
            BodySighting(
                x=match.x + SPRITE_DRAW_OFF_X,
                y=match.y + SPRITE_DRAW_OFF_Y,
                color=match.color_index,
            )
        )

    # Tasks — project each game_map task's world position to screen
    # via the camera lock. When localisation failed we leave the
    # task list empty; the patrol fallback kicks in until we relock.
    if not percep.localized:
        return
    _populate_tasks_from_camera(bot, game_map, frame, task_sprite)


def _projected_radar_dot(
    task: TaskStation,
    cam_x: int,
    cam_y: int,
    player_wx: int,
    player_wy: int,
) -> tuple[bool, int, int]:
    """Project a task icon to its expected on-screen position.

    Returns ``(on_screen, x, y)``:

    - If the task's icon sprite bbox intersects the 128×128 viewport,
      ``on_screen=True`` and ``(x, y)`` is the icon centre in screen
      coords.
    - Otherwise ``on_screen=False`` and ``(x, y)`` is the point on the
      screen edge where the server would render the radar dot —
      clipped along the player→icon ray against the screen rectangle.

    Faithful port of ``projectedRadarDot`` in
    ``~/coding/bitworld/among_them/players/modulabot/tasks.nim:63-108``
    (CollisionW = CollisionH = 1 in the sim so the ``+ CollisionW div
    2`` terms in the Nim math drop out). The icon centre formula
    differs from the ``icon_screen_{x,y}`` values the caller uses for
    the sprite-match branch — there the existing code deliberately
    uses ``task.y - cam_y`` as an approximation. We use the Nim math
    here because it's the formula the server itself uses to decide
    where to draw the radar dot; matching the dot position means
    matching the server's projection.
    """
    icon_sx = task.x + task.w // 2 - SPRITE_SIZE // 2 - cam_x
    icon_sy = task.y - SPRITE_SIZE - 2 - cam_y
    icon_x = icon_sx + SPRITE_SIZE // 2
    icon_y = icon_sy + SPRITE_SIZE // 2
    # Sprite bbox intersects screen: server draws the icon, not a dot.
    if (
        icon_sx + SPRITE_SIZE > 0
        and icon_sy + SPRITE_SIZE > 0
        and icon_sx < SCREEN_WIDTH
        and icon_sy < SCREEN_HEIGHT
    ):
        return True, icon_x, icon_y

    px = float(player_wx - cam_x)
    py = float(player_wy - cam_y)
    dx = float(icon_x) - px
    dy = float(icon_y) - py
    if abs(dx) < 0.5 and abs(dy) < 0.5:
        # Degenerate: player sitting on top of icon. No dot to project.
        return False, 0, 0

    min_x = 0.0
    max_x = float(SCREEN_WIDTH - 1)
    min_y = 0.0
    max_y = float(SCREEN_HEIGHT - 1)
    if abs(dx) > abs(dy):
        ex = max_x if dx > 0 else min_x
        ey = py + dy * (ex - px) / dx
        ey = min(max_y, max(min_y, ey))
    else:
        ey = max_y if dy > 0 else min_y
        ex = px + dx * (ey - py) / dy
        ex = min(max_x, max(min_x, ex))
    return False, int(ex), int(ey)


def _radar_dot_matches(
    radar_dots, proj_x: int, proj_y: int, tolerance: int = RADAR_MATCH_TOLERANCE
) -> bool:
    """True when any detected yellow radar dot lies within
    ``tolerance`` (Chebyshev) of the projected edge position.

    Matches the inner loop of Nim ``updateTaskGuesses``
    (tasks.nim:215-218)."""
    for dot in radar_dots:
        if abs(dot.x - proj_x) <= tolerance and abs(dot.y - proj_y) <= tolerance:
            return True
    return False


def _task_icon_inspect_rect(
    task: TaskStation, cam_x: int, cam_y: int
) -> tuple[int, int, int, int]:
    """Screen-space rectangle the task icon would occupy if rendered.

    Port of Nim ``taskIconInspectRect`` (tasks.nim:125-135). Used by
    :func:`_task_icon_clear_area_visible` to decide whether the
    inspection region is fully on-screen with margin — we only trust
    "no icon there" as evidence when we have a clean look. Phase 6.
    """
    x = task.x + task.w // 2 - TASK_ICON_INSPECT_SIZE // 2 - cam_x
    y = task.y - TASK_ICON_INSPECT_SIZE - cam_y
    return x, y, TASK_ICON_INSPECT_SIZE, TASK_ICON_INSPECT_SIZE


def _task_icon_clear_area_visible(
    task: TaskStation, cam_x: int, cam_y: int
) -> bool:
    """True when the icon's inspection rect is fully on-screen with
    :data:`TASK_CLEAR_SCREEN_MARGIN` pixels of slack on every side.

    Phase 6 latches ``resolved[i] = True`` only when this returns
    True — we don't trust icon absence at the edge of the viewport
    where the icon may have been clipped. Port of Nim
    ``taskIconClearAreaVisible`` (tasks.nim:146-153).
    """
    x, y, w, h = _task_icon_inspect_rect(task, cam_x, cam_y)
    return (
        x >= TASK_CLEAR_SCREEN_MARGIN
        and y >= TASK_CLEAR_SCREEN_MARGIN
        and x + w + TASK_CLEAR_SCREEN_MARGIN <= SCREEN_WIDTH
        and y + h + TASK_CLEAR_SCREEN_MARGIN <= SCREEN_HEIGHT
    )


def _task_icon_maybe_visible(
    frame: np.ndarray,
    task_sprite: Sprite,
    task: TaskStation,
    cam_x: int,
    cam_y: int,
) -> bool:
    """Loose icon-presence check using ``maybe_matches_sprite``.

    Sweeps a small ``TASK_ICON_EXPECTED_SEARCH_RADIUS`` box around
    the projected icon position at three vertical bob offsets (-1,
    0, +1) — animation-frame variants. Returns ``True`` on the first
    fuzzy hit. Phase 6 uses this as a *negative* gate: when even the
    fuzzy check finds nothing AND the strict check finds nothing AND
    the inspection rect is clear, we conclude the task isn't ours.

    Port of Nim ``taskIconMaybeVisibleFor`` (tasks.nim:155-169).
    Note: not vectorised — called only when the strict match has
    already missed and the clear-area check has passed, so the hot
    path bails out early. Total cost per task: 9 search-box
    positions × 3 bob offsets = 27 ``maybe_matches_sprite`` calls
    in the worst case, each ~12×12 pixel comparisons; well under
    1 ms total in pure Python.
    """
    base_x = task.x + task.w // 2 - SPRITE_SIZE // 2 - cam_x
    base_y = task.y - SPRITE_SIZE - 2 - cam_y
    radius = TASK_ICON_EXPECTED_SEARCH_RADIUS
    for bob_y in (-1, 0, 1):
        expected_y = base_y + bob_y
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if maybe_matches_sprite(
                    frame, task_sprite, base_x + dx, expected_y + dy
                ):
                    return True
    return False


def _populate_tasks_from_camera(
    bot: Bot,
    game_map: GameMap,
    frame: np.ndarray,
    task_sprite: Sprite,
) -> None:
    """Emit :class:`~modulabot.state.TaskInfo` entries for every task
    station, projected through the current camera.

    Flag semantics, per CREWMATE_TASK_FIX_PLAN.md Phase 1:

    - ``icon_visible`` — sprite match near the projected icon centre.
      The server only renders task icons for tasks assigned to *this*
      player, so this flag is authoritative assignment evidence.
    - ``arrow_visible`` — the icon is off-screen AND a yellow radar
      dot lies within :data:`RADAR_MATCH_TOLERANCE` of the projected
      screen-edge position. Gated on a real dot; without this, every
      off-screen task on the map reads as "chase me" regardless of
      assignment.
    - ``active`` — player world position inside the task rect plus
      assignment evidence (Phase 2).

    On a first radar-dot match we latch ``bot.tasks.checkout[i] =
    True`` so we don't lose the task from the candidate set when the
    dot momentarily disappears (the server hides dots during some
    transitions). Mirrors ``bot.tasks.checkout`` in the Nim reference.

    **Phase 6: icon-miss negative-evidence pruning.** After running
    the strict + radar checks, we run a *negative* pass: when the
    inspection rect is fully on-screen with margin
    (``_task_icon_clear_area_visible``) AND the strict match missed
    AND the fuzzy match also missed (``_task_icon_maybe_visible``),
    increment ``bot.tasks.icon_misses[i]``. On hitting
    :data:`ICON_MISS_THRESHOLD` we latch ``resolved[i] = True,
    checkout[i] = False`` — this task is *not* assigned to us and we
    won't re-visit it for the rest of the round. The hold and
    confirmation indices are excluded so Phase 3's signal handling
    isn't double-fired in those windows. Any positive (strict or
    fuzzy) match resets the counter to zero.
    """
    percep = bot.percep
    cam_x = percep.camera_x
    cam_y = percep.camera_y
    player_wx = player_world_x(percep)
    player_wy = player_world_y(percep)

    icon_match_radius = 10  # screen-space pixels; slightly looser than the scan radius
    ntasks = len(game_map.tasks)
    # Lazy init: one resolved / state / checkout / icon_misses slot
    # per task. Matches the Nim layout. Done once per round — the
    # four lists grow together and stay the same length for the rest
    # of the round.
    if len(bot.tasks.resolved) < ntasks:
        bot.tasks.resolved.extend([False] * (ntasks - len(bot.tasks.resolved)))
    if len(bot.tasks.states) < ntasks:
        bot.tasks.states.extend(
            [TaskState.NOT_DOING] * (ntasks - len(bot.tasks.states))
        )
    if len(bot.tasks.checkout) < ntasks:
        bot.tasks.checkout.extend([False] * (ntasks - len(bot.tasks.checkout)))
    if len(bot.tasks.icon_misses) < ntasks:
        bot.tasks.icon_misses.extend(
            [0] * (ntasks - len(bot.tasks.icon_misses))
        )

    for task in game_map.tasks:
        # Cheap approximation used for the icon sprite-match branch
        # (matches the pre-Phase-1 code exactly, so tests that depend
        # on it still pass).
        icon_screen_x = task.cx - cam_x
        icon_screen_y = task.y - cam_y  # icon sits just above the rect
        on_screen_approx = (
            0 <= icon_screen_x < SCREEN_WIDTH
            and 0 <= icon_screen_y < SCREEN_HEIGHT
        )

        icon_visible = False
        if on_screen_approx:
            for match in percep.visible_task_icons:
                if (
                    abs(match.x + 6 - icon_screen_x) <= icon_match_radius
                    and abs(match.y + 6 - icon_screen_y) <= icon_match_radius
                ):
                    icon_visible = True
                    break

        # Server-accurate projection for the radar branch. This decides
        # whether the server would have drawn a dot at all, and if so
        # where.
        proj_on_screen, proj_x, proj_y = _projected_radar_dot(
            task, cam_x, cam_y, player_wx, player_wy
        )

        arrow_visible = False
        arrow_x = 0
        arrow_y = 0
        if not proj_on_screen:
            dot_match = _radar_dot_matches(percep.radar_dots, proj_x, proj_y)
            if dot_match and 0 <= task.index < len(bot.tasks.checkout):
                # First time we've seen a dot for this task this round
                # → latch. Never reset within the round: the server
                # hides dots whenever the icon is on-screen, so a
                # "no dot this tick" reading must not drop the task
                # out of the candidate set.
                bot.tasks.checkout[task.index] = True
            checkout_latched = (
                0 <= task.index < len(bot.tasks.checkout)
                and bot.tasks.checkout[task.index]
            )
            arrow_visible = dot_match or checkout_latched
            arrow_x = proj_x
            arrow_y = proj_y

        active_rect = (
            task.x <= player_wx < task.x + task.w
            and task.y <= player_wy < task.y + task.h
        )
        # Phase 2: only declare a task "active" (i.e. A-hold will
        # complete it) when we have independent assignment evidence —
        # a visible icon, or a checkout-latched radar dot. Standing in
        # someone else's task rect no longer starts a hold.
        checkout_evidence = (
            0 <= task.index < len(bot.tasks.checkout)
            and bot.tasks.checkout[task.index]
        )
        active = active_rect and (icon_visible or checkout_evidence)

        # Phase 6: icon-miss negative-evidence pruning. Skip when the
        # task is held / confirming (Phase 3 owns the icon signal in
        # those windows) or already resolved.
        if 0 <= task.index < len(bot.tasks.icon_misses):
            if (
                task.index != bot.tasks.hold_index
                and task.index != bot.tasks.confirming_index
                and not bot.tasks.resolved[task.index]
            ):
                if icon_visible:
                    # Strict positive → reset counter. Skip the
                    # expensive maybe check.
                    bot.tasks.icon_misses[task.index] = 0
                elif _task_icon_clear_area_visible(task, cam_x, cam_y):
                    # Clean view of the inspect rect. The fuzzy check
                    # is the second negative gate — if even that
                    # misses, the absence is meaningful.
                    if _task_icon_maybe_visible(
                        frame, task_sprite, task, cam_x, cam_y
                    ):
                        bot.tasks.icon_misses[task.index] = 0
                    else:
                        bot.tasks.icon_misses[task.index] += 1
                        if (
                            bot.tasks.icon_misses[task.index]
                            >= ICON_MISS_THRESHOLD
                        ):
                            # Latch: this task is *not* assigned to us.
                            # Drop the radar checkout latch too so a
                            # noisy edge pixel can't lure us back.
                            bot.tasks.resolved[task.index] = True
                            bot.tasks.checkout[task.index] = False
                            bot.tasks.icon_misses[task.index] = 0
                else:
                    # Inspection rect not fully on-screen with margin
                    # — don't trust the absence; reset so a partial
                    # view never accumulates toward the threshold.
                    bot.tasks.icon_misses[task.index] = 0

        percep.tasks.append(
            TaskInfo(
                index=task.index,
                # Phase 4.1: when the icon is off-screen, ``x`` / ``y``
                # mirror ``arrow_x`` / ``arrow_y`` so any caller that
                # forgets to gate on ``icon_visible`` reads the screen-
                # edge target instead of (0, 0). Previously off-screen
                # tasks reported ``(0, 0)`` which made
                # ``manhattan_from_center`` return ~64 — wrong but not
                # obviously wrong.
                x=icon_screen_x if on_screen_approx else arrow_x,
                y=icon_screen_y if on_screen_approx else arrow_y,
                arrow_x=arrow_x,
                arrow_y=arrow_y,
                icon_visible=icon_visible,
                arrow_visible=arrow_visible,
                active=active,
                active_rect=active_rect,
                state=(
                    bot.tasks.states[task.index]
                    if task.index < len(bot.tasks.states)
                    else TaskState.NOT_DOING
                ),
            )
        )


def _populate_voting_players(bot: Bot) -> None:
    """Translate parsed voting slots into the policy-facing
    :class:`~modulabot.state.PlayerSighting` list.

    The decision policies read ``bot.percep.players`` during voting
    to find a specific colour's slot (e.g. "flag the accusation_color
    player"). Parsed slots already carry colour + alive info; we
    adapt them into the same shape the state-obs path used so
    nothing downstream cares where the data came from.
    """
    percep = bot.percep
    percep.players = []
    v = bot.voting
    for i in range(v.player_count):
        slot = v.slots[i]
        percep.players.append(
            PlayerSighting(
                slot=i,
                x=0,  # voting screen doesn't need spatial info
                y=0,
                color=slot.color_index,
                alive=slot.alive,
                is_self=(i == v.self_slot),
                is_imposter_known=(
                    slot.color_index in bot.identity.known_imposters
                ),
            )
        )


# ---------------------------------------------------------------------------
# Observation unpacking (shared with perception.pixel_obs)
# ---------------------------------------------------------------------------


def _latest_pixel_frame(observation: np.ndarray) -> np.ndarray:
    """Return the most recent ``(H, W)`` uint8 indexed frame.

    Same shape-handling as the old minimal pixel fallback so callers
    don't have to care which path we took.
    """
    if observation.ndim == 4:
        return np.ascontiguousarray(observation[-1, -1, :, :])
    if observation.ndim == 3:
        return np.ascontiguousarray(observation[-1, :, :])
    if observation.ndim == 2:
        if observation.shape == (SCREEN_HEIGHT, SCREEN_WIDTH):
            return observation
        if observation.shape[1] * 2 == SCREEN_HEIGHT * SCREEN_WIDTH:
            return _unpack_packed(observation[-1])
    if (
        observation.ndim == 1
        and observation.shape[0] * 2 == SCREEN_HEIGHT * SCREEN_WIDTH
    ):
        return _unpack_packed(observation)
    raise ValueError(f"pixel observation shape {observation.shape} not understood")


def _unpack_packed(packed: np.ndarray) -> np.ndarray:
    pixels = np.empty(packed.shape[0] * 2, dtype=np.uint8)
    pixels[0::2] = packed & 0x0F
    pixels[1::2] = packed >> 4
    return pixels.reshape(SCREEN_HEIGHT, SCREEN_WIDTH)


__all__ = [
    "update_from_pixel_observation",
]
