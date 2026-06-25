"""Advanced Eurydice strategic modes.

These modes cover leadership transitions, hostage selection, cross-room
coordination, and lightweight disruption. They intentionally keep their
state in ``belief_state.extra`` so each mode remains self-contained and easy
to reason about.
"""

from __future__ import annotations

import random
import re
from collections.abc import Sequence
from dataclasses import dataclass

from orpheus.mode import Mode, ModeDirective, ModeParams
from orpheus.task import Task
from orpheus.idle import IdleTask
from orpheus.tasks import (
    MoveToTask,
    CreateWhisperTask,
    CloseViewTask,
    OpenGlobalChatTask,
    OpenInfoScreenTask,
    VoteUsurpTask,
    SelectHostagesTask,
    SendMessageTask,
    GrantEntryTask,
)
from orpheus.perception.types import View
from agents.eurydice.ext_keys import MODE_COMPLETE, PLAYER_KNOWLEDGE
from agents.eurydice.knowledge import PlayerKnowledge
from agents.eurydice.types import INTERACTION_RANGE_SQ, Objective, PlayerID, Team


HOLD_REPICK_TICKS = 72
HOLD_CENTER_RADIUS = 25
DECOY_REPICK_TICKS = 72
CROSS_ROOM_COMPLETE_TICKS = 48
LEADERSHIP_TIMEOUT_TICKS = 72
HOSTAGE_SELECT_TIMEOUT_TICKS = 120
SUMMIT_SECOND_MESSAGE_TICKS = 96
INFO_SCREEN_WAIT_TICKS = 48
GLOBAL_CHAT_REVIEW_TICKS = 3
GLOBAL_CHAT_REVIEW_TIMEOUT_TICKS = 24

_HOLD_TARGET_KEY = "_hold_position_target"
_HOLD_TARGET_TICK_KEY = "_hold_position_target_tick"
_DECOY_TARGET_KEY = "_decoy_target"
_DECOY_TARGET_TICK_KEY = "_decoy_target_tick"
_SUMMIT_MESSAGES_SENT_KEY = "_summit_messages_sent"
_CROSS_ROOM_SENT_KEY = "_coordinate_cross_room_sent"
_CROSS_ROOM_SENT_THIS_ENTRY_KEY = "_coordinate_cross_room_sent_this_entry"
_RELAY_SENT_KEY = "_relay_intelligence_sent"
_TIME_WASTE_TARGET_KEY = "_time_waste_target"
_IDENTITY_ANNOUNCED_KEY = "_identity_announcement_sent"


@dataclass(frozen=True)
class HoldPositionParams(ModeParams):
    seek_leadership: bool = False
    defensive: bool = False
    reason: str = ""


@dataclass(frozen=True)
class SeekLeadershipParams(ModeParams):
    reason: str = ""
    target: PlayerID | None = None


@dataclass(frozen=True)
class HostageSelectParams(ModeParams):
    objective: Objective = Objective.IDLE
    protect: tuple[PlayerID, ...] = ()
    move: tuple[PlayerID, ...] = ()


@dataclass(frozen=True)
class SummitInteractParams(ModeParams):
    request_transfer: bool = True
    probe_identity: bool = True
    message: str | None = None


@dataclass(frozen=True)
class CoordinateCrossRoomParams(ModeParams):
    objective: Objective = Objective.POSITION_FOR_WIN
    target: PlayerID | None = None
    message: str = "SEND ME"


@dataclass(frozen=True)
class TimeWasteParams(ModeParams):
    target: PlayerID | None = None
    target_team: Team | None = None
    protocol: str = "stall"
    reason: str = ""


@dataclass(frozen=True)
class RelayIntelligenceParams(ModeParams):
    message: str = "STATUS"
    channel: str = "global"


@dataclass(frozen=True)
class AnnounceIdentityParams(ModeParams):
    message: str = ""


@dataclass(frozen=True)
class ReviewGlobalChatParams(ModeParams):
    reason: str = "identity_claim_attribution"


@dataclass(frozen=True)
class DecoyParams(ModeParams):
    claim: str | None = None
    target_team: Team | None = None


