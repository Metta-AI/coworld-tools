from __future__ import annotations

import argparse
import os
from pathlib import Path

from pydantic import BaseModel, Field

from cogames_rl_researcher.actor_critic import FixPackProposal, analyze_actor_critic
from cogames_rl_researcher.defects import DefectFixPlanItem, build_defect_fix_plan
from cogames_rl_researcher.json_io import read_model, write_json
from cogames_rl_researcher.log_mining import LogMiningReport
from cogames_rl_researcher.startup import (
    AuditBundle,
    FrictionIndex,
    ReaperIncident,
    ReliabilityIndex,
    ResearcherProfile,
    RunStatus,
    StartupConfig,
    StepResult,
    StepSpec,
    SubmitCoverageIndex,
    _build_diagnosis,
    _build_escalation_plan,
    _build_friction_items,
    _build_history_comparison,
    _build_reaper_slo,
    _build_step_catalog,
    _estimate_experiment_family_breadth,
    _evaluate_gates,
    _execute_steps,
    _extract_leaderboard_rank,
    _extract_scrimmage_metrics,
    _first_success_time,
    _parse_successful_step_output_json,
    _run_docs_readthrough_step,
    _summarize_step_failures,
    _synthetic_step_result,
    _utc_now,
    _write_daily_report,
)
from cogames_rl_researcher.swarm import SwarmConfig, build_swarm_plan


class ResumeConfig(BaseModel):
    source: Path
    output_root: Path | None = None
    policy: str | None = None
    policy_name: str | None = None
    season: str | None = None
    mission: str | None = None
    episodes: int | None = Field(default=None, ge=1)
    steps: int | None = Field(default=None, ge=1)
    seed: int | None = Field(default=None, ge=0)
    cogames_bin: str | None = None
    login_server: str | None = None
    server: str | None = None
    researcher_profile: ResearcherProfile | None = None
    detect_idle_seconds: int | None = Field(default=None, ge=1)
    max_step_seconds: int | None = Field(default=None, ge=1)
    max_recoveries: int | None = Field(default=None, ge=0)
    retry_backoff_seconds: int | None = Field(default=None, ge=0)
    allow_interactive_login: bool | None = None
    run_leaderboard: bool = True
    include_missing_scrimmage: bool = True
    include_missing_dry_run: bool = True
    include_missing_upload: bool = True
    include_missing_submit: bool = True
    force_scrimmage: bool = False
    force_dry_run: bool = False
    force_upload: bool = False
    force_submit: bool = False
    emit_swarm_plan: bool = False
    swarm_workers: int = Field(default=3, ge=1)
    swarm_timeout_seconds: int = Field(default=900, ge=1)
    swarm_max_tasks_per_worker: int = Field(default=1, ge=1)
    enforce_gates: bool = True
    log_mining_report: Path | None = None
    include_defect_fix_actions: bool = True


class RankedNextAction(BaseModel):
    rank: int
    action: str
    reason: str


def _neophyte_resume_happy_path_violations(config: ResumeConfig) -> list[str]:
    violations: list[str] = []
    if config.force_scrimmage or config.force_dry_run or config.force_upload or config.force_submit:
        violations.append("force-* resume overrides are not allowed for neophyte profile")
    if (
        not config.include_missing_scrimmage
        or not config.include_missing_dry_run
        or not config.include_missing_upload
        or not config.include_missing_submit
    ):
        violations.append("skip-missing-* resume toggles are not allowed for neophyte profile")
    if not config.run_leaderboard:
        violations.append("run_leaderboard must remain enabled for neophyte profile")
    if config.emit_swarm_plan:
        violations.append("emit_swarm_plan is not allowed for neophyte profile")
    return violations


def _resolve_bundle_path(source: Path) -> Path:
    if source.is_dir():
        return source / "audit_bundle.json"
    return source


def _missing_source_message(resolved_source: Path) -> str:
    return (
        "source must point to a startup/resume run directory (containing audit_bundle.json) "
        f"or an explicit audit_bundle.json path: {resolved_source}"
    )


def _load_bundle(source: Path) -> AuditBundle:
    bundle_path = _resolve_bundle_path(source)
    if not bundle_path.exists():
        raise ValueError(_missing_source_message(bundle_path))
    return read_model(bundle_path, AuditBundle)


