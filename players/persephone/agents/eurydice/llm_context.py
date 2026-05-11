"""Serializable LLM-control context for Eurydice.

This module does not call an LLM.  It defines the compact, JSON-safe
decision packet that future LLM control can consume, plus the constrained
action schema it must return.  Keeping this contract deterministic lets us
test and trace the interface before handing decisions to a model.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Literal

from orpheus.belief_state import BeliefState, ChatMessageRecord
from orpheus.perception.types import View

from agents.eurydice.ext_keys import (
    LAST_DIRECTIVE_MODE,
    PROBE_FAILURES,
    PROBE_STATE,
    PLAYER_KNOWLEDGE,
)
from agents.eurydice.knowledge import PlayerKnowledge
from agents.eurydice.meta_decide import build_strategic_state, player_index_to_id
from agents.eurydice.strategic_state import StrategicState
from agents.eurydice.types import PlayerID


SCHEMA_VERSION = "eurydice.llm_context.v2"
DECISION_SCHEMA_VERSION = "eurydice.llm_decision.v2"

LLM_ACTIONS: tuple[str, ...] = (
    "hold",
    "probe_player",
    "create_whisper",
    "join_whisper",
    "grant_entry",
    "deny_entry",
    "send_whisper",
    "send_global",
    "open_global",
    "open_info",
    "accept_color",
    "accept_role",
    "offer_color",
    "offer_role",
    "reject_offer",
    "exit_whisper",
    "seek_leadership",
    "select_hostage",
    "move_to",
)


@dataclass(frozen=True)
class LLMPlayerSnapshot:
    """Compact social/identity state for one player."""

    player_id: list[int]
    index: int | None = None
    is_self: bool = False
    room: str | None = None
    team: str | None = None
    team_source: str | None = None
    team_confidence: float = 0.0
    role: str | None = None
    role_source: str | None = None
    trust_level: str | None = None
    last_seen_position: list[int] | None = None
    visible_position: list[int] | None = None
    in_current_whisper: bool = False
    last_seen_in_whisper_tick: int | None = None
    exchanged_color_with_us: bool = False
    exchanged_role_with_us: bool = False
    times_interacted: int = 0
    behavioral_flags: list[str] = field(default_factory=list)
    is_leader: bool = False


@dataclass(frozen=True)
class LLMMessageSnapshot:
    """Recent chat message, already clipped for prompt size."""

    tick: int
    channel: str
    text: str
    sender_index: int | None = None
    occupants: list[int] | None = None


@dataclass(frozen=True)
class LLMDecisionContext:
    """Top-level prompt payload for future LLM strategy control."""

    schema_version: str
    tick: int
    view: str
    phase: str
    round_number: int
    timer_secs: int | None
    self: dict[str, Any]
    strategy: dict[str, Any]
    match: dict[str, Any]
    runtime: dict[str, Any]
    players: list[LLMPlayerSnapshot]
    recent_messages: list[LLMMessageSnapshot]
    legal_actions: list[str]
    action_affordances: dict[str, dict[str, Any]]
    hard_constraints: list[str]


@dataclass(frozen=True)
class LLMDecision:
    """Constrained response shape expected from a future LLM controller."""

    schema_version: str = DECISION_SCHEMA_VERSION
    action: Literal[
        "hold",
        "probe_player",
        "create_whisper",
        "join_whisper",
        "grant_entry",
        "deny_entry",
        "send_whisper",
        "send_global",
        "open_global",
        "open_info",
        "accept_color",
        "accept_role",
        "offer_color",
        "offer_role",
        "reject_offer",
        "exit_whisper",
        "seek_leadership",
        "select_hostage",
        "move_to",
    ] = "hold"
    surface: str | None = None
    target: list[int] | None = None
    destination: list[int] | None = None
    hostage_targets: list[list[int]] | None = None
    message: str | None = None
    reveal_color: bool = False
    reveal_role: bool = False
    confidence: float = 0.0
    rationale: str = ""


def build_llm_context(
    belief_state: BeliefState,
    strategic_state: StrategicState | None = None,
    *,
    max_messages: int = 8,
) -> dict[str, Any]:
    """Build a JSON-safe LLM decision context from current Eurydice state."""

    state = strategic_state or build_strategic_state(belief_state)
    context = LLMDecisionContext(
        schema_version=SCHEMA_VERSION,
        tick=int(getattr(belief_state, "tick", 0) or 0),
        view=_name(getattr(belief_state, "view", None)) or "unknown",
        phase=_name(state.current_phase) or "unknown",
        round_number=int(state.current_round or 0),
        timer_secs=getattr(belief_state, "timer_secs", None),
        self=_self_snapshot(belief_state, state),
        strategy=_strategy_snapshot(state),
        match=_match_snapshot(belief_state, state),
        runtime=_runtime_snapshot(belief_state),
        players=_player_snapshots(belief_state),
        recent_messages=_recent_messages(belief_state, max_messages),
        legal_actions=_legal_actions(belief_state),
        action_affordances=_action_affordances(belief_state),
        hard_constraints=_hard_constraints(belief_state),
    )
    return _json_safe(asdict(context))


def llm_decision_schema() -> dict[str, Any]:
    """Return a small JSON-schema-like contract for future LLM outputs."""

    return {
        "schema_version": DECISION_SCHEMA_VERSION,
        "type": "object",
        "required": ["schema_version", "action", "confidence", "rationale"],
        "properties": {
            "schema_version": {"const": DECISION_SCHEMA_VERSION},
            "action": {"enum": list(LLM_ACTIONS)},
            "surface": {
                "description": "Optional control surface such as probe, whisper, or global.",
                "type": ["string", "null"],
                "maxLength": 32,
            },
            "target": {
                "description": "Optional PlayerID as [color, shape].",
                "type": ["array", "null"],
                "items": {"type": "integer"},
                "minItems": 2,
                "maxItems": 2,
            },
            "destination": {
                "description": "Optional world coordinate as [x, y] for move_to.",
                "type": ["array", "null"],
                "items": {"type": "integer"},
                "minItems": 2,
                "maxItems": 2,
            },
            "hostage_targets": {
                "description": "Optional hostage PlayerIDs for select_hostage.",
                "type": ["array", "null"],
                "items": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 2,
                    "maxItems": 2,
                },
            },
            "message": {
                "description": "Optional ASCII chat text, already game-safe.",
                "type": ["string", "null"],
                "maxLength": 48,
            },
            "reveal_color": {"type": "boolean"},
            "reveal_role": {"type": "boolean"},
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "rationale": {
                "description": "Short explanation for trace/debug review.",
                "type": "string",
                "maxLength": 240,
            },
        },
        "additionalProperties": False,
    }


def _self_snapshot(
    belief_state: BeliefState,
    state: StrategicState,
) -> dict[str, Any]:
    player_id = state.my_player_id
    return {
        "player_id": _player_id(player_id),
        "index": getattr(belief_state, "my_index", None),
        "color": getattr(belief_state, "my_color", None),
        "shape": _name(getattr(belief_state, "my_shape", None)),
        "role": _name(state.my_role),
        "team": _name(state.my_team),
        "room": _name(state.my_room),
        "is_leader": bool(getattr(belief_state, "is_leader", False)),
        "position": _position(getattr(belief_state, "position", None)),
    }


def _strategy_snapshot(state: StrategicState) -> dict[str, Any]:
    return {
        "objective": _name(state.current_objective),
        "urgency": _name(state.urgency),
        "key_partner_found": bool(state.key_partner_found),
        "key_partner_id": _player_id(state.key_partner_id),
        "key_partner_room": _name(state.key_partner_room),
        "key_exchange_done": bool(state.key_exchange_done),
        "enemy_key_role_id": _player_id(state.enemy_key_role_id),
        "enemy_key_room": _name(state.enemy_key_role_room),
        "enemy_key_exchange_likely": bool(state.enemy_key_exchange_likely),
        "verified_ally": _player_id(state.verified_ally),
        "probe_coverage_fraction": float(state.probe_coverage_fraction),
        "players_unprobed_in_room": [
            _player_id(player_id) for player_id in state.players_unprobed_in_room
        ],
    }


def _match_snapshot(
    belief_state: BeliefState,
    state: StrategicState,
) -> dict[str, Any]:
    return {
        "player_count": getattr(belief_state, "player_count", None),
        "room_size": _position(getattr(belief_state, "room_size", None)),
        "round_schedule": [list(item) for item in state.round_schedule],
        "match_roles": list(state.match_roles),
        "missing_roles": list(state.missing_roles),
        "echo_substitutions": [list(item) for item in state.echo_substitutions],
        "spy_in_game_config": state.spy_in_game_config,
    }


def _runtime_snapshot(belief_state: BeliefState) -> dict[str, Any]:
    pending_entry = getattr(belief_state, "pending_entry", None)
    probe_state = getattr(belief_state, "extra", {}).get(PROBE_STATE, {})
    return {
        "current_mode": _current_mode(belief_state),
        "current_task": _current_task(belief_state),
        "cooldowns": {
            str(key): int(value)
            for key, value in getattr(belief_state, "cooldowns", {}).items()
            if isinstance(value, int)
        },
        "pending_entry": _indexed_player_ref(pending_entry, belief_state),
        "active_color_offers": _indexed_player_refs(
            getattr(belief_state, "active_color_offers", []),
            belief_state,
        ),
        "active_role_offers": _indexed_player_refs(
            getattr(belief_state, "active_role_offers", []),
            belief_state,
        ),
        "current_whisper_occupants": _indexed_player_refs(
            getattr(belief_state, "whisper_occupants", []),
            belief_state,
        ),
        "pending_offers": dict(getattr(belief_state, "pending_offers", {}) or {}),
        "last_exchange_event": _json_safe(
            getattr(belief_state, "last_exchange_event", None)
        ),
        "hostage_options": _hostage_options_snapshot(belief_state),
        "probe_state": _json_safe(probe_state if isinstance(probe_state, dict) else {}),
        "probe_failures": _probe_failures_snapshot(belief_state),
    }


def _action_affordances(belief_state: BeliefState) -> dict[str, dict[str, Any]]:
    legal = set(_legal_actions(belief_state))
    occupants = _indexed_player_refs(
        getattr(belief_state, "whisper_occupants", []),
        belief_state,
    )
    pending_entry = _indexed_player_ref(getattr(belief_state, "pending_entry", None), belief_state)
    return {
        action: {
            "legal": action in legal,
            "requires_target": action in _target_required_actions(belief_state),
            "requires_message": action in {"send_whisper", "send_global"},
            "requires_destination": action == "move_to",
            "requires_hostage_targets": action == "select_hostage",
            "requires_active_offer": action in {"accept_color", "accept_role"},
            "current_occupants": occupants if action.endswith("role") or action.endswith("color") else [],
            "pending_entry": pending_entry if action in {"grant_entry", "deny_entry"} else None,
            "hostage_options": (
                _hostage_options_snapshot(belief_state)
                if action == "select_hostage"
                else None
            ),
            "chat_cooldown": int(getattr(belief_state, "cooldowns", {}).get("chat", 0)),
        }
        for action in LLM_ACTIONS
    }


def _player_snapshots(belief_state: BeliefState) -> list[LLMPlayerSnapshot]:
    knowledge = _knowledge(belief_state)
    player_ids: set[PlayerID] = set(knowledge)

    index_by_id: dict[PlayerID, int] = {}
    for index, info in getattr(belief_state, "players", {}).items():
        player_id = player_index_to_id(index, belief_state)
        if player_id is None:
            continue
        player_ids.add(player_id)
        index_by_id[player_id] = int(index)

    if getattr(belief_state, "my_index", None) is not None:
        own_id = player_index_to_id(belief_state.my_index, belief_state)
        if own_id is not None:
            player_ids.add(own_id)
            index_by_id[own_id] = int(belief_state.my_index)

    snapshots: list[LLMPlayerSnapshot] = []
    for player_id in sorted(player_ids):
        record = knowledge.get(player_id)
        index = index_by_id.get(player_id)
        info = (
            getattr(belief_state, "players", {}).get(index)
            if index is not None
            else None
        )
        snapshots.append(_player_snapshot(belief_state, player_id, index, info, record))
    return snapshots


def _player_snapshot(
    belief_state: BeliefState,
    player_id: PlayerID,
    index: int | None,
    info: Any,
    record: PlayerKnowledge | None,
) -> LLMPlayerSnapshot:
    position = _position(getattr(info, "position", None)) if info is not None else None
    last_seen = (
        _position(record.last_seen_position)
        if record is not None and record.last_seen_position is not None
        else position
    )
    whisper_occupants = getattr(belief_state, "whisper_occupants", [])
    return LLMPlayerSnapshot(
        player_id=_player_id(player_id) or [int(player_id[0]), int(player_id[1])],
        index=index,
        is_self=_is_self(belief_state, player_id),
        room=_name(record.room if record is not None else getattr(info, "room", None)),
        team=_name(record.team if record is not None else getattr(info, "team", None)),
        team_source=_name(
            record.team_source if record is not None else getattr(info, "team_source", None)
        ),
        team_confidence=(
            float(record.team_confidence) if record is not None else 0.0
        ),
        role=_name(record.role if record is not None else getattr(info, "role", None)),
        role_source=_name(
            record.role_source if record is not None else getattr(info, "role_source", None)
        ),
        trust_level=_name(record.trust_level) if record is not None else None,
        last_seen_position=last_seen,
        visible_position=position,
        in_current_whisper=index in whisper_occupants if index is not None else False,
        last_seen_in_whisper_tick=(
            getattr(info, "last_seen_in_whisper", None) if info is not None else None
        ),
        exchanged_color_with_us=(
            bool(record.has_exchanged_colors_with_us) if record is not None else False
        ),
        exchanged_role_with_us=(
            bool(record.has_exchanged_roles_with_us) if record is not None else False
        ),
        times_interacted=int(record.times_interacted) if record is not None else 0,
        behavioral_flags=(
            sorted(record.behavioral_flags) if record is not None else []
        ),
        is_leader=bool(record.is_leader) if record is not None else False,
    )


def _recent_messages(
    belief_state: BeliefState,
    max_messages: int,
) -> list[LLMMessageSnapshot]:
    messages: list[ChatMessageRecord] = list(getattr(belief_state, "chat_history", []))
    clipped = messages[-max(0, max_messages):]
    return [
        LLMMessageSnapshot(
            tick=int(message.tick),
            channel=str(message.channel),
            text=str(message.text)[:80],
            sender_index=message.sender_index,
            occupants=list(message.occupants) if message.occupants is not None else None,
        )
        for message in clipped
    ]


def _legal_actions(belief_state: BeliefState) -> list[str]:
    view = getattr(belief_state, "view", View.UNKNOWN)
    if view is View.WHISPER:
        actions = [
            "hold",
            "send_whisper",
            "accept_color",
            "accept_role",
            "offer_color",
            "offer_role",
            "reject_offer",
            "exit_whisper",
        ]
        if getattr(belief_state, "pending_entry", None) is not None:
            actions.extend(["grant_entry", "deny_entry"])
        return actions
    if view is View.GLOBAL_CHAT:
        return ["hold", "send_global", "open_info", "seek_leadership"]
    if view is View.INFO_SCREEN:
        return ["hold", "open_global"]
    if view is View.HOSTAGE_SELECT:
        return ["hold", "select_hostage"]
    if view is View.LEADER_SUMMIT:
        return ["hold", "send_whisper"]
    if view in {View.PLAYING, View.WAITING_ENTRY}:
        return [
            "hold",
            "probe_player",
            "create_whisper",
            "join_whisper",
            "open_global",
            "open_info",
            "move_to",
        ]
    return ["hold"]


def _target_required_actions(belief_state: BeliefState) -> set[str]:
    actions = {
        "probe_player",
        "join_whisper",
        "grant_entry",
        "deny_entry",
        "accept_color",
        "accept_role",
        "offer_color",
        "offer_role",
    }
    if _single_non_self_whisper_occupant(belief_state) is not None:
        actions.discard("offer_color")
        actions.discard("offer_role")
    return actions


def _hard_constraints(belief_state: BeliefState) -> list[str]:
    constraints = [
        "Only claim mechanical exchange facts after parsed exchange or info-screen evidence.",
        "Treat role exchange as the only win-condition exchange mechanic.",
        "Do not reveal true role to a known enemy unless the selected strategy is deception or disruption.",
        "Do not reveal color when Spy is in config unless the strategy explicitly accepts Spy risk.",
        "Keep chat short, ASCII, and game-actionable.",
    ]
    if getattr(belief_state, "view", None) is View.HOSTAGE_SELECT:
        constraints.append("Do not initiate or join whispers while selecting hostages.")
    if getattr(belief_state, "view", None) is View.WHISPER:
        constraints.append("If hostile third occupants enter a sensitive exchange, exit or stall.")
    return constraints


def _knowledge(belief_state: BeliefState) -> dict[PlayerID, PlayerKnowledge]:
    raw = getattr(belief_state, "extra", {}).get(PLAYER_KNOWLEDGE, {})
    return raw if isinstance(raw, dict) else {}


def _current_mode(belief_state: BeliefState) -> str | None:
    raw = getattr(belief_state, "extra", {}).get(
        LAST_DIRECTIVE_MODE,
        getattr(belief_state, "inferences", {}).get(LAST_DIRECTIVE_MODE),
    )
    return str(raw) if raw is not None else None


def _current_task(belief_state: BeliefState) -> str | None:
    task = getattr(belief_state, "current_task", None)
    return type(task).__name__ if task is not None else None


def _indexed_player_ref(index: Any, belief_state: BeliefState) -> dict[str, Any] | None:
    if not isinstance(index, int):
        return None
    return {
        "index": int(index),
        "player_id": _player_id(player_index_to_id(index, belief_state)),
    }


def _indexed_player_refs(
    indices: Any,
    belief_state: BeliefState,
) -> list[dict[str, Any]]:
    if not isinstance(indices, list | tuple | set):
        return []
    refs = []
    for index in indices:
        ref = _indexed_player_ref(index, belief_state)
        if ref is not None:
            refs.append(ref)
    return refs


def _probe_failures_snapshot(belief_state: BeliefState) -> list[dict[str, Any]]:
    raw = getattr(belief_state, "extra", {}).get(PROBE_FAILURES, {})
    if not isinstance(raw, dict):
        return []
    failures = []
    for key, count in raw.items():
        if (
            isinstance(key, tuple)
            and len(key) == 2
            and isinstance(key[0], int)
            and isinstance(key[1], tuple)
            and len(key[1]) == 2
        ):
            failures.append(
                {
                    "round": int(key[0]),
                    "target": _player_id(key[1]),
                    "count": int(count),
                }
            )
    return failures


def _hostage_options_snapshot(belief_state: BeliefState) -> dict[str, Any] | None:
    selections = getattr(belief_state, "hostage_selections", None)
    if selections is None:
        return None

    eligible_colors = list(_state_value(selections, "eligible_colors") or [])
    eligible_shapes = list(_state_value(selections, "eligible_shapes") or [])
    selected_positions = set(_int_sequence(_state_value(selections, "selected_positions")))
    required_count = _hostage_target_total(selections, len(eligible_colors))
    remaining_count = max(0, required_count - len(selected_positions))

    options: list[dict[str, Any]] = []
    for position, color in enumerate(eligible_colors):
        shape = eligible_shapes[position] if position < len(eligible_shapes) else None
        shape_value = _shape_value(shape)
        player_id = [int(color), shape_value] if shape_value is not None else None
        options.append(
            {
                "position": position,
                "color": int(color),
                "shape": shape_value,
                "player_id": player_id,
                "selected": position in selected_positions,
            }
        )

    return {
        "required_count": required_count,
        "remaining_count": remaining_count,
        "selected_positions": sorted(selected_positions),
        "is_committed": bool(_state_value(selections, "is_committed")),
        "options": options,
    }


def _single_non_self_whisper_occupant(
    belief_state: BeliefState,
) -> PlayerID | None:
    my_index = getattr(belief_state, "my_index", None)
    candidates: list[PlayerID] = []
    for index in getattr(belief_state, "whisper_occupants", []) or []:
        if index == my_index:
            continue
        player_id = player_index_to_id(index, belief_state)
        if player_id is not None:
            candidates.append(player_id)
    return candidates[0] if len(candidates) == 1 else None


def _hostage_target_total(selections: Any, eligible_count: int) -> int:
    count_label = _state_value(selections, "count_label")
    if isinstance(count_label, str):
        parts = count_label.split("/")
        if len(parts) >= 2:
            digits = "".join(char for char in parts[1] if char.isdigit())
            if digits:
                return min(eligible_count, max(0, int(digits)))

    for name in ("required_count", "hostage_count", "target_count", "count"):
        value = _state_value(selections, name)
        if value is None:
            continue
        try:
            return min(eligible_count, max(0, int(value)))
        except (TypeError, ValueError):
            continue

    return min(2, eligible_count)


def _int_sequence(value: Any) -> tuple[int, ...]:
    if isinstance(value, list | tuple):
        result: list[int] = []
        for item in value:
            try:
                result.append(int(item))
            except (TypeError, ValueError):
                continue
        return tuple(result)
    return ()


def _shape_value(shape: Any) -> int | None:
    if shape is None:
        return None
    value = getattr(shape, "value", shape)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _state_value(source: Any, *names: str) -> Any:
    for name in names:
        if isinstance(source, dict) and name in source:
            return source[name]
        if hasattr(source, name):
            return getattr(source, name)
    return None


def _is_self(belief_state: BeliefState, player_id: PlayerID) -> bool:
    my_index = getattr(belief_state, "my_index", None)
    if isinstance(my_index, int):
        return player_id == player_index_to_id(my_index, belief_state)
    return False


def _player_id(player_id: PlayerID | None) -> list[int] | None:
    if player_id is None:
        return None
    return [int(player_id[0]), int(player_id[1])]


def _position(position: Any) -> list[int] | None:
    if position is None:
        return None
    if isinstance(position, tuple | list):
        if len(position) >= 2:
            return [int(position[0]), int(position[1])]
    return None


def _name(value: Any) -> str | None:
    if value is None:
        return None
    name = getattr(value, "name", None)
    if isinstance(name, str):
        return name.lower()
    raw = getattr(value, "value", None)
    if isinstance(raw, str):
        return raw
    if isinstance(value, str):
        return value.lower()
    return str(value)


def _json_safe(value: Any) -> Any:
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [_json_safe(item) for item in value]
    return value