class HoldPositionMode(Mode):
    """Stay in the current room while making small noncommittal movements."""

    params_type = ModeParams

    def select_task(self, belief_state, action_memory) -> Task | None:
        del action_memory

        if getattr(belief_state, "view", None) not in {
            View.PLAYING,
            View.WAITING_ENTRY,
            View.HOSTAGE_SELECT,
        }:
            _complete_mode(belief_state)
            return IdleTask()

        if getattr(belief_state, "pending_entry", None) is not None:
            return GrantEntryTask()

        position = _position2d(getattr(belief_state, "position", None))
        if position is None:
            return IdleTask()

        tick = _tick(belief_state)
        target = belief_state.extra.get(_HOLD_TARGET_KEY)
        target_tick = int(belief_state.extra.get(_HOLD_TARGET_TICK_KEY, -HOLD_REPICK_TICKS))
        if target is None or tick - target_tick >= HOLD_REPICK_TICKS:
            target = _random_center_target(belief_state)
            belief_state.extra[_HOLD_TARGET_KEY] = target
            belief_state.extra[_HOLD_TARGET_TICK_KEY] = tick

        return _move_to(target)

    def mode_enter(self, belief_state, action_memory) -> None:
        del action_memory
        _clear_mode_completion(belief_state)
        belief_state.extra.pop(_HOLD_TARGET_KEY, None)
        belief_state.extra.pop(_HOLD_TARGET_TICK_KEY, None)

    def mode_switch_cleanup(
        self,
        belief_state,
        action_memory,
        new_mode_directive: ModeDirective,
    ) -> None:
        del action_memory, new_mode_directive
        belief_state.extra.pop(_HOLD_TARGET_KEY, None)
        belief_state.extra.pop(_HOLD_TARGET_TICK_KEY, None)


class SeekLeadershipMode(Mode):
    """Open the usurp interface and vote for our own player slot."""

    params_type = ModeParams

    def select_task(self, belief_state, action_memory) -> Task | None:
        if getattr(action_memory, "ticks_active", 0) > LEADERSHIP_TIMEOUT_TICKS:
            _complete_mode(belief_state)
            return IdleTask()

        if getattr(belief_state, "view", None) is not View.GLOBAL_CHAT:
            return OpenGlobalChatTask()

        return VoteUsurpTask(candidate=_self_candidate_index(belief_state))

    def mode_enter(self, belief_state, action_memory) -> None:
        del action_memory
        _clear_mode_completion(belief_state)

    def mode_switch_cleanup(
        self,
        belief_state,
        action_memory,
        new_mode_directive: ModeDirective,
    ) -> None:
        del belief_state, action_memory, new_mode_directive


class HostageSelectMode(Mode):
    """As leader, choose available hostage slots and then let the UI finish."""

    params_type = HostageSelectParams
    params: HostageSelectParams | ModeParams = HostageSelectParams()

    def select_task(self, belief_state, action_memory) -> Task | None:
        if getattr(belief_state, "view", None) not in {
            View.HOSTAGE_SELECT,
            View.GLOBAL_CHAT,
        }:
            _complete_mode(belief_state)
            return IdleTask()

        if getattr(action_memory, "ticks_active", 0) > HOSTAGE_SELECT_TIMEOUT_TICKS:
            _complete_mode(belief_state)
            return IdleTask()

        selections = getattr(belief_state, "hostage_selections", None)
        requested = tuple(getattr(self.params, "move", ()) or ())
        if requested:
            targets = _hostage_target_indices_for_player_ids(selections, requested)
        else:
            targets = _hostage_target_indices(selections)
        if selections is not None and targets is not None:
            return SelectHostagesTask(targets)

        return IdleTask()

    def mode_enter(self, belief_state, action_memory) -> None:
        del action_memory
        _clear_mode_completion(belief_state)

    def mode_switch_cleanup(
        self,
        belief_state,
        action_memory,
        new_mode_directive: ModeDirective,
    ) -> None:
        del belief_state, action_memory, new_mode_directive


class SummitInteractMode(Mode):
    """Use the leader summit to probe identity and request transfer."""

    params_type = ModeParams

    def select_task(self, belief_state, action_memory) -> Task | None:
        messages_sent = int(belief_state.extra.get(_SUMMIT_MESSAGES_SENT_KEY, 0))

        if messages_sent == 0:
            belief_state.extra[_SUMMIT_MESSAGES_SENT_KEY] = 1
            return SendMessageTask(text="WHO ARE YOU", channel="whisper")

        if (
            messages_sent == 1
            and getattr(action_memory, "ticks_active", 0) > SUMMIT_SECOND_MESSAGE_TICKS
        ):
            belief_state.extra[_SUMMIT_MESSAGES_SENT_KEY] = 2
            return SendMessageTask(text="SEND ME", channel="whisper")

        return IdleTask()

    def mode_enter(self, belief_state, action_memory) -> None:
        del action_memory
        _clear_mode_completion(belief_state)
        belief_state.extra[_SUMMIT_MESSAGES_SENT_KEY] = 0

    def mode_switch_cleanup(
        self,
        belief_state,
        action_memory,
        new_mode_directive: ModeDirective,
    ) -> None:
        del action_memory, new_mode_directive
        belief_state.extra.pop(_SUMMIT_MESSAGES_SENT_KEY, None)


