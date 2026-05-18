#!/usr/bin/env -S uv run
"""Run scripted baselines and emit a JSON+HTML report bundle.

Thread Vision staged artifact pipeline:
- Stage 2: Execute scripted specialist and adaptive baselines across fixed seeds,
  compute guardrails + role KPIs, and emit thresholded JSON/HTML artifacts.
- Stage 3: Add BC-readiness checks and shaped-reward/KPI alignment checks.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, pstdev
from typing import Any, Literal

from agent_policies.tools.eval.cogsguard.evals.planky_evals import (
    PlankyAlignerFullCycle,
    PlankyMinerFullCycle,
    PlankyMultiRole,
    PlankyScoutExplore,
    PlankyScramblerTarget,
)
from cogsguard.game import ForcedRoleVibesVariant
from cogsguard.game.damage import DamageVariant
from cogsguard.game.teams import TeamConfig, TeamVariant
from cogsguard.game.vibes import VibesVariant
from cogsguard.missions.arena import make_arena_map_builder
from cogsguard.missions.mission import CvCMission
from cogsguard.train.reward_variants import apply_reward_variants

from mettagrid.policy.loader import discover_and_register_policies, initialize_or_load_policy
from mettagrid.policy.policy import PolicySpec
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.runner.rollout import resolve_env_for_seed, run_episode_local
from mettagrid.runner.types import PureSingleEpisodeResult
from mettagrid.simulator.rollout import Rollout
from mettagrid.simulator.time_averaged_stats import TimeAveragedStatsHandler

ELEMENTS = ("carbon", "oxygen", "germanium", "silicon")


@dataclass(frozen=True)
class BaselineTarget:
    key: str
    label: str
    role: str
    policy: str
    mission_cls: type
    max_steps: int
    init_kwargs: dict[str, Any]


@dataclass(frozen=True)
class ThresholdRule:
    metric: str
    op: Literal["min", "max"]
    target: float


TARGETS: tuple[BaselineTarget, ...] = (
    BaselineTarget(
        key="miner_specialist",
        label="Static Miner Specialist",
        role="miner",
        policy="role",
        mission_cls=PlankyMinerFullCycle,
        max_steps=300,
        init_kwargs={"role_order": "miner"},
    ),
    BaselineTarget(
        key="scout_specialist",
        label="Static Scout Specialist",
        role="scout",
        policy="role",
        mission_cls=PlankyScoutExplore,
        max_steps=200,
        init_kwargs={"role_order": "scout"},
    ),
    BaselineTarget(
        key="aligner_specialist",
        label="Static Aligner Specialist",
        role="aligner",
        policy="role",
        mission_cls=PlankyAlignerFullCycle,
        max_steps=300,
        init_kwargs={"role_order": "aligner"},
    ),
    BaselineTarget(
        key="scrambler_specialist",
        label="Static Scrambler Specialist",
        role="scrambler",
        policy="role",
        mission_cls=PlankyScramblerTarget,
        max_steps=300,
        init_kwargs={"role_order": "scrambler"},
    ),
    BaselineTarget(
        key="adaptive_gap_filler",
        label="Adaptive Gap-Filler (role)",
        role="gap_filler",
        policy="role",
        mission_cls=PlankyMultiRole,
        max_steps=240,
        init_kwargs={"gear": 4},
    ),
)

GUARDRAIL_RULES: tuple[ThresholdRule, ...] = (
    ThresholdRule(metric="action_timeouts", op="max", target=0.0),
    ThresholdRule(metric="move_fail_rate", op="max", target=0.10),
    ThresholdRule(metric="noop_rate", op="max", target=0.20),
)

ROLE_KPI_RULES: dict[str, tuple[ThresholdRule, ...]] = {
    "miner": (
        ThresholdRule(metric="resources_per_step", op="min", target=0.01),
        ThresholdRule(metric="resource_diversity", op="min", target=1.0),
        ThresholdRule(metric="role_uptime", op="min", target=0.90),
    ),
    "scout": (
        ThresholdRule(metric="discovery_per_step", op="min", target=20.0),
        ThresholdRule(metric="freeze_proxy", op="max", target=10.0),
        ThresholdRule(metric="role_uptime", op="min", target=0.90),
    ),
    "aligner": (
        ThresholdRule(metric="aligned_junction_held", op="min", target=1.0),
        ThresholdRule(metric="hearts_to_junction_conversion", op="min", target=0.10),
        ThresholdRule(metric="role_uptime", op="min", target=0.90),
    ),
    "scrambler": (
        ThresholdRule(metric="scramble_events", op="min", target=1.0),
        ThresholdRule(metric="clips_junction_suppression", op="min", target=0.05),
        ThresholdRule(metric="role_uptime", op="min", target=0.90),
    ),
    "gap_filler": (
        ThresholdRule(metric="role_coverage", op="min", target=3.0),
        ThresholdRule(metric="role_switch_events", op="max", target=8.0),
    ),
}

FAILURE_FIXES: dict[str, tuple[str, str]] = {
    "action_timeouts": (
        "action timeouts observed",
        "audit per-step loops and pathfinding fallbacks to guarantee bounded decision latency",
    ),
    "move_fail_rate": (
        "high move failure rate",
        "improve collision yielding and blocked-cell rerouting before issuing move actions",
    ),
    "noop_rate": (
        "high noop rate",
        "tighten role decision thresholds to prefer productive actions over waiting",
    ),
    "resources_per_step": (
        "miner objective not achieved (low resource gain)",
        "prioritize extractor acquisition and enforce extract/deposit cadence",
    ),
    "resource_diversity": (
        "miner objective not achieved (low resource diversity)",
        "route to underrepresented resource types before returning to hub loops",
    ),
    "role_uptime": (
        "role commitment unstable",
        "reduce role switching pressure and increase minimum role commitment window",
    ),
    "discovery_per_step": (
        "scout objective not achieved (low discovery rate)",
        "increase frontier targeting and reduce revisits to mapped corridors",
    ),
    "freeze_proxy": (
        "scout objective not achieved (high freeze/stall proxy)",
        "tighten anti-stall fallback and corridor escape logic",
    ),
    "aligned_junction_held": (
        "aligner objective not achieved (no held aligned junctions)",
        "enforce heart prerequisite sequence before junction approach",
    ),
    "hearts_to_junction_conversion": (
        "aligner objective not achieved (poor heart-to-junction conversion)",
        "improve junction targeting once hearts are acquired and avoid idle heart hoarding",
    ),
    "scramble_events": (
        "scrambler objective not achieved (no scramble pressure)",
        "prioritize enemy-junction targeting after heart acquisition",
    ),
    "clips_junction_suppression": (
        "scrambler objective not achieved (weak opponent suppression)",
        "raise priority of contesting enemy-held junctions during pressure windows",
    ),
    "role_coverage": (
        "adaptive role coverage incomplete",
        "tune gap detection priorities and commitment windows",
    ),
    "role_switch_events": (
        "adaptive role switching is too noisy",
        "increase switch cooldown and hysteresis to reduce thrash",
    ),
}

BC_PRIMARY_KPI: dict[str, str] = {
    "miner": "resources_per_step",
    "scout": "discovery_per_step",
    "aligner": "hearts_to_junction_conversion",
    "scrambler": "scramble_events",
    "gap_filler": "role_coverage",
}

SHAPED_REWARD_ALIGNMENT_RULES: dict[str, dict[str, set[str]]] = {
    "miner": {
        "resource_gain": {
            "carbon_gained",
            "oxygen_gained",
            "germanium_gained",
            "silicon_gained",
            "gain_diversity",
        },
        "resource_deposit": {
            "team_carbon_deposited",
            "team_oxygen_deposited",
            "team_germanium_deposited",
            "team_silicon_deposited",
            "loss_diversity",
        },
    },
    "scout": {"exploration": {"cell_visited"}},
    "aligner": {
        "alignment": {"junction_aligned_by_agent"},
        "hearts": {"heart_gained"},
    },
    "scrambler": {"scramble": {"junction_scrambled_by_agent"}},
}

SCRIPTED_REPORT_SCOPE_NOTE = (
    "This report enforces technical scripted-baseline gates only (reliability, KPI, BC-readiness, "
    "reward-alignment). Product retention/cohort metrics are tracked separately outside this script."
)

SPRINT_STAGE_GATE_THRESHOLDS: dict[str, int] = {
    "stage2_targets_passing_overall": len(TARGETS),
    "stage3_targets_bc_ready": len(TARGETS),
    "stage3_reward_alignment_roles": len(SHAPED_REWARD_ALIGNMENT_RULES),
}


def _sum_agent_stat(agent_stats: list[dict[str, float]], key: str) -> float:
    return sum(float(agent.get(key, 0.0)) for agent in agent_stats)


def _sum_hub_stat(team_stats: dict[str, Any], key: str) -> float:
    return float(team_stats.get(key, 0.0))


def _extract_numeric_stats(scope: dict[str, Any]) -> dict[str, float]:
    return {
        str(raw_key): float(raw_value) for raw_key, raw_value in scope.items() if isinstance(raw_value, (int, float))
    }


def _extract_team_stats(stats: dict[str, Any]) -> dict[str, dict[str, float]]:
    scope = stats.get("team")
    if not isinstance(scope, dict):
        return {"cogs": {}, "clips": {}}

    cogs_scope = scope.get("cogs")
    clips_scope = scope.get("clips")
    if isinstance(cogs_scope, dict) or isinstance(clips_scope, dict):
        return {
            "cogs": _extract_numeric_stats(cogs_scope or {}),
            "clips": _extract_numeric_stats(clips_scope or {}),
        }

    # Single-team episodes expose a flat team stats map.
    flat_scope = _extract_numeric_stats(scope)
    if flat_scope:
        return {"cogs": flat_scope, "clips": {}}

    return {"cogs": {}, "clips": {}}


def _sum_element_stats(
    *,
    agent_stats: list[dict[str, float]],
    cogs_stats: dict[str, Any],
    agent_suffix: str,
    hub_suffix: str,
) -> tuple[float, dict[str, float]]:
    per_element: dict[str, float] = {}
    for element in ELEMENTS:
        from_agent = _sum_agent_stat(agent_stats, f"{element}.{agent_suffix}")
        from_hub = _sum_hub_stat(cogs_stats, f"{element}.{hub_suffix}")
        per_element[element] = max(from_agent, from_hub)
    return sum(per_element.values()), per_element


def _role_signal(agent_stats: list[dict[str, float]], role: str) -> float:
    gained = _sum_agent_stat(agent_stats, f"{role}.gained")
    amount = _sum_agent_stat(agent_stats, f"{role}.amount")
    return max(gained, amount)


def _role_uptime(cogs_stats: dict[str, Any], agent_stats: list[dict[str, float]], role: str, steps: int) -> float:
    held = _sum_hub_stat(cogs_stats, f"aligned.c:{role}.held")
    if held > 0.0:
        return held / max(float(steps), 1.0)
    amount = _sum_agent_stat(agent_stats, f"{role}.amount")
    if amount > 0.0:
        return min(amount / max(float(len(agent_stats)), 1.0), 1.0)
    gained = _sum_agent_stat(agent_stats, f"{role}.gained")
    if gained > 0.0:
        return 1.0
    return 0.0


def _policy_role(agent_policy: Any) -> str | None:
    state = getattr(agent_policy, "_state", None)
    if state is None:
        return None

    role = getattr(state, "role", None)
    if role is None:
        return None

    role_value = getattr(role, "value", role)
    return str(role_value)


@dataclass(frozen=True)
class RoleTransition:
    step: int
    agent_id: int
    previous_role: str | None
    current_role: str
    counted: bool


def _policy_role_vibe(agent_policy: Any) -> str | None:
    state = getattr(agent_policy, "_state", None)
    if state is None:
        return None

    current_vibe = getattr(state, "current_vibe", None)
    if current_vibe is None:
        return None

    vibe = str(getattr(current_vibe, "value", current_vibe))
    if vibe not in {"miner", "scout", "aligner", "scrambler"}:
        return None
    return vibe


def _collect_role_transitions(
    rollout: Rollout,
    agent_policies: list[Any],
) -> tuple[float, list[RoleTransition]]:
    previous_roles = [_policy_role_vibe(agent_policy) for agent_policy in agent_policies]
    role_switch_events = 0.0
    transitions: list[RoleTransition] = []

    while not rollout.is_done():
        rollout.step()
        current_roles = [_policy_role_vibe(agent_policy) for agent_policy in agent_policies]
        step = int(rollout._sim.current_step)
        for agent_id, (previous_role, current_role) in enumerate(zip(previous_roles, current_roles, strict=True)):
            if current_role is None or current_role == previous_role:
                continue

            counted = previous_role is not None
            if counted:
                role_switch_events += 1.0
            transitions.append(
                RoleTransition(
                    step=step,
                    agent_id=agent_id,
                    previous_role=previous_role,
                    current_role=current_role,
                    counted=counted,
                )
            )
        previous_roles = current_roles

    return role_switch_events, transitions


def _run_episode_local_with_role_switches(
    *,
    policy_spec: PolicySpec,
    env_cfg: Any,
    seed: int,
    device: str,
) -> tuple[PureSingleEpisodeResult, float, list[RoleTransition]]:
    env_for_rollout = resolve_env_for_seed(env_cfg, seed)
    env_interface = PolicyEnvInterface.from_mg_cfg(env_for_rollout)
    policy = initialize_or_load_policy(env_interface, policy_spec, device_override=device)
    agent_policies = [policy.agent_policy(agent_id) for agent_id in range(env_for_rollout.game.num_agents)]
    stats_handler = TimeAveragedStatsHandler()

    rollout = Rollout(
        env_for_rollout,
        agent_policies,
        policy_names=[policy_spec.name] * env_for_rollout.game.num_agents,
        max_action_time_ms=10000,
        render_mode="none",
        autostart=False,
        seed=seed,
        event_handlers=[stats_handler],
    )

    role_switch_events, transitions = _collect_role_transitions(rollout, agent_policies)

    results = PureSingleEpisodeResult(
        rewards=list(rollout._sim.episode_rewards),
        action_timeouts=list(rollout.timeout_counts),
        stats=rollout._sim.episode_stats,
        steps=rollout._sim.current_step,
        time_averaged_game_stats=stats_handler.time_averaged_game_stats,
        overage_exceeded_at=list(rollout.overage_exceeded_at),
    )
    return results, role_switch_events, transitions


def _compute_kpis(
    role: str,
    agent_stats: list[dict[str, float]],
    hub_stats: dict[str, Any],
    steps: int,
    *,
    role_switch_events: float | None = None,
) -> dict[str, float]:
    cogs = hub_stats.get("cogs") or {}
    clips = hub_stats.get("clips") or {}

    total_element_gained, per_element_gain = _sum_element_stats(
        agent_stats=agent_stats,
        cogs_stats=cogs,
        agent_suffix="gained",
        hub_suffix="deposited",
    )
    total_element_deposited, per_element_deposit = _sum_element_stats(
        agent_stats=agent_stats,
        cogs_stats=cogs,
        agent_suffix="deposited",
        hub_suffix="deposited",
    )

    diversity = sum(1 for element in ELEMENTS if (per_element_gain[element] + per_element_deposit[element]) > 0.0)

    aligned_by_agent = _sum_agent_stat(agent_stats, "junction.aligned_by_agent")
    aligned_junction_gained = max(_sum_hub_stat(cogs, "aligned.junction.gained"), aligned_by_agent)
    aligned_junction_held = _sum_hub_stat(cogs, "aligned.junction.held")
    if aligned_junction_held <= 0.0 and aligned_junction_gained > 0.0:
        aligned_junction_held = aligned_junction_gained
    hearts_gained = max(_sum_agent_stat(agent_stats, "heart.gained"), _sum_hub_stat(cogs, "heart.withdrawn"))
    clips_junction_held = _sum_hub_stat(clips, "aligned.junction.held")
    clips_junction_lost = _sum_hub_stat(clips, "aligned.junction.lost")
    scramble_events = max(_sum_agent_stat(agent_stats, "junction.scrambled_by_agent"), clips_junction_lost)

    vibe_change_events = _sum_agent_stat(agent_stats, "action.change_vibe.success")
    effective_role_switch_events = role_switch_events if role_switch_events is not None else vibe_change_events

    kpis: dict[str, float] = {
        "resources_per_step": total_element_gained / max(steps, 1),
        "deposited_to_gained_ratio": total_element_deposited / max(total_element_gained, 1.0),
        "resource_diversity": float(diversity),
        "discovery_per_step": _sum_agent_stat(agent_stats, "cell.visited") / max(steps, 1),
        "freeze_proxy": _sum_agent_stat(agent_stats, "status.max_steps_without_motion") / max(len(agent_stats), 1),
        "role_uptime": _role_uptime(cogs, agent_stats, role if role != "gap_filler" else "miner", steps),
        "aligned_junction_held": aligned_junction_held,
        "aligned_junction_gained": aligned_junction_gained,
        "hearts_to_junction_conversion": aligned_junction_gained / max(hearts_gained, 1.0),
        "scrambled_by_agent": _sum_agent_stat(agent_stats, "junction.scrambled_by_agent"),
        "scramble_events": scramble_events,
        "clips_junction_held": clips_junction_held,
        "clips_junction_suppression": max(0.0, 1.0 - (clips_junction_held / max(float(steps), 1.0))),
        "role_switch_events": effective_role_switch_events,
    }

    if role == "gap_filler":
        role_uptime_by_role = {
            r: _role_uptime(cogs, agent_stats, r, steps) for r in ("miner", "scout", "aligner", "scrambler")
        }
        if role_switch_events is None:
            setup_switches = 2.0 * float(len(agent_stats))
            kpis["role_switch_events"] = max(vibe_change_events - setup_switches, 0.0)
        role_coverage = sum(1.0 for r in role_uptime_by_role if _role_signal(agent_stats, r) > 0.0)
        kpis["role_coverage"] = role_coverage
        kpis["role_uptime"] = max(role_uptime_by_role.values(), default=0.0)

    return kpis


def _compute_guardrails(agent_stats: list[dict[str, float]]) -> dict[str, float]:
    move_success = _sum_agent_stat(agent_stats, "action.move.success")
    move_failed = _sum_agent_stat(agent_stats, "action.move.failed")
    noop_success = _sum_agent_stat(agent_stats, "action.noop.success")
    timeouts = _sum_agent_stat(agent_stats, "action.timeout")
    total_actions = max(move_success + move_failed + noop_success, 1.0)
    return {
        "action_timeouts": timeouts,
        "move_success": move_success,
        "move_failed": move_failed,
        "noop_success": noop_success,
        "move_fail_rate": move_failed / total_actions,
        "noop_rate": noop_success / total_actions,
    }


def _objective_score(role: str, kpis: dict[str, float]) -> float:
    if role == "miner":
        return min(kpis["resources_per_step"] / 0.05, 1.0)
    if role == "scout":
        return min(kpis["discovery_per_step"] / 50.0, 1.0)
    if role == "aligner":
        return max(min(kpis["aligned_junction_held"] / 50.0, 1.0), min(kpis["hearts_to_junction_conversion"], 1.0))
    if role == "scrambler":
        return max(min(kpis["scramble_events"] / 1.0, 1.0), min(kpis["clips_junction_suppression"] / 0.25, 1.0))
    if role == "gap_filler":
        return min(kpis["role_coverage"] / 4.0, 1.0)
    return 0.0


def _fingerprint(role: str, kpis: dict[str, float], guardrails: dict[str, float]) -> dict[str, float]:
    return {
        "objective": _objective_score(role, kpis),
        "activity": max(0.0, 1.0 - guardrails["noop_rate"]),
        "efficiency": max(0.0, 1.0 - guardrails["move_fail_rate"]),
        "reliability": 0.0 if guardrails["action_timeouts"] > 0 else 1.0,
    }


def _evaluate_rules(values: dict[str, float], rules: tuple[ThresholdRule, ...]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    for rule in rules:
        value = float(values[rule.metric])
        passed = value >= rule.target if rule.op == "min" else value <= rule.target
        checks.append(
            {
                "metric": rule.metric,
                "value": value,
                "operator": rule.op,
                "target": rule.target,
                "pass": passed,
            }
        )

    return {
        "checks": checks,
        "passed": all(check["pass"] for check in checks),
        "failed_metrics": [check["metric"] for check in checks if not check["pass"]],
    }


def _diagnose(
    role: str,
    kpis: dict[str, float],
    threshold_eval: dict[str, Any],
) -> dict[str, str]:
    for metric in threshold_eval["guardrails"]["failed_metrics"]:
        symptom, next_fix = FAILURE_FIXES.get(metric, ("guardrail failure", "inspect failing guardrail metric"))
        return {"symptom": symptom, "next_fix": next_fix}

    for metric in threshold_eval["kpis"]["failed_metrics"]:
        symptom, next_fix = FAILURE_FIXES.get(metric, ("kpi failure", "inspect failing KPI metric"))
        return {"symptom": symptom, "next_fix": next_fix}

    if role == "gap_filler" and kpis["role_coverage"] < 4.0:
        symptom, next_fix = FAILURE_FIXES["role_coverage"]
        return {"symptom": symptom, "next_fix": next_fix}

    return {
        "symptom": "no major failure symptom",
        "next_fix": "continue monitoring with broader mission coverage",
    }


def _run_target_seed(target: BaselineTarget, seed: int) -> dict[str, Any]:
    mission = target.mission_cls()
    env_cfg = mission.make_env()
    env_cfg.game.max_steps = target.max_steps
    spec = PolicySpec(class_path=target.policy, data_path=None, init_kwargs=target.init_kwargs)
    role_switch_events: float | None = None
    if target.role == "gap_filler":
        results, role_switch_events, _transitions = _run_episode_local_with_role_switches(
            policy_spec=spec,
            env_cfg=env_cfg,
            seed=seed,
            device="cpu",
        )
    else:
        results, _replay = run_episode_local(
            policy_specs=[spec],
            assignments=[0] * env_cfg.game.num_agents,
            env=env_cfg,
            seed=seed,
            device="cpu",
            render_mode="none",
        )

    agent_stats = [dict(stats) for stats in (results.stats.get("agent") or [])]
    hub_stats = _extract_team_stats(results.stats)
    guardrails = _compute_guardrails(agent_stats)
    kpis = _compute_kpis(
        target.role,
        agent_stats,
        hub_stats,
        int(results.steps),
        role_switch_events=role_switch_events,
    )
    fingerprint = _fingerprint(target.role, kpis, guardrails)

    role_rules = ROLE_KPI_RULES.get(target.role, ())
    threshold_eval = {
        "guardrails": _evaluate_rules(guardrails, GUARDRAIL_RULES),
        "kpis": _evaluate_rules(kpis, role_rules),
    }
    threshold_eval["overall_pass"] = threshold_eval["guardrails"]["passed"] and threshold_eval["kpis"]["passed"]
    diagnosis = _diagnose(target.role, kpis, threshold_eval)

    return {
        "seed": seed,
        "steps": int(results.steps),
        "num_agents": len(results.rewards),
        "reward_sum": float(sum(results.rewards)),
        "non_zero_reward": any(abs(float(r)) > 1e-9 for r in results.rewards),
        "guardrails": guardrails,
        "kpis": kpis,
        "fingerprint": fingerprint,
        "thresholds": threshold_eval,
        "diagnosis": diagnosis,
    }


def _run_target(target: BaselineTarget, seeds: list[int]) -> dict[str, Any]:
    mission_name = target.mission_cls.__name__
    runs = [_run_target_seed(target, seed) for seed in seeds]
    aggregate = _aggregate_runs(target.role, runs)

    return {
        "target": {
            "key": target.key,
            "label": target.label,
            "role": target.role,
            "policy": target.policy,
            "mission": mission_name,
            "max_steps": target.max_steps,
            "init_kwargs": target.init_kwargs,
        },
        "runs": runs,
        "aggregate": aggregate,
    }


def _aggregate_runs(role: str, runs: list[dict[str, Any]]) -> dict[str, Any]:
    if not runs:
        return {}

    def avg(path: tuple[str, ...]) -> float:
        total = 0.0
        for run in runs:
            value: Any = run
            for key in path:
                value = value[key]
            total += float(value)
        return total / len(runs)

    aggregate_guardrails = {
        "action_timeouts": avg(("guardrails", "action_timeouts")),
        "move_fail_rate": avg(("guardrails", "move_fail_rate")),
        "noop_rate": avg(("guardrails", "noop_rate")),
    }
    aggregate_kpis = {key: avg(("kpis", key)) for key in runs[0]["kpis"]}
    aggregate_fingerprint = {key: avg(("fingerprint", key)) for key in runs[0]["fingerprint"]}

    threshold_eval = {
        "guardrails": _evaluate_rules(aggregate_guardrails, GUARDRAIL_RULES),
        "kpis": _evaluate_rules(aggregate_kpis, ROLE_KPI_RULES.get(role, ())),
    }
    threshold_eval["overall_pass"] = threshold_eval["guardrails"]["passed"] and threshold_eval["kpis"]["passed"]
    diagnosis = _diagnose(role, aggregate_kpis, threshold_eval)

    return {
        "episodes": len(runs),
        "non_zero_reward_rate": sum(1 for run in runs if run["non_zero_reward"]) / len(runs),
        "guardrail_pass_rate": sum(1 for run in runs if run["thresholds"]["guardrails"]["passed"]) / len(runs),
        "kpi_pass_rate": sum(1 for run in runs if run["thresholds"]["kpis"]["passed"]) / len(runs),
        "overall_pass_rate": sum(1 for run in runs if run["thresholds"]["overall_pass"]) / len(runs),
        "guardrails": aggregate_guardrails,
        "kpis": aggregate_kpis,
        "fingerprint": aggregate_fingerprint,
        "thresholds": threshold_eval,
        "diagnosis": diagnosis,
    }


def _compute_stage_status(targets: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(targets)
    overall_pass_targets = sum(1 for target in targets if target["aggregate"]["thresholds"]["overall_pass"])
    guardrail_pass_targets = sum(1 for target in targets if target["aggregate"]["thresholds"]["guardrails"]["passed"])
    kpi_pass_targets = sum(1 for target in targets if target["aggregate"]["thresholds"]["kpis"]["passed"])

    return {
        "total_targets": total,
        "targets_passing_guardrails": guardrail_pass_targets,
        "targets_passing_kpis": kpi_pass_targets,
        "targets_passing_overall": overall_pass_targets,
        "overall_stage_pass": overall_pass_targets == total,
    }


def _round_map(values: dict[str, Any]) -> dict[str, float]:
    return {k: round(float(v), 6) for k, v in values.items()}


def _run_signature(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "steps": int(run["steps"]),
        "num_agents": int(run["num_agents"]),
        "reward_sum": round(float(run["reward_sum"]), 6),
        "guardrails": _round_map(run["guardrails"]),
        "kpis": _round_map(run["kpis"]),
        "thresholds": {
            "guardrails": bool(run["thresholds"]["guardrails"]["passed"]),
            "kpis": bool(run["thresholds"]["kpis"]["passed"]),
            "overall": bool(run["thresholds"]["overall_pass"]),
        },
    }


def _compute_bc_readiness(
    targets: list[dict[str, Any]],
    target_specs: dict[str, BaselineTarget],
    seeds: list[int],
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []

    for target_entry in targets:
        target_meta = target_entry["target"]
        role = target_meta["role"]
        primary_kpi = BC_PRIMARY_KPI[role]

        runs = target_entry["runs"]
        primary_values = [float(run["kpis"][primary_kpi]) for run in runs]
        primary_non_zero_rate = sum(1 for value in primary_values if value > 0.0) / max(len(primary_values), 1)
        primary_mean = mean(primary_values)
        primary_std = pstdev(primary_values) if len(primary_values) > 1 else 0.0
        primary_cv = primary_std / max(abs(primary_mean), 1e-9)

        deterministic_seed = seeds[0]
        target_spec = target_specs[target_meta["key"]]
        baseline_seed_run = next((run for run in runs if int(run["seed"]) == deterministic_seed), runs[0])
        deterministic_probe = _run_target_seed(target_spec, deterministic_seed)
        deterministic_under_seed = _run_signature(deterministic_probe) == _run_signature(baseline_seed_run)

        kpi_pass_rate = float(target_entry["aggregate"]["kpi_pass_rate"])
        role_consistent = kpi_pass_rate >= (2.0 / 3.0)
        low_noise = primary_cv <= 1.0
        bc_ready = deterministic_under_seed and role_consistent and low_noise and primary_non_zero_rate >= (2.0 / 3.0)

        entries.append(
            {
                "target_key": target_meta["key"],
                "role": role,
                "policy": target_meta["policy"],
                "primary_kpi": primary_kpi,
                "deterministic_seed": deterministic_seed,
                "deterministic_under_seed": deterministic_under_seed,
                "kpi_pass_rate": kpi_pass_rate,
                "primary_non_zero_rate": primary_non_zero_rate,
                "primary_mean": primary_mean,
                "primary_std": primary_std,
                "primary_cv": primary_cv,
                "role_consistent": role_consistent,
                "low_noise": low_noise,
                "bc_ready": bc_ready,
            }
        )

    total = len(entries)
    bc_ready_targets = sum(1 for entry in entries if entry["bc_ready"])
    deterministic_targets = sum(1 for entry in entries if entry["deterministic_under_seed"])

    return {
        "targets": entries,
        "total_targets": total,
        "targets_deterministic": deterministic_targets,
        "targets_bc_ready": bc_ready_targets,
        "overall_pass": bc_ready_targets == total,
    }


def _collect_role_conditional_reward_keys() -> dict[str, set[str]]:
    forced_roles = ForcedRoleVibesVariant()
    role_order = tuple(forced_roles.role_order)
    mission = CvCMission(
        name="thread_vision_role_conditional_audit",
        description="Thread Vision shaped reward alignment audit",
        map_builder=make_arena_map_builder(num_agents=4),
        num_agents=4,
        min_cogs=4,
        max_cogs=4,
        max_steps=100,
    ).with_variants(
        [
            TeamVariant(default_teams={"cogs": TeamConfig(num_agents=4)}),
            DamageVariant(),
            VibesVariant(),
            forced_roles,
        ]
    )
    env = mission.make_env()
    apply_reward_variants(env, variants=["role_conditional"])
    if not env.game.agents:
        raise ValueError("Expected per-agent configs for role_conditional reward alignment audit")

    reward_keys_by_role: dict[str, set[str]] = {}
    vibe_names = env.game.vibe_names
    for agent in env.game.agents:
        vibe_id = agent.vibe
        if vibe_id < 0 or vibe_id >= len(vibe_names):
            raise ValueError(f"Unexpected vibe_id {vibe_id} in forced role audit")
        role = vibe_names[vibe_id]
        if role not in role_order:
            raise ValueError(f"Unexpected role {role!r} in forced role audit")
        if role not in SHAPED_REWARD_ALIGNMENT_RULES:
            continue
        reward_keys = set(agent.rewards)
        if role in reward_keys_by_role and reward_keys_by_role[role] != reward_keys:
            raise ValueError(f"Mismatched reward keys for role {role} in forced role audit")
        reward_keys_by_role[role] = reward_keys

    missing_roles = [role for role in SHAPED_REWARD_ALIGNMENT_RULES if role not in reward_keys_by_role]
    if missing_roles:
        raise ValueError(f"Missing role reward configs in role_conditional audit: {missing_roles}")

    return reward_keys_by_role


def _compute_shaped_reward_alignment() -> dict[str, Any]:
    reward_keys_by_role = _collect_role_conditional_reward_keys()
    role_results: list[dict[str, Any]] = []

    for role, expected_groups in SHAPED_REWARD_ALIGNMENT_RULES.items():
        actual_keys = reward_keys_by_role[role]
        groups: list[dict[str, Any]] = []
        for group_name, expected_keys in expected_groups.items():
            matched = sorted(actual_keys & expected_keys)
            groups.append(
                {
                    "group": group_name,
                    "expected_keys": sorted(expected_keys),
                    "matched_keys": matched,
                    "pass": len(matched) > 0,
                }
            )

        role_results.append(
            {
                "role": role,
                "reward_keys": sorted(actual_keys),
                "groups": groups,
                "pass": all(group["pass"] for group in groups),
            }
        )

    total = len(role_results)
    passing = sum(1 for result in role_results if result["pass"])
    return {
        "roles": role_results,
        "total_roles": total,
        "roles_passing": passing,
        "overall_pass": passing == total,
    }


def _compute_stage3_status(targets: list[dict[str, Any]], seeds: list[int]) -> dict[str, Any]:
    target_specs = {target.key: target for target in TARGETS}
    bc_readiness = _compute_bc_readiness(targets, target_specs, seeds)
    shaped_reward_alignment = _compute_shaped_reward_alignment()
    return {
        "bc_readiness": bc_readiness,
        "shaped_reward_alignment": shaped_reward_alignment,
        "overall_stage3_pass": bc_readiness["overall_pass"] and shaped_reward_alignment["overall_pass"],
    }


def _compute_acceptance_gates(stage_status: dict[str, Any], stage3_status: dict[str, Any]) -> dict[str, Any]:
    stage2_threshold = SPRINT_STAGE_GATE_THRESHOLDS["stage2_targets_passing_overall"]
    stage3_bc_threshold = SPRINT_STAGE_GATE_THRESHOLDS["stage3_targets_bc_ready"]
    stage3_align_threshold = SPRINT_STAGE_GATE_THRESHOLDS["stage3_reward_alignment_roles"]

    stage2_actual = int(stage_status["targets_passing_overall"])
    stage3_bc_actual = int(stage3_status["bc_readiness"]["targets_bc_ready"])
    stage3_align_actual = int(stage3_status["shaped_reward_alignment"]["roles_passing"])

    checks = [
        {
            "name": "stage2_targets_passing_overall",
            "actual": stage2_actual,
            "threshold": stage2_threshold,
            "pass": stage2_actual >= stage2_threshold,
        },
        {
            "name": "stage3_targets_bc_ready",
            "actual": stage3_bc_actual,
            "threshold": stage3_bc_threshold,
            "pass": stage3_bc_actual >= stage3_bc_threshold,
        },
        {
            "name": "stage3_reward_alignment_roles",
            "actual": stage3_align_actual,
            "threshold": stage3_align_threshold,
            "pass": stage3_align_actual >= stage3_align_threshold,
        },
    ]

    return {
        "checks": checks,
        "overall_pass": all(check["pass"] for check in checks),
    }


def _render_html(report: dict[str, Any], output_path: Path) -> None:
    role_blocks: list[str] = []
    chart_data: dict[str, dict[str, float]] = {}

    for entry in report["targets"]:
        target = entry["target"]
        agg = entry["aggregate"]
        diag = agg["diagnosis"]
        thresholds = agg["thresholds"]
        chart_data[target["label"]] = agg["fingerprint"]

        status = "PASS" if thresholds["overall_pass"] else "FAIL"
        role_blocks.append(
            f"""
