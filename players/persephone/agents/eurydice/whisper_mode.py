"""Eurydice in-whisper interaction protocol mode."""

from __future__ import annotations

from orpheus.idle import IdleTask
from orpheus.logging import LogLevel
from orpheus.mode import Mode, ModeDirective, ModeParams
from orpheus.perception.types import View
from orpheus.task import Task
from orpheus.tasks import (
    AcceptColorExchangeTask,
    AcceptRoleExchangeTask,
    ExitWhisperTask,
    GrantEntryTask,
    OfferColorExchangeTask,
    OfferRoleExchangeTask,
    SendMessageTask,
)

from agents.eurydice.advanced_modes import TimeWasteParams
from agents.eurydice.deception import spy_should_accept_role_exchange
from agents.eurydice.ext_keys import (
    LAST_NON_WHISPER_DIRECTIVE,
    MODE_COMPLETE,
    PLAYER_KNOWLEDGE,
    STRATEGIC_STATE,
    WHISPER_EXIT_REASON,
    WHISPER_MODE_STATE,
)
from agents.eurydice.knowledge import PlayerKnowledge
from agents.eurydice.modes import ProbeSystematicParams, ProbeTargetParams
from agents.eurydice.pipeline import player_index_to_id
from agents.eurydice.types import (
    PROTOCOL_TIMEOUTS,
    Objective,
    PlayerID,
    ProbeIntent,
    Role,
    Team,
    Urgency,
)
from agents.eurydice.whisper_state import WhisperModeState

from .log import logger


ACTION_COOLDOWN_TICKS = 48
OFFER_RESPONSE_TIMEOUT_TICKS = 72
EXTRACT_TIMEOUT_TICKS = 96
STALL_FIRST_MESSAGE_TICK = 48
STALL_SECOND_MESSAGE_TICK = 144
WAIT_FOR_OCCUPANT_TIMEOUT_TICKS = 360
_WHISPER_EXIT_LOGGED = "_eurydice_whisper_exit_logged"
_WHISPER_ENTRY_GRANTED_LOGGED = "_eurydice_whisper_entry_granted_logged"

SENSITIVE_ENTRY_STATES = frozenset({"COLOR_EXCHANGE", "ROLE_EXCHANGE", "EXTRACT", "EXIT"})
VALID_FSM_STATES = frozenset(
    {
        "ENTER",
        "ASSESS",
        "WAIT_FOR_OCCUPANT",
        "COLOR_EXCHANGE",
        "EVALUATE",
        "ROLE_EXCHANGE",
        "EXTRACT",
        "STALL",
        "EXIT",
    }
)


