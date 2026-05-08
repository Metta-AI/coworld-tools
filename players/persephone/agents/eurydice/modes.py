"""Basic Eurydice modes."""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from orpheus.idle import IdleMode, IdleTask
from orpheus.mode import Mode, ModeDirective, ModeParams
from orpheus.perception.types import View
from orpheus.task import ActCommand, Task
from orpheus.tasks import CreateWhisperTask, MoveToTask, RequestEntryTask

from agents.eurydice.ext_keys import (
    FOUND_TARGET,
    MODE_COMPLETE,
    PLAYER_KNOWLEDGE,
    SCOUT_STATE,
    STRATEGIC_STATE,
)
from agents.eurydice.knowledge import PlayerKnowledge
from agents.eurydice.pipeline import minimap_sighting_to_player_id, player_index_to_id
from agents.eurydice.types import (
    INTERACTION_RANGE,
    INTERACTION_RANGE_SQ,
    PlayerID,
    ProbeIntent,
    Team,
)


OVERWORLD_VIEWS: frozenset[View] = frozenset(
    {View.PLAYING, View.HOSTAGE_SELECT, View.WAITING_ENTRY}
)
WAYPOINT_REACHED_RANGE_SQ = 10 * 10
WAYPOINT_STALE_TICKS = 72


@dataclass
class ScoutState:
    current_waypoint: tuple[int, int] | None = None
    waypoint_set_tick: int = 0
    players_seen_this_sweep: set[PlayerID] = field(default_factory=set)


@dataclass(frozen=True)
class ProbeTargetParams(ModeParams):
    target: PlayerID = (0, 0)
    intent: ProbeIntent = ProbeIntent.GENERAL
    skip_color_exchange: bool = False
    max_approach_ticks: int = 96


@dataclass(frozen=True)
class ProbeSystematicParams(ModeParams):
    target_team: Team | None = None
    intent: ProbeIntent = ProbeIntent.GENERAL
    cautious: bool = False
    aggressive: bool = False


class EurydiceIdleMode(IdleMode):
    """Simple idle mode for non-interactive phases."""

    params_type = ModeParams

    def select_task(self, belief_state, action_memory) -> Task | None:
        return IdleTask()

    def mode_enter(self, belief_state, action_memory) -> None:
        pass

    def mode_switch_cleanup(
        self,
        belief_state,
        action_memory,
        new_mode_directive: ModeDirective,
    ) -> None:
        pass


class ScoutMode(Mode):
    """Wander the room until an unprobed nearby player is found."""

    params_type = ModeParams

    def select_task(self, belief_state, action_memory) -> Task | None:
        if getattr(belief_state, "view", None) not in OVERWORLD_VIEWS:
            return IdleTask()

        state = _scout_state(belief_state)
        position = _position2d(getattr(belief_state, "position", None))
        if position is None:
            return IdleTask()

        target = _nearby_unprobed_player(belief_state, position, state)
        if target is not None:
            _complete_mode(belief_state, found_target=target)
            return IdleTask()

        waypoint = state.current_waypoint
        if (
            waypoint is None
            or _distance_sq(position, waypoint) < WAYPOINT_REACHED_RANGE_SQ
            or getattr(belief_state, "tick", 0) - state.waypoint_set_tick
            > WAYPOINT_STALE_TICKS
        ):
            waypoint = _random_waypoint(belief_state)
            state.current_waypoint = waypoint
            state.waypoint_set_tick = getattr(belief_state, "tick", 0)
            state.players_seen_this_sweep.clear()

        return _move_to(waypoint)

    def mode_enter(self, belief_state, action_memory) -> None:
        _clear_mode_completion(belief_state)
        belief_state.extra[SCOUT_STATE] = ScoutState()

    def mode_switch_cleanup(
        self,
        belief_state,
        action_memory,
        new_mode_directive: ModeDirective,
    ) -> None:
        belief_state.extra.pop(SCOUT_STATE, None)


