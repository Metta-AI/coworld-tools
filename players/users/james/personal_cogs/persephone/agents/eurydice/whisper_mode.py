"""Eurydice in-whisper interaction protocol mode."""

from __future__ import annotations

from dataclasses import dataclass

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
    PROBE_STATE,
    STRATEGIC_STATE,
    WHISPER_EXIT_REASON,
    WHISPER_MODE_STATE,
)
from agents.eurydice.knowledge import PlayerKnowledge
from agents.eurydice.modes import (
    BlindOfferRoleExchangeTask,
    BlindGrantEntryTask,
    ProbeSystematicParams,
    ProbeTargetParams,
)
from agents.eurydice.pipeline import player_index_to_id
from agents.eurydice.types import (
    PROTOCOL_TIMEOUTS,
    PlayerID,
    Role,
    Team,
    Urgency,
)
from agents.eurydice.whisper_state import WhisperModeState

from .log import logger


ACTION_COOLDOWN_TICKS = 48
# Was 72 (3 s); paired with the key_exchange protocol-timeout bump above so
# offerers wait long enough for the partner's accept menu sequence to land.
OFFER_RESPONSE_TIMEOUT_TICKS = 144
EXTRACT_TIMEOUT_TICKS = 96
STALL_FIRST_MESSAGE_TICK = 48
STALL_SECOND_MESSAGE_TICK = 144
WAIT_FOR_OCCUPANT_TIMEOUT_TICKS = 360
LLM_WHISPER_DECISION_COOLDOWN_TICKS = 48
KEY_IN_WHISPER_GRANT_TICKS = 12
KEY_IN_WHISPER_REQUESTER_SETTLE_TICKS = 24
KEY_IN_WHISPER_OFFER_TICKS = 96
KEY_IN_WHISPER_IDLE_TICKS = 24
_WHISPER_EXIT_LOGGED = "_eurydice_whisper_exit_logged"
_WHISPER_ENTRY_GRANTED_LOGGED = "_eurydice_whisper_entry_granted_logged"
_WHISPER_ENTRY_DECISION_LOGGED = "_eurydice_whisper_entry_decision_logged"
_EXCHANGE_MENU_STEPS = {
    "color_offer": 3,
    "color_accept": 5,
    "role_offer": 3,
    "role_accept": 5,
}

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


@dataclass(frozen=True)
class InWhisperParams(ModeParams):
    """Runtime configuration for optional mode-local LLM whisper control."""

    llm_control: str = "off"
    llm_provider: str = "hold"