class CoordinateCrossRoomMode(Mode):
    """Ask the local leader to send us across during hostage exchange."""

    params_type = ModeParams
    params: CoordinateCrossRoomParams | ModeParams = CoordinateCrossRoomParams()

    def select_task(self, belief_state, action_memory) -> Task | None:
        sent = bool(belief_state.extra.get(_CROSS_ROOM_SENT_KEY, False))
        sent_this_entry = bool(
            belief_state.extra.get(_CROSS_ROOM_SENT_THIS_ENTRY_KEY, False)
        )

        if sent and not sent_this_entry:
            _complete_mode(belief_state)
            return IdleTask()

        if sent and getattr(action_memory, "ticks_active", 0) > CROSS_ROOM_COMPLETE_TICKS:
            _complete_mode(belief_state)
            return IdleTask()

        belief_state.extra[_CROSS_ROOM_SENT_KEY] = True
        belief_state.extra[_CROSS_ROOM_SENT_THIS_ENTRY_KEY] = True
        message = getattr(self.params, "message", "SEND ME") or "SEND ME"
        return SendMessageTask(text=message, channel="global")

    def mode_enter(self, belief_state, action_memory) -> None:
        del action_memory
        _clear_mode_completion(belief_state)
        belief_state.extra.pop(_CROSS_ROOM_SENT_THIS_ENTRY_KEY, None)

    def mode_switch_cleanup(
        self,
        belief_state,
        action_memory,
        new_mode_directive: ModeDirective,
    ) -> None:
        del action_memory, new_mode_directive
        belief_state.extra.pop(_CROSS_ROOM_SENT_THIS_ENTRY_KEY, None)


class UsurpMode(SeekLeadershipMode):
    """Compatibility alias for the leadership-seeking usurp behavior."""


class TimeWasteMode(Mode):
    """Approach a known player and try to occupy them in a whisper."""

    params_type = ModeParams
    params: TimeWasteParams | ModeParams = TimeWasteParams()

    def select_task(self, belief_state, action_memory) -> Task | None:
        del action_memory

        position = _position2d(getattr(belief_state, "position", None))
        if position is None:
            return IdleTask()

        target_id = getattr(self.params, "target", None) or _time_waste_target(
            belief_state
        )
        if target_id is None:
            return IdleTask()

        target_position = _knowledge_position(belief_state, target_id)
        if target_position is None:
            belief_state.extra.pop(_TIME_WASTE_TARGET_KEY, None)
            return IdleTask()

        if _distance_sq(position, target_position) < INTERACTION_RANGE_SQ:
            return CreateWhisperTask()

        return _move_to(target_position)

    def mode_enter(self, belief_state, action_memory) -> None:
        del action_memory
        _clear_mode_completion(belief_state)
        belief_state.extra.pop(_TIME_WASTE_TARGET_KEY, None)

    def mode_switch_cleanup(
        self,
        belief_state,
        action_memory,
        new_mode_directive: ModeDirective,
    ) -> None:
        del action_memory, new_mode_directive
        belief_state.extra.pop(_TIME_WASTE_TARGET_KEY, None)


class DecoyMode(Mode):
    """Wander through the room without looking for probe targets."""

    params_type = ModeParams

    def select_task(self, belief_state, action_memory) -> Task | None:
        del action_memory

        position = _position2d(getattr(belief_state, "position", None))
        if position is None:
            return IdleTask()

        tick = _tick(belief_state)
        target = belief_state.extra.get(_DECOY_TARGET_KEY)
        target_tick = int(belief_state.extra.get(_DECOY_TARGET_TICK_KEY, -DECOY_REPICK_TICKS))
        if target is None or tick - target_tick >= DECOY_REPICK_TICKS:
            target = _random_room_target(belief_state)
            belief_state.extra[_DECOY_TARGET_KEY] = target
            belief_state.extra[_DECOY_TARGET_TICK_KEY] = tick

        return _move_to(target)

    def mode_enter(self, belief_state, action_memory) -> None:
        del action_memory
        _clear_mode_completion(belief_state)
        belief_state.extra.pop(_DECOY_TARGET_KEY, None)
        belief_state.extra.pop(_DECOY_TARGET_TICK_KEY, None)

    def mode_switch_cleanup(
        self,
        belief_state,
        action_memory,
        new_mode_directive: ModeDirective,
    ) -> None:
        del action_memory, new_mode_directive
        belief_state.extra.pop(_DECOY_TARGET_KEY, None)
        belief_state.extra.pop(_DECOY_TARGET_TICK_KEY, None)


