from __future__ import annotations

import argparse
import shlex
import subprocess
import time
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from cogames_rl_researcher.json_io import write_json

DefectStatus = Literal["open", "triaged", "fixed", "dismissed"]

AUTH_MARKERS = (
    "not authenticated",
    "authentication failed",
    "token",
    "unauthorized",
    "forbidden",
    "run: cogames auth login",
)


class CrashDefect(BaseModel):
    defect_id: str
    submitted_at: datetime
    reporter: str
    command: str
    observed_error: str
    stacktrace: str | None = None
    context: str | None = None
    season: str | None = None
    policy_name: str | None = None
    likely_owner: str
    proposed_fix: str
    status: DefectStatus = "open"


class DefectBacklogItem(BaseModel):
    signature: str
    count: int
    likely_owner: str
    recommended_fix: str


class DefectBacklog(BaseModel):
    generated_at: datetime
    defects_path: str
    total_defects: int
    open_defects: int
    status_counts: dict[str, int]
    top_signatures: list[DefectBacklogItem]


class DefectFixPlanItem(BaseModel):
    priority: int
    defect_id: str
    likely_owner: str
    command: str
    proposed_fix: str
    reason: str


class DefectFixPlan(BaseModel):
    generated_at: datetime
    source_defects_path: str
    open_defects: int
    items: list[DefectFixPlanItem]


class DefectFixAttempt(BaseModel):
    attempt_id: str
    defect_id: str
    command: str
    started_at: datetime
    ended_at: datetime
    duration_seconds: float
    return_code: int | None
    timed_out: bool
    status: Literal["success", "failed"]
    stdout_log: str
    stderr_log: str


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _defects_path(store_dir: Path) -> Path:
    return store_dir / "crash_defects.jsonl"


def _backlog_path(store_dir: Path) -> Path:
    return store_dir / "defect_backlog.json"


def _fix_plan_path(store_dir: Path) -> Path:
    return store_dir / "defect_fix_plan.json"


def load_crash_defects(store_dir: Path) -> list[CrashDefect]:
    defects_path = _defects_path(store_dir)
    if not defects_path.exists():
        return []

    defects: list[CrashDefect] = []
    for line in defects_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        defects.append(CrashDefect.model_validate_json(line))
    return defects


def _write_crash_defects(store_dir: Path, defects: list[CrashDefect]) -> None:
    store_dir.mkdir(parents=True, exist_ok=True)
    lines = [defect.model_dump_json() for defect in defects]
    _defects_path(store_dir).write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def build_defect_backlog(store_dir: Path) -> DefectBacklog:
    defects = load_crash_defects(store_dir)

    status_counts = Counter(defect.status for defect in defects)
    by_signature = Counter((defect.observed_error, defect.likely_owner, defect.proposed_fix) for defect in defects)

    top_signatures = [
        DefectBacklogItem(
            signature=signature,
            count=count,
            likely_owner=likely_owner,
            recommended_fix=recommended_fix,
        )
        for (signature, likely_owner, recommended_fix), count in by_signature.most_common(10)
    ]

    backlog = DefectBacklog(
        generated_at=_utc_now(),
        defects_path=str(_defects_path(store_dir)),
        total_defects=len(defects),
        open_defects=status_counts.get("open", 0),
        status_counts=dict(status_counts),
        top_signatures=top_signatures,
    )
    write_json(_backlog_path(store_dir), backlog)
    return backlog


def build_defect_fix_plan(store_dir: Path, *, max_items: int = 5) -> DefectFixPlan:
    defects = load_crash_defects(store_dir)
    candidates = [defect for defect in defects if defect.status in {"open", "triaged"}]
    open_count = sum(1 for defect in defects if defect.status == "open")
    candidates_sorted = sorted(candidates, key=lambda item: item.submitted_at, reverse=True)
    items = [
        DefectFixPlanItem(
            priority=index,
            defect_id=defect.defect_id,
            likely_owner=defect.likely_owner,
            command=defect.command,
            proposed_fix=defect.proposed_fix,
            reason=f"status={defect.status}; submitted_at={defect.submitted_at.isoformat()}",
        )
        for index, defect in enumerate(candidates_sorted[:max_items], start=1)
    ]
    plan = DefectFixPlan(
        generated_at=_utc_now(),
        source_defects_path=str(_defects_path(store_dir)),
        open_defects=open_count,
        items=items,
    )
    store_dir.mkdir(parents=True, exist_ok=True)
    write_json(_fix_plan_path(store_dir), plan)
    return plan