class InWhisperMode(Mode):
    """Run Eurydice's finite-state whisper interaction protocol."""

    params_type = ModeParams

    def select_task(self, belief_state, action_memory) -> Task | None:
        del action_memory

        raw_state = belief_state.extra.get(WHISPER_MODE_STATE)
        old_fsm_state = (
            raw_state.fsm_state
            if isinstance(raw_state, WhisperModeState)
            else None
        )
        state = _whisper_state(belief_state)
        tick = _tick(belief_state)
        if old_fsm_state is None:
            old_fsm_state = state.fsm_state

        task = self._select_task_impl(belief_state, state, tick)
        _log_fsm_transition(belief_state, state, old_fsm_state)
        return task

    def _select_task_impl(
        self,
        belief_state,
        state: WhisperModeState,
        tick: int,
    ) -> Task | None:
        if _forced_ejected(belief_state, state):
            _complete_mode(belief_state, "forced_ejection", state)
            return IdleTask()

        if _protocol_timed_out(state, tick):
            _transition_to_exit(belief_state, state, "protocol_timeout")

        entry_task = _entry_request_task(belief_state, state)
        if entry_task is not None:
            return entry_task

        if _abort_for_hostile_new_entrant(belief_state, state):
            return IdleTask()

        if state.fsm_state == "ENTER":
            return self._enter_task(belief_state, state)
        if state.fsm_state == "WAIT_FOR_OCCUPANT":
            return self._wait_for_occupant_task(belief_state, state)
        if state.fsm_state == "ASSESS":
            return self._assess_task(belief_state, state)
        if state.fsm_state == "COLOR_EXCHANGE":
            return self._color_exchange_task(belief_state, state)
        if state.fsm_state == "EVALUATE":
            return self._evaluate_task(belief_state, state)
        if state.fsm_state == "ROLE_EXCHANGE":
            return self._role_exchange_task(belief_state, state)
        if state.fsm_state == "EXTRACT":
            return self._extract_task(belief_state, state)
        if state.fsm_state == "STALL":
            return self._stall_task(belief_state, state)
        if state.fsm_state == "EXIT":
            return self._exit_task(belief_state, state)

        _transition_to_exit(belief_state, state, "invalid_fsm_state")
        return IdleTask()

    def mode_enter(self, belief_state, action_memory) -> None:
        del action_memory

        previous = belief_state.extra.get(WHISPER_MODE_STATE)
        protocol = _protocol_from_context(belief_state, previous)
        belief_state.extra.pop(MODE_COMPLETE, None)
        belief_state.extra.pop(WHISPER_EXIT_REASON, None)
        belief_state.extra.pop(_WHISPER_EXIT_LOGGED, None)
        belief_state.extra.pop(_WHISPER_ENTRY_GRANTED_LOGGED, None)
        belief_state.extra[WHISPER_MODE_STATE] = WhisperModeState(
            protocol=protocol,
            fsm_state="ENTER",
            entered_tick=_tick(belief_state),
        )

    def mode_switch_cleanup(
        self,
        belief_state,
        action_memory,
        new_mode_directive: ModeDirective,
    ) -> None:
        del action_memory, new_mode_directive
        belief_state.extra.pop(WHISPER_MODE_STATE, None)

    def _enter_task(self, belief_state, state: WhisperModeState) -> Task:
        if getattr(belief_state, "view", None) is not View.WHISPER:
            return IdleTask()

        knowledge = _player_knowledge(belief_state)
        my_team = _my_team(belief_state)
        my_id = _my_player_id(belief_state)
        occupants = _current_occupants(belief_state)
        candidates = [pid for pid in occupants if pid is not None and pid != my_id]
        key_partner_id = _key_partner_id(belief_state)

        state.occupants_at_entry = list(occupants)
        state.target_occupant = _select_whisper_target(
            candidates,
            knowledge,
            my_team,
            key_partner_id,
        )
        state.hostile_present = _hostile_or_unknown_present(
            candidates,
            state.target_occupant,
            knowledge,
            my_team,
        )
        state.fsm_state = "ASSESS"
        return IdleTask()

    def _wait_for_occupant_task(self, belief_state, state: WhisperModeState) -> Task:
        tick = _tick(belief_state)
        if tick - state.entered_tick > WAIT_FOR_OCCUPANT_TIMEOUT_TICKS:
            _transition_to_exit(belief_state, state, "wait_timeout")
            return IdleTask()

        my_id = _my_player_id(belief_state)
        occupants = _current_occupants(belief_state)
        candidates = [pid for pid in occupants if pid is not None and pid != my_id]
        if candidates:
            knowledge = _player_knowledge(belief_state)
            my_team = _my_team(belief_state)
            key_partner_id = _key_partner_id(belief_state)
            state.target_occupant = _select_whisper_target(
                candidates, knowledge, my_team, key_partner_id,
            )
            state.hostile_present = _hostile_or_unknown_present(
                candidates, state.target_occupant, knowledge, my_team,
            )
            state.fsm_state = "ASSESS"

        return IdleTask()

    def _assess_task(self, belief_state, state: WhisperModeState) -> Task:
        my_role = _my_role(belief_state)
        occupants = _current_occupants(belief_state)

        if (
            len(occupants) > 2
            and state.hostile_present
            and _is_key_role(my_role)
        ):
            _log_protocol_selected(
                belief_state,
                state,
                occupants,
                "hostile_multi_occupant_key_role_exit",
            )
            _transition_to_exit(belief_state, state, "hostile_present")
            return IdleTask()

        if state.protocol == "stall":
            _log_protocol_selected(belief_state, state, occupants, "stall_protocol")
            state.fsm_state = "STALL"
            return IdleTask()

        if state.protocol == "key_exchange":
            _log_protocol_selected(belief_state, state, occupants, "key_exchange_protocol")
            state.fsm_state = "ROLE_EXCHANGE"
            return IdleTask()

        if state.protocol == "quick_verify":
            if state.target_occupant is None:
                state.fsm_state = "WAIT_FOR_OCCUPANT"
                return IdleTask()
            target_record = _target_knowledge(state.target_occupant, belief_state)
            if target_record is not None and target_record.team is not None:
                _log_protocol_selected(
                    belief_state,
                    state,
                    occupants,
                    "quick_verify_known_team",
                )
                state.fsm_state = "EVALUATE"
                return IdleTask()
            _log_protocol_selected(
                belief_state,
                state,
                occupants,
                "quick_verify_unknown_target",
            )
            state.fsm_state = "COLOR_EXCHANGE"
            return IdleTask()

        if state.protocol == "infiltration" and _target_is_enemy(
            state.target_occupant,
            _player_knowledge(belief_state),
            _my_team(belief_state),
        ):
            _log_protocol_selected(
                belief_state,
                state,
                occupants,
                "infiltration_enemy_extract",
            )
            state.fsm_state = "EXTRACT"
            return IdleTask()

        target_record = _target_knowledge(state.target_occupant, belief_state)
        if target_record is not None and target_record.team is not None:
            _log_protocol_selected(belief_state, state, occupants, "known_team_evaluate")
            state.fsm_state = "EVALUATE"
            return IdleTask()

        if state.target_occupant is None:
            state.fsm_state = "WAIT_FOR_OCCUPANT"
            return IdleTask()

        _log_protocol_selected(belief_state, state, occupants, "unknown_target_color_exchange")
        state.fsm_state = "COLOR_EXCHANGE"
        return IdleTask()

    def _color_exchange_task(self, belief_state, state: WhisperModeState) -> Task:
        tick = _tick(belief_state)

        if _exchange_completed_since(
            belief_state,
            "swapped_colors",
            state.waiting_for_response_since,
        ):
            state.color_exchange_completed = True
            state.fsm_state = "EVALUATE"
            return IdleTask()

        if state.color_exchange_initiated and _response_timed_out(state, tick):
            _log_exchange_outcome(
                belief_state,
                state,
                "color",
                "timeout",
                state.target_occupant,
                None,
            )
            _transition_to_exit(belief_state, state, "color_exchange_timeout")
            return IdleTask()

        if _pending_offer(belief_state, "color"):
            target_index = _offer_index("color", state.target_occupant, belief_state)
            if target_index is None:
                return IdleTask()
            if _exchange_action_on_cooldown(state, tick):
                return IdleTask()
            state.color_exchange_initiated = True
            state.waiting_for_response_since = tick
            _log_exchange_outcome(
                belief_state,
                state,
                "color",
                "accept",
                player_index_to_id(target_index, belief_state),
                None,
            )
            return AcceptColorExchangeTask(player_index=target_index)

        if not state.color_exchange_initiated:
            if _exchange_action_on_cooldown(state, tick):
                return IdleTask()
            state.color_exchange_initiated = True
            state.waiting_for_response_since = tick
            _log_exchange_outcome(
                belief_state,
                state,
                "color",
                "offer",
                state.target_occupant,
                _offered_value("color", belief_state),
            )
            return OfferColorExchangeTask()

        return IdleTask()

    def _evaluate_task(self, belief_state, state: WhisperModeState) -> Task:
        my_role = _my_role(belief_state)
        my_team = _my_team(belief_state)
        target_record = _target_knowledge(state.target_occupant, belief_state)
        target_team = target_record.team if target_record is not None else None

        if target_team is not None and my_team is not None:
            if target_team is my_team and _intent_involves_partner_search(
                belief_state,
                state,
            ):
                state.fsm_state = "ROLE_EXCHANGE"
                return IdleTask()
            if target_team is not my_team and _is_key_role(my_role):
                _transition_to_exit(belief_state, state, "hostile_target_key_role")
                return IdleTask()
            if target_team is not my_team and _is_grunt_role(my_role):
                state.fsm_state = "EXTRACT"
                return IdleTask()

        _transition_to_exit(belief_state, state, "evaluation_complete")
        return IdleTask()

    def _role_exchange_task(self, belief_state, state: WhisperModeState) -> Task:
        tick = _tick(belief_state)

        if _exchange_completed_since(
            belief_state,
            "shared_roles",
            state.waiting_for_response_since,
        ):
            state.role_exchange_completed = True
            _transition_to_exit(belief_state, state, "role_exchange_complete")
            return IdleTask()

        if state.role_exchange_initiated and _response_timed_out(state, tick):
            _log_exchange_outcome(
                belief_state,
                state,
                "role",
                "timeout",
                state.target_occupant,
                None,
            )
            _transition_to_exit(belief_state, state, "role_exchange_timeout")
            return IdleTask()

        if _pending_offer(belief_state, "role"):
            target_index = _offer_index("role", state.target_occupant, belief_state)
            offerer_id = (
                player_index_to_id(target_index, belief_state)
                if target_index is not None
                else state.target_occupant
            )
            if not _should_accept_role_offer(offerer_id, belief_state):
                _log_exchange_outcome(
                    belief_state,
                    state,
                    "role",
                    "reject",
                    offerer_id,
                    None,
                )
                _transition_to_exit(belief_state, state, "role_offer_rejected")
                return IdleTask()

            if target_index is None:
                return IdleTask()
            if _exchange_action_on_cooldown(state, tick):
                return IdleTask()
            state.role_exchange_initiated = True
            state.waiting_for_response_since = tick
            _log_exchange_outcome(
                belief_state,
                state,
                "role",
                "accept",
                player_index_to_id(target_index, belief_state),
                None,
            )
            return AcceptRoleExchangeTask(player_index=target_index)

        if not state.role_exchange_initiated:
            if _exchange_action_on_cooldown(state, tick):
                return IdleTask()
            state.role_exchange_initiated = True
            state.waiting_for_response_since = tick
            _log_exchange_outcome(
                belief_state,
                state,
                "role",
                "offer",
                state.target_occupant,
                _offered_value("role", belief_state),
            )
            return OfferRoleExchangeTask()

        return IdleTask()

    def _extract_task(self, belief_state, state: WhisperModeState) -> Task:
        tick = _tick(belief_state)

        if state.messages_sent == 0:
            state.messages_sent += 1
            state.waiting_for_response_since = tick
            return SendMessageTask(text="WHO ARE YOU", channel="whisper")

        if tick - state.waiting_for_response_since > EXTRACT_TIMEOUT_TICKS:
            _transition_to_exit(belief_state, state, "extract_timeout")

        return IdleTask()

    def _stall_task(self, belief_state, state: WhisperModeState) -> Task:
        tick = _tick(belief_state)
        elapsed = tick - state.entered_tick

        if elapsed > PROTOCOL_TIMEOUTS["stall"]:
            _transition_to_exit(belief_state, state, "stall_timeout")
            return IdleTask()

        if elapsed >= STALL_FIRST_MESSAGE_TICK and state.messages_sent == 0:
            state.messages_sent = 1
            state.waiting_for_response_since = tick
            return SendMessageTask(text="THINKING", channel="whisper")

        if elapsed >= STALL_SECOND_MESSAGE_TICK and state.messages_sent == 1:
            state.messages_sent = 2
            state.waiting_for_response_since = tick
            return SendMessageTask(text="WHO ARE YOU", channel="whisper")

        return IdleTask()

    def _exit_task(self, belief_state, state: WhisperModeState) -> Task:
        if getattr(belief_state, "view", None) is not View.WHISPER:
            _complete_mode(belief_state, "normal", state)
            return IdleTask()

        if not state.exit_initiated:
            state.exit_initiated = True
            return ExitWhisperTask()

        return IdleTask()


