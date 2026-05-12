"""Resource, inventory, and state query helpers."""

from __future__ import annotations

from cogamer.cvc.agent.geometry import manhattan
from cogamer.cvc.agent.types import (
    _ELEMENTS,
    _EMERGENCY_RESOURCE_LOW,
    _GEAR_COSTS,
    _HEART_BATCH_TARGETS,
    _HP_THRESHOLDS,
)
from mettagrid.sdk.agent import MettagridState, SemanticEntity


def absolute_position(state: MettagridState) -> tuple[int, int]:
    return (
        int(state.self_state.attributes.get("global_x", 0)),
        int(state.self_state.attributes.get("global_y", 0)),
    )


def attr_int(entity: SemanticEntity, name: str, default: int = 0) -> int:
    value = entity.attributes.get(name)
    return default if value is None else int(value)


def attr_str(entity: SemanticEntity, name: str) -> str | None:
    value = entity.attributes.get(name)
    if value is None:
        return None
    return str(value)


def has_role_gear(state: MettagridState, role: str) -> bool:
    return int(state.self_state.inventory.get(role, 0)) > 0


def resource_total(state: MettagridState) -> int:
    return sum(int(state.self_state.inventory.get(resource, 0)) for resource in _ELEMENTS)


def deposit_threshold(state: MettagridState) -> int:
    if has_role_gear(state, "miner"):
        return 12
    return 4


def team_id(state: MettagridState) -> str:
    if state.team_summary is None:
        return str(state.self_state.attributes.get("team", ""))
    return state.team_summary.team_id


def team_min_resource(state: MettagridState) -> int:
    if state.team_summary is None:
        return 0
    return min(int(state.team_summary.shared_inventory.get(resource, 0)) for resource in _ELEMENTS)


def needs_emergency_mining(state: MettagridState) -> bool:
    if state.team_summary is None:
        return False
    return team_min_resource(state) < _EMERGENCY_RESOURCE_LOW


def resource_priority(state: MettagridState, *, resource_bias: str) -> list[str]:
    shared_inventory = {} if state.team_summary is None else state.team_summary.shared_inventory
    return sorted(
        _ELEMENTS,
        key=lambda resource: (
            int(shared_inventory.get(resource, 0)),
            0 if resource == resource_bias else 1,
            resource,
        ),
    )


def inventory_signature(state: MettagridState) -> tuple[tuple[str, int], ...]:
    return tuple(sorted((name, int(value)) for name, value in state.self_state.inventory.items()))


def role_vibe(role: str) -> str:
    if role in {"aligner", "miner", "scrambler", "scout"}:
        return f"change_vibe_{role}"
    return "change_vibe_default"


def retreat_threshold(state: MettagridState, role: str) -> int:
    threshold = _HP_THRESHOLDS[role]
    step = state.step or 0
    if step >= 2_500:
        if role in {"aligner", "scrambler"}:
            threshold += 15
        elif role == "miner":
            threshold += 10
    if not has_role_gear(state, role):
        threshold += 10
    return threshold


def phase_name(state: MettagridState, role: str) -> str:
    hp = int(state.self_state.inventory.get("hp", 0))
    if hp <= retreat_threshold(state, role):
        return "retreat"
    if not has_role_gear(state, role):
        if role != "miner" and not team_can_afford_gear(state, role):
            return "fund_gear"
        return "regear"
    if role in {"aligner", "scrambler"} and int(state.self_state.inventory.get("heart", 0)) <= 0:
        return "hearts"
    if role == "miner" and resource_total(state) >= deposit_threshold(state):
        return "deposit"
    if role == "miner":
        return "economy"
    if role == "aligner":
        return "expand"
    if role == "scrambler":
        return "pressure"
    return "explore"


def heart_batch_target(state: MettagridState, role: str) -> int:
    if role not in _HEART_BATCH_TARGETS:
        return 0
    return _HEART_BATCH_TARGETS[role]


def team_can_afford_gear(state: MettagridState, role: str) -> bool:
    if role not in _GEAR_COSTS:
        return True
    if state.team_summary is None:
        return False
    inventory = state.team_summary.shared_inventory
    return all(int(inventory.get(resource, 0)) >= amount for resource, amount in _GEAR_COSTS[role].items())


def team_can_refill_hearts(state: MettagridState) -> bool:
    if state.team_summary is None:
        return False
    inventory = state.team_summary.shared_inventory
    if int(inventory.get("heart", 0)) > 0:
        return True
    return all(int(inventory.get(resource, 0)) >= 7 for resource in _ELEMENTS)


def heart_supply_capacity(state: MettagridState) -> int:
    if state.team_summary is None:
        return 0
    inventory = state.team_summary.shared_inventory
    return int(inventory.get("heart", 0)) + team_min_resource(state) // 7


def should_batch_hearts(
    state: MettagridState,
    *,
    role: str,
    hub_position: tuple[int, int] | None,
) -> bool:
    if hub_position is None:
        return False
    hearts = int(state.self_state.inventory.get("heart", 0))
    batch_target = heart_batch_target(state, role)
    if hearts <= 0 or hearts >= batch_target:
        return False
    if not team_can_refill_hearts(state):
        return False
    return manhattan(absolute_position(state), hub_position) <= 1
