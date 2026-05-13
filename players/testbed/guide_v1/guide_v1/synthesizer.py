from __future__ import annotations

import subprocess
import time
from pathlib import Path

from .framework import AgentFrameworkRef


def run_synthesizer(
    prompt: str,
    *,
    game_source: Path,
    output_dir: Path,
    agent_framework: AgentFrameworkRef | None = None,
    output_file: Path | None = None,
    model: str | None = None,
) -> str:
    cmd = [
        "claude",
        "-p",
        prompt,
        "--bare",
        "--allowedTools",
        "Read,Edit",
        "--add-dir",
        str(output_dir),
        "--add-dir",
        str(game_source),
    ]
    if agent_framework is not None:
        for extra_dir in _existing_framework_dirs(agent_framework):
            cmd.extend(["--add-dir", str(extra_dir)])
    if model:
        cmd.extend(["--model", model])

    try:
        process = subprocess.Popen(
            cmd,
            cwd=game_source,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("Claude executable not found: claude") from exc

    stable_since: float | None = None
    last_signature: tuple[int, int] | None = None
    while True:
        returncode = process.poll()
        if returncode is not None:
            stdout, stderr = process.communicate()
            if returncode != 0 and not _file_has_content(output_file):
                detail = stderr.strip() or stdout.strip() or f"exit code {returncode}"
                raise RuntimeError(f"Claude synthesizer failed: {detail}")
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


def _file_has_content(path: Path | None) -> bool:
    if path is None:
        return False
    try:
        return path.exists() and bool(path.read_text(encoding="utf-8").strip())
    except OSError:
        return False


def _file_signature(path: Path | None) -> tuple[int, int] | None:
    if path is None:
        return None
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