def _whisper_state(belief_state) -> WhisperModeState:
    state = belief_state.extra.get(WHISPER_MODE_STATE)
    if not isinstance(state, WhisperModeState):
        state = WhisperModeState(
            protocol=_protocol_from_context(belief_state, None),
            entered_tick=_tick(belief_state),
        )
        belief_state.extra[WHISPER_MODE_STATE] = state
    if state.fsm_state not in VALID_FSM_STATES:
        state.fsm_state = "EXIT"
    if state.protocol not in PROTOCOL_TIMEOUTS:
        state.protocol = "standard"
    return state


def _protocol_from_context(
    belief_state,
    previous: WhisperModeState | None,
) -> str:
    """Infer the intended whisper protocol from the mode that entered whisper."""

    directive = belief_state.extra.get(LAST_NON_WHISPER_DIRECTIVE)
    params = directive.params if isinstance(directive, ModeDirective) else None

    explicit_protocol = getattr(params, "protocol", None)
    if explicit_protocol in PROTOCOL_TIMEOUTS:
        return explicit_protocol

    if isinstance(params, TimeWasteParams):
        return "stall"

    if isinstance(params, ProbeTargetParams):
        if params.skip_color_exchange:
            return "key_exchange"
        if params.intent is ProbeIntent.VERIFY_SELF_AS_SPY:
            return "quick_verify"
        if _my_role(belief_state) is Role.SPY:
            return "infiltration"

    if isinstance(params, ProbeSystematicParams):
        if params.intent is ProbeIntent.VERIFY_SELF_AS_SPY:
            return "quick_verify"
        if _my_role(belief_state) is Role.SPY:
            return "infiltration"

    strategic_state = belief_state.extra.get(STRATEGIC_STATE)
    if (
        getattr(strategic_state, "current_objective", None)
        is Objective.COMPLETE_KEY_EXCHANGE
        and _key_partner_id(belief_state) is not None
    ):
        return "key_exchange"

    if isinstance(previous, WhisperModeState) and previous.protocol in PROTOCOL_TIMEOUTS:
        return previous.protocol
    return "standard"


