"""Basic Eurydice modes."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import ClassVar

from orpheus.idle import IdleMode, IdleTask
from orpheus.logging import LogLevel
from orpheus.mode import Mode, ModeDirective, ModeParams
from orpheus.perception.types import View
from orpheus.task import ActCommand, Task
from orpheus.tasks import (
    AcceptRoleExchangeTask,
    CancelEntryTask,
    GrantEntryTask,
    InitiateWhisperTask,
    MoveAndInitiateWhisperTask,
    MoveToTask,
    OfferRoleExchangeTask,
    RendezvousEntrySweepTask,
)
from orpheus.types import BUTTON_A

from agents.eurydice.ext_keys import (
    FOUND_TARGET,
    MODE_COMPLETE,
    PLAYER_KNOWLEDGE,
    PROBE_FAILURES,
    PROBE_STATE,
    SCOUT_STATE,
    STRATEGIC_STATE,
)
from agents.eurydice.knowledge import PlayerKnowledge
from agents.eurydice.log import logger
from agents.eurydice.pipeline import minimap_sighting_to_player_id, player_index_to_id
from agents.eurydice.types import (
    INTERACTION_RANGE,
    INTERACTION_RANGE_SQ,
    PlayerID,
    ProbeIntent,
    Role,
    Team,
)


SCOUT_VIEWS: frozenset[View] = frozenset({View.PLAYING})
PROBE_VIEWS: frozenset[View] = frozenset({View.PLAYING, View.WAITING_ENTRY})
WAYPOINT_REACHED_RANGE_SQ = 10 * 10
WAYPOINT_STALE_TICKS = 72
WHISPER_RECENCY_TICKS = 72
REQUEST_ENTRY_RANGE = INTERACTION_RANGE + 12
REQUEST_ENTRY_RANGE_SQ = REQUEST_ENTRY_RANGE * REQUEST_ENTRY_RANGE
SERVER_ENTRY_RANGE = 20
SERVER_ENTRY_RANGE_SQ = SERVER_ENTRY_RANGE * SERVER_ENTRY_RANGE
CREATE_WHISPER_CLEARANCE = INTERACTION_RANGE + 6
CREATE_WHISPER_CLEARANCE_SQ = CREATE_WHISPER_CLEARANCE * CREATE_WHISPER_CLEARANCE
KEY_RENDEZVOUS_REACHED_RANGE = 8
KEY_RENDEZVOUS_REACHED_RANGE_SQ = (
    KEY_RENDEZVOUS_REACHED_RANGE * KEY_RENDEZVOUS_REACHED_RANGE
)
KEY_RENDEZVOUS_PARTNER_RANGE = INTERACTION_RANGE + 12
KEY_RENDEZVOUS_PARTNER_RANGE_SQ = (
    KEY_RENDEZVOUS_PARTNER_RANGE * KEY_RENDEZVOUS_PARTNER_RANGE
)
KEY_RENDEZVOUS_OPEN_RANGE = SERVER_ENTRY_RANGE
KEY_RENDEZVOUS_OPEN_RANGE_SQ = (
    KEY_RENDEZVOUS_OPEN_RANGE * KEY_RENDEZVOUS_OPEN_RANGE
)
KEY_RENDEZVOUS_STALE_WHISPER_RANGE = (
    KEY_RENDEZVOUS_REACHED_RANGE + REQUEST_ENTRY_RANGE
)
KEY_RENDEZVOUS_STALE_WHISPER_RANGE_SQ = (
    KEY_RENDEZVOUS_STALE_WHISPER_RANGE * KEY_RENDEZVOUS_STALE_WHISPER_RANGE
)
KEY_REQUESTER_SWEEP_RADIUS = KEY_RENDEZVOUS_PARTNER_RANGE
KEY_REQUESTER_VISIBLE_ENTRY_RANGE = 4
KEY_REQUESTER_VISIBLE_ENTRY_RANGE_SQ = (
    KEY_REQUESTER_VISIBLE_ENTRY_RANGE * KEY_REQUESTER_VISIBLE_ENTRY_RANGE
)
KEY_REQUESTER_BLIND_ENTRY_DELAY_TICKS = 120
KEY_REQUESTER_ROLES = frozenset({Role.HADES, Role.PERSEPHONE})
KEY_OPENER_ROLES = frozenset({Role.CERBERUS, Role.DEMETER})
KEY_SHARED_RENDEZVOUS = (54, 66)
KEY_RENDEZVOUS_POINTS: dict[Role, tuple[int, int]] = {
    Role.HADES: KEY_SHARED_RENDEZVOUS,
    Role.CERBERUS: KEY_SHARED_RENDEZVOUS,
    Role.PERSEPHONE: KEY_SHARED_RENDEZVOUS,
    Role.DEMETER: KEY_SHARED_RENDEZVOUS,
}
PROBE_STAGGER_MAX_TICKS = 72
PROBE_ENTRY_TIMEOUT_TICKS = 72
KEY_PROBE_ENTRY_TIMEOUT_TICKS = 144
PROBE_FAILURE_CAP_PER_TARGET_ROUND = 1
_PROBE_STAGGER_KEY = "_eurydice_probe_stagger"
_KEY_RENDEZVOUS_LOG_KEY = "_eurydice_key_rendezvous_log_signature"
BLIND_KEY_CREATE_SETTLE_TICKS = 8
BLIND_KEY_GRANT_TICKS = 12
BLIND_KEY_OFFER_TICKS = 72
BLIND_KEY_REQUESTER_OFFER_SETTLE_TICKS = 6
BLIND_KEY_REQUESTER_OFFER_TICKS = 48
BLIND_KEY_IDLE_TICKS = 4
INTRO_ROSTER_DWELL_TICKS = 12
INTRO_PANEL_DWELL_TICKS = 6
INTRO_PANEL_TIMEOUT_TICKS = 48
BLIND_KEY_MENU_VIEWS: frozenset[View] = frozenset({View.PLAYING, View.WHISPER})
BLIND_KEY_FIRST_GRANT_TICKS = KEY_REQUESTER_BLIND_ENTRY_DELAY_TICKS


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
    request_only: bool = False
    open_in_place: bool = False


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
        if getattr(belief_state, "view", None) in {
            View.ROSTER_REVEAL,
            View.ROLE_REVEAL,
        }:
            return IntroAdvanceTask()
        return IdleTask()

    def mode_enter(self, belief_state, action_memory) -> None:
        pass


class IntroAdvanceTask(Task):
    """Advance intro panels after their information has had time to parse."""

    valid_views: set[View] = {View.ROSTER_REVEAL, View.ROLE_REVEAL}

    def select_action(self, belief_state, action_memory) -> ActCommand:
        signature = (
            getattr(belief_state, "view", None),
            getattr(belief_state, "role_reveal_panel_index", None),
        )
        if getattr(action_memory, "intro_signature", None) != signature:
            action_memory.intro_signature = signature
            action_memory.intro_signature_tick = getattr(belief_state, "tick", 0)
            action_memory.intro_pressed = False
            action_memory.pressed_last_tick = False

        if getattr(action_memory, "intro_pressed", False):
            return ActCommand()

        dwell_ticks = (
            getattr(belief_state, "tick", 0)
            - getattr(action_memory, "intro_signature_tick", 0)
        )
        if not _intro_panel_ready(belief_state, dwell_ticks):
            return ActCommand()

        button = action_memory.step_button_press(BUTTON_A)
        if button:
            action_memory.intro_pressed = True
        return ActCommand(buttons=button)


def _intro_panel_ready(belief_state, dwell_ticks: int) -> bool:
    view = getattr(belief_state, "view", None)
    if view is View.ROSTER_REVEAL:
        return dwell_ticks >= INTRO_ROSTER_DWELL_TICKS
    if view is not View.ROLE_REVEAL:
        return False

    panel_index = getattr(belief_state, "role_reveal_panel_index", None)
    if panel_index == 1:
        parsed = (
            getattr(belief_state, "my_role", None) is not None
            and getattr(belief_state, "my_team", None) is not None
            and getattr(belief_state, "my_room", None) is not None
        )
        return dwell_ticks >= INTRO_PANEL_DWELL_TICKS and (
            parsed or dwell_ticks >= INTRO_PANEL_TIMEOUT_TICKS
        )
    if panel_index == 2:
        parsed = (
            bool(getattr(belief_state, "match_roles", []))
            or bool(getattr(belief_state, "missing_roles", []))
            or bool(getattr(belief_state, "echo_substitutions", []))
            or getattr(belief_state, "spy_in_game_config", None) is not None
        )
        return dwell_ticks >= INTRO_PANEL_DWELL_TICKS and (
            parsed or dwell_ticks >= INTRO_PANEL_TIMEOUT_TICKS
        )
    if panel_index == 3:
        parsed = bool(getattr(belief_state, "round_schedule", []))
        return dwell_ticks >= INTRO_PANEL_DWELL_TICKS and (
            parsed or dwell_ticks >= INTRO_PANEL_TIMEOUT_TICKS
        )
    return dwell_ticks >= INTRO_PANEL_TIMEOUT_TICKS

    def mode_switch_cleanup(
        self,
        belief_state,
        action_memory,
        new_mode_directive: ModeDirective,
    ) -> None:
        pass


@dataclass(frozen=True)
class BlindGrantEntryTask(Task):
    """Run the grant-entry menu sequence when whisper pixels are unavailable."""

    valid_views: ClassVar[frozenset[View]] = BLIND_KEY_MENU_VIEWS

    def select_action(self, belief_state, action_memory) -> ActCommand:
        command = GrantEntryTask().select_action(belief_state, action_memory)
        if (
            command.buttons == 0
            and int(getattr(action_memory, "sequence_step", 0)) >= 3
            and not getattr(action_memory, "menu_button_active", False)
        ):
            return ActCommand(buttons=action_memory.step_button_press(BUTTON_A))
        return command


@dataclass(frozen=True)
class BlindOfferRoleExchangeTask(Task):
    """Offer a role exchange when server whisper state is inferred but hidden."""

    valid_views: ClassVar[frozenset[View]] = BLIND_KEY_MENU_VIEWS

    def select_action(self, belief_state, action_memory) -> ActCommand:
        return OfferRoleExchangeTask().select_action(belief_state, action_memory)


@dataclass(frozen=True)
class BlindAcceptRoleExchangeTask(Task):
    """Accept the first role offer when server whisper state is inferred."""

    player_index: int = 0
    valid_views: ClassVar[frozenset[View]] = BLIND_KEY_MENU_VIEWS

    def select_action(self, belief_state, action_memory) -> ActCommand:
        return AcceptRoleExchangeTask(self.player_index).select_action(
            belief_state,
            action_memory,
        )


def _clear_blind_menu_sequence(action_memory) -> None:
    for name in (
        "menu_step",
        "sequence_step",
        "menu_open_attempted",
        "menu_category_index",
        "menu_item_index",
        "menu_target_index",
        "pressed_last_tick",
    ):
        if hasattr(action_memory, name):
            delattr(action_memory, name)


class ScoutMode(Mode):
    """Wander the room until an unprobed nearby player is found."""

    params_type = ModeParams

    def select_task(self, belief_state, action_memory) -> Task | None:
        if getattr(belief_state, "view", None) not in SCOUT_VIEWS:
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
        if getattr(belief_state, "view", None) not in PROBE_VIEWS:
            return IdleTask()

        params = _probe_target_params(self.params, belief_state)
        if _target_failed_this_round(
            belief_state,
            params.target,
        ) and not _should_retry_failed_target(params):
            _complete_mode(belief_state, found_target=None)
            return IdleTask()
        if (
            getattr(action_memory, "ticks_active", 0)
            > params.max_approach_ticks
        ):
            InitiateWhisperTask.clear_state(belief_state)
            _record_probe_failed(
                belief_state,
                params.target,
                reason="approach_timeout",
            )
            _complete_mode(belief_state, found_target=None)
            if _should_retry_failed_target(params):
                action_memory.clear()
            return IdleTask()

        _record_probe_target_selected(belief_state, params.target)
        return _probe_target_task(
            belief_state,
            params.target,
            max_approach_ticks=params.max_approach_ticks,
            request_only=params.request_only,
            open_in_place=params.open_in_place,
            intent=params.intent,
            skip_color_exchange=params.skip_color_exchange,
        )

    def mode_enter(self, belief_state, action_memory) -> None:
        _clear_mode_completion(belief_state)
        InitiateWhisperTask.clear_state(belief_state)

    def mode_switch_cleanup(
        self,
        belief_state,
        action_memory,
        new_mode_directive: ModeDirective,
    ) -> None:
        InitiateWhisperTask.clear_state(belief_state)


class ProbeSystematicMode(Mode):
    """Pick the best available probe target and initiate contact."""

    params_type = ModeParams  # Accept bare ModeParams from evaluators
    params: ProbeSystematicParams | ModeParams = ProbeSystematicParams()

    def select_task(self, belief_state, action_memory) -> Task | None:
        if getattr(belief_state, "view", None) not in PROBE_VIEWS:
            return IdleTask()

        if getattr(belief_state, "view", None) is View.WAITING_ENTRY:
            return _waiting_entry_task(
                belief_state,
                target=_state_target(_active_probe_state(belief_state)),
            )

        if InitiateWhisperTask.has_failed(belief_state):
            state = _active_probe_state(belief_state)
            target = _state_target(state)
            if target is not None:
                _record_probe_failed(
                    belief_state,
                    target,
                    reason="initiate_timeout",
                )
            InitiateWhisperTask.clear_state(belief_state)

        key_rendezvous_task = _key_systematic_rendezvous_task(
            self.params,
            belief_state,
        )
        if key_rendezvous_task is not None:
            return key_rendezvous_task

        stagger_until = belief_state.extra.get(_PROBE_STAGGER_KEY, 0)
        if getattr(belief_state, "tick", 0) < stagger_until:
            return IdleTask()

        target = self._select_target(belief_state)
        if target is None:
            position = _position2d(getattr(belief_state, "position", None))
            if position is None:
                return IdleTask()
            state = _scout_state(belief_state)
            found = _nearby_unprobed_player(belief_state, position, state)
            if found is not None:
                _complete_mode(belief_state, found_target=found)
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
            return _move_to(waypoint)

        _record_probe_target_selected(belief_state, target)
        return _probe_target_task(
            belief_state,
            target,
            **_systematic_probe_options(self.params, belief_state),
        )

    def mode_enter(self, belief_state, action_memory) -> None:
        _clear_mode_completion(belief_state)
        InitiateWhisperTask.clear_state(belief_state)
        if _PROBE_STAGGER_KEY not in belief_state.extra:
            belief_state.extra[_PROBE_STAGGER_KEY] = (
                getattr(belief_state, "tick", 0) + random.randint(0, PROBE_STAGGER_MAX_TICKS)
            )

    def mode_switch_cleanup(
        self,
        belief_state,
        action_memory,
        new_mode_directive: ModeDirective,
    ) -> None:
        InitiateWhisperTask.clear_state(belief_state)

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

        if _target_failed_this_round(belief_state, player_id):
            return -1.0

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

        score += _stable_probe_tiebreaker(belief_state, player_id)

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

        if _target_recently_in_whisper(belief_state, player_id):
            score += 120.0

        return score


def _stable_probe_tiebreaker(belief_state, target: PlayerID) -> float:
    """Return a sub-point per-agent target preference for equal-score probes."""
    my_index = getattr(belief_state, "my_index", None)
    own_id = (
        player_index_to_id(my_index, belief_state)
        if isinstance(my_index, int)
        else None
    )
    own_color, own_shape = own_id or (0, 0)
    target_color, target_shape = target
    raw = (
        (own_color + 1) * (target_color + 3) * 31
        + (own_shape + 5) * (target_shape + 7) * 17
        + (own_color + own_shape + 11) * (target_color + target_shape + 13)
    ) % 997
    return raw / 997.0


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
            request_only=params.request_only,
            open_in_place=params.open_in_place,
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
    request_only: bool = False,
    open_in_place: bool = False,
    intent: ProbeIntent | None = None,
    skip_color_exchange: bool = False,
) -> Task:
    del max_approach_ticks

    if InitiateWhisperTask.has_failed(belief_state):
        InitiateWhisperTask.clear_state(belief_state)
        _record_probe_failed(
            belief_state,
            target,
            reason="initiate_timeout",
        )
        _complete_mode(belief_state, found_target=None)
        return IdleTask()

    if getattr(belief_state, "view", None) is View.WAITING_ENTRY:
        return _waiting_entry_task(belief_state, target=target)

    blind_key_task = _blind_key_exchange_menu_task(
        belief_state,
        _active_probe_state(belief_state),
        target=target,
        request_only=request_only,
        open_in_place=open_in_place,
    )
    if blind_key_task is not None:
        return blind_key_task

    position = _position2d(getattr(belief_state, "position", None))
    if position is None:
        return IdleTask()

    rendezvous = _key_rendezvous_point(belief_state, intent, skip_color_exchange)
    if request_only and rendezvous is not None:
        return _key_requester_rendezvous_task(
            belief_state,
            target,
            position,
            rendezvous,
            intent=intent,
            skip_color_exchange=skip_color_exchange,
        )
    if (
        open_in_place
        and rendezvous is not None
        and _distance_sq(position, rendezvous) > KEY_RENDEZVOUS_OPEN_RANGE_SQ
    ):
        _log_key_rendezvous_decision(
            belief_state,
            "move_to_rendezvous",
            target=target,
            position=position,
            rendezvous=rendezvous,
            intent=intent,
            skip_color_exchange=skip_color_exchange,
            open_in_place=open_in_place,
            request_only=request_only,
        )
        return _move_to(rendezvous)

    found = _find_player_for_target(belief_state, target)
    if found is None:
        target_position = _last_known_position(belief_state, target)
        if target_position is None and not open_in_place:
            if request_only:
                return _move_to(_random_waypoint(belief_state))
            _complete_mode(belief_state, found_target=None)
            return IdleTask()

        if (
            target_position is not None
            and _distance_sq(position, target_position) < INTERACTION_RANGE_SQ
        ):
            whisper_player = _find_nearby_target_whisper(
                belief_state,
                position,
                target,
            )
            if whisper_player is not None:
                wp_index, _wp_info, wp_position = whisper_player
                if _distance_sq(position, wp_position) <= SERVER_ENTRY_RANGE_SQ:
                    _record_probe_attempt_started(
                        belief_state,
                        target,
                        action="entry_requested",
                        intent=intent,
                        skip_color_exchange=skip_color_exchange,
                    )
                    return InitiateWhisperTask(target_index=wp_index, use_button_b=True)
                _record_probe_attempt_started(
                    belief_state,
                    target,
                    action="entry_requested",
                    intent=intent,
                    skip_color_exchange=skip_color_exchange,
                )
                return MoveAndInitiateWhisperTask(
                    wp_position[0],
                    wp_position[1],
                    target_index=wp_index,
                    use_button_b=True,
                    button_radius=(
                        KEY_REQUESTER_VISIBLE_ENTRY_RANGE
                        if skip_color_exchange and _probe_intent_name(intent) == "FIND_KEY_PARTNER"
                        else None
                    ),
                )
            if request_only:
                return IdleTask()
            safe_position = _safe_whisper_create_position(belief_state, position)
            if safe_position is not None:
                return _move_to(safe_position)
            _record_probe_attempt_started(
                belief_state,
                target,
                action="whisper_created",
                intent=intent,
                skip_color_exchange=skip_color_exchange,
            )
            return InitiateWhisperTask(target_index=None)

        if open_in_place and not request_only:
            safe_position = _safe_whisper_create_position(belief_state, position)
            if safe_position is not None:
                _log_key_rendezvous_decision(
                    belief_state,
                    "move_to_clearance",
                    target=target,
                    position=position,
                    rendezvous=rendezvous,
                    target_position=target_position,
                    destination=safe_position,
                    intent=intent,
                    skip_color_exchange=skip_color_exchange,
                    open_in_place=open_in_place,
                    request_only=request_only,
                )
                return _move_to(safe_position)
            _log_key_rendezvous_decision(
                belief_state,
                "create_whisper",
                target=target,
                position=position,
                rendezvous=rendezvous,
                target_position=target_position,
                intent=intent,
                skip_color_exchange=skip_color_exchange,
                open_in_place=open_in_place,
                request_only=request_only,
            )
            _record_probe_attempt_started(
                belief_state,
                target,
                action="whisper_created",
                intent=intent,
                skip_color_exchange=skip_color_exchange,
            )
            return InitiateWhisperTask(target_index=None)

        if target_position is not None:
            return _move_to(target_position)
        return IdleTask()

    target_index, player, target_position = found
    if _distance_sq(position, target_position) < INTERACTION_RANGE_SQ:
        current_tick = getattr(belief_state, "tick", 0)
        last_whisper_tick = getattr(player, "last_seen_in_whisper", None)
        target_in_whisper = (
            last_whisper_tick is not None
            and current_tick - last_whisper_tick < WHISPER_RECENCY_TICKS
        )
        if target_in_whisper:
            if _distance_sq(position, target_position) > SERVER_ENTRY_RANGE_SQ:
                _record_probe_attempt_started(
                    belief_state,
                    target,
                    action="entry_requested",
                    intent=intent,
                    skip_color_exchange=skip_color_exchange,
                )
                return MoveAndInitiateWhisperTask(
                    target_position[0],
                    target_position[1],
                    target_index=target_index,
                    use_button_b=True,
                    button_radius=(
                        KEY_REQUESTER_VISIBLE_ENTRY_RANGE
                        if skip_color_exchange and _probe_intent_name(intent) == "FIND_KEY_PARTNER"
                        else None
                    ),
                )
            _record_probe_attempt_started(
                belief_state,
                target,
                action="entry_requested",
                intent=intent,
                skip_color_exchange=skip_color_exchange,
            )
            return InitiateWhisperTask(target_index=target_index, use_button_b=True)
        if request_only:
            if _distance_sq(position, target_position) > SERVER_ENTRY_RANGE_SQ:
                _record_probe_attempt_started(
                    belief_state,
                    target,
                    action="entry_requested",
                    intent=intent,
                    skip_color_exchange=skip_color_exchange,
                )
                return MoveAndInitiateWhisperTask(
                    target_position[0],
                    target_position[1],
                    target_index=target_index,
                    use_button_b=True,
                    button_radius=(
                        KEY_REQUESTER_VISIBLE_ENTRY_RANGE
                        if skip_color_exchange and _probe_intent_name(intent) == "FIND_KEY_PARTNER"
                        else None
                    ),
                )
            if _nearby_recent_non_target_whisper(belief_state, position, target):
                if skip_color_exchange and _probe_intent_name(intent) == "FIND_KEY_PARTNER":
                    _record_probe_attempt_started(
                        belief_state,
                        target,
                        action="entry_requested",
                        intent=intent,
                        skip_color_exchange=skip_color_exchange,
                    )
                    return RendezvousEntrySweepTask(
                        target_position[0],
                        target_position[1],
                        target_index=target_index,
                        use_button_b=True,
                        radius=KEY_REQUESTER_SWEEP_RADIUS,
                    )
                return _move_to(target_position)
            if skip_color_exchange and _probe_intent_name(intent) == "FIND_KEY_PARTNER":
                _record_probe_attempt_started(
                    belief_state,
                    target,
                    action="entry_requested",
                    intent=intent,
                    skip_color_exchange=skip_color_exchange,
                )
                if _distance_sq(position, target_position) <= SERVER_ENTRY_RANGE_SQ:
                    return InitiateWhisperTask(
                        target_index=target_index,
                        use_button_b=True,
                    )
                return MoveAndInitiateWhisperTask(
                    target_position[0],
                    target_position[1],
                    target_index=target_index,
                    use_button_b=True,
                )
            return IdleTask()
        if open_in_place:
            safe_position = _safe_whisper_create_position(belief_state, position)
            if safe_position is not None:
                _log_key_rendezvous_decision(
                    belief_state,
                    "move_to_clearance",
                    target=target,
                    position=position,
                    rendezvous=rendezvous,
                    target_position=target_position,
                    destination=safe_position,
                    intent=intent,
                    skip_color_exchange=skip_color_exchange,
                    open_in_place=open_in_place,
                    request_only=request_only,
                )
                return _move_to(safe_position)
            _log_key_rendezvous_decision(
                belief_state,
                "create_whisper",
                target=target,
                position=position,
                rendezvous=rendezvous,
                target_position=target_position,
                intent=intent,
                skip_color_exchange=skip_color_exchange,
                open_in_place=open_in_place,
                request_only=request_only,
            )
            _record_probe_attempt_started(
                belief_state,
                target,
                action="whisper_created",
                intent=intent,
                skip_color_exchange=skip_color_exchange,
            )
            return InitiateWhisperTask(target_index=None, use_button_b=False)
        # Do not join an unrelated nearby whisper. If the selected target is
        # not in a whisper, create our own and let them request entry.
        safe_position = _safe_whisper_create_position(belief_state, position)
        if safe_position is not None:
            return _move_to(safe_position)
        _record_probe_attempt_started(
            belief_state,
            target,
            action="whisper_created",
            intent=intent,
            skip_color_exchange=skip_color_exchange,
        )
        return InitiateWhisperTask(target_index=target_index, use_button_b=False)

    if open_in_place and not request_only:
        if (
            rendezvous is not None
            and _distance_sq(position, rendezvous) > KEY_RENDEZVOUS_OPEN_RANGE_SQ
        ):
            _log_key_rendezvous_decision(
                belief_state,
                "move_to_rendezvous",
                target=target,
                position=position,
                rendezvous=rendezvous,
                target_position=target_position,
                intent=intent,
                skip_color_exchange=skip_color_exchange,
                open_in_place=open_in_place,
                request_only=request_only,
            )
            return _move_to(rendezvous)
        safe_position = _safe_whisper_create_position(belief_state, position)
        if safe_position is not None:
            _log_key_rendezvous_decision(
                belief_state,
                "move_to_clearance",
                target=target,
                position=position,
                rendezvous=rendezvous,
                target_position=target_position,
                destination=safe_position,
                intent=intent,
                skip_color_exchange=skip_color_exchange,
                open_in_place=open_in_place,
                request_only=request_only,
            )
            return _move_to(safe_position)
        _log_key_rendezvous_decision(
            belief_state,
            "create_whisper",
            target=target,
            position=position,
            rendezvous=rendezvous,
            target_position=target_position,
            intent=intent,
            skip_color_exchange=skip_color_exchange,
            open_in_place=open_in_place,
            request_only=request_only,
        )
        _record_probe_attempt_started(
            belief_state,
            target,
            action="whisper_created",
            intent=intent,
            skip_color_exchange=skip_color_exchange,
        )
        return InitiateWhisperTask(target_index=None, use_button_b=False)

    return _move_to(target_position)


def _key_systematic_rendezvous_task(
    params: ProbeSystematicParams | ModeParams,
    belief_state,
) -> Task | None:
    intent = getattr(params, "intent", ProbeIntent.GENERAL)
    if _probe_intent_name(intent) != "FIND_KEY_PARTNER":
        return None

    position = _position2d(getattr(belief_state, "position", None))
    rendezvous = _key_rendezvous_point(
        belief_state,
        intent,
        skip_color_exchange=True,
    )
    if position is None or rendezvous is None:
        return None

    role = _strategic_role(belief_state)
    _record_key_probe_selected(
        belief_state,
        intent=intent,
        skip_color_exchange=True,
    )
    distance_to_rendezvous = _distance_sq(position, rendezvous)
    blind_key_task = _blind_key_exchange_menu_task(
        belief_state,
        _active_probe_state(belief_state),
        target=_state_target(_active_probe_state(belief_state)),
        request_only=role in KEY_REQUESTER_ROLES,
        open_in_place=role in KEY_OPENER_ROLES,
    )
    if blind_key_task is not None:
        return blind_key_task

    if role in KEY_OPENER_ROLES:
        if distance_to_rendezvous > KEY_RENDEZVOUS_OPEN_RANGE_SQ:
            _log_key_rendezvous_decision(
                belief_state,
                "move_to_rendezvous",
                target=None,
                position=position,
                rendezvous=rendezvous,
                intent=intent,
                skip_color_exchange=True,
            )
            return _move_to(rendezvous)
        safe_position = _safe_whisper_create_position(belief_state, position)
        if safe_position is not None:
            _log_key_rendezvous_decision(
                belief_state,
                "move_to_clearance",
                target=None,
                position=position,
                rendezvous=rendezvous,
                destination=safe_position,
                intent=intent,
                skip_color_exchange=True,
            )
            return _move_to(safe_position)
        _log_key_rendezvous_decision(
            belief_state,
            "create_whisper",
            target=None,
            position=position,
            rendezvous=rendezvous,
            intent=intent,
            skip_color_exchange=True,
        )
        _record_key_probe_attempt_started(
            belief_state,
            target=None,
            action="whisper_created",
            intent=intent,
            skip_color_exchange=True,
        )
        return InitiateWhisperTask(target_index=None, use_button_b=False)

    if role in KEY_REQUESTER_ROLES:
        if distance_to_rendezvous > KEY_REQUESTER_VISIBLE_ENTRY_RANGE_SQ:
            _log_key_rendezvous_decision(
                belief_state,
                "move_to_rendezvous",
                target=None,
                position=position,
                rendezvous=rendezvous,
                intent=intent,
                skip_color_exchange=True,
                request_only=True,
            )
            return _move_to(rendezvous)
        if not _key_requester_blind_entry_ready(belief_state):
            _log_key_rendezvous_decision(
                belief_state,
                "wait_for_opener",
                target=None,
                position=position,
                rendezvous=rendezvous,
                intent=intent,
                skip_color_exchange=True,
                request_only=True,
            )
            return IdleTask()
        _log_key_rendezvous_decision(
            belief_state,
            "request_blind",
            target=None,
            position=position,
            rendezvous=rendezvous,
            intent=intent,
            skip_color_exchange=True,
            request_only=True,
        )
        _record_key_probe_attempt_started(
            belief_state,
            target=None,
            action="entry_requested",
            intent=intent,
            skip_color_exchange=True,
        )
        return RendezvousEntrySweepTask(
            rendezvous[0],
            rendezvous[1],
            target_index=None,
            use_button_b=True,
            radius=KEY_REQUESTER_SWEEP_RADIUS,
            button_radius=KEY_REQUESTER_VISIBLE_ENTRY_RANGE,
        )

    if distance_to_rendezvous > KEY_RENDEZVOUS_REACHED_RANGE_SQ:
        _log_key_rendezvous_decision(
            belief_state,
            "move_to_rendezvous",
            target=None,
            position=position,
            rendezvous=rendezvous,
            intent=intent,
            skip_color_exchange=True,
        )
        return _move_to(rendezvous)

    return None


def _key_requester_rendezvous_task(
    belief_state,
    target: PlayerID,
    position: tuple[int, int],
    rendezvous: tuple[int, int],
    *,
    intent: ProbeIntent | None,
    skip_color_exchange: bool,
) -> Task:
    confirmed_target = _is_confirmed_key_partner_target(belief_state, target)
    if not confirmed_target:
        if _distance_sq(position, rendezvous) > KEY_REQUESTER_VISIBLE_ENTRY_RANGE_SQ:
            _log_key_rendezvous_decision(
                belief_state,
                "move_to_rendezvous",
                target=target,
                position=position,
                rendezvous=rendezvous,
                intent=intent,
                skip_color_exchange=skip_color_exchange,
                request_only=True,
            )
            return _move_to(rendezvous)
        if not _key_requester_blind_entry_ready(belief_state):
            _log_key_rendezvous_decision(
                belief_state,
                "wait_for_opener",
                target=target,
                position=position,
                rendezvous=rendezvous,
                intent=intent,
                skip_color_exchange=skip_color_exchange,
                request_only=True,
            )
            return IdleTask()
        _log_key_rendezvous_decision(
            belief_state,
            "request_blind",
            target=target,
            position=position,
            rendezvous=rendezvous,
            intent=intent,
            skip_color_exchange=skip_color_exchange,
            request_only=True,
        )
        _record_key_probe_attempt_started(
            belief_state,
            target=None,
            action="entry_requested",
            intent=intent,
            skip_color_exchange=skip_color_exchange,
        )
        return RendezvousEntrySweepTask(
            rendezvous[0],
            rendezvous[1],
            target_index=None,
            use_button_b=True,
            radius=KEY_REQUESTER_SWEEP_RADIUS,
            button_radius=KEY_REQUESTER_VISIBLE_ENTRY_RANGE,
        )

    target_whisper = _find_nearby_target_whisper(
        belief_state,
        position,
        target,
    )
    if target_whisper is not None:
        target_index, _target_info, target_position = target_whisper
        if (
            _distance_sq(target_position, rendezvous)
            > KEY_RENDEZVOUS_STALE_WHISPER_RANGE_SQ
        ):
            _log_key_rendezvous_decision(
                belief_state,
                "request_rendezvous_stale_target_whisper",
                target=target,
                position=position,
                rendezvous=rendezvous,
                target_index=target_index,
                target_position=target_position,
                intent=intent,
                skip_color_exchange=skip_color_exchange,
                request_only=True,
            )
            if _distance_sq(position, rendezvous) > KEY_REQUESTER_VISIBLE_ENTRY_RANGE_SQ:
                return _move_to(rendezvous)
            _record_probe_attempt_started(
                belief_state,
                target,
                action="entry_requested",
                intent=intent,
                skip_color_exchange=skip_color_exchange,
            )
            return RendezvousEntrySweepTask(
                rendezvous[0],
                rendezvous[1],
                target_index=target_index,
                use_button_b=True,
                radius=KEY_REQUESTER_SWEEP_RADIUS,
                button_radius=KEY_REQUESTER_VISIBLE_ENTRY_RANGE,
            )
        if (
            _distance_sq(position, target_position)
            <= KEY_REQUESTER_VISIBLE_ENTRY_RANGE_SQ
        ):
            _log_key_rendezvous_decision(
                belief_state,
                "request_target_whisper",
                target=target,
                position=position,
                rendezvous=rendezvous,
                target_index=target_index,
                target_position=target_position,
                intent=intent,
                skip_color_exchange=skip_color_exchange,
                request_only=True,
            )
            _record_probe_attempt_started(
                belief_state,
                target,
                action="entry_requested",
                intent=intent,
                skip_color_exchange=skip_color_exchange,
            )
            return InitiateWhisperTask(target_index=target_index, use_button_b=True)
        _log_key_rendezvous_decision(
            belief_state,
            "move_to_target_whisper",
            target=target,
            position=position,
            rendezvous=rendezvous,
            target_index=target_index,
            target_position=target_position,
            intent=intent,
            skip_color_exchange=skip_color_exchange,
            request_only=True,
        )
        _record_probe_attempt_started(
            belief_state,
            target,
            action="entry_requested",
            intent=intent,
            skip_color_exchange=skip_color_exchange,
        )
        return MoveAndInitiateWhisperTask(
            target_position[0],
            target_position[1],
            target_index=target_index,
            use_button_b=True,
            button_radius=KEY_REQUESTER_VISIBLE_ENTRY_RANGE,
        )

    visible_target = _find_player_for_target(belief_state, target)
    if visible_target is not None:
        target_index, _target_info, target_position = visible_target
        if _distance_sq(target_position, rendezvous) <= KEY_RENDEZVOUS_PARTNER_RANGE_SQ:
            last_whisper_tick = getattr(_target_info, "last_seen_in_whisper", None)
            target_in_whisper = (
                last_whisper_tick is not None
                and getattr(belief_state, "tick", 0) - last_whisper_tick
                < WHISPER_RECENCY_TICKS
            )
            if not target_in_whisper:
                _log_key_rendezvous_decision(
                    belief_state,
                    "wait_for_visible_partner_opener",
                    target=target,
                    position=position,
                    rendezvous=rendezvous,
                    target_index=target_index,
                    target_position=target_position,
                    intent=intent,
                    skip_color_exchange=skip_color_exchange,
                    request_only=True,
                )
                if (
                    _distance_sq(position, target_position)
                    > KEY_REQUESTER_VISIBLE_ENTRY_RANGE_SQ
                ):
                    return _move_to(target_position)
                _log_key_rendezvous_decision(
                    belief_state,
                    "request_visible_partner_after_opener_wait",
                    target=target,
                    position=position,
                    rendezvous=rendezvous,
                    target_index=target_index,
                    target_position=target_position,
                    intent=intent,
                    skip_color_exchange=skip_color_exchange,
                    request_only=True,
                )
                _record_probe_attempt_started(
                    belief_state,
                    target,
                    action="entry_requested",
                    intent=intent,
                    skip_color_exchange=skip_color_exchange,
                )
                return InitiateWhisperTask(target_index=target_index, use_button_b=True)
            if _distance_sq(position, target_position) > SERVER_ENTRY_RANGE_SQ:
                _log_key_rendezvous_decision(
                    belief_state,
                    "move_to_visible_partner",
                    target=target,
                    position=position,
                    rendezvous=rendezvous,
                    target_index=target_index,
                    target_position=target_position,
                    intent=intent,
                    skip_color_exchange=skip_color_exchange,
                    request_only=True,
                )
                _record_probe_attempt_started(
                    belief_state,
                    target,
                    action="entry_requested",
                    intent=intent,
                    skip_color_exchange=skip_color_exchange,
                )
                return MoveAndInitiateWhisperTask(
                    target_position[0],
                    target_position[1],
                    target_index=target_index,
                    use_button_b=True,
                    button_radius=KEY_REQUESTER_VISIBLE_ENTRY_RANGE,
                )
            _log_key_rendezvous_decision(
                belief_state,
                "request_visible_partner",
                target=target,
                position=position,
                rendezvous=rendezvous,
                target_index=target_index,
                target_position=target_position,
                intent=intent,
                skip_color_exchange=skip_color_exchange,
                request_only=True,
            )
            _record_probe_attempt_started(
                belief_state,
                target,
                action="entry_requested",
                intent=intent,
                skip_color_exchange=skip_color_exchange,
            )
            return InitiateWhisperTask(target_index=target_index, use_button_b=True)

    if _distance_sq(position, rendezvous) > KEY_REQUESTER_VISIBLE_ENTRY_RANGE_SQ:
        _log_key_rendezvous_decision(
            belief_state,
            "move_to_rendezvous",
            target=target,
            position=position,
            rendezvous=rendezvous,
            intent=intent,
            skip_color_exchange=skip_color_exchange,
            request_only=True,
        )
        return _move_to(rendezvous)

    nearby_whisper = _find_nearby_recent_whisper(belief_state, position)
    if nearby_whisper is not None:
        whisper_index, _whisper_info, _whisper_position = nearby_whisper
        _log_key_rendezvous_decision(
            belief_state,
            "request_nearby_whisper",
            target=target,
            position=position,
            rendezvous=rendezvous,
            target_index=whisper_index,
            target_position=_whisper_position,
            intent=intent,
            skip_color_exchange=skip_color_exchange,
            request_only=True,
        )
        _record_probe_attempt_started(
            belief_state,
            target,
            action="entry_requested",
            intent=intent,
            skip_color_exchange=skip_color_exchange,
        )
        if (
            _distance_sq(position, _whisper_position)
            <= KEY_REQUESTER_VISIBLE_ENTRY_RANGE_SQ
        ):
            return InitiateWhisperTask(target_index=whisper_index, use_button_b=True)
        return MoveAndInitiateWhisperTask(
            _whisper_position[0],
            _whisper_position[1],
            target_index=whisper_index,
            use_button_b=True,
            button_radius=KEY_REQUESTER_VISIBLE_ENTRY_RANGE,
        )

    if not _key_requester_blind_entry_ready(belief_state):
        _log_key_rendezvous_decision(
            belief_state,
            "wait_for_opener",
            target=target,
            position=position,
            rendezvous=rendezvous,
            intent=intent,
            skip_color_exchange=skip_color_exchange,
            request_only=True,
        )
        return IdleTask()

    _log_key_rendezvous_decision(
        belief_state,
        "request_blind",
        target=target,
        position=position,
        rendezvous=rendezvous,
        intent=intent,
        skip_color_exchange=skip_color_exchange,
        request_only=True,
    )
    _record_probe_attempt_started(
        belief_state,
        target,
        action="entry_requested",
        intent=intent,
        skip_color_exchange=skip_color_exchange,
    )
    return RendezvousEntrySweepTask(
        rendezvous[0],
        rendezvous[1],
        target_index=None,
        use_button_b=True,
        radius=KEY_REQUESTER_SWEEP_RADIUS,
        button_radius=KEY_REQUESTER_VISIBLE_ENTRY_RANGE,
    )


def _is_confirmed_key_partner_target(belief_state, target: PlayerID) -> bool:
    strategic_state = belief_state.extra.get(STRATEGIC_STATE)
    key_partner_id = getattr(strategic_state, "key_partner_id", None)
    return isinstance(key_partner_id, tuple) and key_partner_id == target


def _key_requester_blind_entry_ready(belief_state) -> bool:
    tick = getattr(belief_state, "tick", 0)
    strategic_state = belief_state.extra.get(STRATEGIC_STATE)
    round_start_tick = getattr(strategic_state, "round_start_tick", None)
    if isinstance(round_start_tick, int) and round_start_tick > 0:
        elapsed = max(0, tick - round_start_tick)
    else:
        state = _active_probe_state(belief_state)
        selected_tick = state.get("selected_tick")
        if not isinstance(selected_tick, int):
            selected_tick = state.get("started_tick")
        if isinstance(selected_tick, int):
            elapsed = max(0, tick - selected_tick)
        else:
            elapsed = 0
    return elapsed >= KEY_REQUESTER_BLIND_ENTRY_DELAY_TICKS


def _blind_key_exchange_menu_task(
    belief_state,
    state: dict,
    *,
    target: PlayerID | None,
    request_only: bool,
    open_in_place: bool,
) -> Task | None:
    if not _state_is_key_probe(state):
        return None
    if getattr(belief_state, "view", None) not in BLIND_KEY_MENU_VIEWS:
        return None

    action = state.get("action")
    if action not in {"whisper_created", "entry_requested"}:
        return None

    started_tick = state.get("started_tick")
    if not isinstance(started_tick, int):
        return None

    position = _position2d(getattr(belief_state, "position", None))
    rendezvous = _key_rendezvous_point(
        belief_state,
        ProbeIntent.FIND_KEY_PARTNER,
        skip_color_exchange=True,
    )
    if (
        position is not None
        and rendezvous is not None
        and _distance_sq(position, rendezvous) > KEY_RENDEZVOUS_PARTNER_RANGE_SQ
    ):
        return None

    tick = getattr(belief_state, "tick", 0)
    age = max(0, tick - started_tick)
    state_target = _state_target(state) or target
    if action == "whisper_created" and open_in_place and not request_only:
        if age < BLIND_KEY_CREATE_SETTLE_TICKS:
            _log_key_rendezvous_decision(
                belief_state,
                "blind_create_settle",
                target=state_target,
                position=position,
                rendezvous=rendezvous,
                intent=ProbeIntent.FIND_KEY_PARTNER,
                skip_color_exchange=True,
                open_in_place=True,
            )
            return InitiateWhisperTask(target_index=None, use_button_b=False)

        if age < BLIND_KEY_FIRST_GRANT_TICKS:
            _log_key_rendezvous_decision(
                belief_state,
                "blind_wait_for_entry_request",
                target=state_target,
                position=position,
                rendezvous=rendezvous,
                intent=ProbeIntent.FIND_KEY_PARTNER,
                skip_color_exchange=True,
                open_in_place=True,
            )
            return IdleTask()

        phase_tick = (age - BLIND_KEY_FIRST_GRANT_TICKS) % (
            BLIND_KEY_GRANT_TICKS + BLIND_KEY_OFFER_TICKS + BLIND_KEY_IDLE_TICKS
        )
        if phase_tick < BLIND_KEY_GRANT_TICKS:
            _log_key_rendezvous_decision(
                belief_state,
                "blind_grant_entry",
                target=state_target,
                position=position,
                rendezvous=rendezvous,
                intent=ProbeIntent.FIND_KEY_PARTNER,
                skip_color_exchange=True,
                open_in_place=True,
            )
            return BlindGrantEntryTask()
        if phase_tick < BLIND_KEY_GRANT_TICKS + BLIND_KEY_OFFER_TICKS:
            _log_key_rendezvous_decision(
                belief_state,
                "blind_offer_role",
                target=state_target,
                position=position,
                rendezvous=rendezvous,
                intent=ProbeIntent.FIND_KEY_PARTNER,
                skip_color_exchange=True,
                open_in_place=True,
            )
            return BlindOfferRoleExchangeTask()
        return IdleTask()

    if action == "entry_requested" and request_only and not open_in_place:
        if age < BLIND_KEY_REQUESTER_OFFER_SETTLE_TICKS:
            return None
        phase_tick = (age - BLIND_KEY_REQUESTER_OFFER_SETTLE_TICKS) % (
            BLIND_KEY_REQUESTER_OFFER_TICKS + BLIND_KEY_IDLE_TICKS
        )
        if phase_tick < BLIND_KEY_REQUESTER_OFFER_TICKS:
            _log_key_rendezvous_decision(
                belief_state,
                "blind_offer_role_requester",
                target=state_target,
                position=position,
                rendezvous=rendezvous,
                intent=ProbeIntent.FIND_KEY_PARTNER,
                skip_color_exchange=True,
                request_only=True,
            )
            return BlindOfferRoleExchangeTask()
        return IdleTask()

    return None


def _waiting_entry_task(
    belief_state,
    *,
    target: PlayerID | None,
) -> Task:
    state = _active_probe_state(belief_state)
    if _state_is_key_probe(state):
        state["saw_waiting_entry"] = True
        state["waiting_entry_tick"] = getattr(belief_state, "tick", 0)
        belief_state.extra[PROBE_STATE] = state
    started_tick = int(state.get("started_tick", getattr(belief_state, "tick", 0)))
    timeout = (
        KEY_PROBE_ENTRY_TIMEOUT_TICKS
        if _state_is_key_probe(state)
        else PROBE_ENTRY_TIMEOUT_TICKS
    )
    if getattr(belief_state, "tick", 0) - started_tick > timeout:
        if target is not None:
            _record_probe_failed(
                belief_state,
                target,
                reason="entry_timeout",
            )
        _complete_mode(belief_state, found_target=None)
        return CancelEntryTask()
    return IdleTask()


def _systematic_probe_options(
    params: ProbeSystematicParams | ModeParams,
    belief_state,
) -> dict[str, object]:
    intent = getattr(params, "intent", ProbeIntent.GENERAL)
    if _probe_intent_name(intent) != "FIND_KEY_PARTNER":
        return {"intent": intent}

    strategic_state = belief_state.extra.get(STRATEGIC_STATE) or getattr(
        belief_state,
        "inferences",
        {},
    ).get(STRATEGIC_STATE)
    my_role = getattr(strategic_state, "my_role", None)
    return {
        "intent": intent,
        "skip_color_exchange": True,
        "max_approach_ticks": 240,
        "request_only": my_role in KEY_REQUESTER_ROLES,
        "open_in_place": my_role in KEY_OPENER_ROLES,
    }


def _probe_intent_name(intent) -> str:
    return getattr(intent, "name", str(intent)).upper()


def _key_rendezvous_point(
    belief_state,
    intent: ProbeIntent | None,
    skip_color_exchange: bool,
) -> tuple[int, int] | None:
    if _probe_intent_name(intent) != "FIND_KEY_PARTNER":
        return None
    if not skip_color_exchange:
        return None

    role = _strategic_role(belief_state)
    point = KEY_RENDEZVOUS_POINTS.get(role)
    if point is None:
        return None
    return _clamp_to_room(point, belief_state)


def _strategic_role(belief_state) -> Role | None:
    strategic_state = belief_state.extra.get(STRATEGIC_STATE) or getattr(
        belief_state,
        "inferences",
        {},
    ).get(STRATEGIC_STATE)
    role = getattr(strategic_state, "my_role", None)
    if isinstance(role, Role):
        return role

    raw_role = getattr(belief_state, "my_role", None)
    if isinstance(raw_role, Role):
        return raw_role
    if isinstance(raw_role, str):
        return Role.__members__.get(raw_role.strip().upper())
    return None


def _target_recently_in_whisper(belief_state, player_id: PlayerID) -> bool:
    current_tick = getattr(belief_state, "tick", 0)
    for index, pinfo in getattr(belief_state, "players", {}).items():
        if index == getattr(belief_state, "my_index", None):
            continue
        pid = player_index_to_id(index, belief_state)
        if pid != player_id:
            continue
        last_whisper = getattr(pinfo, "last_seen_in_whisper", None)
        return (
            last_whisper is not None
            and current_tick - last_whisper < WHISPER_RECENCY_TICKS
        )
    return False


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


def _find_nearby_target_whisper(
    belief_state,
    position: tuple[int, int],
    target: PlayerID,
) -> tuple[int, object, tuple[int, int]] | None:
    current_tick = getattr(belief_state, "tick", 0)
    for index, player in getattr(belief_state, "players", {}).items():
        if index == getattr(belief_state, "my_index", None):
            continue
        player_id = player_index_to_id(index, belief_state)
        if player_id != target:
            continue
        last_whisper = getattr(player, "last_seen_in_whisper", None)
        if last_whisper is None or current_tick - last_whisper > WHISPER_RECENCY_TICKS:
            return None
        player_position = _position2d(getattr(player, "position", None))
        if player_position is not None:
            return (index, player, player_position)
    return None


def _find_nearby_recent_whisper(
    belief_state,
    position: tuple[int, int],
) -> tuple[int, object, tuple[int, int]] | None:
    current_tick = getattr(belief_state, "tick", 0)
    best: tuple[int, object, tuple[int, int]] | None = None
    best_distance = REQUEST_ENTRY_RANGE_SQ + 1
    for index, player in getattr(belief_state, "players", {}).items():
        if index == getattr(belief_state, "my_index", None):
            continue
        last_whisper = getattr(player, "last_seen_in_whisper", None)
        if last_whisper is None or current_tick - last_whisper > WHISPER_RECENCY_TICKS:
            continue
        player_position = _position2d(getattr(player, "position", None))
        if player_position is None:
            continue
        distance = _distance_sq(position, player_position)
        if distance <= REQUEST_ENTRY_RANGE_SQ and distance < best_distance:
            best = (index, player, player_position)
            best_distance = distance
    return best


def _nearby_recent_non_target_whisper(
    belief_state,
    position: tuple[int, int],
    target: PlayerID,
) -> bool:
    current_tick = getattr(belief_state, "tick", 0)
    for index, player in getattr(belief_state, "players", {}).items():
        if index == getattr(belief_state, "my_index", None):
            continue
        player_id = player_index_to_id(index, belief_state)
        if player_id == target:
            continue
        last_whisper = getattr(player, "last_seen_in_whisper", None)
        if last_whisper is None or current_tick - last_whisper > WHISPER_RECENCY_TICKS:
            continue
        player_position = _position2d(getattr(player, "position", None))
        if (
            player_position is not None
            and _distance_sq(position, player_position) < INTERACTION_RANGE_SQ
        ):
            return True
    return False


def _safe_whisper_create_position(
    belief_state,
    position: tuple[int, int],
) -> tuple[int, int] | None:
    blocker = _nearest_recent_whisper_blocker(belief_state, position)
    if blocker is None:
        return None
    return _step_away_from(position, blocker, belief_state)


def _nearest_recent_whisper_blocker(
    belief_state,
    position: tuple[int, int],
) -> tuple[int, int] | None:
    current_tick = getattr(belief_state, "tick", 0)
    nearest: tuple[int, int] | None = None
    nearest_distance = CREATE_WHISPER_CLEARANCE_SQ
    for index, player in getattr(belief_state, "players", {}).items():
        if index == getattr(belief_state, "my_index", None):
            continue
        last_whisper = getattr(player, "last_seen_in_whisper", None)
        if last_whisper is None or current_tick - last_whisper > WHISPER_RECENCY_TICKS:
            continue
        player_position = _position2d(getattr(player, "position", None))
        if player_position is None:
            continue
        distance = _distance_sq(position, player_position)
        if distance < nearest_distance:
            nearest = player_position
            nearest_distance = distance
    return nearest


def _step_away_from(
    position: tuple[int, int],
    blocker: tuple[int, int],
    belief_state,
) -> tuple[int, int]:
    dx = position[0] - blocker[0]
    dy = position[1] - blocker[1]
    if dx == 0 and dy == 0:
        direction = 1 if (getattr(belief_state, "my_index", 0) or 0) % 2 == 0 else -1
        dx, dy = direction, 1
    distance = max(1.0, (dx * dx + dy * dy) ** 0.5)
    scale = CREATE_WHISPER_CLEARANCE / distance
    target = (
        int(round(blocker[0] + dx * scale)),
        int(round(blocker[1] + dy * scale)),
    )
    return _clamp_to_room(target, belief_state)


def _clamp_to_room(
    position: tuple[int, int],
    belief_state,
) -> tuple[int, int]:
    room_size = getattr(belief_state, "room_size", None)
    if room_size is None:
        return position
    width, height = room_size
    return (
        min(max(0, position[0]), max(0, int(width))),
        min(max(0, position[1]), max(0, int(height))),
    )


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


def _active_probe_state(belief_state) -> dict:
    state = belief_state.extra.get(PROBE_STATE)
    return state if isinstance(state, dict) else {}


def _state_target(state: dict) -> PlayerID | None:
    target = state.get("target")
    if (
        isinstance(target, tuple)
        and len(target) == 2
        and all(isinstance(value, int) for value in target)
    ):
        return target
    if (
        isinstance(target, list)
        and len(target) == 2
        and all(isinstance(value, int) for value in target)
    ):
        return (target[0], target[1])
    return None


def _state_is_key_probe(state: dict) -> bool:
    intent = str(state.get("intent", "")).upper()
    return bool(state.get("skip_color_exchange")) or intent == "FIND_KEY_PARTNER"


def _log_key_rendezvous_decision(
    belief_state,
    action: str,
    *,
    target: PlayerID | None,
    position: tuple[int, int] | None,
    rendezvous: tuple[int, int] | None,
    intent: ProbeIntent | None,
    skip_color_exchange: bool,
    target_index: int | None = None,
    target_position: tuple[int, int] | None = None,
    destination: tuple[int, int] | None = None,
    request_only: bool = False,
    open_in_place: bool = False,
) -> None:
    if not logger:
        return
    if _probe_intent_name(intent) != "FIND_KEY_PARTNER":
        return

    distance_sq = (
        _distance_sq(position, rendezvous)
        if position is not None and rendezvous is not None
        else None
    )
    target_distance_sq = (
        _distance_sq(position, target_position)
        if position is not None and target_position is not None
        else None
    )
    payload = {
        "action": action,
        "role": _role_event_value(_strategic_role(belief_state)),
        "target": _player_id_event_value(target),
        "target_index": target_index,
        "position": _position_event_value(position),
        "rendezvous": _position_event_value(rendezvous),
        "destination": _position_event_value(destination),
        "target_position": _position_event_value(target_position),
        "distance_sq": distance_sq,
        "target_distance_sq": target_distance_sq,
        "request_only": bool(request_only),
        "open_in_place": bool(open_in_place),
        "skip_color_exchange": bool(skip_color_exchange),
        "round": int(getattr(belief_state, "round", 0) or 0),
    }
    signature = (
        action,
        payload["target"],
        target_index,
        payload["position"],
        payload["destination"],
        payload["target_position"],
        payload["round"],
    )
    if belief_state.extra.get(_KEY_RENDEZVOUS_LOG_KEY) == signature:
        return
    belief_state.extra[_KEY_RENDEZVOUS_LOG_KEY] = signature
    logger.event("key_rendezvous_decision", payload, LogLevel.DECISIONS)


def _position_event_value(position: tuple[int, int] | None) -> list[int] | None:
    if position is None:
        return None
    return [int(position[0]), int(position[1])]


def _player_id_event_value(player_id: PlayerID | None) -> list[int] | None:
    if player_id is None:
        return None
    return [int(player_id[0]), int(player_id[1])]


def _role_event_value(role: Role | None) -> str | None:
    if role is None:
        return None
    return getattr(role, "name", str(role)).lower()


def _record_probe_target_selected(belief_state, target: PlayerID) -> None:
    state = _active_probe_state(belief_state)
    if _state_target(state) == target and not state.get("completed"):
        return
    belief_state.extra[PROBE_STATE] = {
        "target": target,
        "selected_tick": getattr(belief_state, "tick", 0),
        "round": getattr(belief_state, "round", 0) or 0,
    }
    _log_probe_event(belief_state, "probe_target_selected", target, {})


def _record_probe_attempt_started(
    belief_state,
    target: PlayerID,
    *,
    action: str,
    intent: ProbeIntent | None = None,
    skip_color_exchange: bool = False,
) -> None:
    tick = getattr(belief_state, "tick", 0)
    state = _active_probe_state(belief_state)
    if (
        _state_target(state) == target
        and state.get("started_tick") is not None
        and state.get("action") == action
        and state.get("intent") == _probe_intent_name(intent)
        and bool(state.get("skip_color_exchange")) == bool(skip_color_exchange)
        and not state.get("completed")
    ):
        return
    belief_state.extra[PROBE_STATE] = {
        "target": target,
        "selected_tick": state.get("selected_tick", tick),
        "started_tick": tick,
        "round": getattr(belief_state, "round", 0) or 0,
        "action": action,
        "intent": _probe_intent_name(intent),
        "skip_color_exchange": bool(skip_color_exchange),
    }
    _log_probe_event(belief_state, "probe_attempt_started", target, {"action": action})
    _log_probe_event(belief_state, action, target, {})


def _record_key_probe_selected(
    belief_state,
    *,
    intent: ProbeIntent | None = None,
    skip_color_exchange: bool = False,
) -> None:
    tick = getattr(belief_state, "tick", 0)
    state = _active_probe_state(belief_state)
    intent_name = _probe_intent_name(intent)
    if (
        _state_target(state) is None
        and state.get("intent") == intent_name
        and bool(state.get("skip_color_exchange")) == bool(skip_color_exchange)
        and not state.get("completed")
    ):
        return
    belief_state.extra[PROBE_STATE] = {
        "target": None,
        "selected_tick": tick,
        "round": getattr(belief_state, "round", 0) or 0,
        "intent": intent_name,
        "skip_color_exchange": bool(skip_color_exchange),
    }


def _record_key_probe_attempt_started(
    belief_state,
    target: PlayerID | None,
    *,
    action: str,
    intent: ProbeIntent | None = None,
    skip_color_exchange: bool = False,
) -> None:
    if target is not None:
        _record_probe_attempt_started(
            belief_state,
            target,
            action=action,
            intent=intent,
            skip_color_exchange=skip_color_exchange,
        )
        return

    tick = getattr(belief_state, "tick", 0)
    state = _active_probe_state(belief_state)
    intent_name = _probe_intent_name(intent)
    if (
        _state_target(state) is None
        and state.get("started_tick") is not None
        and state.get("action") == action
        and state.get("intent") == intent_name
        and bool(state.get("skip_color_exchange")) == bool(skip_color_exchange)
        and not state.get("completed")
    ):
        return

    belief_state.extra[PROBE_STATE] = {
        "target": None,
        "selected_tick": state.get("selected_tick", tick),
        "started_tick": tick,
        "round": getattr(belief_state, "round", 0) or 0,
        "action": action,
        "intent": intent_name,
        "skip_color_exchange": bool(skip_color_exchange),
    }
    if not logger:
        return
    payload = {
        "target": None,
        "round": int(getattr(belief_state, "round", 0) or 0),
        "action": action,
    }
    logger.event("probe_attempt_started", payload, LogLevel.EVENTS)
    logger.event(action, payload, LogLevel.EVENTS)


def _record_probe_failed(
    belief_state,
    target: PlayerID,
    *,
    reason: str,
) -> None:
    failures = belief_state.extra.setdefault(PROBE_FAILURES, {})
    key = _failure_key(belief_state, target)
    failures[key] = int(failures.get(key, 0)) + 1
    state = _active_probe_state(belief_state)
    state.update(
        {
            "target": target,
            "completed": True,
            "failed": True,
            "failure_reason": reason,
        }
    )
    belief_state.extra[PROBE_STATE] = state
    _log_probe_event(
        belief_state,
        "probe_failed",
        target,
        {"reason": reason, "failures_this_round": failures[key]},
    )


def _target_failed_this_round(belief_state, target: PlayerID) -> bool:
    failures = belief_state.extra.get(PROBE_FAILURES, {})
    if not isinstance(failures, dict):
        return False
    return int(failures.get(_failure_key(belief_state, target), 0)) >= (
        PROBE_FAILURE_CAP_PER_TARGET_ROUND
    )


def _should_retry_failed_target(params: ProbeTargetParams) -> bool:
    return (
        params.intent is ProbeIntent.FIND_KEY_PARTNER
        and params.skip_color_exchange
    )


def _failure_key(belief_state, target: PlayerID) -> tuple[int, PlayerID]:
    return (int(getattr(belief_state, "round", 0) or 0), target)


def _log_probe_event(
    belief_state,
    event_type: str,
    target: PlayerID,
    data: dict,
) -> None:
    if not logger:
        return
    logger.event(
        event_type,
        {
            "target": [int(target[0]), int(target[1])],
            "round": int(getattr(belief_state, "round", 0) or 0),
            **data,
        },
        LogLevel.EVENTS,
    )


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