class InWhisperMode(Mode):
    """Run Eurydice's finite-state whisper interaction protocol."""

    params_type = InWhisperParams
    params: InWhisperParams | ModeParams = InWhisperParams()

    def select_task(self, belief_state, action_memory) -> Task | None:
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

        task = self._select_task_impl(belief_state, state, tick, action_memory)
        _log_fsm_transition(belief_state, state, old_fsm_state)
        return task

    def _select_task_impl(
        self,
        belief_state,
        state: WhisperModeState,
        tick: int,
        action_memory,
    ) -> Task | None:
        if _forced_ejected(belief_state, state):
            _complete_mode(belief_state, "forced_ejection", state)
            return IdleTask()

        if _protocol_timed_out(state, tick):
            _transition_to_exit(belief_state, state, "protocol_timeout")

        entry_task = _entry_request_task(belief_state, state, self.params)
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
            return self._color_exchange_task(belief_state, state, action_memory)
        if state.fsm_state == "EVALUATE":
            return self._evaluate_task(belief_state, state)
        if state.fsm_state == "ROLE_EXCHANGE":
            return self._role_exchange_task(belief_state, state, action_memory)
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
        key_partner_id = _key_exchange_target_id(belief_state)
        created_by_us = _key_exchange_created_by_us(belief_state)
        state.created_by_us = created_by_us

        state.occupants_at_entry = list(occupants)
        if state.protocol == "key_exchange" and key_partner_id is not None:
            state.target_occupant = key_partner_id if key_partner_id in occupants else None
        else:
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
        if (
            state.protocol == "key_exchange"
            and key_partner_id is not None
            and state.target_occupant == key_partner_id
        ):
            _log_protocol_selected(
                belief_state,
                state,
                occupants,
                "key_exchange_known_partner_direct_role_offer",
            )
            state.fsm_state = "ROLE_EXCHANGE"
            return IdleTask()
        if state.protocol == "key_exchange" and key_partner_id is not None:
            _log_protocol_selected(
                belief_state,
                state,
                occupants,
                (
                    "key_exchange_created_wait_for_partner"
                    if created_by_us
                    else "key_exchange_wait_for_partner"
                ),
            )
            state.fsm_state = "WAIT_FOR_OCCUPANT"
            return IdleTask()

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
            key_partner_id = _key_exchange_target_id(belief_state)
            if state.protocol == "key_exchange" and key_partner_id is not None:
                if key_partner_id not in occupants:
                    state.target_occupant = None
                    state.hostile_present = _hostile_or_unknown_present(
                        candidates, state.target_occupant, knowledge, my_team,
                    )
                    if state.protocol == "key_exchange":
                        return _key_exchange_wait_task(
                            belief_state,
                            state,
                            tick,
                            candidates,
                        )
                    return IdleTask()
                state.target_occupant = key_partner_id
            else:
                state.target_occupant = _select_whisper_target(
                    candidates, knowledge, my_team, key_partner_id,
                )
            state.hostile_present = _hostile_or_unknown_present(
                candidates, state.target_occupant, knowledge, my_team,
            )
            state.fsm_state = "ASSESS"

        if state.protocol == "key_exchange":
            return _key_exchange_wait_task(belief_state, state, tick, candidates)
        return IdleTask()

    def _assess_task(self, belief_state, state: WhisperModeState) -> Task:
        my_role = _my_role(belief_state)
        occupants = _current_occupants(belief_state)

        if state.messages_sent == 0:
            llm_task = _llm_whisper_task(
                belief_state,
                state,
                self.params,
                {"send_whisper", "exit_whisper", "hold"},
            )
            if llm_task is not None:
                return llm_task

        if state.protocol == "key_exchange":
            key_partner_id = _key_exchange_target_id(belief_state)
            if key_partner_id is not None:
                my_id = _my_player_id(belief_state)
                candidates = [
                    pid for pid in occupants if pid is not None and pid != my_id
                ]
                if key_partner_id not in occupants:
                    state.target_occupant = None
                    state.fsm_state = "WAIT_FOR_OCCUPANT"
                    return IdleTask()
                state.target_occupant = key_partner_id

        if (
            len(occupants) > 2
            and state.hostile_present
            and _is_key_role(my_role)
            and not (
                state.protocol == "key_exchange"
                and state.target_occupant == _key_exchange_target_id(belief_state)
            )
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

        if _is_key_role(my_role):
            _log_protocol_selected(
                belief_state,
                state,
                occupants,
                "key_role_unknown_target_role_probe",
            )
            state.fsm_state = "ROLE_EXCHANGE"
            return IdleTask()

        _log_protocol_selected(belief_state, state, occupants, "unknown_target_color_exchange")
        state.fsm_state = "COLOR_EXCHANGE"
        return IdleTask()

    def _color_exchange_task(
        self,
        belief_state,
        state: WhisperModeState,
        action_memory,
    ) -> Task:
        tick = _tick(belief_state)

        active_task = _active_exchange_task_or_finalize(
            belief_state,
            state,
            action_memory,
            tick,
            {"color_offer", "color_accept"},
        )
        if active_task is not None:
            return active_task

        if _exchange_completed_since(
            belief_state,
            "swapped_colors",
            state.waiting_for_response_since,
        ):
            state.color_exchange_completed = True
            _log_exchange_outcome(
                belief_state,
                state,
                "color",
                "complete",
                state.target_occupant,
                None,
                server_confirmed=True,
            )
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
                server_confirmed=False,
            )
            _transition_to_exit(belief_state, state, "color_exchange_timeout")
            return IdleTask()

        llm_task = _llm_whisper_task(
            belief_state,
            state,
            self.params,
            {"offer_color", "accept_color", "exit_whisper", "hold"},
        )
        if llm_task is not None:
            return llm_task

        if _pending_offer(belief_state, "color"):
            target_index = _offer_index("color", state.target_occupant, belief_state)
            if target_index is None:
                return IdleTask()
            if _exchange_action_on_cooldown(state, tick):
                return IdleTask()
            return _begin_exchange_menu_task(state, tick, "color_accept", target_index)

        if not state.color_exchange_initiated:
            if _exchange_action_on_cooldown(state, tick):
                return IdleTask()
            return _begin_exchange_menu_task(state, tick, "color_offer")

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

    def _role_exchange_task(
        self,
        belief_state,
        state: WhisperModeState,
        action_memory,
    ) -> Task:
        tick = _tick(belief_state)

        active_task = _active_exchange_task_or_finalize(
            belief_state,
            state,
            action_memory,
            tick,
            {"role_offer", "role_accept"},
        )
        if active_task is not None:
            return active_task

        if _exchange_completed_since(
            belief_state,
            "shared_roles",
            state.waiting_for_response_since,
        ):
            state.role_exchange_completed = True
            _log_exchange_outcome(
                belief_state,
                state,
                "role",
                "complete",
                state.target_occupant,
                None,
                server_confirmed=True,
            )
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
                server_confirmed=False,
            )
            _transition_to_exit(belief_state, state, "role_exchange_timeout")
            return IdleTask()

        llm_task = _llm_whisper_task(
            belief_state,
            state,
            self.params,
            {"offer_role", "accept_role", "exit_whisper", "hold"},
        )
        if llm_task is not None:
            return llm_task

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
                    server_confirmed=False,
                )
                _transition_to_exit(belief_state, state, "role_offer_rejected")
                return IdleTask()

            if target_index is None:
                return IdleTask()
            if _exchange_action_on_cooldown(state, tick):
                return IdleTask()
            return _begin_exchange_menu_task(state, tick, "role_accept", target_index)

        if state.protocol == "key_exchange":
            key_partner_id = _key_exchange_target_id(belief_state)
            if key_partner_id is not None and key_partner_id not in _current_occupants(
                belief_state
            ):
                state.target_occupant = None
                state.fsm_state = "WAIT_FOR_OCCUPANT"
                return IdleTask()

        if not state.role_exchange_initiated:
            if _exchange_action_on_cooldown(state, tick):
                return IdleTask()
            return _begin_exchange_menu_task(state, tick, "role_offer")

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