class ProbeTargetMode(Mode):
    """Approach one player and initiate or request a whisper."""

    params_type = ModeParams  # Accept bare ModeParams from evaluators
    params: ProbeTargetParams | ModeParams = ProbeTargetParams()

    def select_task(self, belief_state, action_memory) -> Task | None:
        if getattr(belief_state, "view", None) not in OVERWORLD_VIEWS:
            return IdleTask()

        params = _probe_target_params(self.params, belief_state)
        if (
            getattr(action_memory, "ticks_active", 0)
            > params.max_approach_ticks
        ):
            _complete_mode(belief_state, found_target=None)
            return IdleTask()

        return _probe_target_task(
            belief_state,
            params.target,
            max_approach_ticks=params.max_approach_ticks,
        )

    def mode_enter(self, belief_state, action_memory) -> None:
        _clear_mode_completion(belief_state)

    def mode_switch_cleanup(
        self,
        belief_state,
        action_memory,
        new_mode_directive: ModeDirective,
    ) -> None:
        pass


class ProbeSystematicMode(Mode):
    """Pick the best available probe target and initiate contact."""

    params_type = ModeParams  # Accept bare ModeParams from evaluators
    params: ProbeSystematicParams | ModeParams = ProbeSystematicParams()

    def select_task(self, belief_state, action_memory) -> Task | None:
        if getattr(belief_state, "view", None) not in OVERWORLD_VIEWS:
            return IdleTask()

        target = self._select_target(belief_state)
        if target is None:
            # No visible targets -- wander to explore (don't give up).
            # ScoutMode checks for nearby unprobed players while moving,
            # so we reuse its waypoint logic to keep the agent active.
            position = _position2d(getattr(belief_state, "position", None))
            if position is None:
                return IdleTask()
            # Check for nearby unprobed players (same as scout)
            state = _scout_state(belief_state)
            found = _nearby_unprobed_player(belief_state, position, state)
            if found is not None:
                _complete_mode(belief_state, found_target=found)
                return IdleTask()
            # Wander toward a random waypoint
            waypoint = state.current_waypoint
            if (
                waypoint is None
                or _distance_sq(position, waypoint) < WAYPOINT_REACHED_RANGE_SQ
                or getattr(belief_state, "tick", 0) - state.waypoint_set_tick
                > WAYPOINT_STALE_TICKS
            ):
                waypoint = _random_waypoint(belief_state)
                state.current_waypoint = waypoint
                state.waypoint_set_tick = getattr(belief_state, "tick", 0)
            return _move_to(waypoint)

        return _probe_target_task(belief_state, target)

    def mode_enter(self, belief_state, action_memory) -> None:
        _clear_mode_completion(belief_state)

    def mode_switch_cleanup(
        self,
        belief_state,
        action_memory,
        new_mode_directive: ModeDirective,
    ) -> None:
        pass

    def _select_target(self, belief_state) -> PlayerID | None:
        best_target: PlayerID | None = None
        best_score = -1.0
        position = _position2d(getattr(belief_state, "position", None))

        for player_id, player_position in _known_player_positions(belief_state).items():
            score = self.score_target(belief_state, player_id, player_position, position)
            if score > best_score:
                best_target = player_id
                best_score = score

        if best_target is None or best_score < 0:
            return None
        return best_target

    def score_target(
        self,
        belief_state,
        player_id: PlayerID,
        target_position: tuple[int, int],
        self_position: tuple[int, int] | None = None,
    ) -> float:
        knowledge = _player_knowledge(belief_state).get(player_id)

        if (
            knowledge is not None
            and knowledge.role is not None
            and knowledge.has_exchanged_roles_with_us
        ):
            return -1.0

        score = 0.0
        if knowledge is None or knowledge.times_interacted == 0:
            score += 50.0

        target_team = getattr(self.params, "target_team", None)
        if target_team is not None:
            if knowledge is not None and knowledge.team == target_team:
                score += 30.0
            elif knowledge is not None and knowledge.team is not None:
                score -= 100.0

        if self_position is not None:
            distance = _distance(self_position, target_position)
            score += max(0.0, 40.0 - distance * 0.5)

        flags = knowledge.behavioral_flags if knowledge is not None else set()
        if (
            "exchange_eager" in flags
            or (knowledge is not None and knowledge.exchange_eagerness > 0)
        ):
            score += 20.0
        if (
            "refuses_role_exchange" in flags
            or (knowledge is not None and knowledge.refused_role_exchange)
        ):
            score += 15.0

        if (
            knowledge is not None
            and knowledge.times_interacted > 0
            and knowledge.last_interaction_tick > 0
            and getattr(belief_state, "tick", 0) - knowledge.last_interaction_tick < 360
        ):
            score -= 40.0

        return score


