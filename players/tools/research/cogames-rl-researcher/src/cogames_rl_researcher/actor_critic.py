from __future__ import annotations

import argparse
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from cogames_rl_researcher.json_io import read_model, write_json
from cogames_rl_researcher.log_mining import LogMiningReport
from cogames_rl_researcher.startup import (
    AuditBundle,
    _coverage_score,
    _friction_score,
    _reliability_score,
)

Verdict = Literal["keep", "revert", "investigate"]

RANK_SIGNIFICANCE_THRESHOLD = 1
SCORE_SIGNIFICANCE_THRESHOLD = 1.0
RELIABILITY_SIGNIFICANCE_THRESHOLD = 1.0
FRICTION_SIGNIFICANCE_THRESHOLD = 1.0
SUBMIT_COVERAGE_SIGNIFICANCE_THRESHOLD = 0.25
TIMEOUT_SIGNIFICANCE_THRESHOLD = 0.5


class MetricDelta(BaseModel):
    rank_delta: int | None = None
    score_delta: float | None = None
    reliability_delta: float | None = None
    friction_delta: float | None = None
    submit_coverage_delta: float | None = None
    timeout_delta: float | None = None


class MetricSignificance(BaseModel):
    rank_change_significant: bool = False
    score_change_significant: bool = False
    reliability_change_significant: bool = False
    friction_change_significant: bool = False
    submit_coverage_change_significant: bool = False
    timeout_change_significant: bool = False
    summary: str = "No significant metric changes detected."


class ActorProposal(BaseModel):
    hypothesis: str
    candidate_change: str
    intended_metric: str


class CriticBottleneck(BaseModel):
    rank: int
    category: str
    evidence: str
    fix: str


class CriticAssessment(BaseModel):
    verdict: Verdict
    rationale: str
    bottlenecks: list[CriticBottleneck]


class LogMiningContext(BaseModel):
    report_path: str | None = None
    total_failures: int
    top_failures_considered: int
    generated_at: str


class FixPackProposal(BaseModel):
    priority: int
    source: Literal["log_mining"] = "log_mining"
    category: str
    likely_owner: str
    command: str
    observed_error: str
    proposed_fix: str
    rationale: str


class ActorCriticReport(BaseModel):
    current_run_id: str
    baseline_run_id: str | None
    actor: ActorProposal
    metric_deltas: MetricDelta
    significance: MetricSignificance = Field(default_factory=MetricSignificance)
    critic: CriticAssessment
    log_mining_context: LogMiningContext | None = None
    fix_pack_proposals: list[FixPackProposal] = Field(default_factory=list)


def _compute_deltas(current: AuditBundle, baseline: AuditBundle | None) -> MetricDelta:
    if baseline is None:
        return MetricDelta()

    rank_delta: int | None = None
    if current.leaderboard_rank is not None and baseline.leaderboard_rank is not None:
        rank_delta = baseline.leaderboard_rank - current.leaderboard_rank

    score_delta: float | None = None
    if current.leaderboard_score is not None and baseline.leaderboard_score is not None:
        score_delta = current.leaderboard_score - baseline.leaderboard_score

    timeout_delta: float | None = None
    if current.scrimmage_metrics.action_timeouts is not None and baseline.scrimmage_metrics.action_timeouts is not None:
        timeout_delta = current.scrimmage_metrics.action_timeouts - baseline.scrimmage_metrics.action_timeouts

    return MetricDelta(
        rank_delta=rank_delta,
        score_delta=score_delta,
        reliability_delta=_reliability_score(current) - _reliability_score(baseline),
        friction_delta=_friction_score(current) - _friction_score(baseline),
        submit_coverage_delta=_coverage_score(current) - _coverage_score(baseline),
        timeout_delta=timeout_delta,
    )


def _is_significant(delta: float | int | None, threshold: float | int) -> bool:
    if delta is None:
        return False
    return abs(float(delta)) >= float(threshold)


