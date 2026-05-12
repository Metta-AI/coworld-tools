#!/usr/bin/env -S uv run
"""Run an instrumented CoGsGuard rollout with role/resource tracing."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict

from agent_policies.policies.scripted.cogsguard.scripted_agent.cogsguard.debug_agent import DebugHarness
from agent_policies.policies.scripted.cogsguard.scripted_agent.cogsguard.role_trace import (
    count_role_transitions,
    format_role_trace_line,
    summarize_role_counts,
)
from agent_policies.policies.scripted.cogsguard.scripted_agent.cogsguard.rollout_trace import (
    TRACE_RESOURCES,
    format_resource_trace_line,
    inventory_delta,
    inventory_snapshot,
)
from agent_policies.policies.scripted.cogsguard.scripted_agent.cogsguard.types import ROLE_TO_STRUCTURE_TYPE, Role, StructureType
from agent_policies.policies.scripted.cogsguard.scripted_agent.utils import is_adjacent
from cogsguard.missions.machina_1 import GEAR_COSTS

MOVE_DELTAS = {
    "move_north": (-1, 0),
    "move_south": (1, 0),
    "move_east": (0, 1),
    "move_west": (0, -1),
}


def run_audit(
    *,
    steps: int,
    num_agents: int,
    max_steps: int,
    seed: int,
    recipe_module: str,
    policy_uri: str,
    trace_every: int,
) -> int:
    harness = DebugHarness.from_recipe(
        recipe_module=recipe_module,
        num_agents=num_agents,
        max_steps=max_steps,
        seed=seed,
        policy_uri=policy_uri,
    )

    role_counts_history: list[dict[str, int]] = []
    role_transitions: list[tuple[str, str]] = []
    previous_role_by_agent: dict[int, str] = {}

    resource_trace_lines: list[str] = []
    role_trace_lines: list[str] = []

    previous_inventory: dict[str, int] | None = None

    station_uses: dict[str, int] = defaultdict(int)
    station_uses_with_resources: dict[str, int] = defaultdict(int)

    for _ in range(steps):
        harness.step(1)
        role_counts: Counter[str] = Counter()
        adjacent_roles = {role: False for role in GEAR_COSTS}

        hub_inv = harness.object_inventory("hub", team_name="cogs")
        available_roles = {
            role: all(hub_inv.get(resource, 0) >= amount for resource, amount in cost.items())
            for role, cost in GEAR_COSTS.items()
        }

        for agent_id in range(harness.num_agents):
            state = harness.get_agent_state(agent_id)
            if state is None or state.current_obs is None:
                continue
            role = state.role.value if isinstance(state.role, Role) else str(state.role)
            role_counts[role] += 1

            prev_role = previous_role_by_agent.get(agent_id)
            if prev_role is not None and prev_role != role:
                role_transitions.append((prev_role, role))
            previous_role_by_agent[agent_id] = role

            role_enum = state.role if isinstance(state.role, Role) else None
            station_type = ROLE_TO_STRUCTURE_TYPE.get(role_enum) if role in GEAR_COSTS else None
            station = state.get_structure_position(station_type) if station_type is not None else None
            if station is not None and is_adjacent((state.row, state.col), station):
                adjacent_roles[role] = True

            action_name = state.last_action.name if state.last_action else ""
            if state.using_object_this_step and action_name in MOVE_DELTAS and station is not None:
                dr, dc = MOVE_DELTAS[action_name]
                target = (state.row + dr, state.col + dc)
                if target == station:
                    station_uses[role] += 1
                    if available_roles.get(role, False):
                        station_uses_with_resources[role] += 1

        role_counts_history.append(dict(role_counts))

        if harness.step_count % trace_every == 0:
            role_trace_lines.append(
                format_role_trace_line(
                    step=harness.step_count,
                    role_counts=dict(role_counts),
                    roles=GEAR_COSTS.keys(),
                    transitions=len(role_transitions),
                )
            )
            inventory = inventory_snapshot(hub_inv, TRACE_RESOURCES)
            delta = inventory_delta(previous_inventory, inventory)
            resource_trace_lines.append(
                format_resource_trace_line(
                    step=harness.step_count,
                    inventory=inventory,
                    delta=delta,
                    station_uses=dict(station_uses),
                    station_uses_with_resources=dict(station_uses_with_resources),
                    adjacent_roles=adjacent_roles,
                    available_roles=available_roles,
                )
            )
            previous_inventory = inventory

    print("Cogsguard instrumented audit")
    print(f"- steps: {steps}")
    print(f"- policy_uri: {policy_uri}")
    print(f"- agents: {num_agents}")
    print("Role trace")
    for line in role_trace_lines:
        print(line)
    print("Resource trace (cogs hub)")
    for line in resource_trace_lines:
        print(line)

    summary = summarize_role_counts(role_counts_history, GEAR_COSTS.keys())
    print("Role count summary")
    for role, stats in summary.items():
        print(f"- {role}: min={stats['min']}, max={stats['max']}, avg={stats['avg']:.2f}")

    transition_counts = count_role_transitions(role_transitions)
    if transition_counts:
        print("Role transitions")
        for (prev_role, next_role), count in sorted(transition_counts.items()):
            print(f"- {prev_role} -> {next_role}: {count}")

    junction_counts: list[int] = []
    extractor_counts: list[int] = []
    for i in range(harness.num_agents):
        state = harness.get_agent_state(i)
        if state is None:
            continue
        junctions = [s for s in state.structures.values() if s.structure_type == StructureType.CHARGER]
        extractors = [s for s in state.structures.values() if s.structure_type == StructureType.EXTRACTOR]
        junction_counts.append(len(junctions))
        extractor_counts.append(len(extractors))

    print(f"Charger counts per agent: {junction_counts}")
    print(f"Extractor counts per agent: {extractor_counts}")
    if junction_counts:
        print(
            "Charger counts min/max/avg:",
            min(junction_counts),
            max(junction_counts),
            sum(junction_counts) / len(junction_counts),
        )
    if extractor_counts:
        print(
            "Extractor counts min/max/avg:",
            min(extractor_counts),
            max(extractor_counts),
            sum(extractor_counts) / len(extractor_counts),
        )

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steps", type=int, default=1000)
    parser.add_argument("--agents", type=int, default=2)
    parser.add_argument("--max-steps", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--recipe", default="recipes.experiment.cogsguard")
    parser.add_argument(
        "--policy-uri",
        default="metta://policy/role?miner=1&scout=1",
    )
    parser.add_argument("--trace-every", type=int, default=200)
    args = parser.parse_args()

    return run_audit(
        steps=args.steps,
        num_agents=args.agents,
        max_steps=args.max_steps,
        seed=args.seed,
        recipe_module=args.recipe,
        policy_uri=args.policy_uri,
        trace_every=args.trace_every,
    )


if __name__ == "__main__":
    raise SystemExit(main())