def submit_crash_defect(
    *,
    store_dir: Path,
    reporter: str,
    command: str,
    observed_error: str,
    stacktrace: str | None = None,
    context: str | None = None,
    season: str | None = None,
    policy_name: str | None = None,
    proposed_fix: str | None = None,
) -> CrashDefect:
    store_dir.mkdir(parents=True, exist_ok=True)

    lowered_error = observed_error.lower()
    likely_owner = "auth" if any(marker in lowered_error for marker in AUTH_MARKERS) else "cogames-cli"
    submitted_at = _utc_now()
    defect = CrashDefect(
        defect_id=f"defect-{submitted_at.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}",
        submitted_at=submitted_at,
        reporter=reporter,
        command=command,
        observed_error=observed_error,
        stacktrace=stacktrace,
        context=context,
        season=season,
        policy_name=policy_name,
        likely_owner=likely_owner,
        proposed_fix=proposed_fix
        or (
            "Refresh login token and rerun command with explicit login-server/server args."
            if likely_owner == "auth"
            else "Reproduce with exact command and stderr, then patch root-cause in CLI/runtime path."
        ),
        status="open",
    )

    defects = load_crash_defects(store_dir)
    defects.append(defect)
    _write_crash_defects(store_dir, defects)
    build_defect_backlog(store_dir)
    build_defect_fix_plan(store_dir)
    return defect


def set_defect_status(*, store_dir: Path, defect_id: str, status: DefectStatus) -> CrashDefect:
    defects = load_crash_defects(store_dir)
    for index, defect in enumerate(defects):
        if defect.defect_id != defect_id:
            continue
        updated = defect.model_copy(update={"status": status})
        defects[index] = updated
        _write_crash_defects(store_dir, defects)
        build_defect_backlog(store_dir)
        build_defect_fix_plan(store_dir)
        return updated
    raise ValueError(f"Defect not found: {defect_id}")


