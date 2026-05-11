"""Deterministic validator for future Eurydice LLM decisions.

The validator is intentionally provider-free.  It accepts a JSON-like decision
that matches ``llm_decision_schema()``, checks it against the current
``build_llm_context(...)`` packet, and returns a safe result.  Rejected model
decisions never become button presses; callers can use the returned fallback.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
import hashlib
import json
import re
import string
from typing import Any

from orpheus.belief_state import BeliefState
from orpheus.logging import LogLevel

from agents.eurydice.llm_context import (
    DECISION_SCHEMA_VERSION,
    LLM_ACTIONS,
    build_llm_context,
)
from agents.eurydice.log import logger


MAX_MESSAGE_CHARS = 48
MAX_RATIONALE_CHARS = 240
_DECISION_KEYS = {
    "schema_version",
    "action",
    "surface",
    "target",
    "destination",
    "hostage_targets",
    "message",
    "reveal_color",
    "reveal_role",
    "confidence",
    "rationale",
}
_REQUIRED_KEYS = {"schema_version", "action", "confidence", "rationale"}
_TARGET_REQUIRED_ACTIONS = {
    "probe_player",
    "join_whisper",
    "grant_entry",
    "deny_entry",
    "offer_color",
    "offer_role",
    "accept_color",
    "accept_role",
}
_DESTINATION_REQUIRED_ACTIONS = {"move_to"}
_HOSTAGE_TARGETS_REQUIRED_ACTIONS = {"select_hostage"}
_MESSAGE_REQUIRED_ACTIONS = {"send_whisper", "send_global"}
_ROLE_REVEAL_ACTIONS = {"offer_role", "accept_role"}
_COLOR_REVEAL_ACTIONS = {"offer_color", "accept_color"}
_REVEAL_OVERRIDE_OBJECTIVES = {"disrupt_enemy", "maintain_cover"}
_MECHANICAL_FACT_WORDS = {
    "VERIFIED",
    "CONFIRMED",
    "EXCHANGED",
    "EXCHANGE DONE",
    "ROLE DONE",
    "COLOR DONE",
}
_IDENTITY_PREFIX_RE = re.compile(
    r"\b(?:I\s+AM|I'M|IM)\s+(?:A\s+|AN\s+|THE\s+)?([A-Z]+)\b"
)
_ROLE_POSSESSION_RE = re.compile(r"\bI\s+HAVE\s+([A-Z]+)\b")
_IMPLIED_HERE_RE = re.compile(
    r"\b(HADES|HAD|CERBERUS|CERB|PERSEPHONE|PERS|SEPH|DEMETER|DEM|SPY)\s+HERE\b"
)
_ROLE_ALIASES = {
    "HADES": "hades",
    "HAD": "hades",
    "CERBERUS": "cerberus",
    "CERB": "cerberus",
    "PERSEPHONE": "persephone",
    "PERS": "persephone",
    "SEPH": "persephone",
    "DEMETER": "demeter",
    "DEM": "demeter",
    "SHADE": "shade",
    "NYMPH": "nymph",
    "SPY": "spy",
}
_TEAM_ALIASES = {
    "SHADES": "shades",
    "SHADE": "shades",
    "NYMPHS": "nymphs",
    "NYMPH": "nymphs",
}
_ROLE_TEAMS = {
    "hades": "shades",
    "cerberus": "shades",
    "shade": "shades",
    "persephone": "nymphs",
    "demeter": "nymphs",
    "nymph": "nymphs",
}
_MECHANICAL_ROLE_SOURCES = {"role_exchange", "one_way_reveal"}


@dataclass(frozen=True)
class LLMValidationResult:
    """Validation outcome for one proposed model decision."""

    accepted: bool
    decision: dict[str, Any]
    fallback_decision: dict[str, Any]
    reasons: list[str]
    context_hash: str


def validate_llm_decision(
    decision: Any,
    context: dict[str, Any],
    *,
    fallback_action: str = "hold",
) -> LLMValidationResult:
    """Validate a future LLM decision against a JSON-safe context packet."""

    reasons: list[str] = []
    normalized = _normalize_decision(decision, reasons)
    context_hash = hash_llm_context(context)
    fallback = _fallback_decision(fallback_action)

    if normalized is None:
        return LLMValidationResult(False, {}, fallback, reasons, context_hash)

    _validate_schema(normalized, reasons)
    _validate_action_legality(normalized, context, reasons)
    _validate_target(normalized, context, reasons)
    _validate_message(normalized, context, reasons)
    _validate_reveal_safety(normalized, context, reasons)

    accepted = not reasons
    return LLMValidationResult(
        accepted=accepted,
        decision=normalized if accepted else {},
        fallback_decision=fallback,
        reasons=reasons,
        context_hash=context_hash,
    )


def validate_and_trace_llm_decision(
    belief_state: BeliefState,
    decision: Any,
    *,
    context: dict[str, Any] | None = None,
    fallback_action: str = "hold",
    source: str = "shadow",
) -> LLMValidationResult:
    """Build/validate one decision and emit compact shadow trace events."""

    context = context or build_llm_context(belief_state)
    result = validate_llm_decision(
        decision,
        context,
        fallback_action=fallback_action,
    )
    _trace_validation(context, decision, result, source=source)
    return result


def hash_llm_context(context: dict[str, Any]) -> str:
    """Return a stable short hash for correlating context/decision traces."""

    payload = json.dumps(context, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _normalize_decision(
    decision: Any,
    reasons: list[str],
) -> dict[str, Any] | None:
    if is_dataclass(decision):
        decision = asdict(decision)
    if not isinstance(decision, dict):
        reasons.append("decision_not_object")
        return None
    return dict(decision)


def _validate_schema(decision: dict[str, Any], reasons: list[str]) -> None:
    extra_keys = set(decision) - _DECISION_KEYS
    if extra_keys:
        reasons.append("unknown_fields:" + ",".join(sorted(extra_keys)))

    missing = _REQUIRED_KEYS - set(decision)
    if missing:
        reasons.append("missing_fields:" + ",".join(sorted(missing)))

    if decision.get("schema_version") != DECISION_SCHEMA_VERSION:
        reasons.append("bad_schema_version")

    action = decision.get("action")
    if action not in LLM_ACTIONS:
        reasons.append("unknown_action")

    target = decision.get("target")
    if target is not None and not _is_target(target):
        reasons.append("bad_target_shape")

    destination = decision.get("destination")
    if destination is not None and not _is_coordinate(destination):
        reasons.append("bad_destination_shape")

    hostage_targets = decision.get("hostage_targets")
    if hostage_targets is not None and not _is_hostage_targets(hostage_targets):
        reasons.append("bad_hostage_targets_shape")

    surface = decision.get("surface")
    if surface is not None and not isinstance(surface, str):
        reasons.append("surface_not_string")
    elif isinstance(surface, str) and len(surface) > 32:
        reasons.append("surface_too_long")

    message = decision.get("message")
    if message is not None and not isinstance(message, str):
        reasons.append("message_not_string")

    for key in ("reveal_color", "reveal_role"):
        if key in decision and not isinstance(decision[key], bool):
            reasons.append(f"{key}_not_bool")

    confidence = decision.get("confidence")
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, int | float)
        or not 0.0 <= float(confidence) <= 1.0
    ):
        reasons.append("bad_confidence")

    rationale = decision.get("rationale")
    if not isinstance(rationale, str):
        reasons.append("rationale_not_string")
    elif len(rationale) > MAX_RATIONALE_CHARS:
        reasons.append("rationale_too_long")


def _validate_action_legality(
    decision: dict[str, Any],
    context: dict[str, Any],
    reasons: list[str],
) -> None:
    action = decision.get("action")
    legal_actions = set(context.get("legal_actions") or [])
    if action in LLM_ACTIONS and action not in legal_actions:
        reasons.append("illegal_action_for_view")


def _validate_target(
    decision: dict[str, Any],
    context: dict[str, Any],
    reasons: list[str],
) -> None:
    action = decision.get("action")
    target = decision.get("target")
    if action in _DESTINATION_REQUIRED_ACTIONS and decision.get("destination") is None:
        reasons.append("destination_required")
    if (
        action in _HOSTAGE_TARGETS_REQUIRED_ACTIONS
        and decision.get("hostage_targets") is None
    ):
        reasons.append("hostage_targets_required")
    elif action in _HOSTAGE_TARGETS_REQUIRED_ACTIONS and not decision.get("hostage_targets"):
        reasons.append("hostage_targets_required")

    if action in _TARGET_REQUIRED_ACTIONS and target is None:
        if action in {"offer_color", "offer_role"} and _implicit_whisper_target(context):
            target = _implicit_whisper_target(context)
        else:
            reasons.append("target_required")
            return

    if action in _HOSTAGE_TARGETS_REQUIRED_ACTIONS:
        hostage_targets = decision.get("hostage_targets") or []
        has_hostage_options = _hostage_options(context) is not None
        if len({tuple(item) for item in hostage_targets if _is_target(item)}) != len(hostage_targets):
            reasons.append("duplicate_hostage_targets")
        _validate_hostage_target_count(hostage_targets, context, reasons)
        for hostage_target in hostage_targets:
            player = _player_by_id(context, hostage_target)
            if player is None and not has_hostage_options:
                reasons.append("unknown_hostage_target")
            elif player is not None and player.get("is_self"):
                reasons.append("hostage_target_is_self")
            if not _hostage_target_is_eligible(context, hostage_target):
                reasons.append("hostage_target_not_eligible")

    if action in _DESTINATION_REQUIRED_ACTIONS:
        destination = decision.get("destination")
        if destination is not None and not _destination_in_room(context, destination):
            reasons.append("destination_out_of_bounds")

    if target is None or not _is_target(target):
        return

    player = _player_by_id(context, target)
    if player is None:
        reasons.append("unknown_target")
        return
    if player.get("is_self"):
        reasons.append("target_is_self")

    if action == "probe_player":
        if not player.get("visible_position") and not player.get("last_seen_position"):
            reasons.append("target_position_unknown")

    if action == "join_whisper":
        if not player.get("last_seen_in_whisper_tick"):
            reasons.append("target_not_recently_in_whisper")

    if action in {"grant_entry", "deny_entry"}:
        pending = _pending_entry_id(context)
        if pending is None:
            reasons.append("no_pending_entry")
        elif not _same_target(target, pending):
            reasons.append("target_not_pending_entry")

    if action in {"offer_color", "offer_role", "accept_color", "accept_role"}:
        if not player.get("in_current_whisper"):
            reasons.append("target_not_in_current_whisper")

    if action == "accept_color" and not _same_target_any(
        target, _active_offer_ids(context, "color")
    ):
        reasons.append("no_active_color_offer_from_target")
    if action == "accept_role" and not _same_target_any(
        target, _active_offer_ids(context, "role")
    ):
        reasons.append("no_active_role_offer_from_target")


def _validate_message(
    decision: dict[str, Any],
    context: dict[str, Any],
    reasons: list[str],
) -> None:
    action = decision.get("action")
    message = decision.get("message")
    if action in _MESSAGE_REQUIRED_ACTIONS and not message:
        reasons.append("message_required")
        return
    if not isinstance(message, str) or not message:
        return

    if len(message) > MAX_MESSAGE_CHARS:
        reasons.append("message_too_long")
    if not _is_safe_ascii(message):
        reasons.append("message_not_safe_ascii")

    if _claims_mechanical_fact(message) and not _target_has_mechanical_truth(
        context,
        decision.get("target"),
    ):
        reasons.append("unsupported_mechanical_claim")
    _validate_identity_claims(message, context, reasons)


def _validate_reveal_safety(
    decision: dict[str, Any],
    context: dict[str, Any],
    reasons: list[str],
) -> None:
    action = decision.get("action")
    reveal_role = bool(decision.get("reveal_role")) or action in _ROLE_REVEAL_ACTIONS
    reveal_color = bool(decision.get("reveal_color")) or action in _COLOR_REVEAL_ACTIONS
    objective = _strategy(context).get("objective")

    if reveal_role and objective not in _REVEAL_OVERRIDE_OBJECTIVES:
        target = decision.get("target") or _implicit_whisper_target(context)
        if target is not None:
            player = _player_by_id(context, target)
            if _is_known_enemy(context, player):
                reasons.append("role_reveal_to_known_enemy")
        elif _current_whisper_has_enemy(context):
            reasons.append("role_reveal_to_known_enemy")

    if (
        reveal_color
        and _match(context).get("spy_in_game_config") is True
        and objective not in _REVEAL_OVERRIDE_OBJECTIVES
    ):
        reasons.append("color_reveal_with_spy_risk")


def _trace_validation(
    context: dict[str, Any],
    raw_decision: Any,
    result: LLMValidationResult,
    *,
    source: str,
) -> None:
    if not logger:
        return

    logger.event(
        "llm_context",
        {
            "context_hash": result.context_hash,
            "schema_version": context.get("schema_version"),
            "source": source,
            "view": context.get("view"),
            "phase": context.get("phase"),
            "round_number": context.get("round_number"),
            "legal_actions": context.get("legal_actions", []),
            "players_count": len(context.get("players") or []),
            "messages_count": len(context.get("recent_messages") or []),
            "objective": _strategy(context).get("objective"),
        },
        LogLevel.DECISIONS,
    )
    logger.event(
        "llm_decision",
        {
            "context_hash": result.context_hash,
            "schema_version": _raw_get(raw_decision, "schema_version"),
            "source": source,
            "action": _raw_get(raw_decision, "action"),
            "target": _raw_get(raw_decision, "target"),
            "message": _raw_get(raw_decision, "message"),
            "destination": _raw_get(raw_decision, "destination"),
            "hostage_targets": _raw_get(raw_decision, "hostage_targets"),
            "reveal_color": _raw_get(raw_decision, "reveal_color"),
            "reveal_role": _raw_get(raw_decision, "reveal_role"),
            "confidence": _raw_get(raw_decision, "confidence"),
            "rationale": _raw_get(raw_decision, "rationale"),
        },
        LogLevel.DECISIONS,
    )
    logger.event(
        "llm_decision_accepted" if result.accepted else "llm_decision_rejected",
        {
            "context_hash": result.context_hash,
            "source": source,
            "action": result.decision.get("action")
            if result.accepted
            else _raw_get(raw_decision, "action"),
            "fallback_action": result.fallback_decision.get("action"),
            "reasons": result.reasons,
        },
        LogLevel.DECISIONS,
    )


def _fallback_decision(action: str) -> dict[str, Any]:
    return {
        "schema_version": DECISION_SCHEMA_VERSION,
        "action": action if action in LLM_ACTIONS else "hold",
        "surface": None,
        "target": None,
        "destination": None,
        "hostage_targets": None,
        "message": None,
        "reveal_color": False,
        "reveal_role": False,
        "confidence": 1.0,
        "rationale": "deterministic fallback",
    }


def _raw_get(raw: Any, key: str) -> Any:
    if is_dataclass(raw):
        raw = asdict(raw)
    if isinstance(raw, dict):
        return raw.get(key)
    return None


def _is_coordinate(value: Any) -> bool:
    return _is_target(value)


def _is_hostage_targets(value: Any) -> bool:
    return (
        isinstance(value, list | tuple)
        and all(_is_target(item) for item in value)
    )


def _is_target(value: Any) -> bool:
    return (
        isinstance(value, list | tuple)
        and len(value) == 2
        and all(isinstance(item, int) and not isinstance(item, bool) for item in value)
    )


def _player_by_id(
    context: dict[str, Any],
    target: Any,
) -> dict[str, Any] | None:
    if not _is_target(target):
        return None
    wanted = [int(target[0]), int(target[1])]
    for player in context.get("players") or []:
        if player.get("player_id") == wanted:
            return player
    return None


def _destination_in_room(context: dict[str, Any], destination: Any) -> bool:
    if not _is_coordinate(destination):
        return False
    match = context.get("match") if isinstance(context.get("match"), dict) else {}
    room_size = match.get("room_size")
    if not (
        isinstance(room_size, list | tuple)
        and len(room_size) == 2
        and all(isinstance(value, int) for value in room_size)
    ):
        return True
    return 0 <= int(destination[0]) <= room_size[0] and 0 <= int(destination[1]) <= room_size[1]


def _validate_hostage_target_count(
    hostage_targets: list[Any],
    context: dict[str, Any],
    reasons: list[str],
) -> None:
    options = _hostage_options(context)
    if not options:
        return
    remaining = options.get("remaining_count")
    if isinstance(remaining, int) and remaining >= 0 and len(hostage_targets) != remaining:
        reasons.append("hostage_target_count_mismatch")


def _hostage_target_is_eligible(context: dict[str, Any], target: Any) -> bool:
    options = _hostage_options(context)
    if not options:
        return True
    for item in options.get("options") or []:
        if not isinstance(item, dict):
            continue
        player_id = item.get("player_id")
        if _same_target(target, player_id):
            return not bool(item.get("selected"))
    return False


def _hostage_options(context: dict[str, Any]) -> dict[str, Any] | None:
    raw = _runtime(context).get("hostage_options")
    return raw if isinstance(raw, dict) else None


def _pending_entry_id(context: dict[str, Any]) -> list[int] | None:
    runtime = _runtime(context)
    pending = runtime.get("pending_entry")
    if not isinstance(pending, dict):
        return None
    player_id = pending.get("player_id")
    return player_id if _is_target(player_id) else None


def _active_offer_ids(context: dict[str, Any], kind: str) -> list[list[int]]:
    runtime = _runtime(context)
    field = "active_color_offers" if kind == "color" else "active_role_offers"
    result: list[list[int]] = []
    for item in runtime.get(field) or []:
        if not isinstance(item, dict):
            continue
        player_id = item.get("player_id")
        if _is_target(player_id):
            result.append([int(player_id[0]), int(player_id[1])])
    return result


def _implicit_whisper_target(context: dict[str, Any]) -> list[int] | None:
    occupants = [
        player.get("player_id")
        for player in context.get("players") or []
        if isinstance(player, dict)
        and player.get("in_current_whisper")
        and not player.get("is_self")
        and _is_target(player.get("player_id"))
    ]
    if len(occupants) != 1:
        return None
    return [int(occupants[0][0]), int(occupants[0][1])]


def _same_target(left: Any, right: Any) -> bool:
    return _is_target(left) and _is_target(right) and [int(left[0]), int(left[1])] == [
        int(right[0]),
        int(right[1]),
    ]


def _same_target_any(target: Any, candidates: list[list[int]]) -> bool:
    return any(_same_target(target, candidate) for candidate in candidates)


def _target_has_mechanical_truth(
    context: dict[str, Any],
    target: Any,
) -> bool:
    if target is not None:
        player = _player_by_id(context, target)
        return bool(
            player
            and (
                player.get("exchanged_color_with_us")
                or player.get("exchanged_role_with_us")
            )
        )
    return any(
        player.get("in_current_whisper")
        and (
            player.get("exchanged_color_with_us")
            or player.get("exchanged_role_with_us")
        )
        for player in context.get("players") or []
    )


def _is_known_enemy(
    context: dict[str, Any],
    player: dict[str, Any] | None,
) -> bool:
    if player is None:
        return False
    self_team = (context.get("self") or {}).get("team")
    player_team = player.get("team")
    return bool(self_team and player_team and self_team != player_team)


def _current_whisper_has_enemy(context: dict[str, Any]) -> bool:
    return any(
        player.get("in_current_whisper") and _is_known_enemy(context, player)
        for player in context.get("players") or []
    )


def _claims_mechanical_fact(message: str) -> bool:
    upper = message.upper()
    return any(word in upper for word in _MECHANICAL_FACT_WORDS)


def _validate_identity_claims(
    message: str,
    context: dict[str, Any],
    reasons: list[str],
) -> None:
    upper = message.upper()
    objective = _strategy(context).get("objective")
    allow_deception = objective in _REVEAL_OVERRIDE_OBJECTIVES

    for match in _IDENTITY_PREFIX_RE.finditer(upper):
        keyword = match.group(1)
        claimed_role = _ROLE_ALIASES.get(keyword)
        claimed_team = _TEAM_ALIASES.get(keyword)
        if claimed_role is None and claimed_team is None:
            continue
        if _identity_claim_matches_self(context, claimed_role, claimed_team):
            continue
        if allow_deception:
            continue
        if claimed_role is not None:
            _append_once(reasons, "false_self_role_claim")
        else:
            _append_once(reasons, "false_self_team_claim")

    for match in _IMPLIED_HERE_RE.finditer(upper):
        if _match_followed_by_question(upper, match.end()):
            continue
        claimed_role = _ROLE_ALIASES.get(match.group(1))
        if claimed_role is None:
            continue
        if _identity_claim_matches_self(context, claimed_role, None):
            continue
        if allow_deception:
            continue
        _append_once(reasons, "false_self_role_claim")

    for match in _ROLE_POSSESSION_RE.finditer(upper):
        claimed_role = _ROLE_ALIASES.get(match.group(1))
        if claimed_role is None:
            continue
        if not _role_claim_has_mechanical_support(context, claimed_role):
            _append_once(reasons, "unsupported_role_possession_claim")


def _identity_claim_matches_self(
    context: dict[str, Any],
    claimed_role: str | None,
    claimed_team: str | None,
) -> bool:
    self_snapshot = context.get("self")
    if not isinstance(self_snapshot, dict):
        return False
    self_role = _normalize_name(self_snapshot.get("role"))
    self_team = _normalize_name(self_snapshot.get("team"))

    if claimed_role is not None and claimed_role == self_role:
        return True
    if claimed_team is not None and claimed_team == self_team:
        return True
    if (
        claimed_role in {"shade", "nymph"}
        and _ROLE_TEAMS.get(claimed_role) == self_team
    ):
        return True
    return False


def _role_claim_has_mechanical_support(
    context: dict[str, Any],
    claimed_role: str,
) -> bool:
    self_snapshot = context.get("self")
    if (
        isinstance(self_snapshot, dict)
        and _normalize_name(self_snapshot.get("role")) == claimed_role
    ):
        return True
    for player in context.get("players") or []:
        if not isinstance(player, dict):
            continue
        if _normalize_name(player.get("role")) != claimed_role:
            continue
        if _normalize_name(player.get("role_source")) in _MECHANICAL_ROLE_SOURCES:
            return True
    return False


def _match_followed_by_question(text: str, end: int) -> bool:
    return end < len(text) and text[end:].lstrip().startswith("?")


def _normalize_name(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return value.strip().lower()


def _append_once(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)


def _is_safe_ascii(message: str) -> bool:
    allowed = set(string.ascii_letters + string.digits + " .,!?':;-_/")
    return all(char in allowed for char in message)


def _strategy(context: dict[str, Any]) -> dict[str, Any]:
    strategy = context.get("strategy")
    return strategy if isinstance(strategy, dict) else {}


def _match(context: dict[str, Any]) -> dict[str, Any]:
    match = context.get("match")
    return match if isinstance(match, dict) else {}


def _runtime(context: dict[str, Any]) -> dict[str, Any]:
    runtime = context.get("runtime")
    return runtime if isinstance(runtime, dict) else {}