def _begin_exchange_menu_task(
    state: WhisperModeState,
    tick: int,
    kind: str,
    target_index: int | None = None,
) -> Task:
    state.active_exchange_task = kind
    state.active_exchange_target_index = target_index
    state.active_exchange_started_tick = tick
    return _exchange_menu_task(kind, target_index)


def _active_exchange_task_or_finalize(
    belief_state,
    state: WhisperModeState,
    action_memory,
    tick: int,
    active_kinds: set[str],
) -> Task | None:
    kind = state.active_exchange_task
    if kind is None or kind not in active_kinds:
        return None

    task = _exchange_menu_task(kind, state.active_exchange_target_index)
    if (
        getattr(action_memory, "sequence_step", 0) < _EXCHANGE_MENU_STEPS[kind]
        or getattr(action_memory, "menu_button_active", False)
    ):
        return task

    _finalize_exchange_menu_task(belief_state, state, tick)
    return None


def _exchange_menu_task(kind: str, target_index: int | None) -> Task:
    if kind == "color_offer":
        return OfferColorExchangeTask()
    if kind == "role_offer":
        return OfferRoleExchangeTask()
    if kind == "color_accept" and target_index is not None:
        return AcceptColorExchangeTask(player_index=target_index)
    if kind == "role_accept" and target_index is not None:
        return AcceptRoleExchangeTask(player_index=target_index)
    return IdleTask()