def _forced_ejected(belief_state, state: WhisperModeState) -> bool:
    if state.fsm_state == "EXIT" or state.exit_initiated:
        return False
    if getattr(belief_state, "view", None) is View.WHISPER:
        return False
    return state.fsm_state != "ENTER" or bool(state.occupants_at_entry)


def _protocol_timed_out(state: WhisperModeState, tick: int) -> bool:
    timeout = PROTOCOL_TIMEOUTS.get(state.protocol, PROTOCOL_TIMEOUTS["standard"])
    return state.fsm_state != "EXIT" and tick - state.entered_tick > timeout


def _entry_request_task(belief_state, state: WhisperModeState) -> Task | None:
    if state.fsm_state in SENSITIVE_ENTRY_STATES:
        return None
    if state.protocol == "key_exchange":
        return None
    if getattr(belief_state, "view", None) is not View.WHISPER:
        return None

    pending_entry = getattr(belief_state, "pending_entry", None)
    if pending_entry is None:
        return None
    player_id = player_index_to_id(pending_entry, belief_state)
    knowledge = _player_knowledge(belief_state)
    if _is_probable_ally(player_id, knowledge, _my_team(belief_state)):
        _log_entry_granted(belief_state, state, player_id)
        return GrantEntryTask()
    record = knowledge.get(player_id) if player_id is not None else None
    if record is None or record.team is None:
        _log_entry_granted(belief_state, state, player_id)
        return GrantEntryTask()
    return None


