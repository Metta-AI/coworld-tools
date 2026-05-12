from __future__ import annotations

from cogames_rl_researcher.actor_critic import (
    ActorCriticReport,
    ActorProposal,
    CriticAssessment,
    CriticBottleneck,
    MetricDelta,
)
from cogames_rl_researcher.swarm import SwarmConfig, build_swarm_plan


def _sample_report() -> ActorCriticReport:
    return ActorCriticReport(
        current_run_id="run-1",
        baseline_run_id="run-0",
        actor=ActorProposal(
            hypothesis="Latency is the bottleneck.",
            candidate_change="Reduce action latency.",
            intended_metric="leaderboard rank/score",
        ),
        metric_deltas=MetricDelta(
            rank_delta=-1,
            score_delta=-0.5,
            reliability_delta=-2.0,
            friction_delta=1.0,
            submit_coverage_delta=-0.1,
            timeout_delta=0.8,
        ),
        critic=CriticAssessment(
            verdict="revert",
            rationale="Regression across rank and reliability.",
            bottlenecks=[
                CriticBottleneck(
                    rank=1,
                    category="reliability",
                    evidence="timeout_or_crash_incidents=2",
                    fix="Stabilize runtime.",
                ),
                CriticBottleneck(
                    rank=2,
                    category="friction",
                    evidence="failed_invocations=3",
                    fix="Fix CLI errors.",
                ),
                CriticBottleneck(
                    rank=3,
                    category="coverage",
                    evidence="attempt_to_submit_ratio=0.5",
                    fix="Improve submit completion.",
                ),
            ],
        ),
    )


def test_swarm_plan_respects_capacity() -> None:
    report = _sample_report()
    config = SwarmConfig(workers=2, timeout_seconds=600, max_tasks_per_worker=1)

    plan = build_swarm_plan(report, config)

    assert len(plan.workers) == 2
    assert len(plan.tasks) == 2
    assert all(task.worker_id in {"worker-1", "worker-2"} for task in plan.tasks)


def test_swarm_plan_maps_roles_from_categories() -> None:
    report = _sample_report()
    config = SwarmConfig(workers=4, timeout_seconds=600, max_tasks_per_worker=1)

    plan = build_swarm_plan(report, config)
    role_by_category = {task.source_category: task.role for task in plan.tasks}

    assert role_by_category["reliability"] == "reaper-operator"
    assert role_by_category["friction"] == "cli-debugger"