def _key_exchange_wait_task(
    belief_state,
    state: WhisperModeState,
    tick: int,
    candidates: list[PlayerID] | None = None,
) -> Task:
    if _exchange_completed_since(belief_state, "shared_roles", state.entered_tick):
        state.role_exchange_completed = True
        _log_exchange_outcome(
            belief_state,
            state,
            "role",
            "complete",
            state.target_occupant,
            None,
            server_confirmed=True,
        )
        _transition_to_exit(belief_state, state, "role_exchange_complete")
        return IdleTask()

    if candidates is None:
        my_id = _my_player_id(belief_state)
        candidates = [
            pid
            for pid in _current_occupants(belief_state)
            if pid is not None and pid != my_id
        ]

    key_partner_id = _key_exchange_target_id(belief_state)
    if (
        key_partner_id is not None
        and candidates
        and key_partner_id not in candidates
        and state.occupants_at_entry
    ):
        return _key_exchange_ping_task(belief_state, state, tick)

    elapsed = max(0, tick - state.entered_tick)
    if state.created_by_us:
        phase_tick = elapsed % (
            KEY_IN_WHISPER_GRANT_TICKS
            + KEY_IN_WHISPER_OFFER_TICKS
            + KEY_IN_WHISPER_IDLE_TICKS
        )
        if phase_tick < KEY_IN_WHISPER_GRANT_TICKS:
            return BlindGrantEntryTask()
        if phase_tick < KEY_IN_WHISPER_GRANT_TICKS + KEY_IN_WHISPER_OFFER_TICKS:
            return BlindOfferRoleExchangeTask()
        return IdleTask()

    if elapsed >= KEY_IN_WHISPER_REQUESTER_SETTLE_TICKS:
        phase_tick = (elapsed - KEY_IN_WHISPER_REQUESTER_SETTLE_TICKS) % (
            KEY_IN_WHISPER_OFFER_TICKS + KEY_IN_WHISPER_IDLE_TICKS
        )
        if phase_tick < KEY_IN_WHISPER_OFFER_TICKS:
            return BlindOfferRoleExchangeTask()
        return IdleTask()

    return _key_exchange_ping_task(belief_state, state, tick)


def _key_exchange_ping_task(
    belief_state,
    state: WhisperModeState,
    tick: int,
) -> Task:
    del belief_state
    if (
        state.messages_sent == 0
        or tick - state.waiting_for_response_since >= ACTION_COOLDOWN_TICKS
    ):
        state.messages_sent += 1
        state.waiting_for_response_since = tick
        return SendMessageTask(text="SEND ME", channel="whisper")
    return IdleTask()


def _finalize_exchange_menu_task(
    belief_state,
    state: WhisperModeState,
    tick: int,
) -> None:
    kind = state.active_exchange_task
    target_index = state.active_exchange_target_index
    if kind is None:
        return

    # The final confirm happened on the previous act tick. Start the response
    # window just before this belief tick so immediately observed completion
    # events are not missed.
    state.waiting_for_response_since = max(state.active_exchange_started_tick, tick - 1)
    exchange_type = "role" if kind.startswith("role_") else "color"
    action = "accept" if kind.endswith("_accept") else "offer"
    target = (
        player_index_to_id(target_index, belief_state)
        if target_index is not None
        else state.target_occupant
    )
    our_offer = None if action == "accept" else _offered_value(exchange_type, belief_state)

    if exchange_type == "color":
        state.color_exchange_initiated = True
    else:
        state.role_exchange_initiated = True

    _log_exchange_outcome(
        belief_state,
        state,
        exchange_type,
        action,
        target,
        our_offer,
        server_confirmed=False,
    )
    _clear_active_exchange_task(state)


