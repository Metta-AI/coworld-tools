from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class SmokeError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SmokeResult:
    run_id: str
    passed: bool
    report_file: Path
    agent_returncode: int | None
    frames_saved: int


def run_smoke_test(
    *,
    output_dir: Path,
    agent_url: str,
    server_command: str | None = None,
    server_cwd: Path | None = None,
    health_url: str | None = None,
    startup_timeout: float = 10.0,
    run_timeout: float = 30.0,
    agent_max_frames: int | None = 25,
    python_executable: str | None = None,
) -> SmokeResult:
    output_path = output_dir.expanduser().resolve()
    agent_file = output_path / "agent" / "run_agent.py"
    if not agent_file.exists():
        raise SmokeError(f"generated agent runner not found: {agent_file}")
    if not agent_url:
        raise SmokeError("agent_url is required for smoke testing")
    if server_cwd is not None and not server_cwd.expanduser().exists():
        raise SmokeError(f"server_cwd does not exist: {server_cwd}")
    if startup_timeout <= 0:
        raise SmokeError("startup_timeout must be positive")
    if run_timeout <= 0:
        raise SmokeError("run_timeout must be positive")
    if agent_max_frames is not None and agent_max_frames < 1:
        raise SmokeError("agent_max_frames must be positive when provided")

    run_id = datetime.now(UTC).strftime("smoke_%Y%m%dT%H%M%SZ")
    smoke_root = output_path / "smoke_tests"
    runs_dir = smoke_root / "runs"
    logs_dir = smoke_root / "logs" / run_id
    live_output_dir = smoke_root / "live_runs" / run_id
    runs_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    server_process: subprocess.Popen[bytes] | None = None
    server_stdout_path = logs_dir / "server.stdout.log"
    server_stderr_path = logs_dir / "server.stderr.log"
    server_returncode: int | None = None
    server_started = False
    health_ok = False
    agent_timed_out = False
    agent_result: subprocess.CompletedProcess[str] | None = None
    preflight_error: str | None = None

    started_at = datetime.now(UTC)
    try:
        if server_command:
            server_process = _start_server(
                server_command=server_command,
                server_cwd=server_cwd,
                stdout_path=server_stdout_path,
                stderr_path=server_stderr_path,
            )
            server_started = True
            if health_url:
                health_ok = _wait_for_health(health_url, startup_timeout)
                if not health_ok:
                    preflight_error = f"server health check did not pass before timeout: {health_url}"
            else:
                time.sleep(min(startup_timeout, 1.0))
                if server_process.poll() is not None:
                    preflight_error = f"server command exited before agent run: {server_process.returncode}"

        if preflight_error is None:
            command = _agent_command(
                python_executable=python_executable or sys.executable,
                agent_file=agent_file,
                agent_url=agent_url,
                live_output_dir=live_output_dir,
                agent_max_frames=agent_max_frames,
            )
            try:
                agent_result = subprocess.run(
                    command,
                    cwd=agent_file.parent,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=run_timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                agent_timed_out = True
                agent_result = subprocess.CompletedProcess(
                    args=command,
                    returncode=None,
                    stdout=_coerce_timeout_output(exc.stdout),
                    stderr=_coerce_timeout_output(exc.stderr),
                )
        else:
            command = None
    finally:
        if server_process is not None:
            server_returncode = _stop_server(server_process)

    frames_saved = _count_files(live_output_dir / "frames")
    decoded_frames_saved = _count_files(live_output_dir / "decoded")
    passed = (
        agent_result is not None
        and agent_result.returncode == 0
        and not agent_timed_out
        and preflight_error is None
        and (not server_command or server_started)
        and (not health_url or health_ok)
    )
    finished_at = datetime.now(UTC)
    report = {
        "schema_version": "maker.smoke_test_run.v1",
        "run_id": run_id,
        "status": "passed" if passed else "failed",
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "output_dir": str(output_path),
        "agent_file": str(agent_file.relative_to(output_path)),
        "agent_url": agent_url,
        "agent_command": command,
        "agent_returncode": None if agent_result is None else agent_result.returncode,
        "agent_timed_out": agent_timed_out,
        "agent_stdout": "" if agent_result is None else agent_result.stdout[-8000:],
        "agent_stderr": "" if agent_result is None else agent_result.stderr[-8000:],
        "preflight_error": preflight_error,
        "agent_max_frames": agent_max_frames,
        "live_output_dir": str(live_output_dir.relative_to(output_path)),
        "frames_saved": frames_saved,
        "decoded_frames_saved": decoded_frames_saved,
        "server": {
            "command": server_command,
            "cwd": None if server_cwd is None else str(server_cwd.expanduser().resolve()),
            "started": server_started,
            "returncode_after_stop": server_returncode,
            "stdout_log": str(server_stdout_path.relative_to(output_path)) if server_command else None,
            "stderr_log": str(server_stderr_path.relative_to(output_path)) if server_command else None,
            "health_url": health_url,
            "health_ok": health_ok,
        },
    }
    report_file = runs_dir / f"{run_id}.json"
    report_file.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return SmokeResult(
        run_id=run_id,
        passed=passed,
        report_file=report_file,
        agent_returncode=None if agent_result is None else agent_result.returncode,
        frames_saved=frames_saved,
    )


def _start_server(
    *,
    server_command: str,
    server_cwd: Path | None,
    stdout_path: Path,
    stderr_path: Path,
) -> subprocess.Popen[bytes]:
    args = shlex.split(server_command)
    if not args:
        raise SmokeError("server_command must not be empty")
    stdout_handle = stdout_path.open("wb")
    stderr_handle = stderr_path.open("wb")
    try:
        process = subprocess.Popen(
            args,
            cwd=None if server_cwd is None else server_cwd.expanduser().resolve(),
            stdout=stdout_handle,
            stderr=stderr_handle,
            env=os.environ.copy(),
            start_new_session=True,
        )
        stdout_handle.close()
        stderr_handle.close()
        return process
    except Exception:
        stdout_handle.close()
        stderr_handle.close()
        raise


def _stop_server(process: subprocess.Popen[bytes]) -> int | None:
    if process.poll() is not None:
        return process.returncode
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return process.poll()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)
    return process.returncode


def _wait_for_health(url: str, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if 200 <= response.status < 300:
                    return True
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.1)
    return False


def _agent_command(
    *,
    python_executable: str,
    agent_file: Path,
    agent_url: str,
    live_output_dir: Path,
    agent_max_frames: int | None,
) -> list[str]:
    command = [python_executable, str(agent_file), agent_url]
    text = agent_file.read_text(encoding="utf-8")
    if "--output-root" in text:
        command.extend(["--output-root", str(live_output_dir)])
    if agent_max_frames is not None and "--max-frames" in text:
        command.extend(["--max-frames", str(agent_max_frames)])
    return command


def _count_files(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for item in path.iterdir() if item.is_file())


def _coerce_timeout_output(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
