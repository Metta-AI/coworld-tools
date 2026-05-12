"""Verify the full LLM prompt -> response -> parse pipeline."""

from __future__ import annotations

import os

import pytest

pytestmark = [
    pytest.mark.llm,
    pytest.mark.skipif(
        not os.environ.get("ANTHROPIC_API_KEY"),
        reason="ANTHROPIC_API_KEY not set",
    ),
    pytest.mark.timeout(300),
]


def test_llm_response_parses_successfully():
    """Send the actual prompt to the LLM and confirm _parse_analysis extracts fields."""
    import anthropic

    from cvc_policy.programs import _build_analysis_prompt, _parse_analysis

    ctx = {
        "step": 500,
        "agent_id": "0",
        "hp": 100,
        "inventory": {"heart": 2, "carbon": 5},
        "team_resources": {"carbon": 200, "oxygen": 150, "germanium": 50, "silicon": 100},
        "has_gear": True,
        "roles": "miner=3, aligner=3, scrambler=2",
        "position": (-10, 15),
        "junctions": {"friendly": 5, "enemy": 3, "neutral": 2},
        "stalled": False,
        "oscillating": False,
        "safe_distance": 20,
        "role": "miner",
    }
    prompt = _build_analysis_prompt(ctx)

    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.content[0].text
    parsed = _parse_analysis(text)

    assert "resource_bias" in parsed, f"Failed to parse resource_bias from: {text}"
    assert parsed["resource_bias"] in ("carbon", "oxygen", "germanium", "silicon")
    assert "analysis" in parsed
    assert len(parsed["analysis"]) > 0
