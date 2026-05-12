from __future__ import annotations

import argparse
import shlex
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from cogames.cli.submit import DEFAULT_SUBMIT_SERVER
from cogames_rl_researcher.json_io import write_json
from cogames_rl_researcher.resume import ResumeConfig, run_resume
from cogames_rl_researcher.startup import (
    DEFAULT_SEASON,
    ResearcherProfile,
    StartupConfig,
    _utc_now,
    run_startup,
)
from softmax.auth import DEFAULT_COGAMES_SERVER

RunStatus = Literal["success", "failed", "skipped"]


class ResearchCommandConfig(BaseModel):
    policy: str
    policy_name: str
    season: str = DEFAULT_SEASON
    mission: str = "arena"
    episodes: int = Field(default=10, ge=1)
    steps: int = Field(default=1000, ge=1)
    seed: int = Field(default=42, ge=0)
    output_root: Path = Path("./artifacts/ai_researcher")
    cogames_bin: str = "cogames"
    login_server: str = DEFAULT_COGAMES_SERVER
    server: str = DEFAULT_SUBMIT_SERVER
    detect_idle_seconds: int = Field(default=600, ge=1)
    max_step_seconds: int = Field(default=1800, ge=1)
    max_recoveries: int = Field(default=2, ge=0)
    retry_backoff_seconds: int = Field(default=1, ge=0)
    researcher_profile: ResearcherProfile = "experienced"
    allow_interactive_login: bool = False
    enforce_gates: bool = True

    train_command: str | None = None
    skip_train: bool = False
    train_timeout_seconds: int = Field(default=28_800, ge=1)

    run_resume: bool = True
    emit_swarm_plan: bool = False
    swarm_workers: int = Field(default=3, ge=1)
    swarm_timeout_seconds: int = Field(default=900, ge=1)
    swarm_max_tasks_per_worker: int = Field(default=1, ge=1)


class TrainCommandResult(BaseModel):
    command: str | None
    status: RunStatus
    return_code: int | None
    started_at: datetime
    ended_at: datetime
    duration_seconds: float
    stdout_log: str | None = None
    stderr_log: str | None = None


class ResearchCommandSummary(BaseModel):
    generated_at: datetime
    research_run_id: str
    research_run_dir: str
    train: TrainCommandResult
    startup_run_id: str | None
    startup_run_dir: str | None
    startup_status: RunStatus
    resume_run_id: str | None
    resume_run_dir: str | None
    resume_status: RunStatus
    next_actions_count: int
    overall_status: RunStatus
    summary: str


