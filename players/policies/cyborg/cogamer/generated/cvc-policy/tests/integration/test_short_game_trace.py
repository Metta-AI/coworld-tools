"""Run a short game via the softmax CLI and verify trace output."""

from __future__ import annotations

import glob
import json
import os
import subprocess

import pytest

pytestmark = [
    pytest.mark.llm,
    pytest.mark.skipif(
        not os.environ.get("ANTHROPIC_API_KEY"),
        reason="ANTHROPIC_API_KEY not set",
    ),
    pytest.mark.timeout(300),
]


def test_short_game_produces_trace(tmp_path):
    """Run 600 steps (enough for one LLM call at step 500) and check trace."""
    trace_dir = str(tmp_path / "trace")
    os.makedirs(trace_dir, exist_ok=True)

    env = os.environ.copy()
    env["CVC_TRACE_DIR"] = trace_dir

    result = subprocess.run(
        [
            "softmax", "cogames", "play",
            "-m", "machina_1",
            "-p", "class=cvc_policy.cogamer_policy.CvCPolicy",
            "--render=log",
            "-s", "600",
        ],
        capture_output=True,
        text=True,
        timeout=300,
        env=env,
    )
    assert result.returncode == 0, f"Game failed: {result.stderr[-500:]}"

    trace_files = glob.glob(os.path.join(trace_dir, "*.json"))
    assert len(trace_files) > 0, "No trace files produced"

    trace = json.loads(open(trace_files[0]).read())
    assert "agents" in trace
    assert "llm_trace" in trace
    assert len(trace["agents"]) == 8

    # At 600 steps, LLM should have fired at step 500
    assert len(trace["llm_trace"]) > 0, "No LLM calls recorded in trace"

    agents_with_bias = [
        a for a in trace["agents"].values()
        if a["final_resource_bias"] is not None
    ]
    assert len(agents_with_bias) > 0, (
        "No agents received resource_bias from LLM — parse pipeline is broken"
    )