def _probe_target_params(
    params: ProbeTargetParams | ModeParams,
    belief_state,
) -> ProbeTargetParams:
    if isinstance(params, ProbeTargetParams) and params.target != (0, 0):
        return params

    fallback = _strategic_target(belief_state) or _best_unprobed_target(belief_state)
    if fallback is None:
        return ProbeTargetParams()
    if isinstance(params, ProbeTargetParams):
        return ProbeTargetParams(
            target=fallback,
            intent=params.intent,
            skip_color_exchange=params.skip_color_exchange,
            max_approach_ticks=params.max_approach_ticks,
        )
    return ProbeTargetParams(target=fallback)


def _strategic_target(belief_state) -> PlayerID | None:
    state = belief_state.extra.get(STRATEGIC_STATE) or getattr(
        belief_state, "inferences", {}
    ).get(STRATEGIC_STATE)
    for attr in ("key_partner_id", "enemy_key_role_id", "verified_ally"):
        target = getattr(state, attr, None)
        if target is not None:
            return target
    players_unprobed = getattr(state, "players_unprobed_in_room", None)
    if players_unprobed:
        return players_unprobed[0]
    return None


def _best_unprobed_target(belief_state) -> PlayerID | None:
    knowledge = _player_knowledge(belief_state)
    for player_id in _known_player_positions(belief_state):
        record = knowledge.get(player_id)
        if record is None or record.times_interacted == 0:
            return player_id
    return None


def _probe_target_task(
    belief_state,
    target: PlayerID,
    max_approach_ticks: int | None = None,
) -> Task:
    del max_approach_ticks

    position = _position2d(getattr(belief_state, "position", None))
    if position is None:
        return IdleTask()

    found = _find_player_for_target(belief_state, target)
    if found is None:
        target_position = _last_known_position(belief_state, target)
        if target_position is None:
            _complete_mode(belief_state, found_target=None)
            return IdleTask()

        if _distance_sq(position, target_position) < INTERACTION_RANGE_SQ:
            _complete_mode(belief_state, found_target=target)
            return CreateWhisperTask()

        return _move_to(target_position)

    target_index, player, target_position = found
    if _distance_sq(position, target_position) < INTERACTION_RANGE_SQ:
        _complete_mode(belief_state, found_target=target)
        if getattr(player, "last_seen_in_whisper", None) == getattr(
            belief_state, "tick", 0
        ):
            return RequestEntryTask(target_index)
        return CreateWhisperTask()

    return _move_to(target_position)


def _scout_state(belief_state) -> ScoutState:
    state = belief_state.extra.get(SCOUT_STATE)
    if not isinstance(state, ScoutState):
        state = ScoutState()
        belief_state.extra[SCOUT_STATE] = state
    return state


def _nearby_unprobed_player(
    belief_state,
    position: tuple[int, int],
    state: ScoutState,
) -> PlayerID | None:
    knowledge = _player_knowledge(belief_state)
    for player_id, player_position in _known_player_positions(belief_state).items():
        state.players_seen_this_sweep.add(player_id)
        if _distance_sq(position, player_position) >= INTERACTION_RANGE_SQ:
            continue

        player_knowledge = knowledge.get(player_id)
        if player_knowledge is None or player_knowledge.times_interacted == 0:
            return player_id

    return None


def _find_player_for_target(
    belief_state,
    target: PlayerID,
) -> tuple[int, object, tuple[int, int]] | None:
    target_color = target[0]
    color_match: tuple[int, object, tuple[int, int]] | None = None

    for index, player in getattr(belief_state, "players", {}).items():
        if index == getattr(belief_state, "my_index", None):
            continue
        player_position = _position2d(getattr(player, "position", None))
        if player_position is None:
            continue
        player_id = player_index_to_id(index, belief_state)
        if player_id == target:
            return index, player, player_position
        if (
            player_id is not None
            and player_id[0] == target_color
            and color_match is None
        ):
            color_match = (index, player, player_position)

    return color_match