def _clear_active_exchange_task(state: WhisperModeState) -> None:
    state.active_exchange_task = None
    state.active_exchange_target_index = None
    state.active_exchange_started_tick = 0


def _protocol_from_context(
    belief_state,
    previous: WhisperModeState | None,
) -> str:
    """Infer the intended whisper protocol from the mode that entered whisper."""

    if _active_probe_context_indicates_key_exchange(belief_state):
        return "key_exchange"

    directive = belief_state.extra.get(LAST_NON_WHISPER_DIRECTIVE) or getattr(
        belief_state,
        "inferences",
        {},
    ).get(LAST_NON_WHISPER_DIRECTIVE)
    params = directive.params if isinstance(directive, ModeDirective) else None

    explicit_protocol = getattr(params, "protocol", None)
    if explicit_protocol in PROTOCOL_TIMEOUTS:
        return explicit_protocol

    if isinstance(params, TimeWasteParams) or getattr(params, "protocol", None) == "stall":
        return "stall"

    if isinstance(params, ProbeTargetParams) or hasattr(params, "skip_color_exchange"):
        if getattr(params, "skip_color_exchange", False):
            return "key_exchange"
        if _intent_name(getattr(params, "intent", None)) == "VERIFY_SELF_AS_SPY":
            return "quick_verify"
        if _my_role(belief_state) is Role.SPY:
            return "infiltration"

    if isinstance(params, ProbeSystematicParams) or hasattr(params, "intent"):
        if _intent_name(getattr(params, "intent", None)) == "FIND_KEY_PARTNER":
            return "key_exchange"
        if _intent_name(getattr(params, "intent", None)) == "VERIFY_SELF_AS_SPY":
            return "quick_verify"
        if _my_role(belief_state) is Role.SPY:
            return "infiltration"

    strategic_state = _strategic_state(belief_state)
    objective = getattr(strategic_state, "current_objective", None)
    if (
        _objective_name(objective) == "COMPLETE_KEY_EXCHANGE"
        and _key_partner_id(belief_state) is not None
    ):
        return "key_exchange"
    if (
        _is_key_role(_my_role(belief_state))
        and _key_partner_id(belief_state) is not None
        and not bool(getattr(strategic_state, "key_exchange_done", False))
    ):
        return "key_exchange"

    if isinstance(previous, WhisperModeState) and previous.protocol in PROTOCOL_TIMEOUTS:
        return previous.protocol
    return "standard"


def _active_probe_context_indicates_key_exchange(belief_state) -> bool:
    state = getattr(belief_state, "extra", {}).get(PROBE_STATE)
    if not isinstance(state, dict):
        return False
    completed_tick = state.get("completed_tick")
    if (
        state.get("completed")
        and isinstance(completed_tick, int)
        and _tick(belief_state) - completed_tick > WAIT_FOR_OCCUPANT_TIMEOUT_TICKS
    ):
        return False
    intent = str(state.get("intent", "")).upper()
    return bool(state.get("skip_color_exchange")) or intent == "FIND_KEY_PARTNER"


def _key_exchange_target_id(belief_state) -> PlayerID | None:
    key_partner_id = _key_partner_id(belief_state)
    if key_partner_id is not None:
        return key_partner_id

    state = getattr(belief_state, "extra", {}).get(PROBE_STATE)
    if isinstance(state, dict):
        intent = str(state.get("intent", "")).upper()
        if state.get("skip_color_exchange") or intent == "FIND_KEY_PARTNER":
            completed_tick = state.get("completed_tick")
            if (
                state.get("completed")
                and isinstance(completed_tick, int)
                and _tick(belief_state) - completed_tick > WAIT_FOR_OCCUPANT_TIMEOUT_TICKS
            ):
                return None
            target = state.get("target")
            if isinstance(target, tuple) and len(target) == 2:
                return target
            if isinstance(target, list) and len(target) == 2:
                return (target[0], target[1])
            return None

    directive = belief_state.extra.get(LAST_NON_WHISPER_DIRECTIVE) or getattr(
        belief_state,
        "inferences",
        {},
    ).get(LAST_NON_WHISPER_DIRECTIVE)
    params = directive.params if isinstance(directive, ModeDirective) else None
    if params is not None and (
        getattr(params, "skip_color_exchange", False)
        or _intent_name(getattr(params, "intent", None)) == "FIND_KEY_PARTNER"
    ):
        target = getattr(params, "target", None)
        if isinstance(target, tuple) and len(target) == 2:
            return target

    return None


