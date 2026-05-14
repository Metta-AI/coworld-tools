"""State-observation parser for the cogames BitWorld AmongThem shim.

.. warning::
   This path is **not** exercised in tournament play. The cogames
   ``BitWorldRunner`` hardcodes ``observation_kind="pixels"`` for
   Among Them; structured state observations only come through the
   training-harness ``BitWorldVecEnv`` path. Kept for offline
   evaluation, the test suite, and any future training work that
   wants to share the policy layer. The production path is
   :mod:`~modulabot.perception.pixel_pipeline`.

Layout (matches the ``bitworld_among_them_cyborg`` reference policy
constants):

::

    [ header: 22 features ]
    [ grid:   32 x 32 features ]
    [ 16 players x 8 features ]
    [ 16 bodies  x 8 features ]
    [ 15 tasks   x 8 features ]

Header features of interest (byte indices inside the 22-length header):

- ``[0]``   phase (1 playing / 2 voting / 5 role reveal / other)
- ``[4]``   self role (1 imposter, 0 crewmate)
- ``[9]``   kill cooldown remaining (255 = ready, otherwise countdown)
- ``[10]``  task progress byte (0-255)
- ``[16]``  vote cursor (slot index, meaningful during voting)

Player feature layout (8 bytes per player):

- ``[0]``   kind (1 = player, 0 = slot empty)
- ``[1]``   screen x
- ``[2]``   screen y
- ``[3]``   colour palette index
- ``[4]``   flags (bit 1 = self, bit 2 = alive, bit 3 = imposter known,
            bit 6 = selected in vote UI)
- ``[5..7]`` reserved / per-feature extras (unused here)

Body feature layout (8 bytes per body):

- ``[0]``   kind (2 = body, 0 = empty)
- ``[1]``   screen x
- ``[2]``   screen y
- ``[3]``   colour palette index of victim
- remainder reserved

Task feature layout (8 bytes per task):

- ``[0]``   kind (3 = task, 0 = empty)
- ``[1]``   screen x of task rect
- ``[2]``   screen y of task rect
- ``[3]``   flags (bit 1 incomplete, bit 2 active, bit 3 icon visible,
            bit 4 arrow visible, bit 5 completed)
- ``[5]``   arrow x (radar arrow direction when offscreen)
- ``[6]``   arrow y
- remainder reserved

If the tournament server changes any of these the cyborg reference
will break too, so we take the same risk for the same reward.
"""

from __future__ import annotations

import numpy as np

from ..state import (
    Bot,
    BodySighting,
    Perception,
    Phase,
    PlayerSighting,
    TaskInfo,
    TaskState,
)

STATE_HEADER_FEATURES = 22
STATE_GRID_SIZE = 32
STATE_PLAYER_FEATURES = 8
STATE_BODY_FEATURES = 8
STATE_TASK_FEATURES = 8

STATE_PLAYER_COUNT = 16
STATE_BODY_COUNT = 16
STATE_TASK_COUNT = 15

STATE_PLAYER_FEATURE_OFFSET = STATE_HEADER_FEATURES + STATE_GRID_SIZE * STATE_GRID_SIZE
STATE_BODY_FEATURE_OFFSET = STATE_PLAYER_FEATURE_OFFSET + STATE_PLAYER_FEATURES * STATE_PLAYER_COUNT
STATE_TASK_FEATURE_OFFSET = STATE_BODY_FEATURE_OFFSET + STATE_BODY_FEATURES * STATE_BODY_COUNT
STATE_FEATURES = STATE_TASK_FEATURE_OFFSET + STATE_TASK_FEATURES * STATE_TASK_COUNT

# Phase values
PHASE_PLAYING = 1
PHASE_VOTING = 2
PHASE_ROLE_REVEAL = 5

# Header indices
HEADER_PHASE = 0
HEADER_SELF_ROLE = 4
HEADER_KILL_COOLDOWN = 9
HEADER_TASK_PROGRESS = 10
HEADER_VOTE_CURSOR = 16

# Kind constants
KIND_EMPTY = 0
KIND_PLAYER = 1
KIND_BODY = 2
KIND_TASK = 3

# Player flag bits
PLAYER_SELF = 2
PLAYER_ALIVE = 4
PLAYER_IMPOSTER = 8
PLAYER_SELECTED = 64

# Task flag bits
TASK_INCOMPLETE = 2
TASK_ACTIVE = 4
TASK_ICON_VISIBLE = 8
TASK_ARROW_VISIBLE = 16
TASK_COMPLETED = 32

KILL_COOLDOWN_READY = 255


def looks_like_state_observation(observation: np.ndarray) -> bool:
    """Return ``True`` if ``observation`` matches the state-obs layout.

    Accepts both the stacked form ``(frame_stack, STATE_FEATURES)`` and
    the flattened form ``(STATE_FEATURES * frame_stack,)``. Rejects pixel
    observations (which are always 2D+ with a 128-wide last dim).
    """
    if observation.ndim == 1:
        return observation.shape[0] % STATE_FEATURES == 0
    if observation.ndim == 2:
        return observation.shape[1] == STATE_FEATURES or (
            observation.shape[1] % STATE_FEATURES == 0 and observation.shape[1] != 128
        )
    return False