class RelayIntelligenceMode(Mode):
    """Open room chat, send one short status ping, then finish."""

    params_type = ModeParams
    params: RelayIntelligenceParams | ModeParams = RelayIntelligenceParams()

    def select_task(self, belief_state, action_memory) -> Task | None:
        del action_memory

        if belief_state.extra.get(_RELAY_SENT_KEY):
            _complete_mode(belief_state)
            return IdleTask()

        if getattr(belief_state, "view", None) is not View.GLOBAL_CHAT:
            return OpenGlobalChatTask()

        belief_state.extra[_RELAY_SENT_KEY] = True
        _complete_mode(belief_state)
        message = getattr(self.params, "message", "STATUS") or "STATUS"
        channel = getattr(self.params, "channel", "global") or "global"
        return SendMessageTask(text=message, channel=channel)

    def mode_enter(self, belief_state, action_memory) -> None:
        del action_memory
        _clear_mode_completion(belief_state)
        belief_state.extra.pop(_RELAY_SENT_KEY, None)

    def mode_switch_cleanup(
        self,
        belief_state,
        action_memory,
        new_mode_directive: ModeDirective,
    ) -> None:
        del action_memory, new_mode_directive
        belief_state.extra.pop(_RELAY_SENT_KEY, None)


class AnnounceIdentityMode(Mode):
    """Broadcast a truthful self role claim once for partner discovery."""

    params_type = AnnounceIdentityParams
    params: AnnounceIdentityParams | ModeParams = AnnounceIdentityParams()

    def select_task(self, belief_state, action_memory) -> Task | None:
        del action_memory

        message = getattr(self.params, "message", "") or ""
        key = (getattr(belief_state, "round", 0) or 0, message)
        if belief_state.extra.get(_IDENTITY_ANNOUNCED_KEY) == key:
            _complete_mode(belief_state)
            return IdleTask()

        if getattr(belief_state, "view", None) not in {View.PLAYING, View.GLOBAL_CHAT}:
            _complete_mode(belief_state)
            return IdleTask()

        if getattr(belief_state, "cooldowns", {}).get("chat", 0) > 0:
            return IdleTask()

        if not message:
            _complete_mode(belief_state)
            return IdleTask()

        belief_state.extra[_IDENTITY_ANNOUNCED_KEY] = key
        _complete_mode(belief_state)
        return SendMessageTask(text=message, channel="global")

    def mode_enter(self, belief_state, action_memory) -> None:
        del action_memory
        _clear_mode_completion(belief_state)

    def mode_switch_cleanup(
        self,
        belief_state,
        action_memory,
        new_mode_directive: ModeDirective,
    ) -> None:
        del belief_state, action_memory, new_mode_directive


class CheckInfoScreenMode(Mode):
    """Open the info screen briefly so belief update can ingest it."""

    params_type = ModeParams

    def select_task(self, belief_state, action_memory) -> Task | None:
        view = getattr(belief_state, "view", None)
        if view is View.GLOBAL_CHAT:
            return CloseViewTask()
        if view is not View.INFO_SCREEN:
            return OpenInfoScreenTask()

        if getattr(action_memory, "ticks_active", 0) > INFO_SCREEN_WAIT_TICKS:
            _complete_mode(belief_state)
            return CloseViewTask()

        return IdleTask()

    def mode_enter(self, belief_state, action_memory) -> None:
        del action_memory
        _clear_mode_completion(belief_state)

    def mode_switch_cleanup(
        self,
        belief_state,
        action_memory,
        new_mode_directive: ModeDirective,
    ) -> None:
        del belief_state, action_memory, new_mode_directive