def _resolve_log_mining_report_path(config: ResumeConfig, output_root: Path) -> Path | None:
    if config.log_mining_report is not None:
        if not config.log_mining_report.exists():
            raise ValueError(f"log mining report not found: {config.log_mining_report}")
        return config.log_mining_report

    default_path = output_root / "log_mining_report.json"
    if default_path.exists():
        return default_path
    return None


def _has_success(bundle: AuditBundle, step_name: str) -> bool:
    return any(step.step_name == step_name and step.status == "success" for step in bundle.steps)


def _build_effective_startup_config(previous: AuditBundle, config: ResumeConfig) -> StartupConfig:
    base = previous.config
    return base.model_copy(
        update={
            "policy": config.policy or base.policy,
            "policy_name": config.policy_name or base.policy_name,
            "season": config.season or base.season,
            "mission": config.mission or base.mission,
            "episodes": config.episodes or base.episodes,
            "steps": config.steps or base.steps,
            "seed": config.seed if config.seed is not None else base.seed,
            "output_root": config.output_root or base.output_root,
            "cogames_bin": config.cogames_bin or base.cogames_bin,
            "login_server": config.login_server or base.login_server,
            "server": config.server or base.server,
            "researcher_profile": config.researcher_profile or base.researcher_profile,
            "detect_idle_seconds": config.detect_idle_seconds or base.detect_idle_seconds,
            "max_step_seconds": config.max_step_seconds or base.max_step_seconds,
            "max_recoveries": config.max_recoveries if config.max_recoveries is not None else base.max_recoveries,
            "retry_backoff_seconds": (
                config.retry_backoff_seconds if config.retry_backoff_seconds is not None else base.retry_backoff_seconds
            ),
            "allow_interactive_login": (
                config.allow_interactive_login
                if config.allow_interactive_login is not None
                else base.allow_interactive_login
            ),
            "run_upload": True,
            "run_submit": True,
            "run_leaderboard": True,
        }
    )


def _select_resume_steps(previous: AuditBundle, config: ResumeConfig, catalog: dict[str, StepSpec]) -> list[StepSpec]:
    steps: list[StepSpec] = [catalog["login_auth_check"]]

    if config.force_scrimmage or (config.include_missing_scrimmage and not _has_success(previous, "scrimmage_eval")):
        steps.append(catalog["scrimmage_eval"])

    if config.force_dry_run or (
        config.include_missing_dry_run and not _has_success(previous, "upload_dry_run_validation")
    ):
        steps.append(catalog["upload_dry_run_validation"])

    if config.force_upload or (config.include_missing_upload and not _has_success(previous, "upload")):
        steps.append(catalog["upload"])

    if config.force_submit or (config.include_missing_submit and not _has_success(previous, "submit")):
        steps.append(catalog["submit"])

    if config.run_leaderboard:
        steps.append(catalog["leaderboard_check"])

    return steps


def _build_ranked_next_actions(
    *,
    friction_items: list,
    leaderboard_rank: int | None,
    action_timeouts: float | None,
    attempt_to_submit_ratio: float,
) -> list[RankedNextAction]:
    actions: list[RankedNextAction] = []

    if friction_items:
        top_item = friction_items[0]
        actions.append(
            RankedNextAction(
                rank=1,
                action="Fix top friction failure and rerun startup workflow",
                reason=f"Observed owner={top_item.likely_owner}: {top_item.observed_error}",
            )
        )

    if leaderboard_rank is None:
        actions.append(
            RankedNextAction(
                rank=len(actions) + 1,
                action="Verify upload/submit completion and refresh leaderboard visibility",
                reason="No leaderboard entry found for the policy after resume.",
            )
        )

    if action_timeouts is not None and action_timeouts > 0:
        actions.append(
            RankedNextAction(
                rank=len(actions) + 1,
                action="Reduce action latency and rerun scrimmage",
                reason=f"action_timeouts={action_timeouts:.2f} in current artifacts.",
            )
        )

    if attempt_to_submit_ratio < 1.0:
        actions.append(
            RankedNextAction(
                rank=len(actions) + 1,
                action="Improve submit reliability before new variants",
                reason=f"attempt_to_submit_ratio={attempt_to_submit_ratio:.2f}",
            )
        )

    if not actions:
        actions.append(
            RankedNextAction(
                rank=1,
                action="Run a single-factor experiment and compare rank/reliability deltas",
                reason="Resume workflow completed without immediate blockers.",
            )
        )

    return actions[:3]