def _assess_significance(deltas: MetricDelta) -> MetricSignificance:
    significance = MetricSignificance(
        rank_change_significant=_is_significant(deltas.rank_delta, RANK_SIGNIFICANCE_THRESHOLD),
        score_change_significant=_is_significant(deltas.score_delta, SCORE_SIGNIFICANCE_THRESHOLD),
        reliability_change_significant=_is_significant(deltas.reliability_delta, RELIABILITY_SIGNIFICANCE_THRESHOLD),
        friction_change_significant=_is_significant(deltas.friction_delta, FRICTION_SIGNIFICANCE_THRESHOLD),
        submit_coverage_change_significant=_is_significant(
            deltas.submit_coverage_delta,
            SUBMIT_COVERAGE_SIGNIFICANCE_THRESHOLD,
        ),
        timeout_change_significant=_is_significant(deltas.timeout_delta, TIMEOUT_SIGNIFICANCE_THRESHOLD),
    )

    notes: list[str] = []
    if significance.rank_change_significant and deltas.rank_delta is not None:
        notes.append(f"rank_delta={deltas.rank_delta:+d}")
    if significance.score_change_significant and deltas.score_delta is not None:
        notes.append(f"score_delta={deltas.score_delta:+.2f}")
    if significance.reliability_change_significant and deltas.reliability_delta is not None:
        notes.append(f"reliability_delta={deltas.reliability_delta:+.2f}")
    if significance.friction_change_significant and deltas.friction_delta is not None:
        notes.append(f"friction_delta={deltas.friction_delta:+.2f}")
    if significance.submit_coverage_change_significant and deltas.submit_coverage_delta is not None:
        notes.append(f"submit_coverage_delta={deltas.submit_coverage_delta:+.2f}")
    if significance.timeout_change_significant and deltas.timeout_delta is not None:
        notes.append(f"timeout_delta={deltas.timeout_delta:+.2f}")

    if notes:
        significance.summary = "Significant changes: " + ", ".join(notes) + "."

    return significance


def _actor_proposal(current: AuditBundle) -> ActorProposal:
    if current.scrimmage_metrics.action_timeouts and current.scrimmage_metrics.action_timeouts > 0:
        return ActorProposal(
            hypothesis="Policy latency is suppressing reliability and rank stability.",
            candidate_change="Reduce action latency (smaller model/batch or profile slow paths) and rerun scrimmage.",
            intended_metric="leaderboard rank/score",
        )

    return ActorProposal(
        hypothesis="Single-factor policy variant can improve rank without hurting reliability.",
        candidate_change="Test one controlled policy variant and run full startup+resume loop.",
        intended_metric="leaderboard rank/score",
    )


def _split_failure_signature(signature: str) -> tuple[str, str]:
    if " :: " not in signature:
        return signature, "unknown error"
    command, error = signature.split(" :: ", maxsplit=1)
    return command.strip(), error.strip()


def _log_failure_fix(*, category: str, likely_owner: str) -> str:
    if likely_owner == "auth" or category == "setup/auth":
        return "Refresh auth/token flow and rerun command with explicit login/server endpoints."
    if category == "submission workflow":
        return "Run upload --dry-run reproduction first, then patch submit/upload argument or server handling."
    if category == "runtime/performance":
        return "Profile timeout path, lower latency-sensitive settings, and rerun scrimmage/eval pack."
    if category == "data integrity":
        return "Validate input/output schema at source and make JSON parsing strict in the failing command path."
    return "Improve CLI error surface/defaults and add a regression test for this command failure."


def _log_mining_bottlenecks(log_mining_report: LogMiningReport | None, *, limit: int = 2) -> list[CriticBottleneck]:
    if log_mining_report is None or log_mining_report.total_failures <= 0:
        return []

    bottlenecks: list[CriticBottleneck] = []
    for aggregate in log_mining_report.top_failures[:limit]:
        command, error = _split_failure_signature(aggregate.signature)
        bottlenecks.append(
            CriticBottleneck(
                rank=0,
                category=aggregate.category,
                evidence=(
                    f"log_mining_count={aggregate.count}; command={command}; "
                    f"owner={aggregate.likely_owner}; error={error}"
                ),
                fix=_log_failure_fix(category=aggregate.category, likely_owner=aggregate.likely_owner),
            )
        )
    return bottlenecks


def _rerank_bottlenecks(bottlenecks: list[CriticBottleneck], *, limit: int = 3) -> list[CriticBottleneck]:
    return [item.model_copy(update={"rank": idx}) for idx, item in enumerate(bottlenecks[:limit], start=1)]


def _build_fix_pack_proposals(log_mining_report: LogMiningReport | None, *, limit: int = 5) -> list[FixPackProposal]:
    if log_mining_report is None or log_mining_report.total_failures <= 0:
        return []

    proposals: list[FixPackProposal] = []
    for index, aggregate in enumerate(log_mining_report.top_failures[:limit], start=1):
        command, error = _split_failure_signature(aggregate.signature)
        proposals.append(
            FixPackProposal(
                priority=index,
                category=aggregate.category,
                likely_owner=aggregate.likely_owner,
                command=command,
                observed_error=error,
                proposed_fix=_log_failure_fix(category=aggregate.category, likely_owner=aggregate.likely_owner),
                rationale=f"log_mining_count={aggregate.count}; prioritize repeated failure signature.",
            )
        )
    return proposals


