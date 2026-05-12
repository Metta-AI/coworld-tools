from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from cogames_rl_researcher.actor_critic import ActorCriticReport
from cogames_rl_researcher.coverage import CoveragePackSummary, CoverageVariant
from cogames_rl_researcher.json_io import read_model, write_json

ProposalType = Literal["retry", "explore", "promote"]


class CoverageTuningProposal(BaseModel):
    priority: int
    proposal_type: ProposalType
    focus_category: str
    source_variant_id: str | None
    reason: str
    variant: CoverageVariant


class CoverageTuningPlan(BaseModel):
    generated_at: datetime
    source_coverage_pack_path: str
    source_actor_critic_report_path: str | None
    focus_category: str
    proposals: list[CoverageTuningProposal]
    summary: str


def build_coverage_tuning_plan(
    *,
    coverage_pack_summary: CoveragePackSummary,
    source_coverage_pack_path: str,
    actor_critic_report: ActorCriticReport | None = None,
    source_actor_critic_report_path: str | None = None,
    max_proposals: int = 5,
) -> CoverageTuningPlan:
    focus_category = (
        actor_critic_report.critic.bottlenecks[0].category
        if actor_critic_report is not None and actor_critic_report.critic.bottlenecks
        else "coverage"
    )
    ranked = sorted(
        coverage_pack_summary.results,
        key=lambda item: (
            item.status != "success",
            item.submit_successes == 0,
            item.leaderboard_rank is None,
            item.leaderboard_rank if item.leaderboard_rank is not None else 10_000,
            -item.attempt_to_submit_ratio,
        ),
    )

    proposals: list[CoverageTuningProposal] = []
    seen_variant_ids: set[str] = set()

    failed_or_partial = [
        result
        for result in ranked
        if result.submit_successes == 0 or result.attempt_to_submit_ratio < 1.0 or result.status != "success"
    ]

    for result in failed_or_partial:
        proposal = CoverageTuningProposal(
            priority=len(proposals) + 1,
            proposal_type="retry",
            focus_category=focus_category,
            source_variant_id=result.variant_id,
            reason=(
                f"submit_successes={result.submit_successes}, "
                f"attempt_to_submit_ratio={result.attempt_to_submit_ratio:.2f}; retry to improve valid submit coverage"
            ),
            variant=CoverageVariant(
                variant_id=f"{result.variant_id}-retry",
                policy_name=f"{result.policy_name}-retry",
                policy=coverage_pack_summary.base_policy,
            ),
        )
        if proposal.variant.variant_id in seen_variant_ids:
            continue
        proposals.append(proposal)
        seen_variant_ids.add(proposal.variant.variant_id)
        if len(proposals) >= max_proposals:
            break

    successful = [result for result in ranked if result.submit_successes > 0 and result.status == "success"]

    if len(proposals) < max_proposals and successful:
        promoted = CoverageTuningProposal(
            priority=len(proposals) + 1,
            proposal_type="promote",
            focus_category=focus_category,
            source_variant_id=successful[0].variant_id,
            reason="Top successful variant promoted as stability reference in next pack.",
            variant=CoverageVariant(
                variant_id=f"{successful[0].variant_id}-promote",
                policy_name=f"{successful[0].policy_name}-promote",
                policy=coverage_pack_summary.base_policy,
            ),
        )
        if promoted.variant.variant_id not in seen_variant_ids:
            proposals.append(promoted)
            seen_variant_ids.add(promoted.variant.variant_id)

    for seed in (7, 19, 37):
        if len(proposals) >= max_proposals or not successful:
            break
        proposal = CoverageTuningProposal(
            priority=len(proposals) + 1,
            proposal_type="explore",
            focus_category=focus_category,
            source_variant_id=successful[0].variant_id,
            reason="Top successful variant selected for controlled seed exploration.",
            variant=CoverageVariant(
                variant_id=f"{successful[0].variant_id}-seed{seed}",
                policy_name=f"{successful[0].policy_name}-seed{seed}",
                policy=coverage_pack_summary.base_policy,
                seed=seed,
            ),
        )
        if proposal.variant.variant_id in seen_variant_ids:
            continue
        proposals.append(proposal)
        seen_variant_ids.add(proposal.variant.variant_id)

    summary = (
        f"focus={focus_category}; variants_attempted={coverage_pack_summary.attempted_variants}; "
        f"successful_submits={coverage_pack_summary.successful_submits}; "
        f"family_breadth={coverage_pack_summary.experiment_family_breadth}/"
        f"{coverage_pack_summary.attempted_experiment_families}; "
        f"proposals={len(proposals)}."
    )

    return CoverageTuningPlan(
        generated_at=datetime.now(UTC),
        source_coverage_pack_path=source_coverage_pack_path,
        source_actor_critic_report_path=source_actor_critic_report_path,
        focus_category=focus_category,
        proposals=proposals,
        summary=summary,
    )


def write_coverage_tuning_plan(
    *,
    coverage_pack_path: Path,
    output_path: Path,
    actor_critic_report_path: Path | None = None,
    max_proposals: int = 5,
) -> CoverageTuningPlan:
    coverage_summary = read_model(coverage_pack_path, CoveragePackSummary)

    actor_critic_report = None
    if actor_critic_report_path is not None:
        actor_critic_report = read_model(actor_critic_report_path, ActorCriticReport)

    plan = build_coverage_tuning_plan(
        coverage_pack_summary=coverage_summary,
        source_coverage_pack_path=str(coverage_pack_path),
        actor_critic_report=actor_critic_report,
        source_actor_critic_report_path=str(actor_critic_report_path) if actor_critic_report_path is not None else None,
        max_proposals=max_proposals,
    )
    write_json(output_path, plan)
    return plan


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build next variant pack from coverage + actor/critic artifacts")
    parser.add_argument("--coverage-pack", required=True, help="Path to coverage_pack.json")
    parser.add_argument("--output", required=True, help="Output JSON path for coverage tuning plan")
    parser.add_argument("--actor-critic-report", default=None, help="Optional actor_critic_report.json path")
    parser.add_argument("--max-proposals", type=int, default=5)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    plan = write_coverage_tuning_plan(
        coverage_pack_path=Path(args.coverage_pack),
        output_path=Path(args.output),
        actor_critic_report_path=Path(args.actor_critic_report) if args.actor_critic_report else None,
        max_proposals=args.max_proposals,
    )

    print(f"focus_category={plan.focus_category}")
    print(f"proposals={len(plan.proposals)}")
    print(f"output={args.output}")
    return 0 if plan.proposals else 1


if __name__ == "__main__":
    raise SystemExit(main())