def _last_known_position(
    belief_state,
    target: PlayerID,
) -> tuple[int, int] | None:
    knowledge = _player_knowledge(belief_state)
    record = knowledge.get(target)
    if record is not None and record.last_seen_position is not None:
        return record.last_seen_position

    for player_id, other_record in knowledge.items():
        if player_id[0] != target[0] or _is_self_player_id(belief_state, player_id):
            continue
        if other_record.last_seen_position is not None:
            return other_record.last_seen_position

    current_tick = getattr(belief_state, "tick", None)
    for sighting in getattr(belief_state, "minimap_sightings", []):
        if getattr(sighting, "tick", None) != current_tick:
            continue
        player_id = minimap_sighting_to_player_id(sighting, belief_state)
        if player_id == target or (player_id is not None and player_id[0] == target[0]):
            return tuple(sighting.position)

    return None


def _known_player_positions(belief_state) -> dict[PlayerID, tuple[int, int]]:
    """Return best known positions from knowledge, minimap, then direct sightings."""
    positions: dict[PlayerID, tuple[int, int]] = {}

    for player_id, record in _player_knowledge(belief_state).items():
        if _is_self_player_id(belief_state, player_id):
            continue
        if record.last_seen_position is not None:
            positions[player_id] = record.last_seen_position

    current_tick = getattr(belief_state, "tick", None)
    for sighting in getattr(belief_state, "minimap_sightings", []):
        if getattr(sighting, "tick", None) != current_tick:
            continue
        player_id = minimap_sighting_to_player_id(sighting, belief_state)
        if player_id is None or _is_self_player_id(belief_state, player_id):
            continue
        positions[player_id] = tuple(sighting.position)

    for index, player in getattr(belief_state, "players", {}).items():
        if index == getattr(belief_state, "my_index", None):
            continue
        player_position = _position2d(getattr(player, "position", None))
        if player_position is None:
            continue
        player_id = player_index_to_id(index, belief_state)
        if player_id is not None and not _is_self_player_id(belief_state, player_id):
            positions[player_id] = player_position

    return positions


def _is_self_player_id(belief_state, player_id: PlayerID) -> bool:
    my_index = getattr(belief_state, "my_index", None)
    if my_index is not None:
        return player_id == player_index_to_id(my_index, belief_state)

    my_color = getattr(belief_state, "my_color", None)
    my_shape = getattr(belief_state, "my_shape", None)
    if my_color is None or my_shape is None:
        return False
    shape = int(getattr(my_shape, "value", my_shape))
    return player_id == (my_color, shape)


def _unprobed_known_positions(belief_state) -> list[tuple[int, int]]:
    knowledge = _player_knowledge(belief_state)
    positions: list[tuple[int, int]] = []
    for player_id, position in _known_player_positions(belief_state).items():
        record = knowledge.get(player_id)
        if record is None or record.times_interacted == 0:
            positions.append(position)
    return positions


def _player_knowledge(belief_state) -> dict[PlayerID, PlayerKnowledge]:
    knowledge = belief_state.extra.get(PLAYER_KNOWLEDGE)
    if isinstance(knowledge, dict):
        return knowledge
    return {}


def _random_waypoint(belief_state) -> tuple[int, int]:
    known_positions = _unprobed_known_positions(belief_state)
    if known_positions:
        return random.choice(known_positions)

    room_size = getattr(belief_state, "room_size", None) or (200, 200)
    width, height = room_size
    return (random.randint(0, max(0, width)), random.randint(0, max(0, height)))


def _position2d(position) -> tuple[int, int] | None:
    if position is None:
        return None
    return int(position[0]), int(position[1])


def _distance_sq(a: tuple[int, int], b: tuple[int, int]) -> int:
    dx = a[0] - b[0]
    dy = a[1] - b[1]
    return dx * dx + dy * dy


def _distance(a: tuple[int, int], b: tuple[int, int]) -> float:
    return _distance_sq(a, b) ** 0.5


def _move_to(target: tuple[int, int]) -> MoveToTask:
    return MoveToTask(target[0], target[1])


def _complete_mode(
    belief_state,
    found_target: PlayerID | None = None,
) -> None:
    belief_state.extra[MODE_COMPLETE] = True
    belief_state.extra[FOUND_TARGET] = found_target


def _clear_mode_completion(belief_state) -> None:
    belief_state.extra.pop(MODE_COMPLETE, None)
    belief_state.extra.pop(FOUND_TARGET, None)


__all__ = [
    "ScoutState",
    "ProbeTargetParams",
    "ProbeSystematicParams",
    "EurydiceIdleMode",
    "ScoutMode",
    "ProbeTargetMode",
    "ProbeSystematicMode",
]