def _critic_bottlenecks(
    current: AuditBundle,
    deltas: MetricDelta,
    log_mining_report: LogMiningReport | None = None,
) -> list[CriticBottleneck]:
    bottlenecks: list[CriticBottleneck] = []

    bottlenecks.extend(_log_mining_bottlenecks(log_mining_report))

    if current.friction_index.failed_invocations > 0:
        bottlenecks.append(
            CriticBottleneck(
                rank=len(bottlenecks) + 1,
                category="friction",
                evidence=f"failed_invocations={current.friction_index.failed_invocations}",
                fix="Resolve top command failures before expanding experiment breadth.",
            )
        )

    if current.reliability_index.timeout_or_crash_incidents > 0:
        bottlenecks.append(
            CriticBottleneck(
                rank=len(bottlenecks) + 1,
                category="reliability",
                evidence=(f"timeout_or_crash_incidents={current.reliability_index.timeout_or_crash_incidents}"),
                fix="Stabilize runtime and retry behavior before rank-only optimization.",
            )
        )

    if deltas.timeout_delta is not None and deltas.timeout_delta > 0:
        bottlenecks.append(
            CriticBottleneck(
                rank=len(bottlenecks) + 1,
                category="performance",
                evidence=f"timeout_delta=+{deltas.timeout_delta:.2f}",
                fix="Revert or tune latency-sensitive changes and rerun eval pack.",
            )
        )

    if current.submit_coverage_index.attempt_to_submit_ratio < 1.0:
        bottlenecks.append(
            CriticBottleneck(
                rank=len(bottlenecks) + 1,
                category="coverage",
                evidence=(f"attempt_to_submit_ratio={current.submit_coverage_index.attempt_to_submit_ratio:.2f}"),
                fix="Increase submit completion rate before adding new variants.",
            )
        )

    if not bottlenecks:
        bottlenecks.append(
            CriticBottleneck(
                rank=1,
                category="none",
                evidence="No immediate bottlenecks in rank/reliability/friction/coverage signals.",
                fix="Proceed with one controlled variant and compare against this baseline.",
            )
        )

    return _rerank_bottlenecks(bottlenecks)


def _critic_assessment(
    current: AuditBundle,
    deltas: MetricDelta,
    significance: MetricSignificance,
    log_mining_report: LogMiningReport | None = None,
) -> CriticAssessment:
    bottlenecks = _critic_bottlenecks(current, deltas, log_mining_report)

    rank_improved = deltas.rank_delta is not None and deltas.rank_delta > 0 and significance.rank_change_significant
    rank_regressed = deltas.rank_delta is not None and deltas.rank_delta < 0 and significance.rank_change_significant

    score_improved = deltas.score_delta is not None and deltas.score_delta > 0 and significance.score_change_significant
    score_regressed = (
        deltas.score_delta is not None and deltas.score_delta < 0 and significance.score_change_significant
    )

    positive_rank_signal = rank_improved or score_improved
    negative_rank_signal = rank_regressed or score_regressed

    reliability_regressed = (
        deltas.reliability_delta is not None
        and deltas.reliability_delta < 0
        and significance.reliability_change_significant
    )
    reliability_improved = (
        deltas.reliability_delta is not None
        and deltas.reliability_delta > 0
        and significance.reliability_change_significant
    )
    friction_regressed = (
        deltas.friction_delta is not None and deltas.friction_delta > 0 and significance.friction_change_significant
    )
    friction_improved = (
        deltas.friction_delta is not None and deltas.friction_delta < 0 and significance.friction_change_significant
    )
    coverage_regressed = (
        deltas.submit_coverage_delta is not None
        and deltas.submit_coverage_delta < 0
        and significance.submit_coverage_change_significant
    )
    coverage_improved = (
        deltas.submit_coverage_delta is not None
        and deltas.submit_coverage_delta > 0
        and significance.submit_coverage_change_significant
    )

    has_comparable_rank_or_score = deltas.rank_delta is not None or deltas.score_delta is not None
    rank_indistinguishable = (
        has_comparable_rank_or_score
        and not significance.rank_change_significant
        and not significance.score_change_significant
    )

    if not has_comparable_rank_or_score:
        verdict: Verdict = "investigate"
        rationale = "No comparable rank/score baseline available; investigate with another controlled run."
    elif positive_rank_signal and not reliability_regressed and not friction_regressed and not coverage_regressed:
        verdict = "keep"
        rationale = (
            "Significant rank/score improvement detected with no significant reliability/friction/coverage regression."
        )
    elif negative_rank_signal and (reliability_regressed or friction_regressed or coverage_regressed):
        verdict = "revert"
        rationale = "Significant rank/score regression with significant reliability/friction/coverage regression."
    elif rank_indistinguishable and reliability_improved and not friction_regressed and not coverage_regressed:
        verdict = "keep"
        rationale = (
            "Rank/score is statistically indistinguishable; tie-break favors significant reliability improvement."
        )
    elif rank_indistinguishable and reliability_regressed:
        verdict = "revert"
        rationale = (
            "Rank/score is statistically indistinguishable; tie-break rejects significant reliability regression."
        )
    elif rank_indistinguishable and friction_improved and not coverage_regressed:
        verdict = "keep"
        rationale = "Rank/score is statistically indistinguishable; tie-break favors lower friction."
    elif rank_indistinguishable and friction_regressed:
        verdict = "revert"
        rationale = "Rank/score is statistically indistinguishable; tie-break rejects higher friction."
    elif rank_indistinguishable and coverage_improved:
        verdict = "keep"
        rationale = "Rank/score is statistically indistinguishable; tie-break favors broader submit coverage."
    elif rank_indistinguishable and coverage_regressed:
        verdict = "revert"
        rationale = "Rank/score is statistically indistinguishable; tie-break rejects reduced submit coverage."
    elif not positive_rank_signal and not negative_rank_signal and (reliability_regressed and friction_regressed):
        verdict = "revert"
        rationale = "No significant rank/score gain and both reliability and friction regressed significantly."
    else:
        verdict = "investigate"
        rationale = "Mixed or statistically weak signal; run targeted diagnostics before keep/revert decision."

    rationale = f"{rationale} {significance.summary}".strip()

    return CriticAssessment(verdict=verdict, rationale=rationale, bottlenecks=bottlenecks)