def _abort_for_hostile_new_entrant(
    belief_state,
    state: WhisperModeState,
) -> bool:
    if state.fsm_state not in {"COLOR_EXCHANGE", "ROLE_EXCHANGE"}:
        return False
    if state.role_exchange_completed:
        return False
    if getattr(belief_state, "view", None) is not View.WHISPER:
        return False
    if not state.occupants_at_entry:
        return False

    current = _current_occupants(belief_state)
    old_set = set(state.occupants_at_entry)
    new_entrants = [pid for pid in current if pid not in old_set]
    state.occupants_at_entry = current
    if not new_entrants:
        return False

    knowledge = _player_knowledge(belief_state)
    my_team = _my_team(belief_state)
    hostile_or_unknown = [
        pid for pid in new_entrants if not _is_probable_ally(pid, knowledge, my_team)
    ]
    if hostile_or_unknown and _is_key_role(_my_role(belief_state)):
        _transition_to_exit(belief_state, state, "hostile_entered_sensitive_exchange")
        return True
    return False


def _current_occupants(belief_state) -> list[PlayerID]:
    occupants: list[PlayerID] = []
    for index in getattr(belief_state, "whisper_occupants", []) or []:
        player_id = player_index_to_id(index, belief_state)
        if player_id is not None:
            occupants.append(player_id)
    return occupants