def _fix_pack_actions(fix_pack_proposals: list[FixPackProposal], *, max_actions: int = 2) -> list[RankedNextAction]:
    actions: list[RankedNextAction] = []
    for proposal in fix_pack_proposals[:max_actions]:
        actions.append(
            RankedNextAction(
                rank=len(actions) + 1,
                action=f"Apply fix pack for {proposal.category}: {proposal.command}",
                reason=proposal.rationale,
            )
        )
    return actions


def _defect_fix_actions(plan_items: list[DefectFixPlanItem], *, max_actions: int = 2) -> list[RankedNextAction]:
    actions: list[RankedNextAction] = []
    for item in plan_items[:max_actions]:
        actions.append(
            RankedNextAction(
                rank=len(actions) + 1,
                action=f"Validate defect fix for {item.defect_id}: {item.command}",
                reason=f"{item.proposed_fix} ({item.reason})",
            )
        )
    return actions


def _merge_ranked_actions(
    primary: list[RankedNextAction],
    secondary: list[RankedNextAction],
    *,
    max_actions: int = 3,
) -> list[RankedNextAction]:
    merged: list[RankedNextAction] = []
    seen_actions: set[str] = set()

    for action in [*primary, *secondary]:
        if action.action in seen_actions:
            continue
        seen_actions.add(action.action)
        merged.append(RankedNextAction(rank=len(merged) + 1, action=action.action, reason=action.reason))
        if len(merged) >= max_actions:
            break

    return merged


