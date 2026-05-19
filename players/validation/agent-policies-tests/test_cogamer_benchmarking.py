from __future__ import annotations

import json

from policies.cyborg.cogamer.cvc.benchmarking import (
    compare_learning_runs,
    discover_learning_files,
    summarize_learning_file,
)


def test_summarize_learning_file_extracts_current_cogamer_metrics(tmp_path):
    learning_file = tmp_path / "run.json"
    learning_file.write_text(
        json.dumps(
            {
                "game_id": "run",
                "llm_log": [
                    {
                        "step": 10,
                        "agent": 0,
                        "latency_ms": 1200,
                        "metrics_snapshot": {"heart_total": 1},
                    },
                    {"step": 20, "agent": 0, "error": "rate limited"},
                ],
                "snapshots": [
                    {
                        "step": 0,
                        "agent_id": 0,
                        "inventory": {"heart": 0},
                        "team_resources": {
                            "carbon": 1,
                            "oxygen": 0,
                            "germanium": 0,
                            "silicon": 0,
                        },
                        "junctions": {"friendly": 0, "neutral": 3, "enemy": 1},
                        "stalled": False,
                        "objective": "resource_coverage",
                    },
                    {
                        "step": 10,
                        "agent_id": 0,
                        "inventory": {"heart": 1},
                        "team_resources": {
                            "carbon": 2,
                            "oxygen": 1,
                            "germanium": 0,
                            "silicon": 0,
                        },
                        "junctions": {"friendly": 2, "neutral": 1, "enemy": 1},
                        "stalled": True,
                        "objective": "economy_bootstrap",
                    },
                    {
                        "step": 20,
                        "agent_id": 0,
                        "inventory": {"heart": 2},
                        "team_resources": {
                            "carbon": 2,
                            "oxygen": 1,
                            "germanium": 1,
                            "silicon": 0,
                        },
                        "junctions": {"friendly": 3, "neutral": 1, "enemy": 0},
                        "oscillating": True,
                        "objective": "aligner_pressure",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    summary = summarize_learning_file(learning_file)

    assert summary.game_id == "run"
    assert summary.total_steps == 20
    assert summary.agents == 1
    assert summary.llm_count == 2
    assert summary.llm_errors == 1
    assert summary.final_hearts == 2
    assert summary.final_resource_units == 4
    assert summary.resource_types_seen_final == 3
    assert summary.peak_friendly_junctions == 3
    assert summary.stagnation.total_stalled_steps == 11
    assert summary.stagnation.stalls_by_objective["economy_bootstrap"] == 10
    assert summary.stagnation.stalls_by_objective["aligner_pressure"] == 1


def test_compare_learning_runs_exposes_per_objective_stall_metrics(tmp_path):
    for index, stalled in enumerate((False, True, True)):
        (tmp_path / f"run-{index}.json").write_text(
            json.dumps(
                {
                    "game_id": f"run-{index}",
                    "llm_log": [],
                    "snapshots": [
                        {
                            "step": 0,
                            "agent_id": 0,
                            "team_resources": {
                                "carbon": index,
                                "oxygen": 0,
                                "germanium": 0,
                                "silicon": 0,
                            },
                            "junctions": {"friendly": index, "neutral": 0, "enemy": 0},
                            "stalled": stalled,
                            "objective": "resource_coverage",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

    files = discover_learning_files(tmp_path)
    metrics = compare_learning_runs(files)

    assert len(files) == 3
    assert metrics["stall_steps_resource_coverage"].mean == 2 / 3
    assert metrics["peak_friendly_junctions"].mean == 1