def _latest_frame(observation: np.ndarray) -> np.ndarray:
    """Return the single most-recent ``STATE_FEATURES``-length vector."""
    if observation.ndim == 1:
        frame_stack = observation.shape[0] // STATE_FEATURES
        return observation.reshape(frame_stack, STATE_FEATURES)[-1]
    if observation.ndim == 2 and observation.shape[1] == STATE_FEATURES:
        return observation[-1]
    if observation.ndim == 2 and observation.shape[1] % STATE_FEATURES == 0:
        frame_stack = observation.shape[1] // STATE_FEATURES
        return observation.reshape(observation.shape[0], frame_stack, STATE_FEATURES)[-1, -1]
    raise ValueError(f"state observation shape {observation.shape} not understood")


def update_from_state_obs(bot: Bot, observation: np.ndarray) -> None:
    """Populate ``bot.percep`` (and adjacent sub-records) from a state obs."""
    frame = _latest_frame(observation)
    percep = bot.percep

    phase_byte = int(frame[HEADER_PHASE])
    percep.phase = _phase_from_byte(phase_byte)
    percep.interstitial = percep.phase in (
        Phase.VOTING,
        Phase.ROLE_REVEAL,
        Phase.INTERSTITIAL,
    )
    percep.interstitial_text = ""  # state obs doesn't carry OCR text
    percep.localized = True  # we always know our position in state-obs mode
    percep.task_progress = float(frame[HEADER_TASK_PROGRESS]) / 255.0

    # Voting cursor: only meaningful during VOTING phase.
    if percep.phase == Phase.VOTING:
        bot.voting.cursor = int(frame[HEADER_VOTE_CURSOR])
    else:
        bot.voting.cursor = -1

    # Role reveal: lock in self role once we see the explicit byte.
    if percep.phase == Phase.ROLE_REVEAL:
        bot.identity.self_color = bot.identity.self_color  # nothing to update here
        if int(frame[HEADER_SELF_ROLE]) == 1:
            from ..state import Role

            bot.role = Role.IMPOSTER
    else:
        # During play, also trust the header if it says we're an imposter.
        # Kill-cooldown counting down is another strong signal.
        if int(frame[HEADER_SELF_ROLE]) == 1:
            from ..state import Role

            bot.role = Role.IMPOSTER
        elif bot.role.value == 0:  # UNKNOWN
            from ..state import Role

            bot.role = Role.CREWMATE

    # Imposter sub-record: kill cooldown → kill_ready.
    bot.imposter.kill_ready = int(frame[HEADER_KILL_COOLDOWN]) == KILL_COOLDOWN_READY

    _parse_players(frame, percep, bot)
    _parse_bodies(frame, percep)
    _parse_tasks(frame, percep, bot)
    _adapt_voting_cache(bot, percep)


def _phase_from_byte(byte: int) -> Phase:
    if byte == PHASE_PLAYING:
        return Phase.PLAYING
    if byte == PHASE_VOTING:
        return Phase.VOTING
    if byte == PHASE_ROLE_REVEAL:
        return Phase.ROLE_REVEAL
    if byte == 0:
        return Phase.UNKNOWN
    return Phase.INTERSTITIAL


def _parse_players(frame: np.ndarray, percep: Perception, bot: Bot) -> None:
    players = frame[STATE_PLAYER_FEATURE_OFFSET:STATE_BODY_FEATURE_OFFSET].reshape(
        STATE_PLAYER_COUNT, STATE_PLAYER_FEATURES
    )
    percep.players.clear()
    for slot, row in enumerate(players):
        kind = int(row[0])
        if kind != KIND_PLAYER:
            continue
        flags = int(row[4])
        sighting = PlayerSighting(
            slot=slot,
            x=int(row[1]),
            y=int(row[2]),
            color=int(row[3]),
            alive=bool(flags & PLAYER_ALIVE),
            is_self=bool(flags & PLAYER_SELF),
            is_imposter_known=bool(flags & PLAYER_IMPOSTER),
        )
        percep.players.append(sighting)
        if sighting.is_self:
            bot.identity.self_slot = slot
            bot.identity.self_color = sighting.color
        if sighting.is_imposter_known and not sighting.is_self:
            bot.identity.known_imposters.add(sighting.color)
        bot.identity.last_seen[slot] = percep.tick


def _parse_bodies(frame: np.ndarray, percep: Perception) -> None:
    bodies = frame[STATE_BODY_FEATURE_OFFSET:STATE_TASK_FEATURE_OFFSET].reshape(
        STATE_BODY_COUNT, STATE_BODY_FEATURES
    )
    percep.bodies.clear()
    for row in bodies:
        if int(row[0]) != KIND_BODY:
            continue
        percep.bodies.append(
            BodySighting(x=int(row[1]), y=int(row[2]), color=int(row[3]))
        )