class ReviewGlobalChatMode(Mode):
    """Open global chat briefly so sender sprites disambiguate identity shouts."""

    params_type = ReviewGlobalChatParams
    params: ReviewGlobalChatParams | ModeParams = ReviewGlobalChatParams()

    def select_task(self, belief_state, action_memory) -> Task | None:
        view = getattr(belief_state, "view", None)
        if view is View.GLOBAL_CHAT:
            if getattr(action_memory, "ticks_active", 0) >= GLOBAL_CHAT_REVIEW_TICKS:
                _mark_global_chat_review_done(belief_state)
                _complete_mode(belief_state)
                return CloseViewTask()
            return IdleTask()

        if getattr(action_memory, "ticks_active", 0) >= GLOBAL_CHAT_REVIEW_TIMEOUT_TICKS:
            _mark_global_chat_review_done(belief_state)
            _complete_mode(belief_state)
            return IdleTask()

        if view in {View.PLAYING, View.HOSTAGE_SELECT, View.LEADER_SUMMIT}:
            return OpenGlobalChatTask()

        if view in {View.INFO_SCREEN, View.WHISPER}:
            return CloseViewTask()

        _complete_mode(belief_state)
        return IdleTask()

    def mode_enter(self, belief_state, action_memory) -> None:
        del action_memory
        _clear_mode_completion(belief_state)

    def mode_switch_cleanup(
        self,
        belief_state,
        action_memory,
        new_mode_directive: ModeDirective,
    ) -> None:
        del belief_state, action_memory, new_mode_directive


def _mark_global_chat_review_done(belief_state) -> None:
    belief_state.extra["_identity_global_chat_review_done"] = (
        getattr(belief_state, "round", 0) or 0
    )


def _complete_mode(belief_state) -> None:
    belief_state.extra[MODE_COMPLETE] = True


def _clear_mode_completion(belief_state) -> None:
    belief_state.extra.pop(MODE_COMPLETE, None)


def _tick(belief_state) -> int:
    return int(getattr(belief_state, "tick", 0) or 0)


def _position2d(position) -> tuple[int, int] | None:
    if position is None:
        return None
    return (int(position[0]), int(position[1]))


def _room_size(belief_state) -> tuple[int, int]:
    size = getattr(belief_state, "room_size", None) or (200, 200)
    return (max(1, int(size[0])), max(1, int(size[1])))


def _random_center_target(belief_state) -> tuple[int, int]:
    width, height = _room_size(belief_state)
    center_x = width // 2
    center_y = height // 2
    x = random.randint(center_x - HOLD_CENTER_RADIUS, center_x + HOLD_CENTER_RADIUS)
    y = random.randint(center_y - HOLD_CENTER_RADIUS, center_y + HOLD_CENTER_RADIUS)
    return (_clamp(x, 0, width), _clamp(y, 0, height))


def _random_room_target(belief_state) -> tuple[int, int]:
    width, height = _room_size(belief_state)
    return (random.randint(0, width), random.randint(0, height))


def _move_to(target: tuple[int, int]) -> MoveToTask:
    return MoveToTask(int(target[0]), int(target[1]))


def _distance_sq(a: tuple[int, int], b: tuple[int, int]) -> int:
    dx = int(a[0]) - int(b[0])
    dy = int(a[1]) - int(b[1])
    return dx * dx + dy * dy


def _self_candidate_index(belief_state) -> int:
    my_index = getattr(belief_state, "my_index", None)
    if my_index is None:
        return 0
    return max(0, int(my_index))


def _hostage_target_indices(selections) -> tuple[int, ...] | None:
    eligible_count = _eligible_count(selections)
    if eligible_count <= 0:
        return None

    selected_positions = set(_int_sequence(_state_value(selections, "selected_positions")))
    if _state_value(selections, "is_committed"):
        return ()

    target_total = _hostage_target_total(selections, eligible_count)
    remaining = max(0, target_total - len(selected_positions))
    if remaining == 0:
        return ()

    targets: list[int] = []
    for index in range(eligible_count):
        if index in selected_positions:
            continue
        targets.append(index)
        if len(targets) >= remaining:
            break
    return tuple(targets)


def _hostage_target_indices_for_player_ids(
    selections,
    requested: Sequence[PlayerID],
) -> tuple[int, ...] | None:
    if selections is None:
        return None

    selected_positions = set(_int_sequence(_state_value(selections, "selected_positions")))
    options = _hostage_player_id_positions(selections)
    if not options:
        return None

    targets: list[int] = []
    for player_id in requested:
        position = options.get((int(player_id[0]), int(player_id[1])))
        if position is None:
            return None
        if position in selected_positions:
            continue
        targets.append(position)
    return tuple(targets)


