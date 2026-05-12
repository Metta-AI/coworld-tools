from __future__ import annotations

import argparse
import re
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from cogames_rl_researcher.json_io import write_json

FrictionCategory = Literal[
    "setup/auth",
    "cli usability",
    "data integrity",
    "runtime/performance",
    "submission workflow",
]

LOG_SUFFIXES = {".log", ".txt", ".md", ".jsonl", ".out", ".err"}
ERROR_MARKERS = (
    "error",
    "failed",
    "failure",
    "traceback",
    "exception",
    "unauthorized",
    "forbidden",
    "timeout",
)
AUTH_MARKERS = (
    "not authenticated",
    "authentication failed",
    "token",
    "unauthorized",
    "forbidden",
    "run: cogames auth login",
)
COGAMES_COMMAND_PATTERN = re.compile(r"(cogames(?:\s+[^\n\r]+)?)")


def _utc_now() -> datetime:
    return datetime.now(UTC)


class MinedFailure(BaseModel):
    source_file: str
    line_number: int
    agent: str
    command: str
    observed_error: str
    likely_owner: str
    category: FrictionCategory


class MinedFailureAggregate(BaseModel):
    signature: str
    count: int
    likely_owner: str
    category: FrictionCategory


class LogMiningReport(BaseModel):
    generated_at: datetime
    roots: list[str]
    agents: list[str]
    files_scanned: int
    total_failures: int
    failures_by_agent: dict[str, int]
    top_failures: list[MinedFailureAggregate]
    failures: list[MinedFailure]


class LogMiningConfig(BaseModel):
    log_roots: list[Path] = Field(default_factory=lambda: [Path("./artifacts"), Path("./logs")])
    output_path: Path = Path("./artifacts/ai_researcher/log_mining_report.json")
    agents: list[str] = Field(default_factory=lambda: ["gastown", "claude", "codex"])
    max_failures: int = Field(default=200, ge=1)
    poll_interval_seconds: int = Field(default=300, ge=1)
    iterations: int = Field(default=1, ge=0)


def _iter_log_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return [
        path
        for path in root.rglob("*")
        if path.is_file() and (path.suffix.lower() in LOG_SUFFIXES or path.name.endswith(".stderr.log"))
    ]


def _extract_command(line: str) -> str | None:
    match = COGAMES_COMMAND_PATTERN.search(line)
    if match is None:
        return None
    return match.group(1).strip()


def _is_error_line(line: str) -> bool:
    lowered = line.lower()
    return any(marker in lowered for marker in ERROR_MARKERS)


def _looks_like_auth_failure(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in AUTH_MARKERS)


def _agent_for(*, file_path: Path, line: str, agents: list[str]) -> str | None:
    lowered_path = str(file_path).lower()
    lowered_line = line.lower()
    for agent in agents:
        lowered_agent = agent.lower()
        if lowered_agent in lowered_path or lowered_agent in lowered_line:
            return agent
    return None


def _category_for(*, command: str, error_text: str) -> FrictionCategory:
    lowered_error = error_text.lower()
    lowered_command = command.lower()

    if _looks_like_auth_failure(error_text) or " login" in f" {lowered_command}":
        return "setup/auth"
    if any(token in lowered_command for token in (" upload", " submit", " leaderboard")):
        return "submission workflow"
    if "json" in lowered_error or "parse" in lowered_error:
        return "data integrity"
    if "timeout" in lowered_error or "stall" in lowered_error or "latency" in lowered_error:
        return "runtime/performance"
    return "cli usability"


def _likely_owner(error_text: str) -> str:
    if _looks_like_auth_failure(error_text):
        return "auth"
    return "cogames-cli"