<section class=\"card\">
  <h2>{target["label"]} <span class=\"badge {status.lower()}\">{status}</span></h2>
  <p><strong>Policy:</strong> {target["policy"]} &nbsp; <strong>Mission:</strong> {target["mission"]}</p>
  <p><strong>Top failure symptom:</strong> {diag["symptom"]}</p>
  <p><strong>Next fix:</strong> {diag["next_fix"]}</p>
  <ul>
    <li>overall_pass_rate: {agg["overall_pass_rate"]:.2f}</li>
    <li>guardrail_pass_rate: {agg["guardrail_pass_rate"]:.2f}</li>
    <li>kpi_pass_rate: {agg["kpi_pass_rate"]:.2f}</li>
    <li>move_fail_rate: {agg["guardrails"]["move_fail_rate"]:.3f}</li>
    <li>noop_rate: {agg["guardrails"]["noop_rate"]:.3f}</li>
    <li>timeouts: {agg["guardrails"]["action_timeouts"]:.1f}</li>
  </ul>
</section>
"""
        )

    stage = report["stage_status"]
    stage3 = report["stage3_status"]
    stage3_bc_ready = stage3["bc_readiness"]["targets_bc_ready"]
    stage3_bc_total = stage3["bc_readiness"]["total_targets"]
    stage3_det = stage3["bc_readiness"]["targets_deterministic"]
    stage3_align = stage3["shaped_reward_alignment"]["roles_passing"]
    stage3_align_total = stage3["shaped_reward_alignment"]["total_roles"]
    acceptance_gates = report["acceptance_gates"]
    acceptance_gate_items = "".join(
        (f"<li>{check['name']}: {check['actual']} / {check['threshold']} (pass={check['pass']})</li>")
        for check in acceptance_gates["checks"]
    )
    footer_text = (
        "Thread Vision staged artifact bundle: Stage 2 KPI/guardrail report + Stage 3 BC/reward "
        "alignment checks. Retention/cohort metrics are tracked outside this report."
    )

    html = f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Scripted Baselines Report</title>
  <style>
    :root {{
      --bg: #f6f8fb;
      --panel: #ffffff;
      --ink: #0f172a;
      --muted: #475569;
      --line: #dbe2ea;
      --pass: #15803d;
      --fail: #b91c1c;
    }}
    body {{
      margin: 0;
      font-family: ui-sans-serif, -apple-system, Segoe UI, sans-serif;
      color: var(--ink);
      background: radial-gradient(circle at top left, #e2f5ee, var(--bg) 45%);
    }}
    .wrap {{ max-width: 1100px; margin: 0 auto; padding: 24px; }}
    h1 {{ margin: 0 0 8px; }}
    .sub {{ color: var(--muted); margin-bottom: 20px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(270px, 1fr)); gap: 12px; }}
    .card {{ background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 14px; }}
    .badge {{ border-radius: 999px; padding: 2px 8px; font-size: 0.8rem; }}
    .badge.pass {{ background: #dcfce7; color: var(--pass); }}
    .badge.fail {{ background: #fee2e2; color: var(--fail); }}
    canvas {{ width: 100%; max-width: 420px; height: 340px; display: block; margin: 0 auto; }}
    .footer {{ color: var(--muted); margin-top: 14px; font-size: 0.9rem; }}
  </style>
</head>
<body>
  <div class=\"wrap\">
    <h1>Scripted Baselines Report</h1>
    <p class=\"sub\">Generated {report["generated_at_utc"]} • Seeds: {", ".join(str(s) for s in report["seeds"])}</p>
    <section class=\"card\">
      <h2>Stage 2 Status</h2>
      <ul>
        <li>overall_stage_pass: {stage["overall_stage_pass"]}</li>
        <li>targets_passing_overall: {stage["targets_passing_overall"]} / {stage["total_targets"]}</li>
        <li>targets_passing_guardrails: {stage["targets_passing_guardrails"]} / {stage["total_targets"]}</li>
        <li>targets_passing_kpis: {stage["targets_passing_kpis"]} / {stage["total_targets"]}</li>
      </ul>
    </section>
    <section class=\"card\">
      <h2>Stage 3 Status</h2>
      <ul>
        <li>overall_stage3_pass: {stage3["overall_stage3_pass"]}</li>
        <li>bc_ready_targets: {stage3_bc_ready} / {stage3_bc_total}</li>
        <li>deterministic_targets: {stage3_det} / {stage3_bc_total}</li>
        <li>reward_alignment_roles: {stage3_align} / {stage3_align_total}</li>
      </ul>
    </section>
    <section class=\"card\">
      <h2>Technical Sprint Gates</h2>
      <p>This report covers technical scripted-baseline gates only. Retention/cohort metrics are tracked separately.</p>
      <ul>
        <li>overall_pass: {acceptance_gates["overall_pass"]}</li>
        {acceptance_gate_items}
      </ul>
    </section>
    <section class=\"card\">
      <h2>Role Fingerprints</h2>
      <canvas id=\"radar\" width=\"420\" height=\"340\"></canvas>
    </section>
    <div class=\"grid\">{"".join(role_blocks)}</div>
    <p class=\"footer\">{footer_text}</p>
  </div>
  <script>
    const data = {json.dumps(chart_data)};
    const labels = ["objective", "activity", "efficiency", "reliability"];
    const colors = ["#0f766e", "#7c3aed", "#dc2626", "#2563eb", "#ca8a04", "#0ea5e9"];
    const canvas = document.getElementById("radar");
    const ctx = canvas.getContext("2d");

    function drawRadar() {{
      const cx = 210;
      const cy = 170;
      const r = 120;
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.strokeStyle = "#cbd5e1";
      ctx.lineWidth = 1;
      for (let ring = 1; ring <= 4; ring++) {{
        ctx.beginPath();
        for (let i = 0; i < labels.length; i++) {{
          const angle = -Math.PI / 2 + (2 * Math.PI * i) / labels.length;
          const x = cx + Math.cos(angle) * r * (ring / 4);
          const y = cy + Math.sin(angle) * r * (ring / 4);
          if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }}
        ctx.closePath();
        ctx.stroke();
      }}
      ctx.fillStyle = "#334155";
      ctx.font = "12px sans-serif";
      for (let i = 0; i < labels.length; i++) {{
        const angle = -Math.PI / 2 + (2 * Math.PI * i) / labels.length;
        const x = cx + Math.cos(angle) * (r + 16);
        const y = cy + Math.sin(angle) * (r + 16);
        ctx.fillText(labels[i], x - 24, y + 4);
      }}

      let idx = 0;
      for (const [name, vals] of Object.entries(data)) {{
        const color = colors[idx % colors.length];
        ctx.strokeStyle = color;
        ctx.fillStyle = color + "33";
        ctx.lineWidth = 2;
        ctx.beginPath();
        labels.forEach((label, i) => {{
          const v = Math.max(0, Math.min(1, vals[label] || 0));
          const angle = -Math.PI / 2 + (2 * Math.PI * i) / labels.length;
          const x = cx + Math.cos(angle) * r * v;
          const y = cy + Math.sin(angle) * r * v;
          if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }});
        ctx.closePath();
        ctx.fill();
        ctx.stroke();
        ctx.fillStyle = color;
        ctx.fillRect(16, 16 + idx * 16, 10, 10);
        ctx.fillStyle = "#0f172a";
        ctx.fillText(name, 30, 25 + idx * 16);
        idx += 1;
      }}
    }}

    drawRadar();
  </script>
</body>
</html>
"""
    output_path.write_text(html)