def _key_exchange_created_by_us(belief_state) -> bool:
    state = getattr(belief_state, "extra", {}).get(PROBE_STATE)
    if isinstance(state, dict) and state.get("action") == "whisper_created":
        return True

    directive = belief_state.extra.get(LAST_NON_WHISPER_DIRECTIVE) or getattr(
        belief_state,
        "inferences",
        {},
    ).get(LAST_NON_WHISPER_DIRECTIVE)
    params = directive.params if isinstance(directive, ModeDirective) else None
    return bool(getattr(params, "open_in_place", False)) and not bool(
        getattr(params, "request_only", False)
    )


def _intent_name(intent) -> str:
    return getattr(intent, "name", str(intent)).upper()


def _objective_name(objective) -> str:
    return getattr(objective, "name", str(objective)).upper()


def _forced_ejected(belief_state, state: WhisperModeState) -> bool:
    if state.fsm_state == "EXIT" or state.exit_initiated:
        return False
    if getattr(belief_state, "view", None) is View.WHISPER:
        return False
    return state.fsm_state != "ENTER" or bool(state.occupants_at_entry)


def _protocol_timed_out(state: WhisperModeState, tick: int) -> bool:
    timeout = PROTOCOL_TIMEOUTS.get(state.protocol, PROTOCOL_TIMEOUTS["standard"])
    if state.protocol == "key_exchange" and state.fsm_state == "WAIT_FOR_OCCUPANT":
        timeout = WAIT_FOR_OCCUPANT_TIMEOUT_TICKS
    return state.fsm_state != "EXIT" and tick - state.entered_tick > timeout


def _entry_request_task(
    belief_state,
    state: WhisperModeState,
    params: InWhisperParams | ModeParams,
) -> Task | None:
    if getattr(belief_state, "view", None) is not View.WHISPER:
        return None

    pending_entry = getattr(belief_state, "pending_entry", None)
    if pending_entry is None:
        return None

    player_id = player_index_to_id(pending_entry, belief_state)
    if state.protocol == "key_exchange":
        key_target_id = _key_exchange_target_id(belief_state)
        if key_target_id is not None:
            if player_id == key_target_id:
                _log_entry_request_decision(
                    belief_state,
                    state,
                    pending_entry,
                    player_id,
                    decision="grant_key_partner",
                )
                _log_entry_granted(belief_state, state, player_id)
                return GrantEntryTask()
            _log_entry_request_decision(
                belief_state,
                state,
                pending_entry,
                player_id,
                decision="deny_non_partner_key_exchange",
            )
            return None

    llm_task = _llm_whisper_task(
        belief_state,
        state,
        params,
        {"grant_entry", "deny_entry", "hold"},
    )
    if llm_task is not None:
        _log_entry_request_decision(
            belief_state,
            state,
            pending_entry,
            player_id,
            decision=f"llm_{type(llm_task).__name__}",
        )
        return llm_task

    my_id = _my_player_id(belief_state)
    other_occupants = [
        occupant
        for occupant in _current_occupants(belief_state)
        if occupant is not None and occupant != my_id
    ]
    if not other_occupants or player_id == state.target_occupant:
        _log_entry_request_decision(
            belief_state,
            state,
            pending_entry,
            player_id,
            decision="grant_empty_or_target",
        )
        _log_entry_granted(belief_state, state, player_id)
        return GrantEntryTask()

    if state.fsm_state in SENSITIVE_ENTRY_STATES:
        _log_entry_request_decision(
            belief_state,
            state,
            pending_entry,
            player_id,
            decision="hold_sensitive_state",
        )
        return None
    if state.protocol == "key_exchange":
        _log_entry_request_decision(
            belief_state,
            state,
            pending_entry,
            player_id,
            decision="hold_key_exchange",
        )
        return None

    knowledge = _player_knowledge(belief_state)
    if _is_probable_ally(player_id, knowledge, _my_team(belief_state)):
        _log_entry_request_decision(
            belief_state,
            state,
            pending_entry,
            player_id,
            decision="grant_probable_ally",
        )
        _log_entry_granted(belief_state, state, player_id)
        return GrantEntryTask()
    record = knowledge.get(player_id) if player_id is not None else None
    if record is None or record.team is None:
        _log_entry_request_decision(
            belief_state,
            state,
            pending_entry,
            player_id,
            decision="grant_unknown_player",
        )
        _log_entry_granted(belief_state, state, player_id)
        return GrantEntryTask()
    _log_entry_request_decision(
        belief_state,
        state,
        pending_entry,
        player_id,
        decision="deny_known_nonally",
    )
    return None