def _select_whisper_target(
    occupants: list[PlayerID],
    knowledge: dict[PlayerID, PlayerKnowledge],
    my_team: Team | None,
    key_partner_id: PlayerID | None,
) -> PlayerID | None:
    if not occupants:
        return None
    if key_partner_id in occupants:
        return key_partner_id

    for occupant in occupants:
        record = knowledge.get(occupant)
        if record is None or record.team is None:
            return occupant

    for occupant in occupants:
        record = knowledge.get(occupant)
        if (
            record is not None
            and my_team is not None
            and record.team is my_team
            and not record.has_exchanged_roles_with_us
        ):
            return occupant

    return occupants[0]


def _hostile_or_unknown_present(
    occupants: list[PlayerID],
    target: PlayerID | None,
    knowledge: dict[PlayerID, PlayerKnowledge],
    my_team: Team | None,
) -> bool:
    for occupant in occupants:
        if occupant == target:
            continue
        if not _is_probable_ally(occupant, knowledge, my_team):
            return True
    return False


def _is_probable_ally(
    player_id: PlayerID | None,
    knowledge: dict[PlayerID, PlayerKnowledge],
    my_team: Team | None,
) -> bool:
    if player_id is None or my_team is None:
        return False
    record = knowledge.get(player_id)
    if record is None:
        return False
    if record.team is my_team:
        return True
    if record.team is not None:
        return False
    if record.role is not None and _team_for_role(record.role) is my_team:
        return True
    return False


def _should_accept_role_offer(
    offerer_id: PlayerID | None,
    belief_state,
) -> bool:
    knowledge = _player_knowledge(belief_state)
    my_team = _my_team(belief_state)
    my_role = _my_role(belief_state)

    if my_role is Role.SPY:
        strategic_state = belief_state.extra.get(STRATEGIC_STATE)
        verified_ally = getattr(strategic_state, "verified_ally", None)
        if offerer_id is not None and offerer_id == verified_ally:
            return True
        return spy_should_accept_role_exchange(
            knowledge.get(offerer_id) if offerer_id is not None else None,
            my_team,
            verified_ally,
            _urgency(belief_state),
        )

    return _is_probable_ally(offerer_id, knowledge, my_team)


def _target_is_enemy(
    player_id: PlayerID | None,
    knowledge: dict[PlayerID, PlayerKnowledge],
    my_team: Team | None,
) -> bool:
    if player_id is None or my_team is None:
        return False
    record = knowledge.get(player_id)
    return record is not None and record.team is not None and record.team is not my_team


def _is_key_role(role: Role | None) -> bool:
    return role in {Role.HADES, Role.PERSEPHONE, Role.CERBERUS, Role.DEMETER}


def _is_grunt_role(role: Role | None) -> bool:
    return role in {Role.SHADE, Role.NYMPH, Role.SPY}


def _find_target_index(target_pid: PlayerID | None, belief_state) -> int | None:
    if target_pid is None:
        return None
    for index in getattr(belief_state, "whisper_occupants", []) or []:
        if player_index_to_id(index, belief_state) == target_pid:
            return index
    for index in getattr(belief_state, "players", {}):
        if player_index_to_id(index, belief_state) == target_pid:
            return index
    return None


def _offer_index(kind: str, target_pid: PlayerID | None, belief_state) -> int | None:
    target_index = _find_target_index(target_pid, belief_state)
    active_field = "active_color_offers" if kind == "color" else "active_role_offers"
    active_offers = list(getattr(belief_state, active_field, []) or [])
    if target_index is not None and (not active_offers or target_index in active_offers):
        return target_index
    if active_offers:
        return active_offers[0]
    return target_index


def _exchange_completed_since(belief_state, event_type: str, since_tick: int) -> bool:
    event = getattr(belief_state, "last_exchange_event", None)
    if not isinstance(event, dict):
        return False
    event_tick = event.get("tick", -1)
    if not isinstance(event_tick, int):
        return False
    return event.get("type") == event_type and event_tick >= since_tick


def _response_timed_out(state: WhisperModeState, tick: int) -> bool:
    return tick - state.waiting_for_response_since > OFFER_RESPONSE_TIMEOUT_TICKS


