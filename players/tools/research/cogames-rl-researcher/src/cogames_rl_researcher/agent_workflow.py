from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Literal

AgentName = Literal["codex", "claude"]
WorkflowProfile = Literal["neophyte", "experienced"]

AGENT_COMMANDS: dict[AgentName, list[str]] = {
    "codex": ["codex", "exec", "--dangerously-bypass-approvals-and-sandbox", "-"],
    "claude": ["claude", "-p", "--verbose", "--dangerously-skip-permissions"],
}


def _find_repo_root() -> Path:
    this_file = Path(__file__).resolve()
    for candidate in this_file.parents:
        if (candidate / "cogames-rl-researcher" / "prompts").exists():
            return candidate
    raise RuntimeError("Could not find repo root containing cogames-rl-researcher/prompts")


def prompt_path_for_profile(profile: WorkflowProfile, repo_root: Path | None = None) -> Path:
    root = repo_root or _find_repo_root()
    path = root / "cogames-rl-researcher" / "prompts" / f"run-{profile}-workflow.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path


def agent_command(agent: AgentName) -> list[str]:
    return AGENT_COMMANDS[agent]


def report_path_for_profile(profile: WorkflowProfile, repo_root: Path | None = None) -> Path:
    root = repo_root or _find_repo_root()
    return root / "artifacts" / "ai_researcher" / f"{profile}_workflow_report.md"


def _run_agent_prompt(prompt_text: str, agent: AgentName, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        agent_command(agent),
        input=prompt_text,
        cwd=cwd,
        capture_output=False,
        text=True,
        check=False,
    )