def _llm_whisper_task(
    belief_state,
    state: WhisperModeState,
    params: InWhisperParams | ModeParams,
    allowed_actions: set[str],
) -> Task | None:
    control = getattr(params, "llm_control", "off")
    provider_name = getattr(params, "llm_provider", "hold")
    if control not in {"shadow", "whispers", "all"}:
        return None

    from agents.eurydice.llm_provider import make_provider

    provider = make_provider(provider_name)
    try:
        provider_cooldown = int(
            getattr(provider, "decision_cooldown_ticks", 0) or 0
        )
    except (TypeError, ValueError):
        provider_cooldown = 0
    cooldown_ticks = max(LLM_WHISPER_DECISION_COOLDOWN_TICKS, provider_cooldown)

    tick = _tick(belief_state)
    if (
        state.last_llm_action_tick
        and tick - state.last_llm_action_tick < cooldown_ticks
    ):
        return None

    from agents.eurydice.llm_context import build_llm_context
    from agents.eurydice.llm_executor import task_for_whisper_decision
    from agents.eurydice.llm_prompts import build_prompt
    from agents.eurydice.llm_validator import validate_and_trace_llm_decision

    context = build_llm_context(belief_state)
    prompt = build_prompt(context, surface="whisper")
    raw_decision = provider.decide(context, prompt)
    result = validate_and_trace_llm_decision(
        belief_state,
        raw_decision,
        context=context,
        fallback_action="hold",
        source=f"runtime:{control}:{provider.name}:whisper",
    )
    action = (
        result.decision.get("action")
        if result.accepted
        else raw_decision.get("action")
        if isinstance(raw_decision, dict)
        else None
    )
    state.last_llm_action_tick = tick
    state.last_llm_action = str(action) if action is not None else None

    if control == "shadow" or not result.accepted:
        return None
    if result.decision.get("action") not in allowed_actions:
        return None

    task = task_for_whisper_decision(result.decision, belief_state)
    action_name = result.decision.get("action")
    if action_name == "send_whisper":
        state.messages_sent += 1
        state.waiting_for_response_since = tick
    if action_name == "grant_entry":
        _log_entry_granted(
            belief_state,
            state,
            player_index_to_id(getattr(belief_state, "pending_entry", None), belief_state),
        )
    if action_name in {"deny_entry", "exit_whisper"}:
        _transition_to_exit(belief_state, state, "llm_exit_or_deny")
    # Exchange decisions need to update FSM state (active_exchange_task,
    # *_exchange_initiated) so the menu sequence is tracked across ticks.
    # task_for_whisper_decision returns the raw exchange task; rewrap it
    # through _begin_exchange_menu_task to set state correctly.
    if action_name == "offer_role":
        return _begin_exchange_menu_task(state, tick, "role_offer")
    if action_name == "offer_color":
        return _begin_exchange_menu_task(state, tick, "color_offer")
    if action_name == "accept_role" and isinstance(task, AcceptRoleExchangeTask):
        return _begin_exchange_menu_task(state, tick, "role_accept", task.player_index)
    if action_name == "accept_color" and isinstance(task, AcceptColorExchangeTask):
        return _begin_exchange_menu_task(state, tick, "color_accept", task.player_index)
    return task


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
        strategic_state = _strategic_state(belief_state)
        verified_ally = getattr(strategic_state, "verified_ally", None)
        if offerer_id is not None and offerer_id == verified_ally:
            return True
        return spy_should_accept_role_exchange(
            knowledge.get(offerer_id) if offerer_id is not None else None,
            my_team,
            verified_ally,
            _urgency(belief_state),
        )

    if offerer_id is None:
        return False
    record = knowledge.get(offerer_id)
    if record is not None and record.team is not None:
        return my_team is not None and record.team is my_team
    return True


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
    if pending.get(kind, False):
        return True
    active_field = "active_color_offers" if kind == "color" else "active_role_offers"
    return bool(getattr(belief_state, active_field, []) or [])


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

    strategic_state = _strategic_state(belief_state)
    objective = getattr(strategic_state, "current_objective", None)
    objective_name = getattr(objective, "name", str(objective)).upper()
    if objective_name in {"FIND_KEY_PARTNER", "COMPLETE_KEY_EXCHANGE"}:
        return True

    key_partner_id = getattr(strategic_state, "key_partner_id", None)
    return key_partner_id is not None and key_partner_id == state.target_occupant


