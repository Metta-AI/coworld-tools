#!/usr/bin/env -S uv run
"""Run a short CoGsGuard scripted rollout and sanity-check structure discovery."""

from __future__ import annotations

import argparse
from collections.abc import Iterable

from agent_policies.policies.scripted.cogsguard.scripted_agent.cogsguard.debug_agent import DebugHarness
from agent_policies.policies.scripted.cogsguard.scripted_agent.cogsguard.prereq_trace import (
    format_prereq_trace_line,
    prereq_missing,
)
from agent_policies.policies.scripted.cogsguard.scripted_agent.cogsguard.role_trace import (
    count_role_transitions,
    count_steps_with_roles,
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


def _is_hub_tag(name: str, tags: Iterable[str]) -> bool:
    tag_set = set(tags)
    return name in {"hub", "main_nexus"} or bool({"hub", "main_nexus"} & tag_set)


def _is_junction_tag(name: str, tags: Iterable[str]) -> bool:
    combined = {name, *tags}
    return any("junction" in tag or "supply_depot" in tag for tag in combined)


def _has_alignment_tag(name: str, tags: Iterable[str]) -> bool:
    combined = {name, *tags}
    return any("cogs" in tag or "clips" in tag for tag in combined)


MOVE_DELTAS = {
    "move_north": (-1, 0),
    "move_south": (1, 0),
    "move_east": (0, 1),
    "move_west": (0, -1),
}


def _gear_role_stats() -> dict[str, object]:
    return {
        "agents": set(),
        "gear_seen": False,
        "gear_station_uses": 0,
        "gear_acquired": 0,
        "gear_attempts_with_resources": 0,
        "gear_attempts_without_resources": 0,
    }


def run_rollout(
    *,
    steps: int,
    num_agents: int,
    max_steps: int,
    seed: int,
    recipe_module: str,
    policy_uri: str,
    allow_missing_roles: bool,
    trace_prereqs: bool,
    trace_roles: bool,
    trace_role_every: int,
    trace_role_limit: int,
    trace_resources: bool,
    trace_resource_every: int,
    trace_resource_limit: int,
) -> int:
    harness = DebugHarness.from_recipe(
        recipe_module=recipe_module,
        num_agents=num_agents,
        max_steps=max_steps,
        seed=seed,
        policy_uri=policy_uri,
    )

    hub_seen = False
    hub_missing = 0
    junction_alignment_checks = 0
    junction_alignment_mismatches = 0
    neutral_junction_checks = 0
    neutral_junction_mismatches = 0
    expected_roles = {"miner", "scout", "aligner", "scrambler"}
    observed_roles: set[str] = set()
    prereq_trace_lines: list[str] = []
    prereq_stats = {role: {"attempts": 0, "missing_gear": 0, "missing_heart": 0} for role in ("aligner", "scrambler")}
    role_counts_history: list[dict[str, int]] = []
    role_transitions: list[tuple[str, str]] = []
    role_trace_lines: list[str] = []
    last_role_by_agent: dict[int, str] = {}

    role_stats = {role: _gear_role_stats() for role in expected_roles}
    role_stats["miner"] |= {"mine_attempts": 0, "mine_mismatches": 0, "deposit_attempts": 0}
    role_stats["scout"] |= {"unique_positions": {}, "max_structures_seen": 0}
    role_stats["aligner"] |= {"align_attempts": 0, "align_mismatches": 0, "align_cogs_targets": 0}
    role_stats["scrambler"] |= {"scramble_attempts": 0, "scramble_mismatches": 0, "scramble_cogs_targets": 0}

    last_pending_action: dict[int, str | None] = {}
    last_cargo: dict[int, int] = {}
    last_gear: dict[int, dict[str, int]] = {}
    gear_resource_windows = {role: 0 for role in GEAR_COSTS}
    gear_resource_windows_with_adjacent = {role: 0 for role in GEAR_COSTS}
    last_hub_snapshot: dict[str, int] | None = None
    resource_trace_lines: list[str] = []

    if trace_resources and trace_resource_every <= 0:
        raise ValueError("trace_resource_every must be >= 1")

    if trace_role_every <= 0:
        raise ValueError("trace_role_every must be >= 1")

    for _ in range(steps):
        harness.step(1)
        hub_inv = harness.object_inventory("hub", team_name="cogs")
        gear_resources_available = {
            role: all(hub_inv.get(resource, 0) >= amount for resource, amount in cost.items())
            for role, cost in GEAR_COSTS.items()
        }
        for role, available in gear_resources_available.items():
            if available:
                gear_resource_windows[role] += 1

        adjacent_by_role = {role: False for role in GEAR_COSTS}
        role_counts_step = {role: 0 for role in expected_roles}
        transition_events = 0
        station_uses_step = {role: 0 for role in GEAR_COSTS}
        station_uses_with_resources_step = {role: 0 for role in GEAR_COSTS}
        for agent_id in range(harness.num_agents):
            policy = harness.agent_policies[agent_id]
            base_policy = policy._base_policy if hasattr(policy, "_base_policy") else policy
            state = harness.get_agent_state(agent_id)
            if state is None or state.current_obs is None:
                continue
            role_enum = state.role if isinstance(state.role, Role) else None
            role = state.role.value if hasattr(state.role, "value") else str(state.role)
            if role in role_stats:
                station_type = ROLE_TO_STRUCTURE_TYPE.get(role_enum) if role in GEAR_COSTS else None
                station = state.get_structure_position(station_type) if station_type is not None else None
                observed_roles.add(role)
                role_stats[role]["agents"].add(agent_id)
                role_counts_step[role] += 1
                if state.has_gear():
                    role_stats[role]["gear_seen"] = True

                if station is not None and is_adjacent((state.row, state.col), station):
                    adjacent_by_role[role] = True

                gear_snapshot = last_gear.get(agent_id, {})
                current_gear = {
                    "aligner": state.aligner,
                    "scrambler": state.scrambler,
                    "miner": state.miner,
                    "scout": state.scout,
                }
                if role in GEAR_COSTS and current_gear.get(role, 0) > gear_snapshot.get(role, 0):
                    role_stats[role]["gear_acquired"] += 1

                action_name = state.last_action.name if state.last_action else ""
                if state.using_object_this_step and action_name in MOVE_DELTAS and station is not None:
                    dr, dc = MOVE_DELTAS[action_name]
                    target = (state.row + dr, state.col + dc)
                    if target == station:
                        role_stats[role]["gear_station_uses"] += 1
                        station_uses_step[role] += 1
                        if gear_resources_available.get(role, False):
                            role_stats[role]["gear_attempts_with_resources"] += 1
                            station_uses_with_resources_step[role] += 1
                        else:
                            role_stats[role]["gear_attempts_without_resources"] += 1

                last_gear[agent_id] = current_gear

                previous_role = last_role_by_agent.get(agent_id)
                if previous_role is not None and previous_role != role:
                    role_transitions.append((previous_role, role))
                    transition_events += 1
                last_role_by_agent[agent_id] = role
            parsed = base_policy._parse_observation(state, state.current_obs)
            for pos, obj_state in parsed.nearby_objects.items():
                obj_name = obj_state.name.lower()
                obj_tags = [tag.lower() for tag in obj_state.tags]

                if _is_hub_tag(obj_name, obj_tags):
                    hub_seen = True
                    if state.get_structure_position(StructureType.HUB) is None:
                        hub_missing += 1

                if not _is_junction_tag(obj_name, obj_tags):
                    continue

                expected_alignment = None
                if _has_alignment_tag(obj_name, obj_tags):
                    if any("cogs" in tag for tag in obj_tags):
                        expected_alignment = "cogs"
                    elif any("clips" in tag for tag in obj_tags):
                        expected_alignment = "clips"

                struct = state.structures.get(pos)
                if struct is None or struct.structure_type != StructureType.CHARGER:
                    continue
                if pos in state.alignment_overrides:
                    continue

                if expected_alignment is not None:
                    junction_alignment_checks += 1
                    if struct.alignment != expected_alignment:
                        junction_alignment_mismatches += 1
                    continue

                neutral_junction_checks += 1
                if struct.alignment == "clips":
                    neutral_junction_mismatches += 1

            if role == "scout":
                positions = role_stats["scout"]["unique_positions"].setdefault(agent_id, set())
                positions.add((state.row, state.col))
                role_stats["scout"]["max_structures_seen"] = max(
                    role_stats["scout"]["max_structures_seen"],
                    len(state.structures),
                )

            if role == "miner":
                current_cargo = state.total_cargo
                previous_cargo = last_cargo.get(agent_id, current_cargo)
                if current_cargo < previous_cargo:
                    aligned_positions: list[tuple[int, int]] = []
                    hub_pos = state.get_structure_position(StructureType.HUB)
                    if hub_pos is not None:
                        aligned_positions.append(hub_pos)
                    for junction in state.get_structures_by_type(StructureType.CHARGER):
                        if junction.alignment == "cogs":
                            aligned_positions.append(junction.position)
                    if aligned_positions:
                        dist = min(abs(state.row - pos[0]) + abs(state.col - pos[1]) for pos in aligned_positions)
                        if dist <= 1:
                            role_stats["miner"]["deposit_attempts"] += 1
                last_cargo[agent_id] = current_cargo

            current_pending = getattr(state, "_pending_action_type", None)
            previous_pending = last_pending_action.get(agent_id)
            if current_pending != previous_pending:
                last_pending_action[agent_id] = current_pending
                target = getattr(state, "_pending_action_target", None)
                target_struct = state.structures.get(target) if target else None

                if current_pending == "mine" and role == "miner":
                    role_stats["miner"]["mine_attempts"] += 1
                    if target_struct is None or target_struct.structure_type != StructureType.EXTRACTOR:
                        role_stats["miner"]["mine_mismatches"] += 1

                if current_pending == "align" and role == "aligner":
                    role_stats["aligner"]["align_attempts"] += 1
                    prereq_stats["aligner"]["attempts"] += 1
                    missing = prereq_missing(
                        "align",
                        gear=state.aligner,
                        heart=state.heart,
                        influence=state.influence,
                    )
                    if missing.get("gear"):
                        prereq_stats["aligner"]["missing_gear"] += 1
                    if missing.get("heart"):
                        prereq_stats["aligner"]["missing_heart"] += 1
                    if trace_prereqs:
                        prereq_trace_lines.append(
                            format_prereq_trace_line(
                                step=harness.step_count,
                                agent_id=agent_id,
                                action_type="align",
                                gear=state.aligner,
                                heart=state.heart,
                                influence=state.influence,
                                missing=missing,
                            )
                        )
                    if target_struct is None or target_struct.structure_type != StructureType.CHARGER:
                        role_stats["aligner"]["align_mismatches"] += 1
                    elif target_struct.alignment == "cogs":
                        role_stats["aligner"]["align_cogs_targets"] += 1

                if current_pending == "scramble" and role == "scrambler":
                    role_stats["scrambler"]["scramble_attempts"] += 1
                    prereq_stats["scrambler"]["attempts"] += 1
                    missing = prereq_missing(
                        "scramble",
                        gear=state.scrambler,
                        heart=state.heart,
                        influence=state.influence,
                    )
                    if missing.get("gear"):
                        prereq_stats["scrambler"]["missing_gear"] += 1
                    if missing.get("heart"):
                        prereq_stats["scrambler"]["missing_heart"] += 1
                    if trace_prereqs:
                        prereq_trace_lines.append(
                            format_prereq_trace_line(
                                step=harness.step_count,
                                agent_id=agent_id,
                                action_type="scramble",
                                gear=state.scrambler,
                                heart=state.heart,
                                influence=state.influence,
                                missing=missing,
                            )
                        )
                    if target_struct is None or target_struct.structure_type != StructureType.CHARGER:
                        role_stats["scrambler"]["scramble_mismatches"] += 1
                    elif target_struct.alignment == "cogs":
                        role_stats["scrambler"]["scramble_cogs_targets"] += 1

        for role, adjacent in adjacent_by_role.items():
            if adjacent and gear_resources_available.get(role, False):
                gear_resource_windows_with_adjacent[role] += 1

        role_counts_history.append(role_counts_step)
        if (
            trace_roles
            and harness.step_count % trace_role_every == 0
            and (trace_role_limit <= 0 or len(role_trace_lines) < trace_role_limit)
        ):
            role_trace_lines.append(
                format_role_trace_line(
                    step=harness.step_count,
                    role_counts=role_counts_step,
                    roles=sorted(expected_roles),
                    transitions=transition_events,
                )
            )

        if (
            trace_resources
            and harness.step_count % trace_resource_every == 0
            and (trace_resource_limit <= 0 or len(resource_trace_lines) < trace_resource_limit)
        ):
            snapshot = inventory_snapshot(hub_inv, TRACE_RESOURCES)
            delta = inventory_delta(last_hub_snapshot, snapshot)
            resource_trace_lines.append(
                format_resource_trace_line(
                    step=harness.step_count,
                    inventory=snapshot,
                    delta=delta,
                    station_uses=station_uses_step,
                    station_uses_with_resources=station_uses_with_resources_step,
                    adjacent_roles=adjacent_by_role,
                    available_roles=gear_resources_available,
                )
            )
            last_hub_snapshot = snapshot

    print("Cogsguard rollout sanity check")
    print(f"- steps: {steps}")
    print(f"- hub seen: {hub_seen}")
    print(f"- hub missing in structures: {hub_missing}")
    print(f"- tagged junctions checked: {junction_alignment_checks}")
    print(f"- tagged junction mismatches: {junction_alignment_mismatches}")
    print(f"- neutral junctions checked: {neutral_junction_checks}")
    print(f"- neutral junctions flagged as clips: {neutral_junction_mismatches}")
    print(f"- observed roles: {sorted(observed_roles)}")
    print("Role behavior checks")
    print(
        f"- miner: agents={len(role_stats['miner']['agents'])} "
        f"gear_seen={role_stats['miner']['gear_seen']} "
        f"mine_attempts={role_stats['miner']['mine_attempts']} "
        f"mine_mismatches={role_stats['miner']['mine_mismatches']} "
        f"deposit_attempts={role_stats['miner']['deposit_attempts']}"
    )
    scout_positions = [len(pos) for pos in role_stats["scout"]["unique_positions"].values()]
    print(
        f"- scout: agents={len(role_stats['scout']['agents'])} "
        f"gear_seen={role_stats['scout']['gear_seen']} "
        f"unique_positions={scout_positions} "
        f"max_structures_seen={role_stats['scout']['max_structures_seen']}"
    )
    print(
        f"- aligner: agents={len(role_stats['aligner']['agents'])} "
        f"gear_seen={role_stats['aligner']['gear_seen']} "
        f"align_attempts={role_stats['aligner']['align_attempts']} "
        f"align_mismatches={role_stats['aligner']['align_mismatches']} "
        f"align_cogs_targets={role_stats['aligner']['align_cogs_targets']}"
    )
    print(
        f"- scrambler: agents={len(role_stats['scrambler']['agents'])} "
        f"gear_seen={role_stats['scrambler']['gear_seen']} "
        f"scramble_attempts={role_stats['scrambler']['scramble_attempts']} "
        f"scramble_mismatches={role_stats['scrambler']['scramble_mismatches']} "
        f"scramble_cogs_targets={role_stats['scrambler']['scramble_cogs_targets']}"
    )
    print("Gear station diagnostics")
    for role in ["scrambler", "aligner", "miner", "scout"]:
        if role not in role_stats:
            continue
        stats = role_stats[role]
        print(
            f"- {role}: station_uses={stats['gear_station_uses']} "
            f"gear_acquired={stats['gear_acquired']} "
            f"attempts_with_resources={stats['gear_attempts_with_resources']} "
            f"attempts_without_resources={stats['gear_attempts_without_resources']}"
        )
    print(f"- gear resource windows: {gear_resource_windows}")
    print(f"- gear resource windows with role adjacent: {gear_resource_windows_with_adjacent}")
    role_summary = summarize_role_counts(role_counts_history, sorted(expected_roles))
    all_roles_steps = count_steps_with_roles(role_counts_history, sorted(expected_roles))
    core_roles_steps = count_steps_with_roles(role_counts_history, ["miner", "aligner", "scrambler"])
    transition_counts = count_role_transitions(role_transitions)
    print("Role coverage")
    for role in sorted(expected_roles):
        summary = role_summary[role]
        print(f"- {role}: min={summary['min']} max={summary['max']} avg={summary['avg']:.2f}")
    print(f"- steps_with_all_roles: {all_roles_steps}")
    print(f"- steps_with_core_roles: {core_roles_steps}")
    if transition_counts:
        top_transitions = sorted(transition_counts.items(), key=lambda item: item[1], reverse=True)[:5]
        formatted = ", ".join(f"{prev}->{next}:{count}" for (prev, next), count in top_transitions)
        print(f"- top_role_transitions: {formatted}")
    if trace_roles:
        print("Role trace")
        for line in role_trace_lines:
            print(f"- {line}")
    print("Action prerequisite checks")
    print(
        f"- aligner: attempts={prereq_stats['aligner']['attempts']} "
        f"missing_gear={prereq_stats['aligner']['missing_gear']} "
        f"missing_heart={prereq_stats['aligner']['missing_heart']}"
    )
    print(
        f"- scrambler: attempts={prereq_stats['scrambler']['attempts']} "
        f"missing_gear={prereq_stats['scrambler']['missing_gear']} "
        f"missing_heart={prereq_stats['scrambler']['missing_heart']}"
    )
    if trace_prereqs:
        print("Action prerequisite trace")
        for line in prereq_trace_lines:
            print(f"- {line}")
    if trace_resources:
        print("Resource trace (cogs hub inventory)")
        for line in resource_trace_lines:
            print(f"- {line}")

    if hub_seen and hub_missing:
        return 1
    if junction_alignment_mismatches:
        return 1
    if neutral_junction_mismatches:
        return 1
    if not allow_missing_roles:
        if expected_roles - observed_roles:
            return 1
        if role_stats["miner"]["mine_attempts"] == 0 or role_stats["miner"]["mine_mismatches"] > 0:
            return 1
        if role_stats["miner"]["deposit_attempts"] == 0:
            return 1
        if role_stats["aligner"]["align_attempts"] == 0 or role_stats["aligner"]["align_mismatches"] > 0:
            return 1
        if role_stats["aligner"]["align_cogs_targets"] > 0:
            return 1
        if role_stats["scrambler"]["scramble_attempts"] == 0 or role_stats["scrambler"]["scramble_mismatches"] > 0:
            return 1
        if role_stats["scrambler"]["scramble_cogs_targets"] > 0:
            return 1
        if role_stats["scout"]["max_structures_seen"] < 5:
            return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steps", type=int, default=200)
    parser.add_argument("--agents", type=int, default=10)
    parser.add_argument("--max-steps", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--recipe", default="recipes.experiment.cogsguard")
    parser.add_argument(
        "--policy-uri",
        default="metta://policy/role?miner=4&scout=2&aligner=2&scrambler=2",
    )
    parser.add_argument("--allow-missing-roles", action="store_true")
    parser.add_argument("--trace-prereqs", action="store_true")
    parser.add_argument("--trace-roles", action="store_true")
    parser.add_argument("--trace-role-every", type=int, default=1)
    parser.add_argument("--trace-role-limit", type=int, default=0)
    parser.add_argument("--trace-resources", action="store_true")
    parser.add_argument("--trace-resource-every", type=int, default=1)
    parser.add_argument("--trace-resource-limit", type=int, default=0)
    args = parser.parse_args()

    return run_rollout(
        steps=args.steps,
        num_agents=args.agents,
        max_steps=args.max_steps,
        seed=args.seed,
        recipe_module=args.recipe,
        policy_uri=args.policy_uri,
        allow_missing_roles=args.allow_missing_roles,
        trace_prereqs=args.trace_prereqs,
        trace_roles=args.trace_roles,
        trace_role_every=args.trace_role_every,
        trace_role_limit=args.trace_role_limit,
        trace_resources=args.trace_resources,
        trace_resource_every=args.trace_resource_every,
        trace_resource_limit=args.trace_resource_limit,
    )


if __name__ == "__main__":
    raise SystemExit(main())