def _exchange_action_on_cooldown(state: WhisperModeState, tick: int) -> bool:
    last_action = state.waiting_for_response_since
    return last_action > 0 and tick - last_action < ACTION_COOLDOWN_TICKS


def _pending_offer(belief_state, kind: str) -> bool:
    pending = getattr(belief_state, "pending_offers", {}) or {}
    return bool(pending.get(kind, False))


def _target_knowledge(
    player_id: PlayerID | None,
    belief_state,
) -> PlayerKnowledge | None:
    if player_id is None:
        return None
    record = _player_knowledge(belief_state).get(player_id)
    return record if isinstance(record, PlayerKnowledge) else None


def _player_knowledge(belief_state) -> dict[PlayerID, PlayerKnowledge]:
    raw = belief_state.extra.get(PLAYER_KNOWLEDGE, {})
    if not isinstance(raw, dict):
        return {}
    return {
        player_id: record
        for player_id, record in raw.items()
        if isinstance(record, PlayerKnowledge)
    }


def _intent_involves_partner_search(
    belief_state,
    state: WhisperModeState,
) -> bool:
    if state.protocol == "key_exchange":
        return True

    strategic_state = belief_state.extra.get(STRATEGIC_STATE)
    objective = getattr(strategic_state, "current_objective", None)
    objective_name = getattr(objective, "name", str(objective)).upper()
    if objective_name in {"FIND_KEY_PARTNER", "COMPLETE_KEY_EXCHANGE"}:
        return True

    key_partner_id = getattr(strategic_state, "key_partner_id", None)
    return key_partner_id is not None and key_partner_id == state.target_occupant


def _key_partner_id(belief_state) -> PlayerID | None:
    strategic_state = belief_state.extra.get(STRATEGIC_STATE)
    key_partner_id = getattr(strategic_state, "key_partner_id", None)
    if isinstance(key_partner_id, tuple) and len(key_partner_id) == 2:
        return key_partner_id
    return None


def _my_player_id(belief_state) -> PlayerID | None:
    my_index = getattr(belief_state, "my_index", None)
    if my_index is not None:
        return player_index_to_id(my_index, belief_state)
    my_color = getattr(belief_state, "my_color", None)
    my_shape = getattr(belief_state, "my_shape", None)
    if my_color is None or my_shape is None:
        return None
    return (my_color, int(getattr(my_shape, "value", my_shape)))


def _my_role(belief_state) -> Role | None:
    return _coerce_role(getattr(belief_state, "my_role", None))


def _my_team(belief_state) -> Team | None:
    team = _coerce_team(getattr(belief_state, "my_team", None))
    if team is not None:
        return team
    role = _my_role(belief_state)
    return _team_for_role(role)


def _urgency(belief_state) -> Urgency:
    strategic_state = belief_state.extra.get(STRATEGIC_STATE)
    urgency = getattr(strategic_state, "urgency", None)
    if isinstance(urgency, Urgency):
        return urgency
    if urgency is None:
        return Urgency.CALM
    normalized = str(urgency).strip().upper()
    if "." in normalized:
        normalized = normalized.rsplit(".", 1)[-1]
    return Urgency.__members__.get(normalized, Urgency.CALM)


def _coerce_role(value) -> Role | None:
    if isinstance(value, Role):
        return value
    if value is None:
        return None
    normalized = str(value).strip().upper()
    if "." in normalized:
        normalized = normalized.rsplit(".", 1)[-1]
    return Role.__members__.get(normalized)


def _coerce_team(value) -> Team | None:
    if isinstance(value, Team):
        return value
    if value is None:
        return None
    normalized = str(value).strip().upper()
    if "." in normalized:
        normalized = normalized.rsplit(".", 1)[-1]
    if normalized == "SHADES":
        return Team.SHADES
    if normalized == "NYMPHS":
        return Team.NYMPHS
    return Team.__members__.get(normalized)


def _team_for_role(role: Role | None) -> Team | None:
    if role in {Role.HADES, Role.CERBERUS, Role.SHADE}:
        return Team.SHADES
    if role in {Role.PERSEPHONE, Role.DEMETER, Role.NYMPH}:
        return Team.NYMPHS
    return None