def _key_partner_id(belief_state) -> PlayerID | None:
    strategic_state = _strategic_state(belief_state)
    key_partner_id = getattr(strategic_state, "key_partner_id", None)
    if isinstance(key_partner_id, tuple) and len(key_partner_id) == 2:
        return key_partner_id
    return None


def _strategic_state(belief_state):
    return belief_state.extra.get(STRATEGIC_STATE) or getattr(
        belief_state,
        "inferences",
        {},
    ).get(STRATEGIC_STATE)


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
    strategic_state = _strategic_state(belief_state)
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
    _clear_active_exchange_task(state)
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
    *,
    server_confirmed: bool,
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
                "server_confirmed": server_confirmed,
            },
            LogLevel.DECISIONS,
        )


def _log_entry_request_decision(
    belief_state,
    state: WhisperModeState,
    pending_entry: int | None,
    player_id: PlayerID | None,
    *,
    decision: str,
) -> None:
    key_partner_id = _key_partner_id(belief_state)
    my_id = _my_player_id(belief_state)
    occupants = _current_occupants(belief_state)
    payload = {
        "decision": decision,
        "pending_entry": pending_entry,
        "player_id": _player_id_value(player_id),
        "protocol": state.protocol,
        "fsm_state": state.fsm_state,
        "target": _player_id_value(state.target_occupant),
        "key_partner": _player_id_value(key_partner_id),
        "occupants": [_player_id_value(occupant) for occupant in occupants],
        "other_occupants": [
            _player_id_value(occupant)
            for occupant in occupants
            if occupant is not None and occupant != my_id
        ],
    }
    signature = (
        pending_entry,
        payload["player_id"],
        state.protocol,
        state.fsm_state,
        payload["target"],
        payload["key_partner"],
        decision,
        tuple(
            tuple(occupant) if isinstance(occupant, list) else occupant
            for occupant in payload["occupants"]
        ),
    )
    if belief_state.extra.get(_WHISPER_ENTRY_DECISION_LOGGED) == signature:
        return
    belief_state.extra[_WHISPER_ENTRY_DECISION_LOGGED] = signature
    if logger:
        logger.event("entry_request_decision", payload, LogLevel.DECISIONS)


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
    "InWhisperParams",
    "InWhisperMode",
    "_find_target_index",
    "_is_key_role",
    "_is_probable_ally",
    "_select_whisper_target",
]
