from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

from cogames_agents.eval_result_metrics import extract_cogsguard_eval_metrics, parse_eval_result_text


def _load_script_module(script_name: str):
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    script_path = scripts_dir / script_name
    spec = importlib.util.spec_from_file_location(script_name.replace(".py", ""), script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_script_without_site(script_name: str, *args: str) -> subprocess.CompletedProcess[str]:
    agents_dir = Path(__file__).resolve().parents[1]
    return subprocess.run(
        [sys.executable, "-S", f"scripts/{script_name}", *args],
        cwd=agents_dir,
        text=True,
        capture_output=True,
        check=False,
    )


def _write_fake_uv(tmp_path: Path) -> tuple[Path, Path]:
    log_path = tmp_path / "uv.log"
    fake_uv = tmp_path / "uv"
    fake_uv.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            printf '%s\\n' "$*" >> "${FAKE_UV_LOG:?}"
            if [[ "$1" != "run" ]]; then
              echo "expected uv run" >&2
              exit 1
            fi
            shift
            if [[ "$1" != "--project" ]]; then
              echo "expected --project" >&2
              exit 1
            fi
            shift 2
            if [[ "$1" == "cogames" && "$2" == "scrimmage" ]]; then
              cat "${FAKE_COGAMES_JSON:?}"
              exit 0
            fi
            if [[ "$1" == "python" ]]; then
              exit 0
            fi
            echo "unexpected uv invocation: $*" >&2
            exit 1
            """
        )
    )
    fake_uv.chmod(0o755)
    return fake_uv, log_path


def _run_shell_wrapper_from_random_cwd(script_name: str, *args: str) -> tuple[subprocess.CompletedProcess[str], str]:
    agents_dir = Path(__file__).resolve().parents[1]
    script_path = agents_dir / "scripts" / script_name
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        fake_uv, log_path = _write_fake_uv(tmp_path)
        fake_result = tmp_path / "result.json"
        fake_result.write_text(json.dumps(_modern_result()))
        env = os.environ.copy()
        env["PATH"] = f"{tmp_path}:{env['PATH']}"
        env["FAKE_UV_LOG"] = str(log_path)
        env["FAKE_COGAMES_JSON"] = str(fake_result)
        result = subprocess.run(
            ["bash", str(script_path), *args],
            cwd=tmp_path,
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )
        return result, log_path.read_text()


def _modern_result() -> dict:
    return {
        "missions": [
            {
                "mission_name": "cogsguard_machina_1.basic",
                "mission_summary": {
                    "episodes": 2,
                    "policy_summaries": [
                        {
                            "agent_count": 8,
                            "avg_agent_metrics": {
                                "heart.gained": 2.0,
                                "heart.lost": 1.0,
                            },
                            "action_timeouts": 3,
                        }
                    ],
                    "avg_game_stats": {
                        "cogs/aligned.junction.held": 150.0,
                        "cogs/aligned.junction.gained": 4.0,
                    },
                    "per_episode_per_policy_avg_rewards": {
                        "0": [1.0],
                        "1": [3.0],
                    },
                },
            }
        ]
    }


def test_extract_cogsguard_eval_metrics_modern_schema() -> None:
    metrics = extract_cogsguard_eval_metrics(_modern_result())

    assert metrics == {
        "aligned.junction.held": 150.0,
        "aligned.junction.gained": 4.0,
        "heart.gained": 2.0,
        "heart.lost": 1.0,
        "reward": 2.0,
        "action_timeouts": 3.0,
    }


def test_extract_cogsguard_eval_metrics_uses_current_cogs_junction_keys() -> None:
    result = {
        "missions": [
            {
                "mission_summary": {
                    "policy_summaries": [
                        {
                            "avg_agent_metrics": {
                                "heart.gained": 5.0,
                                "heart.lost": 2.0,
                                "reward": 7.0,
                            },
                            "action_timeouts": 0,
                        }
                    ],
                    "avg_game_stats": {
                        "junction.held": 12.0,
                        "junction.gained": 3.0,
                    },
                    "per_episode_per_policy_avg_rewards": {},
                }
            }
        ]
    }

    metrics = extract_cogsguard_eval_metrics(result)

    assert metrics["aligned.junction.held"] == 0.0
    assert metrics["aligned.junction.gained"] == 0.0
    assert metrics["reward"] == 7.0


def test_compare_agents_extracts_aligned_metrics() -> None:
    module = _load_script_module("compare_agents.py")

    metrics = module.extract_metrics(_modern_result())

    assert metrics["aligned.junction.held"] == 150.0
    assert metrics["aligned.junction.gained"] == 4.0
    assert metrics["reward"] == 2.0


def test_regression_check_extracts_aligned_metrics() -> None:
    module = _load_script_module("regression_check.py")

    metrics = module.extract_metrics(_modern_result())

    assert metrics["aligned.junction.held"] == 150.0
    assert metrics["aligned.junction.gained"] == 4.0
    assert metrics["action_timeouts"] == 3.0


def test_compare_agents_runs_as_standalone_script_without_install() -> None:
    result = _run_script_without_site("compare_agents.py", "--help")

    assert result.returncode == 0, result.stderr
    assert "Compare cogames run results." in result.stdout


def test_regression_check_runs_as_standalone_script_without_install() -> None:
    result = _run_script_without_site("regression_check.py", "--help")

    assert result.returncode == 0, result.stderr
    assert "Compare current eval results against baseline" in result.stdout


def test_eval_cogas_runs_from_random_cwd_with_project_pinned_uv() -> None:
    result, uv_log = _run_shell_wrapper_from_random_cwd(
        "eval_cogas.sh",
        "--policy",
        "role",
        "--mission",
        "arena",
        "--episodes",
        "1",
        "--steps",
        "5",
        "--threshold",
        "0",
    )

    assert result.returncode == 0, result.stderr
    assert "--project" in uv_log
    assert str(Path(__file__).resolve().parents[1]) in uv_log


def test_ci_eval_runs_from_random_cwd_with_project_pinned_uv() -> None:
    result, uv_log = _run_shell_wrapper_from_random_cwd(
        "ci_eval.sh",
        "--policy",
        "role",
        "--mission",
        "arena",
        "--episodes",
        "1",
        "--steps",
        "5",
        "--label",
        "random-cwd-smoke",
        "--skip-log",
    )

    assert result.returncode == 0, result.stderr
    assert "--project" in uv_log
    assert str(Path(__file__).resolve().parents[1]) in uv_log


def test_parse_eval_result_text_handles_scrimmage_preamble() -> None:
    raw = 'Preparing evaluation for 1 policies across 1 mission(s)\nSimulating (machina_1)\n{"missions": []}\n'

    parsed = parse_eval_result_text(raw)

    assert parsed == {"missions": []}


def test_extract_cogsguard_eval_metrics_defaults_missing_junction_stats_to_zero() -> None:
    result = {
        "missions": [
            {
                "mission_summary": {
                    "policy_summaries": [
                        {
                            "avg_agent_metrics": {},
                            "action_timeouts": 0,
                        }
                    ],
                    "avg_game_stats": {
                        "cogs/heart.withdrawn": 2.0,
                    },
                    "per_episode_per_policy_avg_rewards": {"0": [0.5]},
                }
            }
        ]
    }

    metrics = extract_cogsguard_eval_metrics(result)

    assert metrics["aligned.junction.held"] == 0.0
    assert metrics["aligned.junction.gained"] == 0.0