def _parse_seeds(raw: str) -> list[int]:
    seeds = [int(entry.strip()) for entry in raw.split(",") if entry.strip()]
    if not seeds:
        raise ValueError("At least one seed is required")
    return seeds


def run_report(*, seeds: list[int], output_dir: Path) -> dict[str, Any]:
    discover_and_register_policies("policies.scripted.cogsguard")

    targets = [_run_target(target, seeds) for target in TARGETS]
    stage_status = _compute_stage_status(targets)
    stage3_status = _compute_stage3_status(targets, seeds)
    acceptance_gates = _compute_acceptance_gates(stage_status, stage3_status)

    report = {
        "thread_vision": "Scripted Base Roles",
        "stage": "stage_2_3_artifact_pipeline",
        "generated_at_utc": datetime.now(tz=UTC).isoformat(),
        "seeds": seeds,
        "targets": targets,
        "stage_status": stage_status,
        "stage3_status": stage3_status,
        "scope_note": SCRIPTED_REPORT_SCOPE_NOTE,
        "acceptance_gates": acceptance_gates,
        "technical_stage_gates": acceptance_gates,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "scripted_baselines_report.json"
    html_path = output_dir / "scripted_baselines_report.html"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True))
    _render_html(report, html_path)

    print("Scripted baselines report generated")
    print(f"- JSON: {json_path}")
    print(f"- HTML: {html_path}")
    print(
        "- Stage 2 status: "
        f"{stage_status['targets_passing_overall']}/{stage_status['total_targets']} targets passing overall"
    )
    stage3_bc_ready = stage3_status["bc_readiness"]["targets_bc_ready"]
    stage3_bc_total = stage3_status["bc_readiness"]["total_targets"]
    stage3_align = stage3_status["shaped_reward_alignment"]["roles_passing"]
    stage3_align_total = stage3_status["shaped_reward_alignment"]["total_roles"]
    print(
        f"- Stage 3 status: bc_ready={stage3_bc_ready}/{stage3_bc_total} alignment={stage3_align}/{stage3_align_total}"
    )
    print(f"- Technical sprint gates: {'PASS' if acceptance_gates['overall_pass'] else 'FAIL'}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", default="11,23,42", help="Comma-separated seed list")
    parser.add_argument(
        "--output-dir",
        default="outputs/scripted_baselines",
        help="Output directory for report artifacts",
    )
    parser.add_argument(
        "--enforce-gates",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Return non-zero if locked technical sprint gates fail",
    )
    args = parser.parse_args()

    seeds = _parse_seeds(args.seeds)
    report = run_report(seeds=seeds, output_dir=Path(args.output_dir))
    if args.enforce_gates and not report["acceptance_gates"]["overall_pass"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