def _run_train_command(*, command: str, run_dir: Path, timeout_seconds: int) -> TrainCommandResult:
    started_at = _utc_now()
    started_mono = time.monotonic()

    stdout_log = run_dir / "train.stdout.log"
    stderr_log = run_dir / "train.stderr.log"

    argv = shlex.split(command)
    return_code: int | None = None
    status: RunStatus = "failed"
    with stdout_log.open("w", encoding="utf-8") as stdout_sink, stderr_log.open("w", encoding="utf-8") as stderr_sink:
        try:
            completed = subprocess.run(
                argv,
                stdout=stdout_sink,
                stderr=stderr_sink,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
            return_code = completed.returncode
            status = "success" if completed.returncode == 0 else "failed"
        except subprocess.TimeoutExpired:
            stderr_sink.write(f"train command timed out after {timeout_seconds} seconds: {' '.join(argv)}\n")
            stderr_sink.flush()

    ended_at = _utc_now()
    return TrainCommandResult(
        command=command,
        status=status,
        return_code=return_code,
        started_at=started_at,
        ended_at=ended_at,
        duration_seconds=time.monotonic() - started_mono,
        stdout_log=str(stdout_log),
        stderr_log=str(stderr_log),
    )


def run_research_command(config: ResearchCommandConfig) -> ResearchCommandSummary:
    started_at = _utc_now()
    research_run_id = f"{started_at.strftime('%Y%m%d_%H%M%S')}_research"
    research_run_dir = config.output_root / research_run_id
    research_run_dir.mkdir(parents=True, exist_ok=True)

    train_result: TrainCommandResult
    if config.skip_train:
        train_result = TrainCommandResult(
            command=config.train_command,
            status="skipped",
            return_code=None,
            started_at=started_at,
            ended_at=_utc_now(),
            duration_seconds=0.0,
        )
    else:
        if not config.train_command:
            raise ValueError("train_command is required unless --skip-train is set")
        train_result = _run_train_command(
            command=config.train_command,
            run_dir=research_run_dir,
            timeout_seconds=config.train_timeout_seconds,
        )

    startup_run_id: str | None = None
    startup_run_dir: str | None = None
    startup_status: RunStatus = "skipped"

    resume_run_id: str | None = None
    resume_run_dir: str | None = None
    resume_status: RunStatus = "skipped"
    next_actions_count = 0

    if train_result.status in {"success", "skipped"}:
        startup_bundle = run_startup(
            StartupConfig(
                policy=config.policy,
                policy_name=config.policy_name,
                season=config.season,
                mission=config.mission,
                episodes=config.episodes,
                steps=config.steps,
                seed=config.seed,
                output_root=config.output_root,
                cogames_bin=config.cogames_bin,
                login_server=config.login_server,
                server=config.server,
                detect_idle_seconds=config.detect_idle_seconds,
                max_step_seconds=config.max_step_seconds,
                max_recoveries=config.max_recoveries,
                retry_backoff_seconds=config.retry_backoff_seconds,
                run_upload=True,
                run_submit=True,
                run_leaderboard=True,
                researcher_profile=config.researcher_profile,
                allow_interactive_login=config.allow_interactive_login,
                enforce_gates=config.enforce_gates,
            )
        )
        startup_run_id = startup_bundle.run_id
        startup_run_dir = startup_bundle.run_dir
        startup_status = startup_bundle.status
        if config.enforce_gates and startup_bundle.gates and startup_bundle.gates.overall_status != "pass":
            startup_status = "failed"

        if config.run_resume and startup_status == "success":
            resumed_bundle, next_actions = run_resume(
                ResumeConfig(
                    source=Path(startup_bundle.run_dir),
                    run_leaderboard=True,
                    emit_swarm_plan=config.emit_swarm_plan,
                    swarm_workers=config.swarm_workers,
                    swarm_timeout_seconds=config.swarm_timeout_seconds,
                    swarm_max_tasks_per_worker=config.swarm_max_tasks_per_worker,
                    researcher_profile=config.researcher_profile,
                    allow_interactive_login=config.allow_interactive_login,
                    enforce_gates=config.enforce_gates,
                )
            )
            resume_run_id = resumed_bundle.run_id
            resume_run_dir = resumed_bundle.run_dir
            resume_status = resumed_bundle.status
            if config.enforce_gates and resumed_bundle.gates and resumed_bundle.gates.overall_status != "pass":
                resume_status = "failed"
            next_actions_count = len(next_actions)

    if train_result.status == "failed" or startup_status == "failed" or resume_status == "failed":
        overall_status: RunStatus = "failed"
    else:
        overall_status = "success"

    summary_text = (
        f"train={train_result.status}, startup={startup_status}, "
        f"resume={resume_status}, next_actions={next_actions_count}"
    )

    summary = ResearchCommandSummary(
        generated_at=_utc_now(),
        research_run_id=research_run_id,
        research_run_dir=str(research_run_dir),
        train=train_result,
        startup_run_id=startup_run_id,
        startup_run_dir=startup_run_dir,
        startup_status=startup_status,
        resume_run_id=resume_run_id,
        resume_run_dir=resume_run_dir,
        resume_status=resume_status,
        next_actions_count=next_actions_count,
        overall_status=overall_status,
        summary=summary_text,
    )

    write_json(research_run_dir / "research_command_summary.json", summary)
    return summary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run cogames research loop (train + startup/resume submit flow)")
    parser.add_argument("--policy", required=True)
    parser.add_argument("--policy-name", required=True)
    parser.add_argument("--season", default=DEFAULT_SEASON)
    parser.add_argument("--mission", default="arena")
    parser.add_argument("--episodes", type=int, default=10)
    parser.add_argument("--steps", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output-root", default="./artifacts/ai_researcher")
    parser.add_argument("--cogames-bin", default="cogames")
    parser.add_argument("--login-server", default=DEFAULT_COGAMES_SERVER)
    parser.add_argument("--server", default=DEFAULT_SUBMIT_SERVER)
    parser.add_argument("--detect-idle-seconds", type=int, default=600)
    parser.add_argument("--max-step-seconds", type=int, default=1800)
    parser.add_argument("--max-recoveries", type=int, default=2)
    parser.add_argument("--retry-backoff-seconds", type=int, default=1)
    parser.add_argument("--researcher-profile", choices=["experienced", "neophyte"], default="experienced")
    parser.add_argument("--allow-interactive-login", action="store_true")
    parser.add_argument(
        "--enforce-gates",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Fail the research command when startup/resume gates do not pass (enabled by default)",
    )

    parser.add_argument("--train-command", default=None)
    parser.add_argument("--skip-train", action="store_true")
    parser.add_argument("--train-timeout-seconds", type=int, default=28_800)

    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--emit-swarm-plan", action="store_true")
    parser.add_argument("--swarm-workers", type=int, default=3)
    parser.add_argument("--swarm-timeout-seconds", type=int, default=900)
    parser.add_argument("--swarm-max-tasks-per-worker", type=int, default=1)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    config = ResearchCommandConfig(
        policy=args.policy,
        policy_name=args.policy_name,
        season=args.season,
        mission=args.mission,
        episodes=args.episodes,
        steps=args.steps,
        seed=args.seed,
        output_root=Path(args.output_root),
        cogames_bin=args.cogames_bin,
        login_server=args.login_server,
        server=args.server,
        detect_idle_seconds=args.detect_idle_seconds,
        max_step_seconds=args.max_step_seconds,
        max_recoveries=args.max_recoveries,
        retry_backoff_seconds=args.retry_backoff_seconds,
        researcher_profile=args.researcher_profile,
        allow_interactive_login=args.allow_interactive_login,
        enforce_gates=args.enforce_gates,
        train_command=args.train_command,
        skip_train=args.skip_train,
        train_timeout_seconds=args.train_timeout_seconds,
        run_resume=not args.no_resume,
        emit_swarm_plan=args.emit_swarm_plan,
        swarm_workers=args.swarm_workers,
        swarm_timeout_seconds=args.swarm_timeout_seconds,
        swarm_max_tasks_per_worker=args.swarm_max_tasks_per_worker,
    )

    summary = run_research_command(config)

    print(f"research_run_id={summary.research_run_id}")
    print(f"overall_status={summary.overall_status}")
    print(f"startup_status={summary.startup_status}")
    print(f"resume_status={summary.resume_status}")
    print(f"summary={summary.summary}")
    print(f"output={Path(summary.research_run_dir) / 'research_command_summary.json'}")

    return 0 if summary.overall_status == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