def _parse_tasks(frame: np.ndarray, percep: Perception, bot: Bot) -> None:
    tasks = frame[STATE_TASK_FEATURE_OFFSET : STATE_TASK_FEATURE_OFFSET + STATE_TASK_FEATURES * STATE_TASK_COUNT].reshape(
        STATE_TASK_COUNT, STATE_TASK_FEATURES
    )
    percep.tasks.clear()
    for index, row in enumerate(tasks):
        if int(row[0]) != KIND_TASK:
            continue
        flags = int(row[3])
        icon_visible = bool(flags & TASK_ICON_VISIBLE)
        arrow_visible = bool(flags & TASK_ARROW_VISIBLE)
        active = bool(flags & TASK_ACTIVE)
        completed = bool(flags & TASK_COMPLETED)
        incomplete = bool(flags & TASK_INCOMPLETE)
        if completed:
            state = TaskState.COMPLETED
        elif icon_visible or active:
            state = TaskState.MANDATORY
        elif arrow_visible or incomplete:
            state = TaskState.MAYBE
        else:
            state = TaskState.NOT_DOING
        percep.tasks.append(
            TaskInfo(
                index=index,
                x=int(row[1]),
                y=int(row[2]),
                arrow_x=int(row[5]),
                arrow_y=int(row[6]),
                state=state,
                icon_visible=icon_visible,
                arrow_visible=arrow_visible,
                active=active,
            )
        )
    # Resize Tasks sub-record to match.
    expected = len(percep.tasks)
    if len(bot.tasks.states) != expected:
        bot.tasks.states = [t.state for t in percep.tasks]
        bot.tasks.resolved = [False] * expected
        bot.tasks.checkout = [False] * expected
        bot.tasks.icon_misses = [0] * expected
    else:
        if len(bot.tasks.checkout) != expected:
            # Keep checkout list aligned; no-op under normal replay.
            bot.tasks.checkout = [False] * expected
        if len(bot.tasks.icon_misses) != expected:
            bot.tasks.icon_misses = [0] * expected
        for i, info in enumerate(percep.tasks):
            # Sticky: once resolved/completed, stay that way; otherwise follow
            # the perception's current read.
            if info.state == TaskState.COMPLETED:
                bot.tasks.states[i] = TaskState.COMPLETED
                bot.tasks.resolved[i] = True
            elif bot.tasks.resolved[i]:
                bot.tasks.states[i] = TaskState.COMPLETED
            else:
                bot.tasks.states[i] = info.state


def _adapt_voting_cache(bot: Bot, percep: Perception) -> None:
    """Populate :mod:`modulabot.voting` parse-cache fields from the
    structured observation.

    The tournament path uses :mod:`modulabot.voting.parse_voting_screen`
    to build this cache from pixels; the state-obs path has no chat
    panel to OCR and no cell sprites to sprite-match, but the policy
    layer should still see a well-formed cache so the voting policy's
    ``player_count > 0`` gate fires. We synthesise slots from the
    observed player list — enough for the decision policy to pick a
    target slot and drive the cursor, but not for anything
    chat-bandwagon related (``chat_sus_color`` stays at
    :data:`VOTE_UNKNOWN`).

    Transitions *out* of voting clear the cache via
    :func:`modulabot.voting.clear_voting_state` so stale slots don't
    leak into the next meeting when tests bounce between phases.
    """
    from ..state import Phase
    from ..voting import MAX_PLAYERS, VOTE_UNKNOWN, VoteSlot, clear_voting_state

    v = bot.voting
    if percep.phase != Phase.VOTING:
        if v.active:
            clear_voting_state(bot)
            v.active = False
        return

    if not v.active:
        clear_voting_state(bot)
        v.active = True
        v.start_tick = percep.tick

    # Rebuild slots from the observed player list. In state-obs mode
    # the slots array is keyed by colour index (matching the pixel
    # path's parser invariant) so downstream lookups via
    # ``vote_slot_for_color`` return the right slot.
    v.player_count = 0
    v.self_slot = VOTE_UNKNOWN
    if len(v.slots) != MAX_PLAYERS:
        v.slots = [VoteSlot(color_index=VOTE_UNKNOWN, alive=False) for _ in range(MAX_PLAYERS)]
    else:
        for i in range(MAX_PLAYERS):
            v.slots[i] = VoteSlot(color_index=VOTE_UNKNOWN, alive=False)
    for sighting in percep.players:
        if sighting.color < 0 or sighting.color >= MAX_PLAYERS:
            continue
        slot_index = sighting.color  # color_index == slot_index convention
        v.slots[slot_index] = VoteSlot(
            color_index=sighting.color,
            alive=sighting.alive,
        )
        v.player_count = max(v.player_count, slot_index + 1)
        if sighting.is_self:
            v.self_slot = slot_index
