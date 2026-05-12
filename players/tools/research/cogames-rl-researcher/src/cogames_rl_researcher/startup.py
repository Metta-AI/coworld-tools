from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from cogames.cli.submit import DEFAULT_SUBMIT_SERVER
from cogames_rl_researcher.json_io import read_model, write_json
from softmax.auth import DEFAULT_COGAMES_SERVER, has_saved_token
from softmax.token_storage import TokenKind

StepStatus = Literal["success", "failed", "stall_timeout", "wall_timeout", "skipped"]
RunStatus = Literal["success", "failed"]
GateStatus = Literal["pass", "fail"]
ResearcherProfile = Literal["experienced", "neophyte"]
IncidentType = Literal["stall_detected", "wall_timeout", "auth_expired", "retry", "escalation"]
FrictionCategory = Literal[
    "setup/auth",
    "cli usability",
    "data integrity",
    "runtime/performance",
    "submission workflow",
]

REAPER_DETECT_SLO_SECONDS = 600
REAPER_RECOVERY_SLO_SECONDS = 300
REAPER_ESCALATION_CONSECUTIVE_FAILURES = 2
DEFAULT_HISTORY_WINDOW_RUNS = 7
DEFAULT_SEASON = "beta-cvc"
DOCS_READ_STEP_NAME = "docs_readthrough"
DOCS_RELATIVE_PATHS = (
    Path("packages/cogames/README.md"),
    Path("packages/cogames/tutorials/03_SUBMIT.md"),
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _step_slug(name: str) -> str:
    return name.lower().replace(" ", "_").replace("-", "_")


class StartupConfig(BaseModel):
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
    run_upload: bool = True
    run_submit: bool = True
    run_leaderboard: bool = True
    researcher_profile: ResearcherProfile = "experienced"
    allow_interactive_login: bool = False
    enforce_gates: bool = True


class StepSpec(BaseModel):
    name: str
    command: list[str]
    required: bool = True


class StepResult(BaseModel):
    step_name: str
    attempt: int
    command: list[str]
    status: StepStatus
    return_code: int | None
    started_at: datetime
    ended_at: datetime
    duration_seconds: float
    stdout_log: str
    stderr_log: str
    stdout_tail: str = ""
    stderr_tail: str = ""


class ReaperIncident(BaseModel):
    timestamp: datetime
    step_name: str
    incident_type: IncidentType
    message: str
    recovery_attempt: int


class FrictionItem(BaseModel):
    category: FrictionCategory
    reproduction_command: str
    observed_error: str
    likely_owner: str
    proposed_fix: str


class ScrimmageMetrics(BaseModel):
    reward: float | None = None
    junction_held: float | None = None
    junction_gained: float | None = None
    heart_gained: float | None = None
    heart_lost: float | None = None
    action_timeouts: float | None = None


class FrictionIndex(BaseModel):
    failed_invocations: int
    rerun_count: int
    time_to_first_successful_scrimmage_seconds: float | None
    time_to_first_successful_upload_submit_seconds: float | None


class ReliabilityIndex(BaseModel):
    downtime_minutes: float
    stalled_run_count: int
    timeout_or_crash_incidents: int
    full_loop_completion_rate_percent: float


class ReaperSlo(BaseModel):
    detect_target_seconds: int = REAPER_DETECT_SLO_SECONDS
    recovery_target_seconds: int = REAPER_RECOVERY_SLO_SECONDS
    escalation_after_consecutive_failed_recoveries: int = REAPER_ESCALATION_CONSECUTIVE_FAILURES
    stall_events: int = 0
    stall_detected_within_target: int = 0
    recovery_attempts: int = 0
    recoveries_started_within_target: int = 0
    escalations: int = 0
    max_consecutive_failed_recoveries: int = 0
    detect_slo_met: bool = True
    recovery_slo_met: bool = True
    escalation_policy_met: bool = True


def _default_reaper_slo() -> ReaperSlo:
    return ReaperSlo()


class HistoryRunPoint(BaseModel):
    run_id: str
    started_at: datetime
    status: RunStatus
    leaderboard_rank: int | None
    reliability_score: float
    friction_score: float
    submit_coverage_score: float


class HistoryComparison(BaseModel):
    generated_at: datetime
    policy_name: str
    season: str
    window_runs: int
    observed_runs: int
    current_run_id: str
    baseline_run_id: str | None
    rank_delta: int | None
    reliability_delta: float | None
    friction_delta: float | None
    submit_coverage_delta: float | None
    summary: str
    run_points: list[HistoryRunPoint]


class GateCheck(BaseModel):
    gate_id: str
    status: GateStatus
    message: str


class GateEvaluation(BaseModel):
    generated_at: datetime
    overall_status: GateStatus
    required_checks_passed: int
    required_checks_total: int
    checks: list[GateCheck]


class GatePolicy(BaseModel):
    profile: ResearcherProfile
    min_submit_coverage_ratio: float
    max_timeout_or_crash_incidents: int
    max_failed_invocations: int
    escalate_after_consecutive_failed_gate_runs: int


class EscalationAction(BaseModel):
    priority: int
    action: str
    reason: str


class EscalationPlan(BaseModel):
    generated_at: datetime
    profile: ResearcherProfile
    gate_overall_status: GateStatus
    consecutive_failed_gate_runs: int
    escalation_threshold: int
    should_escalate: bool
    actions: list[EscalationAction]


class SubmitCoverageIndex(BaseModel):
    distinct_valid_submissions: int
    experiment_family_breadth: int
    attempt_to_submit_ratio: float


class Diagnosis(BaseModel):
    summary: str
    next_experiment_proposal: str
    friction_items: list[FrictionItem]


class AuditBundle(BaseModel):
    run_id: str
    status: RunStatus
    started_at: datetime
    ended_at: datetime
    run_dir: str
    config: StartupConfig
    steps: list[StepResult]
    incidents: list[ReaperIncident]
    scrimmage_metrics: ScrimmageMetrics
    leaderboard_rank: int | None
    leaderboard_score: float | None
    friction_index: FrictionIndex
    reliability_index: ReliabilityIndex
    reaper_slo: ReaperSlo = Field(default_factory=_default_reaper_slo)
    history_comparison: HistoryComparison | None = None
    gates: GateEvaluation | None = None
    escalation_plan: EscalationPlan | None = None
    docs_digest_path: str | None = None
    submit_coverage_index: SubmitCoverageIndex
    diagnosis: Diagnosis


def _neophyte_startup_happy_path_violations(config: StartupConfig) -> list[str]:
    violations: list[str] = []
    if not config.run_upload:
        violations.append("run_upload must remain enabled for neophyte profile")
    if not config.run_submit:
        violations.append("run_submit must remain enabled for neophyte profile")
    if not config.run_leaderboard:
        violations.append("run_leaderboard must remain enabled for neophyte profile")
    return violations


class _StreamCapture:
    def __init__(self, stream_name: str, stream, output_path: Path, last_output_lock: threading.Lock):
        self._stream_name = stream_name
        self._stream = stream
        self._output_path = output_path
        self._last_output_lock = last_output_lock
        self._lines: list[str] = []
        self._last_output_at = time.monotonic()

    @property
    def lines(self) -> list[str]:
        return self._lines

    @property
    def last_output_at(self) -> float:
        with self._last_output_lock:
            return self._last_output_at

    def start(self) -> threading.Thread:
        thread = threading.Thread(target=self._read_stream, name=f"capture-{self._stream_name}", daemon=True)
        thread.start()
        return thread

    def _read_stream(self) -> None:
        with self._output_path.open("w", encoding="utf-8") as sink:
            for line in iter(self._stream.readline, ""):
                self._lines.append(line)
                sink.write(line)
                sink.flush()
                with self._last_output_lock:
                    self._last_output_at = time.monotonic()
        self._stream.close()


def _tail(lines: list[str], max_chars: int = 1600) -> str:
    text = "".join(lines).strip()
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _looks_like_auth_failure(text: str) -> bool:
    lowered = text.lower()
    auth_markers = [
        "not authenticated",
        "authentication failed",
        "token",
        "unauthorized",
        "forbidden",
        "run: cogames auth login",
    ]
    return any(marker in lowered for marker in auth_markers)


def _docs_source_paths() -> list[Path]:
    this_file = Path(__file__).resolve()
    for repo_root in [this_file.parent, *this_file.parents]:
        if (repo_root / "packages" / "cogames" / "README.md").exists():
            return [repo_root / relative for relative in DOCS_RELATIVE_PATHS if (repo_root / relative).exists()]
    return []


def _extract_cogames_commands(text: str) -> list[str]:
    commands: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("$ cogames "):
            commands.append(stripped.removeprefix("$ ").strip())
            continue
        if stripped.startswith("cogames "):
            commands.append(stripped)
            continue
        if stripped.startswith("uv run cogames "):
            commands.append(stripped)
    return commands


def _extract_seasons(commands: list[str]) -> list[str]:
    seasons: list[str] = []
    for command in commands:
        match = re.search(r"--season(?:=|\s+)([A-Za-z0-9:_-]+)", command)
        if match is not None:
            seasons.append(match.group(1))
    return seasons


def _synthetic_step_result(
    *,
    step_name: str,
    attempt: int,
    command: list[str],
    status: StepStatus,
    return_code: int | None,
    steps_dir: Path,
    stdout_text: str = "",
    stderr_text: str = "",
) -> StepResult:
    started_at = _utc_now()
    ended_at = _utc_now()
    step_prefix = f"{_step_slug(step_name)}.attempt{attempt}"
    stdout_log = steps_dir / f"{step_prefix}.stdout.log"
    stderr_log = steps_dir / f"{step_prefix}.stderr.log"
    stdout_log.write_text(stdout_text, encoding="utf-8")
    stderr_log.write_text(stderr_text, encoding="utf-8")
    return StepResult(
        step_name=step_name,
        attempt=attempt,
        command=command,
        status=status,
        return_code=return_code,
        started_at=started_at,
        ended_at=ended_at,
        duration_seconds=max(ended_at.timestamp() - started_at.timestamp(), 0.0),
        stdout_log=str(stdout_log),
        stderr_log=str(stderr_log),
        stdout_tail=stdout_text[-1600:].strip(),
        stderr_tail=stderr_text[-1600:].strip(),
    )


def _run_docs_readthrough_step(*, run_dir: Path, steps_dir: Path) -> tuple[StepResult, str | None]:
    command = ["internal", "docs-readthrough"]
    step_name = DOCS_READ_STEP_NAME
    attempt = 1
    try:
        source_paths = _docs_source_paths()
        if not source_paths:
            error_message = "No CoGames docs sources were found in the repository."
            return (
                _synthetic_step_result(
                    step_name=step_name,
                    attempt=attempt,
                    command=command,
                    status="failed",
                    return_code=1,
                    steps_dir=steps_dir,
                    stderr_text=error_message + "\n",
                ),
                None,
            )

        all_commands: list[str] = []
        for source in source_paths:
            all_commands.extend(_extract_cogames_commands(source.read_text(encoding="utf-8")))
        unique_commands = list(dict.fromkeys(all_commands))
        season_refs = sorted(set(_extract_seasons(unique_commands)))

        digest_payload = {
            "generated_at": _utc_now().isoformat(),
            "sources": [str(path) for path in source_paths],
            "command_count": len(unique_commands),
            "season_refs": season_refs,
            "sample_commands": unique_commands[:40],
        }

        digest_json_path = run_dir / "docs_digest.json"
        digest_md_path = run_dir / "docs_digest.md"
        write_json(digest_json_path, digest_payload)
        digest_md_path.write_text(
            "\n".join(
                [
                    "# CoGames Docs Digest",
                    "",
                    f"- generated_at: {digest_payload['generated_at']}",
                    f"- sources: {len(source_paths)}",
                    f"- command_count: {len(unique_commands)}",
                    f"- season_refs: {', '.join(season_refs) if season_refs else 'none'}",
                    "",
                    "## Sample Commands",
                    *[f"- `{command_line}`" for command_line in unique_commands[:12]],
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        step_result = _synthetic_step_result(
            step_name=step_name,
            attempt=attempt,
            command=command,
            status="success",
            return_code=0,
            steps_dir=steps_dir,
            stdout_text=(
                f"sources={len(source_paths)}\ncommand_count={len(unique_commands)}\ndigest={digest_json_path}\n"
            ),
        )
        return step_result, str(digest_json_path)
    except Exception as exc:  # noqa: BLE001
        return (
            _synthetic_step_result(
                step_name=step_name,
                attempt=attempt,
                command=command,
                status="failed",
                return_code=1,
                steps_dir=steps_dir,
                stderr_text=f"docs readthrough failed: {exc}\n",
            ),
            None,
        )


def _has_saved_auth_token(login_server: str) -> bool:
    return has_saved_token(token_kind=TokenKind.COGAMES, server=login_server)


def _run_command(
    *,
    step_name: str,
    attempt: int,
    command: list[str],
    steps_dir: Path,
    detect_idle_seconds: int,
    max_step_seconds: int,
    env: dict[str, str],
) -> StepResult:
    started_at = _utc_now()
    started_mono = time.monotonic()
    last_output_lock = threading.Lock()

    step_prefix = f"{_step_slug(step_name)}.attempt{attempt}"
    stdout_log = steps_dir / f"{step_prefix}.stdout.log"
    stderr_log = steps_dir / f"{step_prefix}.stderr.log"

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=env,
    )

    assert process.stdout is not None
    assert process.stderr is not None

    stdout_capture = _StreamCapture("stdout", process.stdout, stdout_log, last_output_lock)
    stderr_capture = _StreamCapture("stderr", process.stderr, stderr_log, last_output_lock)

    stdout_thread = stdout_capture.start()
    stderr_thread = stderr_capture.start()

    status: StepStatus = "success"

    while process.poll() is None:
        time.sleep(0.2)
        now = time.monotonic()
        last_output_at = max(stdout_capture.last_output_at, stderr_capture.last_output_at)

        if now - last_output_at > detect_idle_seconds:
            process.kill()
            status = "stall_timeout"
            break

        if now - started_mono > max_step_seconds:
            process.kill()
            status = "wall_timeout"
            break

    process.wait()
    stdout_thread.join(timeout=1.0)
    stderr_thread.join(timeout=1.0)

    return_code = process.returncode
    if status == "success" and return_code != 0:
        status = "failed"

    ended_at = _utc_now()

    return StepResult(
        step_name=step_name,
        attempt=attempt,
        command=command,
        status=status,
        return_code=return_code,
        started_at=started_at,
        ended_at=ended_at,
        duration_seconds=max(ended_at.timestamp() - started_at.timestamp(), 0.0),
        stdout_log=str(stdout_log),
        stderr_log=str(stderr_log),
        stdout_tail=_tail(stdout_capture.lines),
        stderr_tail=_tail(stderr_capture.lines),
    )


def _execute_steps(
    *,
    config: StartupConfig,
    steps: list[StepSpec],
    steps_dir: Path,
    env: dict[str, str],
) -> tuple[RunStatus, list[StepResult], list[ReaperIncident]]:
    step_results: list[StepResult] = []
    incidents: list[ReaperIncident] = []
    run_status: RunStatus = "success"

    for step in steps:
        attempt = 1
        while True:
            if (
                step.name == "login_auth_check"
                and config.cogames_bin == "cogames"
                and not config.allow_interactive_login
                and not _has_saved_auth_token(config.login_server)
            ):
                result = _synthetic_step_result(
                    step_name=step.name,
                    attempt=attempt,
                    command=step.command,
                    status="failed",
                    return_code=1,
                    steps_dir=steps_dir,
                    stderr_text=(
                        "No saved CoGames auth token found for non-interactive mode. "
                        "Run `cogames auth login` manually or pass --allow-interactive-login.\n"
                    ),
                )
                step_results.append(result)
                incidents.append(
                    ReaperIncident(
                        timestamp=_utc_now(),
                        step_name=step.name,
                        incident_type="escalation",
                        message="Missing saved token in non-interactive mode",
                        recovery_attempt=attempt,
                    )
                )
                run_status = "failed"
                break

            result = _run_command(
                step_name=step.name,
                attempt=attempt,
                command=step.command,
                steps_dir=steps_dir,
                detect_idle_seconds=config.detect_idle_seconds,
                max_step_seconds=config.max_step_seconds,
                env=env,
            )
            step_results.append(result)

            if result.status == "success":
                break

            if result.status == "stall_timeout":
                incidents.append(
                    ReaperIncident(
                        timestamp=_utc_now(),
                        step_name=step.name,
                        incident_type="stall_detected",
                        message="No command output detected within idle timeout",
                        recovery_attempt=attempt,
                    )
                )
            elif result.status == "wall_timeout":
                incidents.append(
                    ReaperIncident(
                        timestamp=_utc_now(),
                        step_name=step.name,
                        incident_type="wall_timeout",
                        message="Step exceeded wall timeout",
                        recovery_attempt=attempt,
                    )
                )

            combined_tail = f"{result.stderr_tail}\n{result.stdout_tail}"
            auth_failure = _looks_like_auth_failure(combined_tail)
            if auth_failure:
                if config.allow_interactive_login:
                    incidents.append(
                        ReaperIncident(
                            timestamp=_utc_now(),
                            step_name=step.name,
                            incident_type="auth_expired",
                            message="Auth failure signature detected; forcing login refresh",
                            recovery_attempt=attempt,
                        )
                    )

                    login_refresh = _run_command(
                        step_name=f"{step.name}_auth_refresh",
                        attempt=attempt,
                        command=[
                            config.cogames_bin,
                            "login",
                            "--force",
                            "--login-server",
                            config.login_server,
                        ],
                        steps_dir=steps_dir,
                        detect_idle_seconds=config.detect_idle_seconds,
                        max_step_seconds=config.max_step_seconds,
                        env=env,
                    )
                    step_results.append(login_refresh)
                    if login_refresh.status != "success":
                        incidents.append(
                            ReaperIncident(
                                timestamp=_utc_now(),
                                step_name=step.name,
                                incident_type="retry",
                                message="Auth refresh failed",
                                recovery_attempt=attempt,
                            )
                        )
                else:
                    incidents.append(
                        ReaperIncident(
                            timestamp=_utc_now(),
                            step_name=step.name,
                            incident_type="escalation",
                            message="Auth failure detected with interactive login disabled",
                            recovery_attempt=attempt,
                        )
                    )
                    run_status = "failed"
                    break

            if attempt > config.max_recoveries:
                incidents.append(
                    ReaperIncident(
                        timestamp=_utc_now(),
                        step_name=step.name,
                        incident_type="escalation",
                        message=f"Exceeded {config.max_recoveries} recovery attempts",
                        recovery_attempt=attempt,
                    )
                )
                run_status = "failed"
                break

            incidents.append(
                ReaperIncident(
                    timestamp=_utc_now(),
                    step_name=step.name,
                    incident_type="retry",
                    message="Retrying failed step",
                    recovery_attempt=attempt,
                )
            )
            attempt += 1
            if config.retry_backoff_seconds > 0:
                time.sleep(config.retry_backoff_seconds)

        if run_status == "failed":
            break

    return run_status, step_results, incidents


def _parse_json_output(text: str) -> dict | list:
    stripped = text.strip()
    if not stripped:
        raise ValueError("Empty output")
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        first_obj = stripped.find("{")
        first_arr = stripped.find("[")
        candidates = [idx for idx in [first_obj, first_arr] if idx >= 0]
        if not candidates:
            raise
        start = min(candidates)
        candidate = stripped[start:]
        return json.loads(candidate)


def _extract_scrimmage_metrics(scrimmage_json: dict) -> ScrimmageMetrics:
    missions = scrimmage_json.get("missions", [])
    if not missions:
        return ScrimmageMetrics()

    mission = missions[0]
    summary = mission.get("mission_summary", mission)
    game_stats = summary.get("avg_game_stats", {})
    policy_summaries = summary.get("policy_summaries", [])
    policy_summary = policy_summaries[0] if policy_summaries else {}
    agent_metrics = policy_summary.get("avg_agent_metrics", {})

    per_episode_rewards = policy_summary.get("per_episode_per_policy_avg_rewards", {})
    reward: float | None = None
    if per_episode_rewards:
        values = [value for value in per_episode_rewards.values() if isinstance(value, (int, float))]
        if values:
            reward = float(sum(values) / len(values))
    if reward is None:
        reward_value = agent_metrics.get("reward")
        reward = float(reward_value) if isinstance(reward_value, (int, float)) else None

    return ScrimmageMetrics(
        reward=reward,
        junction_held=_maybe_float(game_stats.get("junction.held")),
        junction_gained=_maybe_float(game_stats.get("junction.gained")),
        heart_gained=_maybe_float(agent_metrics.get("heart.gained")),
        heart_lost=_maybe_float(agent_metrics.get("heart.lost")),
        action_timeouts=_maybe_float(policy_summary.get("action_timeouts")),
    )


def _maybe_float(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _extract_leaderboard_rank(entries: list[dict], policy_name: str) -> tuple[int | None, float | None]:
    for entry in entries:
        policy = entry.get("policy", {}) if isinstance(entry, dict) else {}
        if policy.get("name") == policy_name:
            return _maybe_int(entry.get("rank")), _maybe_float(entry.get("score"))
    return None, None


def _maybe_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    return None


def _build_friction_items(step_results: list[StepResult]) -> list[FrictionItem]:
    items: list[FrictionItem] = []
    for result in step_results:
        if result.status == "success" or result.status == "skipped":
            continue
        error_text = result.stderr_tail or result.stdout_tail or "No stderr/stdout output"
        likely_owner = "auth" if _looks_like_auth_failure(error_text) else "cogames-cli"
        if _looks_like_auth_failure(error_text) or "login" in result.step_name:
            category: FrictionCategory = "setup/auth"
        elif result.step_name in {"upload_dry_run_validation", "upload", "submit", "leaderboard_check"}:
            category = "submission workflow"
        elif result.status in {"stall_timeout", "wall_timeout"}:
            category = "runtime/performance"
        elif "json" in error_text.lower() or "parse" in error_text.lower():
            category = "data integrity"
        else:
            category = "cli usability"
        proposed_fix = (
            "Refresh login token and retry command"
            if likely_owner == "auth"
            else "Inspect command args/output and reproduce locally"
        )
        items.append(
            FrictionItem(
                category=category,
                reproduction_command=" ".join(result.command),
                observed_error=error_text,
                likely_owner=likely_owner,
                proposed_fix=proposed_fix,
            )
        )
    return items


def _first_success_time(step_results: list[StepResult], step_name: str, run_started_at: datetime) -> float | None:
    for result in step_results:
        if result.step_name == step_name and result.status == "success":
            return max(result.ended_at.timestamp() - run_started_at.timestamp(), 0.0)
    return None


def _first_successful_step(step_results: list[StepResult], step_name: str) -> StepResult | None:
    return next(
        (result for result in step_results if result.step_name == step_name and result.status == "success"),
        None,
    )


def _parse_successful_step_output_json(step_results: list[StepResult], step_name: str) -> dict | list | None:
    result = _first_successful_step(step_results, step_name)
    if result is None:
        return None
    output = Path(result.stdout_log).read_text(encoding="utf-8")
    try:
        return _parse_json_output(output)
    except (ValueError, json.JSONDecodeError):
        return None


def _summarize_step_failures(step_results: list[StepResult]) -> tuple[int, int, float, int, int]:
    failed_invocations = sum(1 for result in step_results if result.status not in {"success", "skipped"})
    rerun_count = sum(1 for result in step_results if result.attempt > 1)
    downtime_minutes = (
        sum(
            result.duration_seconds
            for result in step_results
            if result.status in {"failed", "stall_timeout", "wall_timeout"}
        )
        / 60.0
    )
    stalled_count = sum(1 for result in step_results if result.status == "stall_timeout")
    timeout_or_crash = sum(1 for result in step_results if result.status in {"stall_timeout", "wall_timeout"})
    return failed_invocations, rerun_count, downtime_minutes, stalled_count, timeout_or_crash


def _build_reaper_slo(
    *,
    step_results: list[StepResult],
    incidents: list[ReaperIncident],
    detect_target_seconds: int = REAPER_DETECT_SLO_SECONDS,
    recovery_target_seconds: int = REAPER_RECOVERY_SLO_SECONDS,
    escalation_threshold: int = REAPER_ESCALATION_CONSECUTIVE_FAILURES,
) -> ReaperSlo:
    stall_results = [result for result in step_results if result.status == "stall_timeout"]
    stall_detected_within_target = sum(
        1 for result in stall_results if result.duration_seconds <= float(detect_target_seconds)
    )

    recovery_attempts = 0
    recoveries_started_within_target = 0
    failed_statuses = {"failed", "stall_timeout", "wall_timeout"}

    by_step: dict[str, list[StepResult]] = {}
    for result in step_results:
        by_step.setdefault(result.step_name, []).append(result)

    for results in by_step.values():
        ordered = sorted(results, key=lambda item: (item.attempt, item.started_at))
        for idx, result in enumerate(ordered):
            if result.status not in failed_statuses:
                continue
            if idx + 1 >= len(ordered):
                continue
            next_result = ordered[idx + 1]
            if next_result.attempt <= result.attempt:
                continue
            recovery_attempts += 1
            recovery_delay = max(next_result.started_at.timestamp() - result.ended_at.timestamp(), 0.0)
            if recovery_delay <= float(recovery_target_seconds):
                recoveries_started_within_target += 1

    max_consecutive_failed_recoveries = 0
    for results in by_step.values():
        ordered = sorted(results, key=lambda item: (item.attempt, item.started_at))
        consecutive_failed_recoveries = 0
        for result in ordered:
            if result.status == "success":
                consecutive_failed_recoveries = 0
                continue
            if result.status in failed_statuses and result.attempt > 1:
                consecutive_failed_recoveries += 1
                max_consecutive_failed_recoveries = max(
                    max_consecutive_failed_recoveries,
                    consecutive_failed_recoveries,
                )

    escalations = sum(1 for incident in incidents if incident.incident_type == "escalation")
    detect_slo_met = len(stall_results) == 0 or stall_detected_within_target == len(stall_results)
    recovery_slo_met = recovery_attempts == 0 or recoveries_started_within_target == recovery_attempts
    escalation_policy_met = max_consecutive_failed_recoveries < escalation_threshold or escalations > 0

    return ReaperSlo(
        detect_target_seconds=detect_target_seconds,
        recovery_target_seconds=recovery_target_seconds,
        escalation_after_consecutive_failed_recoveries=escalation_threshold,
        stall_events=len(stall_results),
        stall_detected_within_target=stall_detected_within_target,
        recovery_attempts=recovery_attempts,
        recoveries_started_within_target=recoveries_started_within_target,
        escalations=escalations,
        max_consecutive_failed_recoveries=max_consecutive_failed_recoveries,
        detect_slo_met=detect_slo_met,
        recovery_slo_met=recovery_slo_met,
        escalation_policy_met=escalation_policy_met,
    )


def _build_diagnosis(
    *,
    metrics: ScrimmageMetrics,
    leaderboard_rank: int | None,
    friction_items: list[FrictionItem],
) -> Diagnosis:
    timeout_delta = metrics.action_timeouts
    if leaderboard_rank is None:
        summary = "No leaderboard rank found for uploaded policy; focus on submission/visibility checks."
    elif timeout_delta is not None and timeout_delta > 0:
        summary = (
            f"Current rank {leaderboard_rank}; action_timeouts={timeout_delta:.2f}. "
            "Timeout pressure is the most likely reliability bottleneck."
        )
    else:
        summary = f"Current rank {leaderboard_rank}; no immediate timeout regression signal in startup artifacts."

    if friction_items:
        next_experiment = "Resolve top friction item, then rerun startup to confirm full-loop reliability."
    elif timeout_delta is not None and timeout_delta > 0:
        next_experiment = "Reduce policy action latency and rerun scrimmage + submit loop with identical seed."
    else:
        next_experiment = "Run one variant change (single-factor) and compare rank plus reliability deltas."

    return Diagnosis(
        summary=summary,
        next_experiment_proposal=next_experiment,
        friction_items=friction_items,
    )


def _write_daily_report(path: Path, bundle: AuditBundle) -> None:
    report_lines = [
        f"# AI Researcher Daily Report ({bundle.run_id})",
        "",
        f"- status: {bundle.status}",
        f"- season: {bundle.config.season}",
        f"- policy: {bundle.config.policy_name}",
        f"- docs_digest: {bundle.docs_digest_path if bundle.docs_digest_path is not None else 'n/a'}",
        f"- leaderboard_rank: {bundle.leaderboard_rank if bundle.leaderboard_rank is not None else 'n/a'}",
        f"- leaderboard_score: {bundle.leaderboard_score if bundle.leaderboard_score is not None else 'n/a'}",
        "",
        "## Key Metrics",
        f"- reward: {bundle.scrimmage_metrics.reward}",
        f"- junction_held: {bundle.scrimmage_metrics.junction_held}",
        f"- junction_gained: {bundle.scrimmage_metrics.junction_gained}",
        f"- action_timeouts: {bundle.scrimmage_metrics.action_timeouts}",
        "",
        "## Reaper Incidents",
    ]

    if bundle.incidents:
        for incident in bundle.incidents:
            report_lines.append(
                f"- {incident.timestamp.isoformat()} [{incident.incident_type}] "
                f"step={incident.step_name} attempt={incident.recovery_attempt}: {incident.message}"
            )
    else:
        report_lines.append("- none")

    report_lines.extend(
        [
            "",
            "## Reaper SLO",
            f"- detect_target_seconds: {bundle.reaper_slo.detect_target_seconds}",
            f"- stall_events: {bundle.reaper_slo.stall_events}",
            f"- stall_detected_within_target: {bundle.reaper_slo.stall_detected_within_target}",
            f"- detect_slo_met: {bundle.reaper_slo.detect_slo_met}",
            f"- recovery_target_seconds: {bundle.reaper_slo.recovery_target_seconds}",
            f"- recovery_attempts: {bundle.reaper_slo.recovery_attempts}",
            f"- recoveries_started_within_target: {bundle.reaper_slo.recoveries_started_within_target}",
            f"- recovery_slo_met: {bundle.reaper_slo.recovery_slo_met}",
            f"- escalation_threshold: {bundle.reaper_slo.escalation_after_consecutive_failed_recoveries}",
            f"- max_consecutive_failed_recoveries: {bundle.reaper_slo.max_consecutive_failed_recoveries}",
            f"- escalations: {bundle.reaper_slo.escalations}",
            f"- escalation_policy_met: {bundle.reaper_slo.escalation_policy_met}",
            "",
            "## Diagnosis",
            f"- summary: {bundle.diagnosis.summary}",
            f"- next_experiment_proposal: {bundle.diagnosis.next_experiment_proposal}",
            "",
            "## Friction Items",
        ]
    )

    if bundle.diagnosis.friction_items:
        for item in bundle.diagnosis.friction_items:
            report_lines.append(f"- category: {item.category}")
            report_lines.append(f"- reproduction: `{item.reproduction_command}`")
            report_lines.append(f"  observed_error: {item.observed_error}")
            report_lines.append(f"  likely_owner: {item.likely_owner}")
            report_lines.append(f"  proposed_fix: {item.proposed_fix}")
    else:
        report_lines.append("- none")

    if bundle.history_comparison is not None:
        report_lines.extend(
            [
                "",
                "## Historical Comparison",
                f"- window_runs: {bundle.history_comparison.window_runs}",
                f"- observed_runs: {bundle.history_comparison.observed_runs}",
                f"- baseline_run_id: {bundle.history_comparison.baseline_run_id or 'none'}",
                f"- rank_delta: {bundle.history_comparison.rank_delta}",
                f"- reliability_delta: {bundle.history_comparison.reliability_delta}",
                f"- friction_delta: {bundle.history_comparison.friction_delta}",
                f"- submit_coverage_delta: {bundle.history_comparison.submit_coverage_delta}",
                f"- summary: {bundle.history_comparison.summary}",
            ]
        )

    if bundle.gates is not None:
        report_lines.extend(
            [
                "",
                "## Gates",
                f"- overall_status: {bundle.gates.overall_status}",
                f"- required_checks_passed: {bundle.gates.required_checks_passed}",
                f"- required_checks_total: {bundle.gates.required_checks_total}",
            ]
        )
        for check in bundle.gates.checks:
            report_lines.append(f"- {check.gate_id}: {check.status} ({check.message})")

    if bundle.escalation_plan is not None:
        report_lines.extend(
            [
                "",
                "## Escalation Plan",
                f"- profile: {bundle.escalation_plan.profile}",
                f"- gate_overall_status: {bundle.escalation_plan.gate_overall_status}",
                f"- consecutive_failed_gate_runs: {bundle.escalation_plan.consecutive_failed_gate_runs}",
                f"- escalation_threshold: {bundle.escalation_plan.escalation_threshold}",
                f"- should_escalate: {bundle.escalation_plan.should_escalate}",
            ]
        )
        for action in bundle.escalation_plan.actions:
            report_lines.append(f"- {action.priority}. {action.action} ({action.reason})")

    path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")


def _infer_upload_include_files(policy: str, cwd: Path | None = None) -> list[str]:
    match = re.search(r"(?:^|,)class=([^,]+)", policy)
    if match is None:
        return []
    class_path = match.group(1).strip()
    if not class_path:
        return []

    module_path, _, _ = class_path.rpartition(".")
    if not module_path:
        return []

    root = (cwd or Path.cwd()).resolve()
    module_relative = Path(*module_path.split("."))

    module_file = root / module_relative.with_suffix(".py")
    if module_file.is_file():
        return [str(module_file.relative_to(root))]

    module_package_dir = root / module_relative
    if (module_package_dir / "__init__.py").is_file():
        return [str(module_package_dir.relative_to(root))]

    return []


def _append_include_files(command: list[str], include_files: list[str]) -> list[str]:
    if not include_files:
        return command
    command_with_includes = command.copy()
    for include_file in include_files:
        command_with_includes.extend(["--include-files", include_file])
    return command_with_includes


def _build_step_catalog(config: StartupConfig, replay_dir: Path) -> dict[str, StepSpec]:
    upload_include_files = _infer_upload_include_files(config.policy)
    specs = [
        StepSpec(
            name="login_auth_check",
            command=[
                config.cogames_bin,
                "login",
                "--login-server",
                config.login_server,
            ],
        ),
        StepSpec(
            name="scrimmage_eval",
            command=[
                config.cogames_bin,
                "scrimmage",
                "--mission",
                config.mission,
                "--policy",
                config.policy,
                "--episodes",
                str(config.episodes),
                "--steps",
                str(config.steps),
                "--seed",
                str(config.seed),
                "--format",
                "json",
                "--save-replay-dir",
                str(replay_dir),
            ],
        ),
        StepSpec(
            name="upload_dry_run_validation",
            command=_append_include_files(
                [
                    config.cogames_bin,
                    "upload",
                    "--name",
                    config.policy_name,
                    "--policy",
                    config.policy,
                    "--season",
                    config.season,
                    "--dry-run",
                    "--no-submit",
                    "--login-server",
                    config.login_server,
                    "--server",
                    config.server,
                ],
                upload_include_files,
            ),
        ),
        StepSpec(
            name="upload",
            command=_append_include_files(
                [
                    config.cogames_bin,
                    "upload",
                    "--name",
                    config.policy_name,
                    "--policy",
                    config.policy,
                    "--season",
                    config.season,
                    "--no-submit",
                    "--login-server",
                    config.login_server,
                    "--server",
                    config.server,
                ],
                upload_include_files,
            ),
        ),
        StepSpec(
            name="submit",
            command=[
                config.cogames_bin,
                "submit",
                config.policy_name,
                "--season",
                config.season,
                "--login-server",
                config.login_server,
                "--server",
                config.server,
            ],
        ),
        StepSpec(
            name="leaderboard_check",
            command=[
                config.cogames_bin,
                "leaderboard",
                "--season",
                config.season,
                "--json",
                "--login-server",
                config.login_server,
                "--server",
                config.server,
            ],
        ),
    ]
    return {spec.name: spec for spec in specs}


def _select_startup_steps(config: StartupConfig, catalog: dict[str, StepSpec]) -> list[StepSpec]:
    steps: list[StepSpec] = [
        catalog["login_auth_check"],
        catalog["scrimmage_eval"],
        catalog["upload_dry_run_validation"],
    ]
    if config.run_upload:
        steps.append(catalog["upload"])
    if config.run_submit:
        steps.append(catalog["submit"])
    if config.run_leaderboard:
        steps.append(catalog["leaderboard_check"])
    return steps


def run_startup(config: StartupConfig) -> AuditBundle:
    run_started_at = _utc_now()
    run_id = run_started_at.strftime("%Y%m%d_%H%M%S")
    run_dir = config.output_root / run_id
    steps_dir = run_dir / "steps"
    replay_dir = run_dir / "replays"

    steps_dir.mkdir(parents=True, exist_ok=True)
    replay_dir.mkdir(parents=True, exist_ok=True)

    write_json(run_dir / "startup_config.json", config)

    env = dict(os.environ)
    step_results: list[StepResult] = []
    incidents: list[ReaperIncident] = []
    docs_digest_path: str | None = None

    docs_step_result, docs_digest_path = _run_docs_readthrough_step(run_dir=run_dir, steps_dir=steps_dir)
    step_results.append(docs_step_result)

    run_status: RunStatus = "success"
    if docs_step_result.status != "success":
        run_status = "failed"

    step_catalog = _build_step_catalog(config, replay_dir)
    step_specs = _select_startup_steps(config, step_catalog)

    if run_status == "success":
        neophyte_violations = _neophyte_startup_happy_path_violations(config)
        if config.researcher_profile == "neophyte" and neophyte_violations:
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
                    message="Neophyte profile must use documented happy-path startup workflow",
                    recovery_attempt=1,
                )
            )
            run_status = "failed"

    if run_status == "success":
        steps_status, executed_steps, step_incidents = _execute_steps(
            config=config,
            steps=step_specs,
            steps_dir=steps_dir,
            env=env,
        )
        step_results.extend(executed_steps)
        incidents.extend(step_incidents)
        run_status = steps_status

    scrimmage_metrics = ScrimmageMetrics()
    leaderboard_rank: int | None = None
    leaderboard_score: float | None = None

    scrimmage_json = _parse_successful_step_output_json(step_results, "scrimmage_eval")
    if isinstance(scrimmage_json, dict):
        scrimmage_metrics = _extract_scrimmage_metrics(scrimmage_json)

    leaderboard_json = _parse_successful_step_output_json(step_results, "leaderboard_check")
    if isinstance(leaderboard_json, list):
        leaderboard_rank, leaderboard_score = _extract_leaderboard_rank(leaderboard_json, config.policy_name)

    friction_items = _build_friction_items(step_results)

    failed_invocations, rerun_count, downtime_minutes, stalled_count, timeout_or_crash = _summarize_step_failures(
        step_results
    )
    time_to_scrimmage = _first_success_time(step_results, "scrimmage_eval", run_started_at)
    time_to_submit = _first_success_time(step_results, "submit", run_started_at)
    if time_to_submit is None and config.run_submit is False:
        time_to_submit = _first_success_time(step_results, "upload", run_started_at)

    upload_success_count = sum(
        1 for result in step_results if result.step_name == "upload" and result.status == "success"
    )
    submit_attempts = sum(1 for result in step_results if result.step_name == "submit")
    submit_successes = sum(1 for result in step_results if result.step_name == "submit" and result.status == "success")
    attempt_to_submit_ratio = (
        float(submit_successes) / float(submit_attempts)
        if submit_attempts > 0
        else (1.0 if config.run_submit is False and upload_success_count > 0 else 0.0)
    )
    experiment_family_breadth = _estimate_experiment_family_breadth(
        output_root=config.output_root,
        season=config.season,
        policy_name=config.policy_name,
        include_current=attempt_to_submit_ratio > 0.0,
    )

    diagnosis = _build_diagnosis(
        metrics=scrimmage_metrics,
        leaderboard_rank=leaderboard_rank,
        friction_items=friction_items,
    )

    reaper_slo = _build_reaper_slo(
        step_results=step_results,
        incidents=incidents,
    )

    run_ended_at = _utc_now()
    bundle = AuditBundle(
        run_id=run_id,
        status=run_status,
        started_at=run_started_at,
        ended_at=run_ended_at,
        run_dir=str(run_dir),
        config=config,
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
        reaper_slo=reaper_slo,
        docs_digest_path=docs_digest_path,
        submit_coverage_index=SubmitCoverageIndex(
            distinct_valid_submissions=1 if submit_successes > 0 else upload_success_count,
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

    write_json(run_dir / "audit_bundle.json", bundle)
    write_json(run_dir / "history_comparison.json", history_comparison)
    write_json(run_dir / "gates_evaluation.json", gates)
    write_json(run_dir / "escalation_plan.json", escalation_plan)
    _write_daily_report(run_dir / "daily_report.md", bundle)

    return bundle


def _reliability_score(bundle: AuditBundle) -> float:
    return (
        bundle.reliability_index.full_loop_completion_rate_percent
        - bundle.reliability_index.downtime_minutes
        - bundle.reliability_index.timeout_or_crash_incidents * 5.0
    )


def _friction_score(bundle: AuditBundle) -> float:
    return (
        bundle.friction_index.failed_invocations
        + bundle.friction_index.rerun_count
        + (bundle.scrimmage_metrics.action_timeouts or 0.0)
    )


def _coverage_score(bundle: AuditBundle) -> float:
    return (
        bundle.submit_coverage_index.distinct_valid_submissions
        + bundle.submit_coverage_index.attempt_to_submit_ratio
        + bundle.submit_coverage_index.experiment_family_breadth * 0.1
    )


def _policy_family_key(policy_name: str) -> str:
    lowered = policy_name.strip().lower()
    if not lowered:
        return "default"

    trimmed = re.sub(r"[-_](?:seed)?\d+$", "", lowered)
    trimmed = re.sub(r"[-_]v\d+$", "", trimmed)
    trimmed = trimmed.strip("-_")
    return trimmed or lowered


def _load_audit_bundles(output_root: Path) -> list[AuditBundle]:
    bundles: list[AuditBundle] = []
    for path in sorted(output_root.glob("*/audit_bundle.json")):
        try:
            candidate = read_model(path, AuditBundle)
        except (OSError, ValueError, TypeError):
            continue
        bundles.append(candidate)
    return bundles


def _estimate_experiment_family_breadth(
    *,
    output_root: Path,
    season: str,
    policy_name: str,
    include_current: bool = True,
) -> int:
    families: set[str] = set()
    if include_current:
        families.add(_policy_family_key(policy_name))

    for candidate in _load_audit_bundles(output_root):
        if candidate.config.season != season:
            continue
        if candidate.submit_coverage_index.attempt_to_submit_ratio <= 0.0:
            continue

        families.add(_policy_family_key(candidate.config.policy_name))

    return len(families)


def _build_history_comparison(
    *,
    bundle: AuditBundle,
    window_runs: int = DEFAULT_HISTORY_WINDOW_RUNS,
) -> HistoryComparison:
    current_run_dir = Path(bundle.run_dir).resolve()
    historical_bundles: list[AuditBundle] = []

    for candidate in _load_audit_bundles(bundle.config.output_root):
        if Path(candidate.run_dir).resolve() == current_run_dir:
            continue
        if candidate.config.policy_name != bundle.config.policy_name:
            continue
        if candidate.config.season != bundle.config.season:
            continue

        historical_bundles.append(candidate)

    historical_bundles.append(bundle)
    deduped = {candidate.run_id: candidate for candidate in historical_bundles}
    ordered_bundles = sorted(deduped.values(), key=lambda item: item.started_at)
    selected = ordered_bundles[-window_runs:]

    run_points = [
        HistoryRunPoint(
            run_id=item.run_id,
            started_at=item.started_at,
            status=item.status,
            leaderboard_rank=item.leaderboard_rank,
            reliability_score=_reliability_score(item),
            friction_score=_friction_score(item),
            submit_coverage_score=_coverage_score(item),
        )
        for item in selected
    ]

    baseline = selected[-2] if len(selected) > 1 else None
    rank_delta: int | None = None
    reliability_delta: float | None = None
    friction_delta: float | None = None
    submit_coverage_delta: float | None = None

    if baseline is not None:
        if baseline.leaderboard_rank is not None and bundle.leaderboard_rank is not None:
            rank_delta = baseline.leaderboard_rank - bundle.leaderboard_rank
        reliability_delta = _reliability_score(bundle) - _reliability_score(baseline)
        friction_delta = _friction_score(bundle) - _friction_score(baseline)
        submit_coverage_delta = _coverage_score(bundle) - _coverage_score(baseline)

    if baseline is None:
        summary = "Insufficient prior runs for baseline comparison; captured current run as first history point."
    else:
        rank_text = "n/a" if rank_delta is None else f"{rank_delta:+d}"
        reliability_text = "n/a" if reliability_delta is None else f"{reliability_delta:+.2f}"
        friction_text = "n/a" if friction_delta is None else f"{friction_delta:+.2f}"
        coverage_text = "n/a" if submit_coverage_delta is None else f"{submit_coverage_delta:+.2f}"
        summary = (
            f"Baseline {baseline.run_id} -> current {bundle.run_id}: "
            f"rank_delta={rank_text}, "
            f"reliability_delta={reliability_text}, "
            f"friction_delta={friction_text}, "
            f"submit_coverage_delta={coverage_text}."
        )

    return HistoryComparison(
        generated_at=_utc_now(),
        policy_name=bundle.config.policy_name,
        season=bundle.config.season,
        window_runs=window_runs,
        observed_runs=len(selected),
        current_run_id=bundle.run_id,
        baseline_run_id=baseline.run_id if baseline is not None else None,
        rank_delta=rank_delta,
        reliability_delta=reliability_delta,
        friction_delta=friction_delta,
        submit_coverage_delta=submit_coverage_delta,
        summary=summary,
        run_points=run_points,
    )


def _gate_policy_for_profile(profile: ResearcherProfile) -> GatePolicy:
    if profile == "neophyte":
        return GatePolicy(
            profile=profile,
            min_submit_coverage_ratio=1.0,
            max_timeout_or_crash_incidents=0,
            max_failed_invocations=0,
            escalate_after_consecutive_failed_gate_runs=2,
        )

    return GatePolicy(
        profile=profile,
        min_submit_coverage_ratio=0.75,
        max_timeout_or_crash_incidents=1,
        max_failed_invocations=2,
        escalate_after_consecutive_failed_gate_runs=3,
    )


def _consecutive_failed_gate_runs(bundle: AuditBundle, gates: GateEvaluation) -> int:
    history = [
        candidate
        for candidate in _load_audit_bundles(bundle.config.output_root)
        if candidate.config.policy_name == bundle.config.policy_name and candidate.config.season == bundle.config.season
    ]

    deduped: dict[str, AuditBundle] = {candidate.run_id: candidate for candidate in history}
    deduped[bundle.run_id] = bundle

    ordered = sorted(deduped.values(), key=lambda item: item.started_at)
    statuses: list[GateStatus] = []
    for candidate in ordered:
        if candidate.run_id == bundle.run_id:
            statuses.append(gates.overall_status)
        elif candidate.gates is not None:
            statuses.append(candidate.gates.overall_status)
        else:
            statuses.append(_evaluate_gates(candidate).overall_status)

    count = 0
    for status in reversed(statuses):
        if status != "fail":
            break
        count += 1
    return count


def _build_escalation_plan(bundle: AuditBundle, gates: GateEvaluation) -> EscalationPlan:
    policy = _gate_policy_for_profile(bundle.config.researcher_profile)
    consecutive_failed = _consecutive_failed_gate_runs(bundle, gates)
    should_escalate = (
        gates.overall_status == "fail" and consecutive_failed >= policy.escalate_after_consecutive_failed_gate_runs
    )

    actions: list[EscalationAction] = []

    if gates.overall_status == "fail":
        actions.append(
            EscalationAction(
                priority=len(actions) + 1,
                action="Pause new variant expansion and rerun startup with --enforce-gates",
                reason="Required gates failed for current run.",
            )
        )

    failing_gate_ids = {check.gate_id for check in gates.checks if check.status == "fail"}
    if "submit_coverage" in failing_gate_ids:
        actions.append(
            EscalationAction(
                priority=len(actions) + 1,
                action="Run coverage pack with retry-focused variants before new experiments",
                reason="Submit coverage gate failed.",
            )
        )

    if (
        "reaper_detect_slo" in failing_gate_ids
        or "reaper_recovery_slo" in failing_gate_ids
        or "reaper_escalation_policy" in failing_gate_ids
    ):
        actions.append(
            EscalationAction(
                priority=len(actions) + 1,
                action="Tighten reaper settings and run single-variant stability check",
                reason="One or more reaper reliability gates failed.",
            )
        )

    if "reliability_trend" in failing_gate_ids or "friction_trend" in failing_gate_ids:
        actions.append(
            EscalationAction(
                priority=len(actions) + 1,
                action="Revert latest unstable experiment and rerun baseline stability pack",
                reason="Reliability/friction trend gate regression detected against baseline history.",
            )
        )

    if should_escalate:
        actions.append(
            EscalationAction(
                priority=len(actions) + 1,
                action="Escalate to human reviewer with audit bundle and daily report",
                reason=(
                    f"Consecutive failed gate runs ({consecutive_failed}) reached threshold "
                    f"{policy.escalate_after_consecutive_failed_gate_runs}."
                ),
            )
        )

    if not actions:
        actions.append(
            EscalationAction(
                priority=1,
                action="No escalation action required",
                reason="All required gates passed.",
            )
        )

    return EscalationPlan(
        generated_at=_utc_now(),
        profile=policy.profile,
        gate_overall_status=gates.overall_status,
        consecutive_failed_gate_runs=consecutive_failed,
        escalation_threshold=policy.escalate_after_consecutive_failed_gate_runs,
        should_escalate=should_escalate,
        actions=actions,
    )


def _evaluate_gates(bundle: AuditBundle) -> GateEvaluation:
    policy = _gate_policy_for_profile(bundle.config.researcher_profile)

    checks = [
        GateCheck(
            gate_id="full_loop_success",
            status="pass" if bundle.status == "success" else "fail",
            message=f"status={bundle.status}",
        ),
        GateCheck(
            gate_id="reaper_detect_slo",
            status="pass" if bundle.reaper_slo.detect_slo_met else "fail",
            message=(
                f"stall_events={bundle.reaper_slo.stall_events}, "
                f"within_target={bundle.reaper_slo.stall_detected_within_target}"
            ),
        ),
        GateCheck(
            gate_id="reaper_recovery_slo",
            status="pass" if bundle.reaper_slo.recovery_slo_met else "fail",
            message=(
                f"recovery_attempts={bundle.reaper_slo.recovery_attempts}, "
                f"within_target={bundle.reaper_slo.recoveries_started_within_target}"
            ),
        ),
        GateCheck(
            gate_id="reaper_escalation_policy",
            status="pass" if bundle.reaper_slo.escalation_policy_met else "fail",
            message=(
                f"max_consecutive_failed_recoveries={bundle.reaper_slo.max_consecutive_failed_recoveries}, "
                f"escalations={bundle.reaper_slo.escalations}"
            ),
        ),
        GateCheck(
            gate_id="submit_coverage",
            status=(
                "pass"
                if bundle.submit_coverage_index.attempt_to_submit_ratio >= policy.min_submit_coverage_ratio
                else "fail"
            ),
            message=(
                f"attempt_to_submit_ratio={bundle.submit_coverage_index.attempt_to_submit_ratio:.2f}, "
                f"min_required={policy.min_submit_coverage_ratio:.2f}"
            ),
        ),
        GateCheck(
            gate_id="timeout_or_crash_budget",
            status=(
                "pass"
                if bundle.reliability_index.timeout_or_crash_incidents <= policy.max_timeout_or_crash_incidents
                else "fail"
            ),
            message=(
                f"timeout_or_crash_incidents={bundle.reliability_index.timeout_or_crash_incidents}, "
                f"max_allowed={policy.max_timeout_or_crash_incidents}"
            ),
        ),
        GateCheck(
            gate_id="failed_invocations_budget",
            status=("pass" if bundle.friction_index.failed_invocations <= policy.max_failed_invocations else "fail"),
            message=(
                f"failed_invocations={bundle.friction_index.failed_invocations}, "
                f"max_allowed={policy.max_failed_invocations}"
            ),
        ),
        GateCheck(
            gate_id="reliability_trend",
            status=(
                "pass"
                if (
                    bundle.history_comparison is None
                    or bundle.history_comparison.baseline_run_id is None
                    or bundle.history_comparison.reliability_delta is None
                    or bundle.history_comparison.reliability_delta >= 0.0
                )
                else "fail"
            ),
            message=(
                "baseline=n/a"
                if bundle.history_comparison is None or bundle.history_comparison.baseline_run_id is None
                else f"reliability_delta={bundle.history_comparison.reliability_delta:+.2f}"
            ),
        ),
        GateCheck(
            gate_id="friction_trend",
            status=(
                "pass"
                if (
                    bundle.history_comparison is None
                    or bundle.history_comparison.baseline_run_id is None
                    or bundle.history_comparison.friction_delta is None
                    or bundle.history_comparison.friction_delta <= 0.0
                )
                else "fail"
            ),
            message=(
                "baseline=n/a"
                if bundle.history_comparison is None or bundle.history_comparison.baseline_run_id is None
                else f"friction_delta={bundle.history_comparison.friction_delta:+.2f}"
            ),
        ),
    ]

    required_checks_total = len(checks)
    required_checks_passed = sum(1 for check in checks if check.status == "pass")
    overall_status: GateStatus = "pass" if required_checks_passed == required_checks_total else "fail"

    return GateEvaluation(
        generated_at=_utc_now(),
        overall_status=overall_status,
        required_checks_passed=required_checks_passed,
        required_checks_total=required_checks_total,
        checks=checks,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Claude-first AI researcher startup workflow")
    parser.add_argument("--policy", required=True, help="Policy URI/path for scrimmage/upload")
    parser.add_argument("--policy-name", required=True, help="Uploaded policy name")
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
    parser.add_argument("--no-upload", action="store_true")
    parser.add_argument("--no-submit", action="store_true")
    parser.add_argument("--no-leaderboard", action="store_true")
    parser.add_argument("--researcher-profile", choices=["experienced", "neophyte"], default="experienced")
    parser.add_argument(
        "--enforce-gates",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Fail when required startup gates do not pass (enabled by default)",
    )
    parser.add_argument(
        "--allow-interactive-login",
        action="store_true",
        help="Allow browser-based login refresh when auth failures are detected",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    config = StartupConfig(
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
        run_upload=not args.no_upload,
        run_submit=not args.no_submit,
        run_leaderboard=not args.no_leaderboard,
        researcher_profile=args.researcher_profile,
        allow_interactive_login=args.allow_interactive_login,
        enforce_gates=args.enforce_gates,
    )

    bundle = run_startup(config)
    print(f"run_dir={bundle.run_dir}")
    print(f"status={bundle.status}")
    print(f"leaderboard_rank={bundle.leaderboard_rank}")
    if bundle.gates is not None:
        print(f"gates_status={bundle.gates.overall_status}")

    if bundle.status != "success":
        return 1
    if config.enforce_gates and bundle.gates and bundle.gates.overall_status != "pass":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