def mine_cogames_failures(*, log_roots: list[Path], agents: list[str], max_failures: int = 200) -> LogMiningReport:
    files: list[Path] = []
    for root in log_roots:
        files.extend(_iter_log_files(root))

    failures: list[MinedFailure] = []

    for file_path in sorted(files):
        try:
            lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue

        recent_command: str | None = None
        for line_number, line in enumerate(lines, start=1):
            command_on_line = _extract_command(line)
            if command_on_line is not None:
                recent_command = command_on_line

            if not _is_error_line(line):
                continue

            command = command_on_line or recent_command
            if command is None or "cogames" not in command.lower():
                continue

            agent = _agent_for(file_path=file_path, line=line, agents=agents)
            if agent is None:
                continue

            error_text = line.strip()
            category = _category_for(command=command, error_text=error_text)
            likely_owner = _likely_owner(error_text)
            failures.append(
                MinedFailure(
                    source_file=str(file_path),
                    line_number=line_number,
                    agent=agent,
                    command=command,
                    observed_error=error_text,
                    likely_owner=likely_owner,
                    category=category,
                )
            )

            if len(failures) >= max_failures:
                break

        if len(failures) >= max_failures:
            break

    by_agent = Counter(item.agent for item in failures)
    by_signature = Counter((item.command, item.observed_error, item.likely_owner, item.category) for item in failures)

    top_failures = [
        MinedFailureAggregate(
            signature=f"{command} :: {error_text}",
            count=count,
            likely_owner=likely_owner,
            category=category,
        )
        for (command, error_text, likely_owner, category), count in by_signature.most_common(10)
    ]

    return LogMiningReport(
        generated_at=_utc_now(),
        roots=[str(root) for root in log_roots],
        agents=agents,
        files_scanned=len(files),
        total_failures=len(failures),
        failures_by_agent={agent: by_agent.get(agent, 0) for agent in agents},
        top_failures=top_failures,
        failures=failures,
    )


def _write_report(report: LogMiningReport, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(output_path, report)

    markdown_lines = [
        f"# Log Mining Report ({report.generated_at.isoformat()})",
        "",
        f"- files_scanned: {report.files_scanned}",
        f"- total_failures: {report.total_failures}",
        "",
        "## Failures by Agent",
    ]

    for agent, count in report.failures_by_agent.items():
        markdown_lines.append(f"- {agent}: {count}")

    markdown_lines.extend(["", "## Top Failure Signatures"])
    if report.top_failures:
        for item in report.top_failures:
            markdown_lines.append(
                f"- [{item.category}] {item.signature} (count={item.count}, owner={item.likely_owner})"
            )
    else:
        markdown_lines.append("- none")

    output_path.with_suffix(".md").write_text("\n".join(markdown_lines) + "\n", encoding="utf-8")


def run_log_mining_service(config: LogMiningConfig) -> LogMiningReport:
    remaining = config.iterations
    latest_report = LogMiningReport(
        generated_at=_utc_now(),
        roots=[str(root) for root in config.log_roots],
        agents=config.agents,
        files_scanned=0,
        total_failures=0,
        failures_by_agent={agent: 0 for agent in config.agents},
        top_failures=[],
        failures=[],
    )

    while True:
        latest_report = mine_cogames_failures(
            log_roots=config.log_roots,
            agents=config.agents,
            max_failures=config.max_failures,
        )
        _write_report(latest_report, config.output_path)

        if remaining == 1:
            break
        if remaining > 1:
            remaining -= 1

        time.sleep(config.poll_interval_seconds)

    return latest_report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mine cogames command failures from gastown/claude/codex logs")
    parser.add_argument(
        "--log-root",
        action="append",
        dest="log_roots",
        default=None,
        help="Log root directory to scan (repeatable). Defaults to ./artifacts and ./logs",
    )
    parser.add_argument("--output", default="./artifacts/ai_researcher/log_mining_report.json")
    parser.add_argument(
        "--agent",
        action="append",
        dest="agents",
        default=None,
        help="Agent keyword filter (repeatable). Defaults to gastown/claude/codex",
    )
    parser.add_argument("--max-failures", type=int, default=200)
    parser.add_argument("--poll-interval-seconds", type=int, default=300)
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--watch", action="store_true", help="Watch forever (equivalent to --iterations 0)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    config = LogMiningConfig(
        log_roots=[Path(root) for root in (args.log_roots or ["./artifacts", "./logs"])],
        output_path=Path(args.output),
        agents=args.agents or ["gastown", "claude", "codex"],
        max_failures=args.max_failures,
        poll_interval_seconds=args.poll_interval_seconds,
        iterations=0 if args.watch else args.iterations,
    )

    report = run_log_mining_service(config)

    print(f"files_scanned={report.files_scanned}")
    print(f"total_failures={report.total_failures}")
    print(f"output={config.output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