def run_agent_workflow(
    *,
    profile: WorkflowProfile,
    agent: AgentName,
    repo_root: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    root = repo_root or _find_repo_root()
    return _run_agent_prompt(prompt_path_for_profile(profile, repo_root=root).read_text(encoding="utf-8"), agent, root)


def _report_generated(report_path: Path, baseline_mtime: float | None) -> bool:
    if not report_path.exists():
        return False
    if report_path.stat().st_size <= 0:
        return False
    if baseline_mtime is None:
        return True
    return report_path.stat().st_mtime > baseline_mtime


def _deterministic_fallback_script(profile: WorkflowProfile, report_relative_path: Path) -> str:
    report_path_str = report_relative_path.as_posix()
    return f"""set -euo pipefail
mkdir -p artifacts/ai_researcher
TS=$(date +%Y%m%d-%H%M%S)
TS_MODULE=$(echo "$TS" | tr '-' '_')
POLICY_MODULE="{profile}_policy_${{TS_MODULE}}"
POLICY_FILE="${{POLICY_MODULE}}.py"
POLICY_NAME="{profile}-${{TS}}"
CHECKPOINT_DIR="./artifacts/ai_researcher/${{TS}}_tutorial_train"
WORKFLOW_DIR="./artifacts/ai_researcher/${{TS}}_{profile}_workflow"
mkdir -p "$WORKFLOW_DIR"

uv run cogames tutorial make-policy --trainable -o "$POLICY_FILE" | tee "$WORKFLOW_DIR/01_make_policy.log"
uv run cogames tutorial train -m machina_1 \\
  -p "class=${{POLICY_MODULE}}.MyTrainablePolicy" \\
  --steps {2000 if profile == "neophyte" else 3000} \\
  --checkpoints "$CHECKPOINT_DIR" | tee "$WORKFLOW_DIR/02_train.log"

CKPT_FILE=$(find "$CHECKPOINT_DIR" -name 'model_*.pt' | sort | tail -n 1)
if [[ -z "${{CKPT_FILE:-}}" ]]; then
  echo "No checkpoint found in $CHECKPOINT_DIR" >&2
  exit 1
fi

POLICY_SPEC="class=${{POLICY_MODULE}}.MyTrainablePolicy,data=${{CKPT_FILE}}"
STARTUP_LOG="$WORKFLOW_DIR/03_startup.log"
set +e
uv run ./cogames-rl-researcher/scripts/run_ai_researcher_startup.py \\
  --policy "$POLICY_SPEC" \\
  --policy-name "$POLICY_NAME" \\
  --season beta-cvc \\
  --researcher-profile {profile} | tee "$STARTUP_LOG"
STARTUP_EXIT=${{PIPESTATUS[0]}}
set -e

uv run cogames submissions --season beta-cvc --policy "$POLICY_NAME" --json \\
  > "$WORKFLOW_DIR/04_submissions.json" || true
uv run cogames leaderboard --season beta-cvc --json > "$WORKFLOW_DIR/05_leaderboard.json" || true

export WORKFLOW_DIR POLICY_NAME POLICY_FILE CKPT_FILE REPORT_PATH="{report_path_str}"
set +e
python - <<'PY'
import json
import os
import re
from pathlib import Path

workflow_dir = Path(os.environ["WORKFLOW_DIR"])
policy_name = os.environ["POLICY_NAME"]
policy_file = os.environ["POLICY_FILE"]
checkpoint_file = os.environ["CKPT_FILE"]
report_path = Path(os.environ["REPORT_PATH"])

startup_log = workflow_dir / "03_startup.log"
startup_text = startup_log.read_text(encoding="utf-8") if startup_log.exists() else ""

def _extract(key: str) -> str:
    match = re.search(rf"^{{key}}=(.*)$", startup_text, re.MULTILINE)
    return match.group(1).strip() if match else ""

startup_run_dir = _extract("run_dir")
startup_status = _extract("status")
gates_status = _extract("gates_status")

submissions_path = workflow_dir / "04_submissions.json"
submissions_snippet = submissions_path.read_text(encoding="utf-8").strip() if submissions_path.exists() else ""

leaderboard_path = workflow_dir / "05_leaderboard.json"
leaderboard_entries: list[dict] = []
if leaderboard_path.exists():
    try:
        payload = json.loads(leaderboard_path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            leaderboard_entries = [entry for entry in payload if isinstance(entry, dict)]
    except json.JSONDecodeError:
        leaderboard_entries = []

leaderboard_has_policy = False
leaderboard_policy_rank = None
for entry in leaderboard_entries:
    policy = entry.get("policy")
    if isinstance(policy, dict) and policy.get("name") == policy_name:
        leaderboard_has_policy = True
        leaderboard_policy_rank = entry.get("rank")
        break

lines = [
    "# Workflow Report",
    "",
    "## Tutorial Summary",
    "- `01_MAKE_POLICY`: scaffold scripted/trainable policy templates.",
    "- `02_TRAIN`: train a policy, then use checkpoint weights.",
    "- `03_SUBMIT`: upload/submit policy and inspect submissions + leaderboard.",
    "",
    "## Artifacts",
    f"- policy_file: `{{policy_file}}`",
    f"- checkpoint_file: `{{checkpoint_file}}`",
    f"- startup_run_dir: `{{startup_run_dir}}`",
    f"- startup_status: `{{startup_status}}`",
    f"- gates_status: `{{gates_status}}`",
    "",
    "## Submission Evidence",
    f"- submissions_output: `{{submissions_snippet[:400]}}`",
    f"- leaderboard_has_policy: `{{leaderboard_has_policy}}`",
    f"- leaderboard_policy_rank: `{{leaderboard_policy_rank}}`",
]

report_path.parent.mkdir(parents=True, exist_ok=True)
report_path.write_text("\\n".join(lines) + "\\n", encoding="utf-8")
PY
REPORT_EXIT=${{?}}
set -e
if [[ "$REPORT_EXIT" -ne 0 ]]; then
  echo "Report generation failed (exit $REPORT_EXIT), preserving startup exit $STARTUP_EXIT" >&2
fi

exit "$STARTUP_EXIT"
"""


def run_agent_workflow_until_report(
    *,
    profile: WorkflowProfile,
    agent: AgentName,
    repo_root: Path | None = None,
    max_attempts: int = 3,
) -> int:
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    root = repo_root or _find_repo_root()
    prompt_path = prompt_path_for_profile(profile, repo_root=root)
    prompt_text = prompt_path.read_text(encoding="utf-8")
    report_path = report_path_for_profile(profile, repo_root=root)
    baseline_mtime = report_path.stat().st_mtime if report_path.exists() else None

    result = run_agent_workflow(profile=profile, agent=agent, repo_root=root)
    if _report_generated(report_path, baseline_mtime):
        return 0

    for attempt in range(2, max_attempts + 1):
        relative_report = report_path.relative_to(root)
        continuation_prompt = (
            "Continue the same workflow from current repo state.\n"
            f"The required report `{relative_report}` was not produced yet.\n"
            "Execute the remaining shell commands now and finish by writing that report."
        )
        prompt = f"{prompt_text}\n\n{continuation_prompt}"
        print(f"Retrying workflow ({attempt}/{max_attempts})...")
        result = _run_agent_prompt(prompt, agent, root)
        if _report_generated(report_path, baseline_mtime):
            return 0

    print("Agent attempts exhausted without report; running deterministic fallback workflow...")
    fallback = subprocess.run(
        ["bash", "-lc", _deterministic_fallback_script(profile, report_path.relative_to(root))],
        cwd=root,
        capture_output=False,
        text=True,
        check=False,
    )
    if _report_generated(report_path, baseline_mtime):
        return 0
    if fallback.returncode != 0:
        return fallback.returncode

    return result.returncode if result.returncode != 0 else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run AI researcher workflow prompt through Codex or Claude")
    parser.add_argument("--profile", choices=["neophyte", "experienced"], default="neophyte")
    parser.add_argument("--agent", choices=["codex", "claude"], default="codex")
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=3,
        help="Max agent attempts (first run + retries) before failing if the report artifact is missing.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print selected prompt path and agent command without running",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    repo_root = _find_repo_root()
    prompt_path = prompt_path_for_profile(args.profile, repo_root=repo_root)
    command = agent_command(args.agent)

    if args.dry_run:
        print(f"repo_root={repo_root}")
        print(f"profile={args.profile}")
        print(f"prompt={prompt_path}")
        print(f"command={' '.join(command)}")
        print(f"report={report_path_for_profile(args.profile, repo_root=repo_root)}")
        print(f"max_attempts={args.max_attempts}")
        return 0

    print(f"Running {args.agent} with {args.profile} workflow prompt: {prompt_path}")
    return run_agent_workflow_until_report(
        profile=args.profile,
        agent=args.agent,
        repo_root=repo_root,
        max_attempts=args.max_attempts,
    )


if __name__ == "__main__":
    raise SystemExit(main())
