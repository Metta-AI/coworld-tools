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
4. **Adapter layer**: derive ``bot.percep.players`` /
   ``bot.percep.bodies`` / ``bot.percep.tasks`` from the pixel
   matches so the existing state-obs-era policies work unchanged.
   Self-player sighting is painted at screen centre with whatever
   colour :func:`~modulabot.actors.update_self_color` resolved.

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
    GameMap,
    ReferenceData,
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

    _populate_policy_state(bot, reference_data.map)


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


def _populate_policy_state(bot: Bot, game_map: GameMap) -> None:
    """Derive :class:`~modulabot.state.PlayerSighting` /
    :class:`~modulabot.state.BodySighting` / :class:`~modulabot.state.TaskInfo`
    lists from the pixel match results.

    Populated lists live at ``bot.percep.players`` / ``bodies`` /
    ``tasks``. Consumed by the state-obs-era policies in
    :mod:`modulabot.policies`. Kept deliberately shallow — the pixel
    pipeline doesn't need to know anything about the policy layer's
    task-tier priority, goal selection, or chat queue; it just
    translates perception into the vocabulary those policies expect.
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
    _populate_tasks_from_camera(bot, game_map)


def _populate_tasks_from_camera(bot: Bot, game_map: GameMap) -> None:
    """Emit :class:`~modulabot.state.TaskInfo` entries for every task
    station, projected through the current camera.

    ``icon_visible`` is True when we saw a task-icon pixel match near
    the expected on-screen position (within ``ICON_MATCH_RADIUS``
    pixels of the projected icon centre). ``active`` is True when
    the player's world position sits inside the task's rectangle —
    that's where the crewmate policy fires the A-press / hold.

    Off-screen tasks (icons outside the 128×128 viewport) get an
    ``arrow_visible`` hint pointing at the screen edge in the
    direction of the task. The arrow mode is intentionally
    lightweight — the Nim bot's radar-dot reconciliation is a
    future refinement; for now the screen-edge hint is enough to
    keep the crewmate policy's "chase the arrow" branch firing.
    """
    percep = bot.percep
    cam_x = percep.camera_x
    cam_y = percep.camera_y
    player_wx = player_world_x(percep)
    player_wy = player_world_y(percep)

    icon_match_radius = 10  # screen-space pixels; slightly looser than the scan radius
    resolved_count = len(bot.tasks.resolved)
    if resolved_count < len(game_map.tasks):
        # Lazy init: one resolved flag + state slot per task. Matches
        # the Nim layout. Only done once per round — on first
        # populate_tasks, ``bot.tasks.resolved`` starts empty.
        bot.tasks.resolved.extend(
            [False] * (len(game_map.tasks) - resolved_count)
        )
        bot.tasks.states.extend(
            [TaskState.NOT_DOING] * (len(game_map.tasks) - len(bot.tasks.states))
        )

    for task in game_map.tasks:
        # Project icon centre to screen space.
        icon_screen_x = task.cx - cam_x
        icon_screen_y = task.y - cam_y  # icon sits just above the rect
        on_screen = (
            0 <= icon_screen_x < SCREEN_WIDTH
            and 0 <= icon_screen_y < SCREEN_HEIGHT
        )

        icon_visible = False
        if on_screen:
            for match in percep.visible_task_icons:
                if (
                    abs(match.x + 6 - icon_screen_x) <= icon_match_radius
                    and abs(match.y + 6 - icon_screen_y) <= icon_match_radius
                ):
                    icon_visible = True
                    break

        arrow_x = 0
        arrow_y = 0
        arrow_visible = False
        if not on_screen:
            # Point at the screen edge in the task's direction. Rough
            # but sufficient for "steer toward this task until we can
            # see it".
            arrow_x = int(max(0, min(SCREEN_WIDTH - 1, icon_screen_x)))
            arrow_y = int(max(0, min(SCREEN_HEIGHT - 1, icon_screen_y)))
            arrow_visible = True

        active = (
            task.x <= player_wx < task.x + task.w
            and task.y <= player_wy < task.y + task.h
        )

        percep.tasks.append(
            TaskInfo(
                index=task.index,
                x=icon_screen_x if on_screen else 0,
                y=icon_screen_y if on_screen else 0,
                arrow_x=arrow_x,
                arrow_y=arrow_y,
                icon_visible=icon_visible,
                arrow_visible=arrow_visible,
                active=active,
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
