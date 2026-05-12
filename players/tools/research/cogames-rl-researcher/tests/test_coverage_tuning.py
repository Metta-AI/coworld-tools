from __future__ import annotations

from pathlib import Path

from cogames_rl_researcher.actor_critic import (
    ActorCriticReport,
    ActorProposal,
    CriticAssessment,
    CriticBottleneck,
    MetricDelta,
)
from cogames_rl_researcher.coverage import CoveragePackSummary, CoverageVariantResult
from cogames_rl_researcher.coverage_tuning import build_coverage_tuning_plan, write_coverage_tuning_plan
from cogames_rl_researcher.json_io import read_json, write_json


def _sample_coverage_pack() -> CoveragePackSummary:
    return CoveragePackSummary(
        generated_at="2026-02-12T00:00:00Z",
        season="beta-cogsguard",
        base_policy="metta://policy/role_py",
        attempted_variants=2,
        successful_submits=1,
        valid_submit_coverage_ratio=0.5,
        attempted_experiment_families=2,
        experiment_family_breadth=1,
        experiment_family_breadth_ratio=0.5,
        results=[
            CoverageVariantResult(
                variant_id="v-bad",
                policy_name="policy-bad",
                experiment_family="policy-bad",
                run_id="run-bad",
                run_dir="/tmp/run-bad",
                status="failed",
                submit_attempts=1,
                submit_successes=0,
                attempt_to_submit_ratio=0.0,
                leaderboard_rank=None,
            ),
            CoverageVariantResult(
                variant_id="v-good",
                policy_name="policy-good",
                experiment_family="policy-good",
                run_id="run-good",
                run_dir="/tmp/run-good",
                status="success",
                submit_attempts=1,
                submit_successes=1,
                attempt_to_submit_ratio=1.0,
                leaderboard_rank=2,
            ),
        ],
    )


def _sample_actor_critic() -> ActorCriticReport:
    return ActorCriticReport(
        current_run_id="run-current",
        baseline_run_id="run-base",
        actor=ActorProposal(
            hypothesis="Coverage bottleneck limits submit throughput.",
            candidate_change="Increase submit stability.",
            intended_metric="submit coverage index",
        ),
        metric_deltas=MetricDelta(
            rank_delta=0,
            score_delta=0.0,
            reliability_delta=0.0,
            friction_delta=0.0,
            submit_coverage_delta=-0.3,
            timeout_delta=0.0,
        ),
        critic=CriticAssessment(
            verdict="investigate",
            rationale="Coverage is the top bottleneck.",
            bottlenecks=[
                CriticBottleneck(
                    rank=1,
                    category="coverage",
                    evidence="attempt_to_submit_ratio dropped",
                    fix="Increase submit stability and retry failed variants.",
                )
            ],
        ),
    )


def test_build_coverage_tuning_plan_prioritizes_retry_from_failed_variant() -> None:
    plan = build_coverage_tuning_plan(
        coverage_pack_summary=_sample_coverage_pack(),
        source_coverage_pack_path="/tmp/coverage_pack.json",
        actor_critic_report=_sample_actor_critic(),
        source_actor_critic_report_path="/tmp/actor_critic_report.json",
        max_proposals=4,
    )

    assert plan.focus_category == "coverage"
    assert plan.proposals
    assert plan.proposals[0].proposal_type == "retry"
    assert plan.proposals[0].source_variant_id == "v-bad"
    assert "family_breadth=1/2" in plan.summary


def test_write_coverage_tuning_plan_writes_json(tmp_path: Path) -> None:
    coverage_path = tmp_path / "coverage_pack.json"
    write_json(coverage_path, _sample_coverage_pack())

    actor_critic_path = tmp_path / "actor_critic_report.json"
    write_json(actor_critic_path, _sample_actor_critic())

    output_path = tmp_path / "coverage_tuning_plan.json"
    plan = write_coverage_tuning_plan(
        coverage_pack_path=coverage_path,
        output_path=output_path,
        actor_critic_report_path=actor_critic_path,
        max_proposals=3,
    )

    assert output_path.exists()
    payload = read_json(output_path)
    assert payload["focus_category"] == "coverage"
    assert len(payload["proposals"]) <= 3
    assert plan.proposals
