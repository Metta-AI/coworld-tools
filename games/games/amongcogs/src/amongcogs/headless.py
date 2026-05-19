"""Headless debug runner for the Among Us game.

Run with:

    python -m amongcogs.headless --num-agents 12 --max-steps 300 --log-every 25
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from statistics import mean

from amongcogs.constants import INTERACTIVE_STATION_NAMES, STATION_ONLINE_TAG, STATION_SABOTAGED_TAG
from amongcogs.game import (
    CORPSE_RESOURCE,
    MEETING_ACTIVE_RESOURCE,
    MEETING_BALLOT_RESOURCE,
    ROLE_CREW,
    ROLE_IMPOSTOR,
)
from amongcogs.runtime import GAMES, make_game
from amongcogs.shipping import build_gate_check, profile
from mettagrid.policy.loader import discover_and_register_policies, initialize_or_load_policy
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.simulator import Simulation
from mettagrid.util.uri_resolvers.schemes import policy_spec_from_uri


@dataclass
class TimelinePoint:
    step: int
    stations_online: int
    stations_sabotaged: int
    tasks_completed: float
    sabotages: float
    repairs: float
    kills: float
    reports: float
    ejections: float
    vents_used: float
    meeting_calls: float
    emergency_meeting_calls: float
    admin_checks: float
    camera_checks: float
    comms_checks: float
    crew_roles: int
    impostor_roles: int
    corpses: int
    meeting_active_agents: int


@dataclass
class AmongUsHeadlessSummary:
    seed: int
    num_agents: int
    steps: int
    max_steps: int
    completed: bool
    completion_reason: str
    winner: str
    policy_uri: str
    role_counts: dict[str, int]
    totals: dict[str, float]
    game_stats: dict[str, float]
    first_steps: dict[str, int | None]
    actions: dict[str, float | int | dict[str, int]]
    timeline: list[TimelinePoint]
    timings: dict[str, float]

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["timeline"] = [asdict(point) for point in self.timeline]
        return payload


@dataclass(frozen=True)
class AmongUsAuditGateThresholds:
    min_completion_rate: float = 1.0
    min_winner_declared_rate: float = 0.95
    min_tasks_completed_rate: float = 0.95
    min_kills_rate: float = 0.85
    min_reports_rate: float = 0.85
    min_ejections_rate: float = 0.4
    min_repairs_rate: float = 0.55
    min_sabotages_rate: float = 0.3
    min_role_adoption_ratio: float = 1.0
    min_sps_mean: float = 0.0
    max_crew_win_rate: float = 1.0
    min_impostor_win_rate: float = 0.0


@dataclass(frozen=True)
class AmongUsReleaseScenario:
    name: str
    episodes: int
    num_agents: int
    max_steps: int
    gate_profile: str
    end_on_winner: bool
    seed: int = 0
    min_sps_mean: float | None = None


AUDIT_GATE_PROFILES: dict[str, AmongUsAuditGateThresholds] = {
    # Practical baseline for CI/regression detection on current scripted-policy behavior.
    "baseline": AmongUsAuditGateThresholds(),
    # Candidate shipping bar: enforces some winner balance beyond mere completion/coverage.
    "ship_strict": AmongUsAuditGateThresholds(
        min_kills_rate=0.95,
        min_reports_rate=0.95,
        min_ejections_rate=0.45,
        min_repairs_rate=0.7,
        min_sabotages_rate=0.55,
        max_crew_win_rate=0.85,
        min_impostor_win_rate=0.15,
    ),
}

RELEASE_SCENARIO_SUITES: dict[str, tuple[AmongUsReleaseScenario, ...]] = {
    "default": (
        AmongUsReleaseScenario(
            name="default_ship_strict",
            episodes=120,
            num_agents=12,
            max_steps=220,
            gate_profile="ship_strict",
            end_on_winner=False,
            seed=0,
        ),
        AmongUsReleaseScenario(
            name="small_lobby_baseline",
            episodes=40,
            num_agents=8,
            max_steps=180,
            gate_profile="baseline",
            end_on_winner=False,
            seed=1000,
        ),
    ),
}

FIRST_STEP_KEYS = (
    "any_role_assigned",
    "all_roles_assigned",
    "first_task",
    "first_sabotage",
    "first_repair",
    "first_kill",
    "first_report",
    "first_ejection",
    "first_meeting",
    "first_emergency_meeting",
    "first_vent",
    "first_admin_check",
    "first_camera_check",
    "first_comms_check",
    "first_lights_sabotage",
    "first_oxygen_sabotage",
    "first_reactor_sabotage",
    "winner_declared",
)


def run_headless_episode(
    *,
    num_agents: int = 12,
    max_steps: int = 300,
    seed: int = 0,
    policy_uri: str | None = None,
    log_every: int = 25,
    end_on_winner: bool = True,
    verbose: bool = False,
) -> AmongUsHeadlessSummary:
    """Run a full Among Us episode without a renderer and return metrics."""
    game_info = GAMES["amongcogs"]
    resolved_policy_uri = policy_uri or game_info["policy_uri"] or "metta://policy/random"

    for package_name in game_info["policy_packages"]:
        discover_and_register_policies(package_name)

    env = make_game("amongcogs", num_agents=num_agents, max_steps=max_steps)
    env.game.end_episode_on_game_stats = {"winner_declared": 1} if end_on_winner else {}
    env_interface = PolicyEnvInterface.from_mg_cfg(env)
    policy_spec = policy_spec_from_uri(resolved_policy_uri, device="cpu")
    policy = initialize_or_load_policy(env_interface, policy_spec, device_override="cpu")
    agent_policies = [policy.agent_policy(agent_id) for agent_id in range(num_agents)]

    sim = Simulation(env, seed=seed)
    for agent_policy in agent_policies:
        agent_policy.reset(simulation=sim)

    timeline: list[TimelinePoint] = []
    policy_step_ms = 0.0
    sim_step_ms = 0.0
    action_counts: dict[str, int] = {}
    move_attempts = 0
    move_successes = 0
    talk_actions = 0
    talk_chars = 0
    meeting_talk_actions = 0
    meeting_talk_chars = 0
    ballot_talk_actions = 0
    ballot_talk_chars = 0
    total_action_successes = 0
    total_actions = 0

    first_steps = {key: None for key in FIRST_STEP_KEYS}

    wall_start = time.perf_counter()

    try:
        while not sim.is_done():
            issued_actions: list[str] = []
            for agent_id, agent_policy in enumerate(agent_policies):
                in_meeting = sim.agent(agent_id).inventory.get(MEETING_ACTIVE_RESOURCE, 0) > 0
                in_ballot = sim.agent(agent_id).inventory.get(MEETING_BALLOT_RESOURCE, 0) > 0
                action_start = time.perf_counter()
                action = agent_policy.step(sim.agent(agent_id).observation)
                policy_step_ms += (time.perf_counter() - action_start) * 1000.0
                if action.talk is not None:
                    talk_actions += 1
                    talk_chars += len(action.talk)
                    if in_meeting:
                        meeting_talk_actions += 1
                        meeting_talk_chars += len(action.talk)
                    if in_ballot:
                        ballot_talk_actions += 1
                        ballot_talk_chars += len(action.talk)
                    sim.agent(agent_id).set_talk(action.talk)
                    action = replace(action, talk=None)
                sim.agent(agent_id).set_action(action)
                issued_actions.append(action.name)
                action_counts[action.name] = action_counts.get(action.name, 0) + 1

            sim_start = time.perf_counter()
            sim.step()
            sim_step_ms += (time.perf_counter() - sim_start) * 1000.0

            action_success = list(sim.action_success)
            for action_name, succeeded in zip(issued_actions, action_success, strict=False):
                total_actions += 1
                total_action_successes += int(bool(succeeded))
                if action_name.startswith("move_"):
                    move_attempts += 1
                    move_successes += int(bool(succeeded))

            role_counts = _role_counts(sim)
            totals = _totals(sim)
            game_stats = dict(sim.episode_stats.get("game", {}))
            _update_first_steps(
                first_steps,
                step=sim.current_step,
                num_agents=sim.num_agents,
                role_counts=role_counts,
                totals=totals,
                game_stats=game_stats,
            )

            if log_every > 0 and (sim.current_step % log_every == 0 or sim.is_done()):
                point = _snapshot(sim)
                timeline.append(point)
                if verbose:
                    print(
                        f"step={point.step:4d} "
                        f"roles(c/i)={point.crew_roles}/{point.impostor_roles} "
                        f"tasks={point.tasks_completed:.0f} "
                        f"sabotages={point.sabotages:.0f} "
                        f"repairs={point.repairs:.0f} "
                        f"kills={point.kills:.0f} "
                        f"reports={point.reports:.0f} "
                        f"ejections={point.ejections:.0f} "
                        f"corpses={point.corpses} "
                        f"meeting={point.meeting_active_agents} "
                        f"stations online/sab={point.stations_online}/{point.stations_sabotaged}"
                    )

        wall_elapsed = max(1e-9, time.perf_counter() - wall_start)
        role_counts = _role_counts(sim)
        totals = _totals(sim)
        game_stats = dict(sim.episode_stats.get("game", {}))
        winner = (
            "crew"
            if game_stats.get("crew_win", 0) > 0
            else "impostor"
            if game_stats.get("impostor_win", 0) > 0
            else "none"
        )
        completion_reason = "winner_declared" if end_on_winner and winner != "none" else "max_steps"
        move_success_rate = float(move_successes) / move_attempts if move_attempts > 0 else 0.0
        action_success_rate = float(total_action_successes) / total_actions if total_actions > 0 else 0.0

        return AmongUsHeadlessSummary(
            seed=seed,
            num_agents=num_agents,
            steps=sim.current_step,
            max_steps=max_steps,
            completed=sim.is_done(),
            completion_reason=completion_reason,
            winner=winner,
            policy_uri=resolved_policy_uri,
            role_counts=role_counts,
            totals=totals,
            game_stats=game_stats,
            first_steps=first_steps,
            actions={
                "total_actions": total_actions,
                "action_successes": total_action_successes,
                "action_success_rate": action_success_rate,
                "move_attempts": move_attempts,
                "move_successes": move_successes,
                "move_success_rate": move_success_rate,
                "talk_actions": talk_actions,
                "talk_chars": talk_chars,
                "meeting_talk_actions": meeting_talk_actions,
                "meeting_talk_chars": meeting_talk_chars,
                "ballot_talk_actions": ballot_talk_actions,
                "ballot_talk_chars": ballot_talk_chars,
                "counts": dict(sorted(action_counts.items(), key=lambda kv: kv[1], reverse=True)),
            },
            timeline=timeline,
            timings={
                "wall_time_s": wall_elapsed,
                "policy_time_ms": policy_step_ms,
                "sim_step_time_ms": sim_step_ms,
                "sps": float(sim.current_step) / wall_elapsed,
                "policy_time_ms_per_step_per_agent": policy_step_ms / max(1, sim.current_step * sim.num_agents),
                "sim_step_time_ms_per_step": sim_step_ms / max(1, sim.current_step),
            },
        )
    finally:
        sim.close()


def run_headless_audit(
    *,
    episodes: int,
    num_agents: int = 12,
    max_steps: int = 300,
    base_seed: int = 0,
    policy_uri: str | None = None,
    log_every: int = 0,
    end_on_winner: bool = True,
    include_episodes: bool = False,
) -> dict[str, object]:
    """Run multiple headless episodes and return aggregate reliability metrics."""
    if episodes < 1:
        raise ValueError("episodes must be >= 1")

    summaries: list[AmongUsHeadlessSummary] = []
    for i in range(episodes):
        summaries.append(
            run_headless_episode(
                num_agents=num_agents,
                max_steps=max_steps,
                seed=base_seed + i,
                policy_uri=policy_uri,
                log_every=log_every,
                end_on_winner=end_on_winner,
                verbose=False,
            )
        )

    completed = [s.completed for s in summaries]
    steps = [s.steps for s in summaries]
    sps = [s.timings["sps"] for s in summaries]
    wall_time_s = [s.timings["wall_time_s"] for s in summaries]
    role_adoption = [s.role_counts["crew"] + s.role_counts["impostor"] for s in summaries]
    total_actions = [int(s.actions["total_actions"]) for s in summaries]
    talk_actions = [int(s.actions["talk_actions"]) for s in summaries]
    talk_chars = [int(s.actions["talk_chars"]) for s in summaries]
    meeting_talk_actions = [int(s.actions["meeting_talk_actions"]) for s in summaries]
    meeting_talk_chars = [int(s.actions["meeting_talk_chars"]) for s in summaries]
    ballot_talk_actions = [int(s.actions["ballot_talk_actions"]) for s in summaries]
    ballot_talk_chars = [int(s.actions["ballot_talk_chars"]) for s in summaries]

    completion_reasons: dict[str, int] = {}
    winners: dict[str, int] = {}
    for summary in summaries:
        completion_reasons[summary.completion_reason] = completion_reasons.get(summary.completion_reason, 0) + 1
        winners[summary.winner] = winners.get(summary.winner, 0) + 1
    win_condition_counts = {
        "crew_tasks": sum(int(s.game_stats.get("crew_win_tasks", 0) > 0) for s in summaries),
        "crew_elimination": sum(int(s.game_stats.get("crew_win_elimination", 0) > 0) for s in summaries),
        "impostor_sabotage": sum(int(s.game_stats.get("impostor_win_sabotage", 0) > 0) for s in summaries),
        "impostor_elimination": sum(int(s.game_stats.get("impostor_win_elimination", 0) > 0) for s in summaries),
    }

    audit: dict[str, object] = {
        "episodes": episodes,
        "num_agents": num_agents,
        "max_steps": max_steps,
        "base_seed": base_seed,
        "policy_uri": summaries[0].policy_uri,
        "end_on_winner": end_on_winner,
        "completion_rate": float(sum(completed)) / episodes,
        "completion_reasons": completion_reasons,
        "winners": winners,
        "win_conditions": {
            "counts": win_condition_counts,
            "rates": {key: float(value) / episodes for key, value in win_condition_counts.items()},
        },
        "coverage": {
            "tasks_completed_rate": _rate(summaries, lambda s: s.totals["tasks_completed"] > 0),
            "sabotages_rate": _rate(summaries, lambda s: s.totals["sabotages"] > 0),
            "repairs_rate": _rate(summaries, lambda s: s.totals["repairs"] > 0),
            "kills_rate": _rate(summaries, lambda s: s.totals["kills"] > 0),
            "reports_rate": _rate(summaries, lambda s: s.totals["reports"] > 0),
            "ejections_rate": _rate(summaries, lambda s: s.totals["ejections"] > 0),
            "vents_used_rate": _rate(summaries, lambda s: s.totals["vents_used"] > 0),
            "meeting_calls_rate": _rate(summaries, lambda s: s.totals["meeting_calls"] > 0),
            "emergency_meeting_calls_rate": _rate(summaries, lambda s: s.totals["emergency_meeting_calls"] > 0),
            "admin_checks_rate": _rate(summaries, lambda s: s.totals["admin_checks"] > 0),
            "camera_checks_rate": _rate(summaries, lambda s: s.totals["camera_checks"] > 0),
            "comms_checks_rate": _rate(summaries, lambda s: s.totals["comms_checks"] > 0),
            "comms_sabotages_rate": _rate(summaries, lambda s: s.totals["comms_sabotages"] > 0),
            "comms_repairs_rate": _rate(summaries, lambda s: s.totals["comms_repairs"] > 0),
            "lights_sabotages_rate": _rate(summaries, lambda s: s.totals["lights_sabotages"] > 0),
            "oxygen_sabotages_rate": _rate(summaries, lambda s: s.totals["oxygen_sabotages"] > 0),
            "reactor_sabotages_rate": _rate(summaries, lambda s: s.totals["reactor_sabotages"] > 0),
            "meeting_skips_rate": _rate(summaries, lambda s: s.totals["meeting_skips"] > 0),
            "meeting_ties_rate": _rate(summaries, lambda s: s.totals["meeting_ties"] > 0),
            "talk_actions_rate": _rate(summaries, lambda s: int(s.actions["talk_actions"]) > 0),
            "meeting_talk_actions_rate": _rate(summaries, lambda s: int(s.actions["meeting_talk_actions"]) > 0),
            "ballot_talk_actions_rate": _rate(summaries, lambda s: int(s.actions["ballot_talk_actions"]) > 0),
            "winner_declared_rate": _rate(summaries, lambda s: s.game_stats.get("winner_declared", 0) > 0),
        },
        "actions": {
            "total_actions": sum(total_actions),
            "talk_actions": sum(talk_actions),
            "talk_chars": sum(talk_chars),
            "meeting_talk_actions": sum(meeting_talk_actions),
            "meeting_talk_chars": sum(meeting_talk_chars),
            "ballot_talk_actions": sum(ballot_talk_actions),
            "ballot_talk_chars": sum(ballot_talk_chars),
            "talk_actions_mean": mean(talk_actions),
            "meeting_talk_actions_mean": mean(meeting_talk_actions),
            "ballot_talk_actions_mean": mean(ballot_talk_actions),
        },
        "steps": {
            "min": min(steps),
            "max": max(steps),
            "mean": mean(steps),
        },
        "sps": {
            "min": min(sps),
            "max": max(sps),
            "mean": mean(sps),
        },
        "episode_profiles": {
            "steps": profile(steps).to_dict(),
            "sps": profile(sps).to_dict(),
            "wall_time_s": profile(wall_time_s).to_dict(),
        },
        "role_adoption": {
            "min": min(role_adoption),
            "max": max(role_adoption),
            "mean": mean(role_adoption),
            "expected": num_agents,
        },
        "first_steps": {key: _mean_not_none([s.first_steps.get(key) for s in summaries]) for key in FIRST_STEP_KEYS},
    }
    if include_episodes:
        audit["episodes_detail"] = [s.to_dict() for s in summaries]
    return audit


def evaluate_headless_audit_gate(
    audit: dict[str, object],
    *,
    profile: str = "baseline",
    thresholds: AmongUsAuditGateThresholds | None = None,
) -> dict[str, object]:
    """Evaluate audit metrics against a named threshold profile."""
    if thresholds is None:
        try:
            thresholds = AUDIT_GATE_PROFILES[profile]
        except KeyError as exc:
            raise ValueError(f"Unknown gate profile {profile!r}. Choices: {sorted(AUDIT_GATE_PROFILES)}") from exc

    coverage = _dict_field(audit, "coverage")
    winners = _dict_field(audit, "winners")
    role_adoption = _dict_field(audit, "role_adoption")
    sps = _dict_field(audit, "sps")

    completion_rate = float(audit.get("completion_rate", 0.0))
    winner_declared_rate = float(coverage.get("winner_declared_rate", 0.0))
    tasks_completed_rate = float(coverage.get("tasks_completed_rate", 0.0))
    kills_rate = float(coverage.get("kills_rate", 0.0))
    reports_rate = float(coverage.get("reports_rate", 0.0))
    ejections_rate = float(coverage.get("ejections_rate", 0.0))
    repairs_rate = float(coverage.get("repairs_rate", 0.0))
    sabotages_rate = float(coverage.get("sabotages_rate", 0.0))

    expected_adoption = int(role_adoption.get("expected", 0) or 0)
    min_adoption = int(role_adoption.get("min", 0) or 0)
    role_adoption_ratio = float(min_adoption) / max(1, expected_adoption)

    sps_mean = float(sps.get("mean", 0.0))
    winner_total = sum(int(value) for value in winners.values()) if winners else 0
    crew_win_rate = float(int(winners.get("crew", 0))) / max(1, winner_total)
    impostor_win_rate = float(int(winners.get("impostor", 0))) / max(1, winner_total)

    checks = [
        build_gate_check("completion_rate", completion_rate, min_value=thresholds.min_completion_rate),
        build_gate_check(
            "coverage.winner_declared_rate",
            winner_declared_rate,
            min_value=thresholds.min_winner_declared_rate,
        ),
        build_gate_check(
            "coverage.tasks_completed_rate",
            tasks_completed_rate,
            min_value=thresholds.min_tasks_completed_rate,
        ),
        build_gate_check("coverage.kills_rate", kills_rate, min_value=thresholds.min_kills_rate),
        build_gate_check("coverage.reports_rate", reports_rate, min_value=thresholds.min_reports_rate),
        build_gate_check("coverage.ejections_rate", ejections_rate, min_value=thresholds.min_ejections_rate),
        build_gate_check("coverage.repairs_rate", repairs_rate, min_value=thresholds.min_repairs_rate),
        build_gate_check("coverage.sabotages_rate", sabotages_rate, min_value=thresholds.min_sabotages_rate),
        build_gate_check("role_adoption_ratio", role_adoption_ratio, min_value=thresholds.min_role_adoption_ratio),
        build_gate_check("sps.mean", sps_mean, min_value=thresholds.min_sps_mean),
        build_gate_check("winner_rates.crew", crew_win_rate, max_value=thresholds.max_crew_win_rate),
        build_gate_check("winner_rates.impostor", impostor_win_rate, min_value=thresholds.min_impostor_win_rate),
    ]

    failed = [check for check in checks if not bool(check["passed"])]
    return {
        "profile": profile,
        "passed": len(failed) == 0,
        "failed_count": len(failed),
        "checks": checks,
        "metrics": {
            "completion_rate": completion_rate,
            "coverage": {
                "winner_declared_rate": winner_declared_rate,
                "tasks_completed_rate": tasks_completed_rate,
                "kills_rate": kills_rate,
                "reports_rate": reports_rate,
                "ejections_rate": ejections_rate,
                "repairs_rate": repairs_rate,
                "sabotages_rate": sabotages_rate,
            },
            "winner_rates": {
                "crew": crew_win_rate,
                "impostor": impostor_win_rate,
            },
            "role_adoption_ratio": role_adoption_ratio,
            "sps_mean": sps_mean,
        },
    }


def run_headless_determinism_check(
    *,
    episodes: int,
    repeats: int,
    num_agents: int = 12,
    max_steps: int = 300,
    base_seed: int = 0,
    policy_uri: str | None = None,
    end_on_winner: bool = False,
) -> dict[str, object]:
    if repeats < 1:
        raise ValueError("repeats must be >= 1")
    if episodes < 1:
        raise ValueError("episodes must be >= 1")
    if repeats == 1:
        return {
            "checked": False,
            "passed": True,
            "repeats": repeats,
            "episodes": episodes,
            "mismatch_repeats": [],
        }

    signatures: list[tuple[object, ...]] = []
    mismatch_repeats: list[int] = []
    for repeat_idx in range(repeats):
        audit = run_headless_audit(
            episodes=episodes,
            num_agents=num_agents,
            max_steps=max_steps,
            base_seed=base_seed,
            policy_uri=policy_uri,
            log_every=0,
            end_on_winner=end_on_winner,
            include_episodes=False,
        )
        signatures.append(_audit_signature(audit))
        if repeat_idx > 0 and signatures[repeat_idx] != signatures[0]:
            mismatch_repeats.append(repeat_idx)

    return {
        "checked": True,
        "passed": not mismatch_repeats,
        "repeats": repeats,
        "episodes": episodes,
        "mismatch_repeats": mismatch_repeats,
    }


def run_headless_release_suite(
    *,
    suite_name: str = "default",
    policy_uri: str | None = None,
    min_pass_rate: float = 1.0,
    include_audits: bool = False,
) -> dict[str, object]:
    if not 0.0 <= min_pass_rate <= 1.0:
        raise ValueError("min_pass_rate must be in [0, 1]")
    if suite_name not in RELEASE_SCENARIO_SUITES:
        raise ValueError(f"Unknown release suite {suite_name!r}. Choices: {sorted(RELEASE_SCENARIO_SUITES)}")

    scenarios = RELEASE_SCENARIO_SUITES[suite_name]
    scenario_results: list[dict[str, object]] = []
    pass_count = 0
    failures: list[str] = []

    for scenario in scenarios:
        audit = run_headless_audit(
            episodes=scenario.episodes,
            num_agents=scenario.num_agents,
            max_steps=scenario.max_steps,
            base_seed=scenario.seed,
            policy_uri=policy_uri,
            log_every=0,
            end_on_winner=scenario.end_on_winner,
            include_episodes=False,
        )
        thresholds = AUDIT_GATE_PROFILES[scenario.gate_profile]
        if scenario.min_sps_mean is not None:
            thresholds = replace(thresholds, min_sps_mean=float(scenario.min_sps_mean))
        gate = evaluate_headless_audit_gate(audit, profile=scenario.gate_profile, thresholds=thresholds)
        if bool(gate["passed"]):
            pass_count += 1
        else:
            gate_checks = gate.get("checks", [])
            if isinstance(gate_checks, list):
                failed_names = [str(check.get("name")) for check in gate_checks if not bool(check.get("passed"))]
                if failed_names:
                    failures.append(f"{scenario.name}: {', '.join(failed_names)}")
                    continue
            failures.append(f"{scenario.name}: failed gate")

        result: dict[str, object] = {
            "scenario": asdict(scenario),
            "gate": gate,
        }
        if include_audits:
            result["audit"] = audit
        scenario_results.append(result)

    pass_rate = float(pass_count) / max(1, len(scenarios))
    if pass_rate < min_pass_rate:
        failures.insert(0, f"release pass_rate {pass_rate:.2f} < required {min_pass_rate:.2f}")

    return {
        "suite_name": suite_name,
        "pass_rate": pass_rate,
        "min_pass_rate": min_pass_rate,
        "passed": not failures,
        "scenario_results": scenario_results,
        "failures": failures,
    }


def format_headless_audit_summary(payload: dict[str, object]) -> str:
    """Build a concise text summary for no-GUI audit loops."""
    lines: list[str] = []
    release_suite = payload.get("release_suite")
    if isinstance(release_suite, dict):
        failures = release_suite.get("failures", [])
        scenario_results = release_suite.get("scenario_results", [])
        failure_text = ""
        if isinstance(failures, list) and failures:
            failure_text = " failures=" + "; ".join(str(failure) for failure in failures)
        scenario_count = len(scenario_results) if isinstance(scenario_results, list) else 0
        return (
            "amongcogs.release "
            f"suite={release_suite.get('suite_name', 'unknown')} "
            f"passed={bool(release_suite.get('passed', False))} "
            f"pass_rate={float(release_suite.get('pass_rate', 0.0) or 0.0):.3f} "
            f"scenarios={scenario_count}"
            f"{failure_text}"
        )
    if "audit" in payload and isinstance(payload["audit"], dict):
        audit = payload["audit"]
        gate = _dict_field(payload, "gate")
        determinism = _dict_field(payload, "determinism")
    else:
        audit = payload
        gate = {}
        determinism = _dict_field(payload, "determinism") if isinstance(payload, dict) else {}
    if not isinstance(audit, dict):
        return "amongcogs.audit: invalid payload"

    coverage = _dict_field(audit, "coverage")
    winners = _dict_field(audit, "winners")
    episode_profiles = _dict_field(audit, "episode_profiles")

    lines.append(
        (
            "amongcogs.audit "
            f"episodes={int(audit.get('episodes', 0) or 0)} "
            f"complete={float(audit.get('completion_rate', 0.0) or 0.0):.3f} "
            f"winner_declared={float(coverage.get('winner_declared_rate', 0.0) or 0.0):.3f} "
            f"tasks={float(coverage.get('tasks_completed_rate', 0.0) or 0.0):.3f} "
            f"sabotages={float(coverage.get('sabotages_rate', 0.0) or 0.0):.3f} "
            f"repairs={float(coverage.get('repairs_rate', 0.0) or 0.0):.3f}"
        )
    )
    lines.append(
        (
            "winners "
            f"crew={int(winners.get('crew', 0) or 0)} "
            f"impostor={int(winners.get('impostor', 0) or 0)} "
            f"none={int(winners.get('none', 0) or 0)}"
        )
    )

    sps_profile = episode_profiles.get("sps", {})
    steps_profile = episode_profiles.get("steps", {})
    if isinstance(sps_profile, dict) and isinstance(steps_profile, dict):
        lines.append(
            (
                "profiles "
                f"steps(p50={float(steps_profile.get('p50', 0.0) or 0.0):.1f},"
                f"p95={float(steps_profile.get('p95', 0.0) or 0.0):.1f}) "
                f"sps(p50={float(sps_profile.get('p50', 0.0) or 0.0):.1f},"
                f"p95={float(sps_profile.get('p95', 0.0) or 0.0):.1f})"
            )
        )
    lines.append(
        (
            "mechanics "
            f"vents={float(coverage.get('vents_used_rate', 0.0) or 0.0):.3f} "
            f"meetings={float(coverage.get('meeting_calls_rate', 0.0) or 0.0):.3f} "
            f"emergency={float(coverage.get('emergency_meeting_calls_rate', 0.0) or 0.0):.3f} "
            f"admin={float(coverage.get('admin_checks_rate', 0.0) or 0.0):.3f} "
            f"cams={float(coverage.get('camera_checks_rate', 0.0) or 0.0):.3f} "
            f"comms={float(coverage.get('comms_checks_rate', 0.0) or 0.0):.3f} "
            f"lights={float(coverage.get('lights_sabotages_rate', 0.0) or 0.0):.3f} "
            f"oxygen={float(coverage.get('oxygen_sabotages_rate', 0.0) or 0.0):.3f} "
            f"reactor={float(coverage.get('reactor_sabotages_rate', 0.0) or 0.0):.3f}"
        )
    )

    if isinstance(gate, dict) and gate:
        gate_checks = gate.get("checks", [])
        failed_names: list[str] = []
        if isinstance(gate_checks, list):
            failed_names = [str(check.get("name")) for check in gate_checks if not bool(check.get("passed"))]
        lines.append(
            (
                f"gate[{gate.get('profile', 'unknown')}]="
                f"{'PASS' if bool(gate.get('passed', False)) else 'FAIL'}"
                + ("" if not failed_names else f" failed={', '.join(failed_names)}")
            )
        )

    if isinstance(determinism, dict) and bool(determinism.get("checked", False)):
        lines.append(
            (
                "determinism="
                f"{'PASS' if bool(determinism.get('passed', False)) else 'FAIL'} "
                f"repeats={int(determinism.get('repeats', 0) or 0)} "
                f"episodes={int(determinism.get('episodes', 0) or 0)}"
            )
        )
    return "\n".join(lines)


def _snapshot(sim: Simulation) -> TimelinePoint:
    station_counts = _station_counts(sim)
    role_counts = _role_counts(sim)
    totals = _totals(sim)
    return TimelinePoint(
        step=sim.current_step,
        stations_online=station_counts["online"],
        stations_sabotaged=station_counts["sabotaged"],
        tasks_completed=totals["tasks_completed"],
        sabotages=totals["sabotages"],
        repairs=totals["repairs"],
        kills=totals["kills"],
        reports=totals["reports"],
        ejections=totals["ejections"],
        vents_used=totals["vents_used"],
        meeting_calls=totals["meeting_calls"],
        emergency_meeting_calls=totals["emergency_meeting_calls"],
        admin_checks=totals["admin_checks"],
        camera_checks=totals["camera_checks"],
        comms_checks=totals["comms_checks"],
        crew_roles=role_counts["crew"],
        impostor_roles=role_counts["impostor"],
        corpses=_resource_count(sim, CORPSE_RESOURCE),
        meeting_active_agents=_resource_count(sim, MEETING_ACTIVE_RESOURCE),
    )


def _station_counts(sim: Simulation) -> dict[str, int]:
    tag_names = sim.config.game.id_map().tag_names()
    tag_id_map = {name: idx for idx, name in enumerate(tag_names)}
    online_id = tag_id_map.get(STATION_ONLINE_TAG, -1)
    sabotaged_id = tag_id_map.get(STATION_SABOTAGED_TAG, -1)

    online = 0
    sabotaged = 0
    for obj in sim.grid_objects(ignore_types=["wall", "agent"]).values():
        if obj.get("type_name") not in INTERACTIVE_STATION_NAMES:
            continue
        tag_ids = set(obj.get("tag_ids", []))
        if online_id in tag_ids:
            online += 1
        if sabotaged_id in tag_ids:
            sabotaged += 1

    return {
        "online": online,
        "sabotaged": sabotaged,
    }


def _totals(sim: Simulation) -> dict[str, float]:
    agent_stats = sim.episode_stats.get("agent", [])
    game_stats = sim.episode_stats.get("game", {})
    tasks_completed = 0.0
    sabotages = 0.0
    repairs = 0.0
    kills = 0.0
    reports = 0.0
    ejections = 0.0
    for stats in agent_stats:
        tasks_completed += float(stats.get("tasks_completed", 0.0))
        sabotages += float(stats.get("sabotages", 0.0))
        repairs += float(stats.get("repairs", 0.0))
        kills += float(stats.get("kills", 0.0))
        reports += float(stats.get("reports", 0.0))
        ejections += float(stats.get("ejected", 0.0))
    return {
        "tasks_completed": tasks_completed,
        "sabotages": sabotages,
        "repairs": repairs,
        "kills": kills,
        "reports": reports,
        "ejections": ejections,
        "vents_used": float(game_stats.get("vents_used", 0.0)),
        "meeting_calls": float(game_stats.get("meeting_called", 0.0)),
        "emergency_meeting_calls": float(game_stats.get("emergency_meeting_calls", 0.0)),
        "admin_checks": float(game_stats.get("admin_checks", 0.0)),
        "camera_checks": float(game_stats.get("camera_checks", 0.0)),
        "comms_checks": float(game_stats.get("comms_checks", 0.0)),
        "comms_sabotages": float(game_stats.get("comms_sabotages", 0.0)),
        "comms_repairs": float(game_stats.get("comms_repairs", 0.0)),
        "lights_sabotages": float(game_stats.get("lights_sabotages", 0.0)),
        "oxygen_sabotages": float(game_stats.get("oxygen_sabotages", 0.0)),
        "reactor_sabotages": float(game_stats.get("reactor_sabotages", 0.0)),
        "meeting_skips": float(game_stats.get("meeting_skips", 0.0)),
        "meeting_ties": float(game_stats.get("meeting_ties", 0.0)),
    }


def _role_counts(sim: Simulation) -> dict[str, int]:
    crew_roles = 0
    impostor_roles = 0
    for agent_id in range(sim.num_agents):
        inventory = sim.agent(agent_id).inventory
        if inventory.get(ROLE_CREW, 0) > 0:
            crew_roles += 1
        if inventory.get(ROLE_IMPOSTOR, 0) > 0:
            impostor_roles += 1
    return {
        "crew": crew_roles,
        "impostor": impostor_roles,
    }


def _resource_count(sim: Simulation, resource_name: str) -> int:
    total = 0
    for agent_id in range(sim.num_agents):
        total += int(sim.agent(agent_id).inventory.get(resource_name, 0))
    return total


def _normalize_float_dict(values: dict[str, object]) -> tuple[tuple[str, float | None], ...]:
    normalized: list[tuple[str, float | None]] = []
    for key, value in values.items():
        if value is None:
            normalized.append((key, None))
        else:
            normalized.append((key, round(float(value), 6)))
    return tuple(sorted(normalized))


def _normalize_int_dict(values: dict[str, object]) -> tuple[tuple[str, int], ...]:
    return tuple(sorted((key, int(value)) for key, value in values.items()))


def _dict_field(payload: dict[str, object], key: str) -> dict[str, object]:
    value = payload.get(key, {})
    return value if isinstance(value, dict) else {}


def _mark_first_step(first_steps: dict[str, int | None], key: str, step: int, condition: bool) -> None:
    if first_steps[key] is None and condition:
        first_steps[key] = step


def _update_first_steps(
    first_steps: dict[str, int | None],
    *,
    step: int,
    num_agents: int,
    role_counts: dict[str, int],
    totals: dict[str, float],
    game_stats: dict[str, float],
) -> bool:
    _mark_first_step(first_steps, "any_role_assigned", step, role_counts["crew"] > 0 or role_counts["impostor"] > 0)
    _mark_first_step(
        first_steps,
        "all_roles_assigned",
        step,
        role_counts["crew"] + role_counts["impostor"] == num_agents,
    )
    _mark_first_step(first_steps, "first_task", step, totals["tasks_completed"] > 0)
    _mark_first_step(first_steps, "first_sabotage", step, totals["sabotages"] > 0)
    _mark_first_step(first_steps, "first_repair", step, totals["repairs"] > 0)
    _mark_first_step(first_steps, "first_kill", step, totals["kills"] > 0)
    _mark_first_step(first_steps, "first_report", step, totals["reports"] > 0)
    _mark_first_step(first_steps, "first_ejection", step, totals["ejections"] > 0)
    _mark_first_step(first_steps, "first_vent", step, totals["vents_used"] > 0)
    _mark_first_step(first_steps, "first_emergency_meeting", step, totals["emergency_meeting_calls"] > 0)
    _mark_first_step(first_steps, "first_admin_check", step, totals["admin_checks"] > 0)
    _mark_first_step(first_steps, "first_camera_check", step, totals["camera_checks"] > 0)
    _mark_first_step(first_steps, "first_comms_check", step, totals["comms_checks"] > 0)
    _mark_first_step(first_steps, "first_lights_sabotage", step, totals["lights_sabotages"] > 0)
    _mark_first_step(first_steps, "first_oxygen_sabotage", step, totals["oxygen_sabotages"] > 0)
    _mark_first_step(first_steps, "first_reactor_sabotage", step, totals["reactor_sabotages"] > 0)
    _mark_first_step(first_steps, "first_meeting", step, game_stats.get("meeting_called", 0) > 0)
    winner_declared = game_stats.get("winner_declared", 0) > 0
    _mark_first_step(first_steps, "winner_declared", step, winner_declared)
    return winner_declared


def _audit_signature(audit: dict[str, object]) -> tuple[object, ...]:
    coverage = _dict_field(audit, "coverage")
    winners = _dict_field(audit, "winners")
    role_adoption = _dict_field(audit, "role_adoption")
    win_conditions = _dict_field(audit, "win_conditions")
    completion_reasons = _dict_field(audit, "completion_reasons")
    first_steps = _dict_field(audit, "first_steps")
    win_condition_counts = _dict_field(win_conditions, "counts")

    return (
        int(audit.get("episodes", 0) or 0),
        int(audit.get("num_agents", 0) or 0),
        int(audit.get("max_steps", 0) or 0),
        bool(audit.get("end_on_winner", False)),
        round(float(audit.get("completion_rate", 0.0) or 0.0), 6),
        _normalize_int_dict(completion_reasons),
        _normalize_float_dict(coverage),
        _normalize_int_dict(winners),
        _normalize_int_dict(win_condition_counts),
        _normalize_float_dict(
            {
                "role_adoption.min": role_adoption.get("min", 0),
                "role_adoption.max": role_adoption.get("max", 0),
                "role_adoption.mean": role_adoption.get("mean", 0),
                "role_adoption.expected": role_adoption.get("expected", 0),
            }
        ),
        _normalize_float_dict(first_steps),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Among Us in headless mode with scripted agents.")
    parser.add_argument("--episodes", type=int, default=1)
    parser.add_argument("--num-agents", type=int, default=12)
    parser.add_argument("--max-steps", type=int, default=300)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--policy-uri", type=str, default=None)
    parser.add_argument("--log-every", type=int, default=25)
    parser.add_argument("--end-on-winner", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--enforce-gate", action="store_true")
    parser.add_argument("--gate-profile", type=str, default="baseline", choices=sorted(AUDIT_GATE_PROFILES.keys()))
    parser.add_argument("--run-release-suite", action="store_true")
    parser.add_argument("--release-suite", type=str, default="default", choices=sorted(RELEASE_SCENARIO_SUITES.keys()))
    parser.add_argument("--release-min-pass-rate", type=float, default=1.0)
    parser.add_argument("--include-scenario-audits", action="store_true")
    parser.add_argument("--determinism-repeats", type=int, default=1)
    parser.add_argument("--determinism-episodes", type=int, default=6)
    parser.add_argument("--min-sps-mean", type=float, default=None)
    parser.add_argument("--output-json", type=str, default=None)
    parser.add_argument("--output", type=str, default="json", choices=["json", "summary", "both"])
    parser.add_argument("--include-episodes", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    if args.enforce_gate and not args.run_release_suite and args.episodes <= 1:
        raise SystemExit("--enforce-gate requires --episodes > 1")

    payload: dict[str, object]
    if args.run_release_suite:
        payload = {
            "release_suite": run_headless_release_suite(
                suite_name=args.release_suite,
                policy_uri=args.policy_uri,
                min_pass_rate=args.release_min_pass_rate,
                include_audits=args.include_scenario_audits,
            )
        }
    elif args.episodes <= 1:
        summary = run_headless_episode(
            num_agents=args.num_agents,
            max_steps=args.max_steps,
            seed=args.seed,
            policy_uri=args.policy_uri,
            log_every=args.log_every,
            end_on_winner=args.end_on_winner,
            verbose=args.verbose,
        )
        payload = summary.to_dict()
    else:
        audit = run_headless_audit(
            episodes=args.episodes,
            num_agents=args.num_agents,
            max_steps=args.max_steps,
            base_seed=args.seed,
            policy_uri=args.policy_uri,
            log_every=0 if args.verbose else args.log_every,
            end_on_winner=args.end_on_winner,
            include_episodes=args.include_episodes,
        )
        if args.enforce_gate:
            thresholds = AUDIT_GATE_PROFILES[args.gate_profile]
            if args.min_sps_mean is not None:
                thresholds = replace(thresholds, min_sps_mean=float(args.min_sps_mean))
            gate = evaluate_headless_audit_gate(audit, profile=args.gate_profile, thresholds=thresholds)
            payload = {
                "audit": audit,
                "gate": gate,
            }
        else:
            payload = audit

    if args.determinism_repeats > 1:
        payload["determinism"] = run_headless_determinism_check(
            episodes=args.determinism_episodes,
            repeats=args.determinism_repeats,
            num_agents=args.num_agents,
            max_steps=args.max_steps,
            base_seed=args.seed,
            policy_uri=args.policy_uri,
            end_on_winner=args.end_on_winner,
        )

    if args.output in {"summary", "both"}:
        print(format_headless_audit_summary(payload))
    if args.output in {"json", "both"}:
        print(json.dumps(payload, indent=2, sort_keys=True))

    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    if args.enforce_gate:
        gate_failed = False
        if args.run_release_suite:
            suite_dict = payload.get("release_suite", {})
            if isinstance(suite_dict, dict) and not bool(suite_dict.get("passed", False)):
                gate_failed = True
        else:
            gate_dict = payload.get("gate", {})
            if isinstance(gate_dict, dict) and not bool(gate_dict.get("passed", False)):
                gate_failed = True

        determinism_dict = payload.get("determinism", {})
        if isinstance(determinism_dict, dict) and bool(determinism_dict.get("checked", False)):
            if not bool(determinism_dict.get("passed", False)):
                gate_failed = True

        if gate_failed:
            raise SystemExit(2)


def _rate(summaries: list[AmongUsHeadlessSummary], pred) -> float:
    return float(sum(1 for summary in summaries if pred(summary))) / max(1, len(summaries))


def _mean_not_none(values: list[int | None]) -> float | None:
    filtered = [v for v in values if v is not None]
    if not filtered:
        return None
    return float(mean(filtered))


if __name__ == "__main__":
    main()