def _hostage_player_id_positions(selections) -> dict[PlayerID, int]:
    colors = list(_state_value(selections, "eligible_colors") or [])
    shapes = list(_state_value(selections, "eligible_shapes") or [])
    result: dict[PlayerID, int] = {}
    for position, color in enumerate(colors):
        shape = shapes[position] if position < len(shapes) else None
        shape_value = _shape_value(shape)
        if shape_value is None:
            continue
        result[(int(color), shape_value)] = position
    return result


def _eligible_count(selections) -> int:
    for name in ("eligible_colors", "candidates", "target_colors"):
        values = _state_value(selections, name)
        if values is None:
            continue
        try:
            count = len(values)
        except TypeError:
            continue
        if count > 0:
            return int(count)
    return 0


def _hostage_target_total(selections, eligible_count: int) -> int:
    count_label = _state_value(selections, "count_label")
    if isinstance(count_label, str):
        match = re.search(r"/\s*(\d+)", count_label)
        if match:
            return min(eligible_count, max(0, int(match.group(1))))

    explicit_count = _state_value(
        selections,
        "required_count",
        "hostage_count",
        "target_count",
        "count",
    )
    if explicit_count is not None:
        try:
            return min(eligible_count, max(0, int(explicit_count)))
        except (TypeError, ValueError):
            pass

    return min(2, eligible_count)


def _int_sequence(value) -> tuple[int, ...]:
    if value is None:
        return ()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        result: list[int] = []
        for item in value:
            try:
                result.append(int(item))
            except (TypeError, ValueError):
                continue
        return tuple(result)
    return ()


def _shape_value(shape) -> int | None:
    if shape is None:
        return None
    value = getattr(shape, "value", shape)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _time_waste_target(belief_state) -> PlayerID | None:
    target = belief_state.extra.get(_TIME_WASTE_TARGET_KEY)
    if target is not None and _knowledge_position(belief_state, target) is not None:
        return target

    candidates = list(_known_player_positions_from_knowledge(belief_state))
    if not candidates:
        return None

    target = random.choice(candidates)
    belief_state.extra[_TIME_WASTE_TARGET_KEY] = target
    return target


def _known_player_positions_from_knowledge(belief_state) -> list[PlayerID]:
    candidates: list[PlayerID] = []
    for player_id, record in _player_knowledge(belief_state).items():
        if _is_self_player_id(belief_state, player_id):
            continue
        if getattr(record, "last_seen_position", None) is not None:
            candidates.append(player_id)
    return candidates


def _knowledge_position(belief_state, player_id: PlayerID) -> tuple[int, int] | None:
    record = _player_knowledge(belief_state).get(player_id)
    if record is None:
        return None
    return _position2d(getattr(record, "last_seen_position", None))


def _player_knowledge(belief_state) -> dict[PlayerID, PlayerKnowledge]:
    knowledge = belief_state.extra.get(PLAYER_KNOWLEDGE)
    if isinstance(knowledge, dict):
        return knowledge
    return {}


def _is_self_player_id(belief_state, player_id: PlayerID) -> bool:
    my_color = getattr(belief_state, "my_color", None)
    my_shape = getattr(belief_state, "my_shape", None)
    if my_color is None or my_shape is None:
        return False
    shape = int(getattr(my_shape, "value", my_shape))
    return player_id == (int(my_color), shape)


def _state_value(source, *names: str):
    for name in names:
        if isinstance(source, dict) and name in source:
            return source[name]
        if hasattr(source, name):
            return getattr(source, name)
    return None


def _clamp(value: int, lower: int, upper: int) -> int:
    return min(max(value, lower), upper)


__all__ = [
    "HoldPositionParams",
    "SeekLeadershipParams",
    "HostageSelectParams",
    "SummitInteractParams",
    "CoordinateCrossRoomParams",
    "TimeWasteParams",
    "RelayIntelligenceParams",
    "AnnounceIdentityParams",
    "ReviewGlobalChatParams",
    "DecoyParams",
    "HoldPositionMode",
    "SeekLeadershipMode",
    "HostageSelectMode",
    "SummitInteractMode",
    "CoordinateCrossRoomMode",
    "UsurpMode",
    "TimeWasteMode",
    "DecoyMode",
    "RelayIntelligenceMode",
    "AnnounceIdentityMode",
    "ReviewGlobalChatMode",
    "CheckInfoScreenMode",
]
