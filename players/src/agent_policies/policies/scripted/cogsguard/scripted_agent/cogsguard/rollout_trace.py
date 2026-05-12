from __future__ import annotations

from typing import Iterable

from cogsguard.missions.machina_1 import GEAR_COSTS

TRACE_RESOURCES = tuple(sorted({resource for costs in GEAR_COSTS.values() for resource in costs}))


def inventory_snapshot(team_inv: dict[str, int], resources: Iterable[str]) -> dict[str, int]:
    return {resource: int(team_inv.get(resource, 0)) for resource in resources}


def inventory_delta(previous: dict[str, int] | None, current: dict[str, int]) -> dict[str, int]:
    if previous is None:
        return {resource: 0 for resource in current}
    return {resource: current[resource] - previous.get(resource, 0) for resource in current}


def format_resource_trace_line(
    *,
    step: int,
    inventory: dict[str, int],
    delta: dict[str, int],
    station_uses: dict[str, int],
    station_uses_with_resources: dict[str, int],
    adjacent_roles: dict[str, bool],
    available_roles: dict[str, bool],
) -> str:
    inv_str = " ".join(f"{resource}={inventory[resource]}" for resource in TRACE_RESOURCES)
    delta_str = " ".join(f"{resource}={delta[resource]:+d}" for resource in TRACE_RESOURCES)
    uses_str = " ".join(f"{role}={station_uses.get(role, 0)}" for role in GEAR_COSTS)
    uses_with_str = " ".join(f"{role}={station_uses_with_resources.get(role, 0)}" for role in GEAR_COSTS)
    adjacent_str = ",".join(role for role, adjacent in adjacent_roles.items() if adjacent) or "-"
    available_str = ",".join(role for role, available in available_roles.items() if available) or "-"
    return (
        f"step={step} inv[{inv_str}] delta[{delta_str}] "
        f"station_uses[{uses_str}] station_uses_with_resources[{uses_with_str}] "
        f"adjacent_roles[{adjacent_str}] available_roles[{available_str}]"
    )