def validate_defect_fix(
    *,
    store_dir: Path,
    defect_id: str,
    fix_command: str,
    timeout_seconds: int = 900,
    mark_fixed_on_success: bool = False,
) -> DefectFixAttempt:
    if not any(defect.defect_id == defect_id for defect in load_crash_defects(store_dir)):
        raise ValueError(f"Defect not found: {defect_id}")

    attempts_dir = store_dir / "fix_attempt_logs"
    attempts_dir.mkdir(parents=True, exist_ok=True)

    started_at = _utc_now()
    started_mono = time.monotonic()
    attempt_id = f"fix-attempt-{started_at.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    stdout_log = attempts_dir / f"{attempt_id}.stdout.log"
    stderr_log = attempts_dir / f"{attempt_id}.stderr.log"

    argv = shlex.split(fix_command)
    timed_out = False
    return_code: int | None = None
    with stdout_log.open("w", encoding="utf-8") as stdout_sink, stderr_log.open("w", encoding="utf-8") as stderr_sink:
        try:
            process = subprocess.Popen(argv, stdout=stdout_sink, stderr=stderr_sink, text=True)  # noqa: S603
        except FileNotFoundError as exc:
            stderr_sink.write(f"fix validation command failed to start: {exc}\n")
            return_code = 127
        else:
            while process.poll() is None:
                time.sleep(0.2)
                if time.monotonic() - started_mono > float(timeout_seconds):
                    process.kill()
                    timed_out = True
                    break
            process.wait()
            return_code = process.returncode
            if timed_out:
                stderr_sink.write(f"fix validation timed out after {timeout_seconds} seconds\n")

    ended_at = _utc_now()
    attempt = DefectFixAttempt(
        attempt_id=attempt_id,
        defect_id=defect_id,
        command=fix_command,
        started_at=started_at,
        ended_at=ended_at,
        duration_seconds=max(ended_at.timestamp() - started_at.timestamp(), 0.0),
        return_code=return_code,
        timed_out=timed_out,
        status="success" if (not timed_out and return_code == 0) else "failed",
        stdout_log=str(stdout_log),
        stderr_log=str(stderr_log),
    )

    store_dir.mkdir(parents=True, exist_ok=True)
    with (store_dir / "fix_attempts.jsonl").open("a", encoding="utf-8") as sink:
        sink.write(attempt.model_dump_json() + "\n")

    if attempt.status == "success" and mark_fixed_on_success:
        set_defect_status(store_dir=store_dir, defect_id=defect_id, status="fixed")
    else:
        build_defect_backlog(store_dir)
        build_defect_fix_plan(store_dir)

    return attempt


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Crash defect intake/backlog for AI RL researcher workflows")
    parser.add_argument("--store-dir", default="./artifacts/ai_researcher/defects")

    subparsers = parser.add_subparsers(dest="action", required=True)

    submit = subparsers.add_parser("submit", help="Submit a crash defect")
    submit.add_argument("--reporter", required=True)
    submit.add_argument("--command", required=True)
    submit.add_argument("--observed-error", required=True)
    submit.add_argument("--stacktrace", default=None)
    submit.add_argument("--context", default=None)
    submit.add_argument("--season", default=None)
    submit.add_argument("--policy-name", default=None)
    submit.add_argument("--proposed-fix", default=None)

    status = subparsers.add_parser("set-status", help="Update defect status")
    status.add_argument("--defect-id", required=True)
    status.add_argument("--status", choices=["open", "triaged", "fixed", "dismissed"], required=True)

    subparsers.add_parser("backlog", help="Regenerate backlog summary")
    subparsers.add_parser("fix-plan", help="Regenerate ranked defect fix plan")

    validate = subparsers.add_parser("validate-fix", help="Run a fix command for a defect and record validation")
    validate.add_argument("--defect-id", required=True)
    validate.add_argument("--fix-command", required=True)
    validate.add_argument("--timeout-seconds", type=int, default=900)
    validate.add_argument(
        "--mark-fixed-on-success",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Mark the defect fixed only when validation command exits successfully",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    store_dir = Path(args.store_dir)

    if args.action == "submit":
        defect = submit_crash_defect(
            store_dir=store_dir,
            reporter=args.reporter,
            command=args.command,
            observed_error=args.observed_error,
            stacktrace=args.stacktrace,
            context=args.context,
            season=args.season,
            policy_name=args.policy_name,
            proposed_fix=args.proposed_fix,
        )
        print(f"defect_id={defect.defect_id}")
        print(f"status={defect.status}")
        print(f"store={store_dir}")
        return 0

    if args.action == "set-status":
        defect = set_defect_status(store_dir=store_dir, defect_id=args.defect_id, status=args.status)
        print(f"defect_id={defect.defect_id}")
        print(f"status={defect.status}")
        return 0

    if args.action == "fix-plan":
        plan = build_defect_fix_plan(store_dir)
        print(f"open_defects={plan.open_defects}")
        print(f"items={len(plan.items)}")
        print(f"output={_fix_plan_path(store_dir)}")
        return 0

    if args.action == "validate-fix":
        attempt = validate_defect_fix(
            store_dir=store_dir,
            defect_id=args.defect_id,
            fix_command=args.fix_command,
            timeout_seconds=args.timeout_seconds,
            mark_fixed_on_success=args.mark_fixed_on_success,
        )
        print(f"attempt_id={attempt.attempt_id}")
        print(f"status={attempt.status}")
        print(f"timed_out={attempt.timed_out}")
        print(f"return_code={attempt.return_code}")
        return 0 if attempt.status == "success" else 1

    backlog = build_defect_backlog(store_dir)
    print(f"total_defects={backlog.total_defects}")
    print(f"open_defects={backlog.open_defects}")
    print(f"output={_backlog_path(store_dir)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
