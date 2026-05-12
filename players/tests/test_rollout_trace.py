from __future__ import annotations

from cogames_agents.policy.scripted_agent.cogsguard.rollout_trace import (
    TRACE_RESOURCES,
    format_resource_trace_line,
    inventory_delta,
)


def test_inventory_delta_initializes_zeroes() -> None:
    current = {resource: 1 for resource in TRACE_RESOURCES}
    delta = inventory_delta(None, current)
    assert delta == {resource: 0 for resource in TRACE_RESOURCES}


def test_format_resource_trace_line_includes_ordered_fields() -> None:
    inventory = {resource: idx for idx, resource in enumerate(TRACE_RESOURCES)}
    delta = {resource: 0 for resource in TRACE_RESOURCES}
    line = format_resource_trace_line(
        step=5,
        inventory=inventory,
        delta=delta,
        station_uses={"aligner": 1, "scrambler": 0, "miner": 2, "scout": 0},
        station_uses_with_resources={"aligner": 0, "scrambler": 0, "miner": 1, "scout": 0},
        adjacent_roles={"aligner": True, "scrambler": False, "miner": True, "scout": False},
        available_roles={"aligner": True, "scrambler": True, "miner": False, "scout": False},
    )
    assert line.startswith("step=5 inv[")
    expected_inv = " ".join(f"{resource}={inventory[resource]}" for resource in TRACE_RESOURCES)
    assert f"inv[{expected_inv}]" in line
    assert "adjacent_roles[aligner,miner]" in line
    assert "available_roles[aligner,scrambler]" in line
