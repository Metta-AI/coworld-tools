from __future__ import annotations

import subprocess
import time
from pathlib import Path

from .framework import AgentFrameworkRef


def run_claude(
    prompt: str,
    *,
    game_source: Path,
    output_dir: Path,
    agent_framework: AgentFrameworkRef,
    model: str | None = None,
) -> str:
    cmd = [
        "claude",
        "-p",
        prompt,
        "--bare",
        "--allowedTools",
        "Read,Edit,Bash",
        "--add-dir",
        str(game_source),
        "--add-dir",
        str(output_dir),
    ]
    for extra_dir in _existing_framework_dirs(agent_framework):
        cmd.extend(["--add-dir", str(extra_dir)])
    if model:
        cmd.extend(["--model", model])

    return _run_command(cmd, cwd=game_source, runner_name="Claude")


def run_codex(
    prompt: str,
    *,
    game_source: Path,
    output_dir: Path,
    agent_framework: AgentFrameworkRef,
    draft_output_file: Path,
    model: str | None = None,
) -> str:
    cmd = [
        "codex",
        "exec",
        "-C",
        str(output_dir),
        "-s",
        "workspace-write",
        "--skip-git-repo-check",
        "--ephemeral",
        "--add-dir",
        str(game_source),
    ]
    for extra_dir in _existing_framework_dirs(agent_framework):
        cmd.extend(["--add-dir", str(extra_dir)])
    if model:
        cmd.extend(["-m", model])
    cmd.append(prompt)

    stdout = _run_command_until_file_stable(
        cmd,
        cwd=output_dir,
        runner_name="Codex",
        output_file=draft_output_file,
    )

    try:
        content = draft_output_file.read_text(encoding="utf-8")
        if content.strip():
            return content
    except FileNotFoundError:
        pass

    return stdout


def _run_command(cmd: list[str], *, cwd: Path, runner_name: str) -> str:
    try:
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise RuntimeError(f"{runner_name} executable not found: {cmd[0]}") from exc

    if result.returncode != 0:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        detail = stderr or stdout or f"exit code {result.returncode}"
        raise RuntimeError(f"{runner_name} failed: {detail}")

    return result.stdout


def _run_command_until_file_stable(
    cmd: list[str],
    *,
    cwd: Path,
    runner_name: str,
    output_file: Path,
) -> str:
    try:
        process = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"{runner_name} executable not found: {cmd[0]}") from exc

    stable_since: float | None = None
    last_signature: tuple[int, int] | None = None
    while True:
        returncode = process.poll()
        if returncode is not None:
            stdout, stderr = process.communicate()
            if returncode != 0 and not _file_has_content(output_file):
                detail = stderr.strip() or stdout.strip() or f"exit code {returncode}"
                raise RuntimeError(f"{runner_name} failed: {detail}")
            return stdout

        if _file_has_content(output_file):
            signature = _file_signature(output_file)
            if signature == last_signature:
                if stable_since is not None and time.monotonic() - stable_since >= 20:
                    process.terminate()
                    try:
                        stdout, _stderr = process.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        stdout, _stderr = process.communicate()
                    return stdout
            else:
                last_signature = signature
                stable_since = time.monotonic()

        time.sleep(0.5)


def _file_has_content(path: Path) -> bool:
    try:
        return path.exists() and bool(path.read_text(encoding="utf-8").strip())
    except OSError:
        return False


def _file_signature(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_size, stat.st_mtime_ns


def _existing_framework_dirs(agent_framework: AgentFrameworkRef) -> tuple[Path, ...]:
    return tuple(
        path
        for path in (agent_framework.framework_dir, agent_framework.package_source_root)
        if path.exists()
    )