def run_resume(config: ResumeConfig) -> tuple[AuditBundle, list[RankedNextAction]]:
    previous = _load_bundle(config.source)
    effective_config = _build_effective_startup_config(previous, config)

    run_started_at = _utc_now()
    run_id = f"{run_started_at.strftime('%Y%m%d_%H%M%S')}_resume"
    run_dir = effective_config.output_root / run_id
    steps_dir = run_dir / "steps"
    replay_dir = run_dir / "replays"
    steps_dir.mkdir(parents=True, exist_ok=True)
    replay_dir.mkdir(parents=True, exist_ok=True)

    write_json(run_dir / "resume_config.json", config)
    write_json(run_dir / "resume_source_bundle.json", {"source": str(_resolve_bundle_path(config.source))})

    catalog = _build_step_catalog(effective_config, replay_dir)
    selected_steps = _select_resume_steps(previous, config, catalog)

    env = dict(os.environ)
    docs_step_result, docs_digest_path = _run_docs_readthrough_step(run_dir=run_dir, steps_dir=steps_dir)
    step_results: list[StepResult] = [docs_step_result]
    incidents: list[ReaperIncident] = []
    run_status: RunStatus = "success" if docs_step_result.status == "success" else "failed"
    if run_status == "success":
        neophyte_violations = (
            _neophyte_resume_happy_path_violations(config) if effective_config.researcher_profile == "neophyte" else []
        )
        if neophyte_violations:
            step_results.append(
                _synthetic_step_result(
                    step_name="neophyte_happy_path_guard",
                    attempt=1,
                    command=["internal", "neophyte-happy-path-guard"],
                    status="failed",
                    return_code=1,
                    steps_dir=steps_dir,
                    stderr_text="\n".join(neophyte_violations) + "\n",
                )
            )
            incidents.append(
                ReaperIncident(
                    timestamp=_utc_now(),
                    step_name="neophyte_happy_path_guard",
                    incident_type="escalation",
                    message="Neophyte profile must use documented happy-path resume workflow",
                    recovery_attempt=1,
                )
            )
            run_status = "failed"

    if run_status == "success":
        run_status, executed_steps, step_incidents = _execute_steps(
            config=effective_config,
            steps=selected_steps,
            steps_dir=steps_dir,
            env=env,
        )
        step_results.extend(executed_steps)
        incidents.extend(step_incidents)

    scrimmage_metrics = previous.scrimmage_metrics
    scrimmage_json = _parse_successful_step_output_json(step_results, "scrimmage_eval")
    if isinstance(scrimmage_json, dict):
        scrimmage_metrics = _extract_scrimmage_metrics(scrimmage_json)

    leaderboard_rank = previous.leaderboard_rank
    leaderboard_score = previous.leaderboard_score
    leaderboard_json = _parse_successful_step_output_json(step_results, "leaderboard_check")
    if isinstance(leaderboard_json, list):
        leaderboard_rank, leaderboard_score = _extract_leaderboard_rank(
            leaderboard_json,
            effective_config.policy_name,
        )

    friction_items = _build_friction_items(step_results) or previous.diagnosis.friction_items

    failed_invocations, rerun_count, downtime_minutes, stalled_count, timeout_or_crash = _summarize_step_failures(
        step_results
    )
    time_to_scrimmage = _first_success_time(step_results, "scrimmage_eval", run_started_at)
    time_to_submit = _first_success_time(step_results, "submit", run_started_at)

    submit_attempts = sum(1 for result in step_results if result.step_name == "submit")
    submit_successes = sum(1 for result in step_results if result.step_name == "submit" and result.status == "success")
    upload_successes = sum(1 for result in step_results if result.step_name == "upload" and result.status == "success")
    if submit_attempts > 0:
        attempt_to_submit_ratio = float(submit_successes) / float(submit_attempts)
    else:
        attempt_to_submit_ratio = previous.submit_coverage_index.attempt_to_submit_ratio

    experiment_family_breadth = _estimate_experiment_family_breadth(
        output_root=effective_config.output_root,
        season=effective_config.season,
        policy_name=effective_config.policy_name,
        include_current=attempt_to_submit_ratio > 0.0,
    )

    diagnosis = _build_diagnosis(
        metrics=scrimmage_metrics,
        leaderboard_rank=leaderboard_rank,
        friction_items=friction_items,
    )

    ranked_actions = _build_ranked_next_actions(
        friction_items=friction_items,
        leaderboard_rank=leaderboard_rank,
        action_timeouts=scrimmage_metrics.action_timeouts,
        attempt_to_submit_ratio=attempt_to_submit_ratio,
    )

    run_ended_at = _utc_now()
    bundle = AuditBundle(
        run_id=run_id,
        status=run_status,
        started_at=run_started_at,
        ended_at=run_ended_at,
        run_dir=str(run_dir),
        config=effective_config,
        steps=step_results,
        incidents=incidents,
        scrimmage_metrics=scrimmage_metrics,
        leaderboard_rank=leaderboard_rank,
        leaderboard_score=leaderboard_score,
        friction_index=FrictionIndex(
            failed_invocations=failed_invocations,
            rerun_count=rerun_count,
            time_to_first_successful_scrimmage_seconds=time_to_scrimmage,
            time_to_first_successful_upload_submit_seconds=time_to_submit,
        ),
        reliability_index=ReliabilityIndex(
            downtime_minutes=downtime_minutes,
            stalled_run_count=stalled_count,
            timeout_or_crash_incidents=timeout_or_crash,
            full_loop_completion_rate_percent=100.0 if run_status == "success" else 0.0,
        ),
        reaper_slo=_build_reaper_slo(
            step_results=step_results,
            incidents=incidents,
        ),
        docs_digest_path=docs_digest_path,
        submit_coverage_index=SubmitCoverageIndex(
            distinct_valid_submissions=max(submit_successes, upload_successes),
            experiment_family_breadth=experiment_family_breadth,
            attempt_to_submit_ratio=attempt_to_submit_ratio,
        ),
        diagnosis=diagnosis,
    )

    history_comparison = _build_history_comparison(bundle=bundle)
    bundle.history_comparison = history_comparison
    gates = _evaluate_gates(bundle)
    bundle.gates = gates
    escalation_plan = _build_escalation_plan(bundle, gates)
    bundle.escalation_plan = escalation_plan

    log_mining_report_path = _resolve_log_mining_report_path(config, effective_config.output_root)
    log_mining_report = read_model(log_mining_report_path, LogMiningReport) if log_mining_report_path else None
    actor_critic_report = analyze_actor_critic(
        bundle,
        previous,
        log_mining_report=log_mining_report,
        log_mining_report_path=str(log_mining_report_path) if log_mining_report_path is not None else None,
    )

    defect_fix_actions: list[RankedNextAction] = []
    if config.include_defect_fix_actions:
        defect_store = effective_config.output_root / "defects"
        defect_fix_plan = build_defect_fix_plan(defect_store, max_items=5)
        if defect_fix_plan.items:
            write_json(run_dir / "defect_fix_plan.json", defect_fix_plan)
        defect_fix_actions = _defect_fix_actions(defect_fix_plan.items)

    ranked_actions = _merge_ranked_actions(
        defect_fix_actions,
        _merge_ranked_actions(
            _fix_pack_actions(actor_critic_report.fix_pack_proposals),
            ranked_actions,
        ),
    )
    if ranked_actions:
        diagnosis.next_experiment_proposal = ranked_actions[0].action
    bundle.diagnosis = diagnosis

    write_json(run_dir / "audit_bundle.json", bundle)
    write_json(run_dir / "history_comparison.json", history_comparison)
    write_json(run_dir / "gates_evaluation.json", gates)
    write_json(run_dir / "escalation_plan.json", escalation_plan)
    write_json(run_dir / "ranked_next_actions.json", {"actions": ranked_actions})
    write_json(run_dir / "actor_critic_report.json", actor_critic_report)
    if actor_critic_report.fix_pack_proposals:
        write_json(
            run_dir / "fix_pack_plan.json",
            {"proposals": actor_critic_report.fix_pack_proposals},
        )

    swarm_plan = None
    if config.emit_swarm_plan and run_status == "success":
        swarm_plan = build_swarm_plan(
            actor_critic_report,
            SwarmConfig(
                workers=config.swarm_workers,
                timeout_seconds=config.swarm_timeout_seconds,
                max_tasks_per_worker=config.swarm_max_tasks_per_worker,
            ),
        )
        write_json(run_dir / "swarm_plan.json", swarm_plan)

    _write_daily_report(run_dir / "daily_report.md", bundle)

    report_path = run_dir / "daily_report.md"
    with report_path.open("a", encoding="utf-8") as report:
        report.write("\n## Ranked Next Actions\n")
        if ranked_actions:
            for action in ranked_actions:
                report.write(f"- {action.rank}. {action.action}: {action.reason}\n")
        else:
            report.write("- none\n")

        report.write("\n## Actor/Critic\n")
        report.write(f"- verdict: {actor_critic_report.critic.verdict}\n")
        report.write(f"- rationale: {actor_critic_report.critic.rationale}\n")
        report.write("- bottlenecks:\n")
        for bottleneck in actor_critic_report.critic.bottlenecks:
            report.write(
                f"  - {bottleneck.rank}. [{bottleneck.category}] {bottleneck.evidence}; fix: {bottleneck.fix}\n"
            )
        report.write("\n## Fix Pack Proposals\n")
        if actor_critic_report.fix_pack_proposals:
            for proposal in actor_critic_report.fix_pack_proposals:
                report.write(
                    f"- {proposal.priority}. [{proposal.category}] {proposal.command}; fix: {proposal.proposed_fix}\n"
                )
        else:
            report.write("- none\n")
        if swarm_plan is not None:
            report.write("\n## Optional Swarm Plan\n")
            report.write(f"- workers: {len(swarm_plan.workers)}\n")
            report.write(f"- tasks: {len(swarm_plan.tasks)}\n")
            report.write("- output: swarm_plan.json\n")

    return bundle, ranked_actions


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Resume Claude-first AI researcher workflow")
    parser.add_argument("--source", required=True, help="Prior run dir or path to audit_bundle.json")
    parser.add_argument("--output-root", default=None)
    parser.add_argument("--policy", default=None)
    parser.add_argument("--policy-name", default=None)
    parser.add_argument("--season", default=None)
    parser.add_argument("--mission", default=None)
    parser.add_argument("--episodes", type=int, default=None)
    parser.add_argument("--steps", type=int, default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--cogames-bin", default=None)
    parser.add_argument("--login-server", default=None)
    parser.add_argument("--server", default=None)
    parser.add_argument("--researcher-profile", choices=["experienced", "neophyte"], default=None)
    parser.add_argument("--detect-idle-seconds", type=int, default=None)
    parser.add_argument("--max-step-seconds", type=int, default=None)
    parser.add_argument("--max-recoveries", type=int, default=None)
    parser.add_argument("--retry-backoff-seconds", type=int, default=None)
    parser.add_argument("--no-leaderboard", action="store_true")
    parser.add_argument("--force-scrimmage", action="store_true")
    parser.add_argument("--force-dry-run", action="store_true")
    parser.add_argument("--force-upload", action="store_true")
    parser.add_argument("--force-submit", action="store_true")
    parser.add_argument("--skip-missing-scrimmage", action="store_true")
    parser.add_argument("--skip-missing-dry-run", action="store_true")
    parser.add_argument("--skip-missing-upload", action="store_true")
    parser.add_argument("--skip-missing-submit", action="store_true")
    parser.add_argument("--emit-swarm-plan", action="store_true")
    parser.add_argument("--swarm-workers", type=int, default=3)
    parser.add_argument("--swarm-timeout-seconds", type=int, default=900)
    parser.add_argument("--swarm-max-tasks-per-worker", type=int, default=1)
    parser.add_argument(
        "--enforce-gates",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Fail when required resume gates do not pass (enabled by default)",
    )
    parser.add_argument(
        "--allow-interactive-login",
        action="store_true",
        help="Allow browser-based login refresh when auth failures are detected",
    )
    parser.add_argument("--log-mining-report", default=None, help="Optional log_mining_report.json path")
    parser.add_argument(
        "--no-defect-fix-actions",
        action="store_true",
        help="Disable next-action suggestions generated from submitted defect backlog",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    source_path = Path(args.source)
    resolved_source = _resolve_bundle_path(source_path)
    if not resolved_source.exists():
        parser.error(_missing_source_message(resolved_source))

    config = ResumeConfig(
        source=source_path,
        output_root=Path(args.output_root) if args.output_root else None,
        policy=args.policy,
        policy_name=args.policy_name,
        season=args.season,
        mission=args.mission,
        episodes=args.episodes,
        steps=args.steps,
        seed=args.seed,
        cogames_bin=args.cogames_bin,
        login_server=args.login_server,
        server=args.server,
        researcher_profile=args.researcher_profile,
        detect_idle_seconds=args.detect_idle_seconds,
        max_step_seconds=args.max_step_seconds,
        max_recoveries=args.max_recoveries,
        retry_backoff_seconds=args.retry_backoff_seconds,
        run_leaderboard=not args.no_leaderboard,
        include_missing_scrimmage=not args.skip_missing_scrimmage,
        include_missing_dry_run=not args.skip_missing_dry_run,
        include_missing_upload=not args.skip_missing_upload,
        include_missing_submit=not args.skip_missing_submit,
        force_scrimmage=args.force_scrimmage,
        force_dry_run=args.force_dry_run,
        force_upload=args.force_upload,
        force_submit=args.force_submit,
        emit_swarm_plan=args.emit_swarm_plan,
        swarm_workers=args.swarm_workers,
        swarm_timeout_seconds=args.swarm_timeout_seconds,
        swarm_max_tasks_per_worker=args.swarm_max_tasks_per_worker,
        allow_interactive_login=args.allow_interactive_login,
        enforce_gates=args.enforce_gates,
        log_mining_report=Path(args.log_mining_report) if args.log_mining_report else None,
        include_defect_fix_actions=not args.no_defect_fix_actions,
    )

    bundle, ranked_actions = run_resume(config)
    print(f"run_dir={bundle.run_dir}")
    print(f"status={bundle.status}")
    print(f"leaderboard_rank={bundle.leaderboard_rank}")
    if ranked_actions:
        print(f"next_action={ranked_actions[0].action}")
    swarm_plan_path = Path(bundle.run_dir) / "swarm_plan.json"
    if swarm_plan_path.exists():
        print(f"swarm_plan={swarm_plan_path}")
    if bundle.gates is not None:
        print(f"gates_status={bundle.gates.overall_status}")

    if bundle.status != "success":
        return 1
    if config.enforce_gates and bundle.gates and bundle.gates.overall_status != "pass":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