def analyze_actor_critic(
    current: AuditBundle,
    baseline: AuditBundle | None = None,
    *,
    log_mining_report: LogMiningReport | None = None,
    log_mining_report_path: str | None = None,
) -> ActorCriticReport:
    deltas = _compute_deltas(current, baseline)
    significance = _assess_significance(deltas)
    actor = _actor_proposal(current)
    critic = _critic_assessment(current, deltas, significance, log_mining_report)
    fix_pack_proposals = _build_fix_pack_proposals(log_mining_report)
    log_mining_context = None
    if log_mining_report is not None:
        log_mining_context = LogMiningContext(
            report_path=log_mining_report_path,
            total_failures=log_mining_report.total_failures,
            top_failures_considered=min(len(log_mining_report.top_failures), 5),
            generated_at=log_mining_report.generated_at.isoformat(),
        )
    return ActorCriticReport(
        current_run_id=current.run_id,
        baseline_run_id=baseline.run_id if baseline is not None else None,
        actor=actor,
        metric_deltas=deltas,
        significance=significance,
        critic=critic,
        log_mining_context=log_mining_context,
        fix_pack_proposals=fix_pack_proposals,
    )


def write_actor_critic_report(
    *,
    current_bundle_path: Path,
    output_path: Path,
    baseline_bundle_path: Path | None = None,
    log_mining_report_path: Path | None = None,
) -> ActorCriticReport:
    current = read_model(current_bundle_path, AuditBundle)
    baseline = read_model(baseline_bundle_path, AuditBundle) if baseline_bundle_path is not None else None
    log_mining_report = None
    if log_mining_report_path is not None:
        log_mining_report = read_model(log_mining_report_path, LogMiningReport)
    report = analyze_actor_critic(
        current,
        baseline,
        log_mining_report=log_mining_report,
        log_mining_report_path=str(log_mining_report_path) if log_mining_report_path is not None else None,
    )
    write_json(output_path, report)
    return report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run actor/critic analysis on AI researcher audit bundles")
    parser.add_argument("--current", required=True, help="Path to current audit_bundle.json")
    parser.add_argument("--baseline", default=None, help="Optional baseline audit_bundle.json")
    parser.add_argument("--log-mining-report", default=None, help="Optional log_mining_report.json path")
    parser.add_argument("--output", default="./actor_critic_report.json", help="Output JSON path")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    report = write_actor_critic_report(
        current_bundle_path=Path(args.current),
        baseline_bundle_path=Path(args.baseline) if args.baseline else None,
        log_mining_report_path=Path(args.log_mining_report) if args.log_mining_report else None,
        output_path=Path(args.output),
    )

    print(f"verdict={report.critic.verdict}")
    print(f"output={Path(args.output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