def _transition_to_exit(
    belief_state,
    state: WhisperModeState,
    reason: str,
) -> None:
    state.fsm_state = "EXIT"
    belief_state.extra[WHISPER_EXIT_REASON] = reason
    _log_whisper_exit(belief_state, state, reason)


def _log_fsm_transition(
    belief_state,
    state: WhisperModeState,
    old_state: str | None,
) -> None:
    if old_state == state.fsm_state:
        return
    if logger:
        logger.event(
            "whisper_fsm_transition",
            {
                "old_state": old_state,
                "new_state": state.fsm_state,
                "protocol": state.protocol,
                "target": _player_id_value(state.target_occupant),
                "tick_in_whisper": _tick(belief_state) - state.entered_tick,
            },
            LogLevel.DECISIONS,
        )


def _log_protocol_selected(
    belief_state,
    state: WhisperModeState,
    occupants: list[PlayerID],
    reason: str,
) -> None:
    if logger:
        logger.event(
            "whisper_protocol_selected",
            {
                "protocol": state.protocol,
                "reason": reason,
                "occupants": [_player_id_value(player_id) for player_id in occupants],
                "hostile_present": state.hostile_present,
            },
            LogLevel.DECISIONS,
        )


def _log_exchange_outcome(
    belief_state,
    state: WhisperModeState,
    exchange_type: str,
    action: str,
    target: PlayerID | None,
    our_offer: object,
) -> None:
    del belief_state
    if logger:
        logger.event(
            "whisper_exchange_outcome",
            {
                "exchange_type": exchange_type,
                "action": action,
                "target": _player_id_value(
                    target if target is not None else state.target_occupant
                ),
                "our_offer": _event_value(our_offer),
            },
            LogLevel.DECISIONS,
        )


def _log_entry_granted(
    belief_state,
    state: WhisperModeState,
    player_id: PlayerID | None,
) -> None:
    key = _player_id_value(player_id)
    if belief_state.extra.get(_WHISPER_ENTRY_GRANTED_LOGGED) == key:
        return
    belief_state.extra[_WHISPER_ENTRY_GRANTED_LOGGED] = key
    if logger:
        logger.event(
            "entry_granted",
            {
                "target": key,
                "protocol": state.protocol,
                "fsm_state": state.fsm_state,
            },
            LogLevel.DECISIONS,
        )


def _log_whisper_exit(
    belief_state,
    state: WhisperModeState,
    reason: str,
) -> None:
    if belief_state.extra.get(_WHISPER_EXIT_LOGGED):
        return
    belief_state.extra[_WHISPER_EXIT_LOGGED] = True
    if logger:
        logger.event(
            "whisper_exit",
            {
                "reason": reason,
                "protocol": state.protocol,
                "total_ticks": _tick(belief_state) - state.entered_tick,
            },
            LogLevel.DECISIONS,
        )


def _offered_value(kind: str, belief_state) -> object:
    if kind == "role":
        return _my_role(belief_state)
    if kind == "color":
        return _my_team(belief_state)
    return None


def _event_value(value: object) -> object:
    if value is None:
        return None
    name = getattr(value, "name", None)
    if isinstance(name, str):
        return name.lower()
    raw = getattr(value, "value", None)
    if isinstance(raw, str):
        return raw
    return value


def _player_id_value(player_id: PlayerID | None) -> list[int] | None:
    if player_id is None:
        return None
    return [int(player_id[0]), int(player_id[1])]


def _complete_mode(
    belief_state,
    reason: str,
    state: WhisperModeState | None = None,
) -> None:
    final_reason = belief_state.extra.get(WHISPER_EXIT_REASON, reason)
    if state is not None:
        _log_whisper_exit(belief_state, state, final_reason)
    belief_state.extra[MODE_COMPLETE] = True
    belief_state.extra[WHISPER_EXIT_REASON] = final_reason


def _tick(belief_state) -> int:
    tick = getattr(belief_state, "tick", 0)
    return tick if isinstance(tick, int) else 0


__all__ = [
    "InWhisperMode",
    "_find_target_index",
    "_is_key_role",
    "_is_probable_ally",
    "_select_whisper_target",
]
