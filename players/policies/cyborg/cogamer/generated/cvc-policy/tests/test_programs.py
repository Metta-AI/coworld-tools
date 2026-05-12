"""Unit tests for pure functions in cvc.programs: _build_analysis_prompt and _parse_analysis."""

from __future__ import annotations

import json

import pytest

from cvc_policy.programs import _build_analysis_prompt, _parse_analysis

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context(**overrides) -> dict:
    """Return a minimal valid context dict for _build_analysis_prompt.

    Mirrors the shape produced by ``_summarize`` in ``programs.py``.
    """
    base = {
        "step": 500,
        "agent_id": "a0",
        "hp": 80,
        "inventory": {"heart": 3, "carbon": 2},
        "team_resources": {"carbon": 10, "oxygen": 5, "germanium": 0, "silicon": 3},
        "has_gear": True,
        "roles": "miner=4, aligner=2, scrambler=2",
        "position": (22, 44),
        "junctions": {"friendly": 3, "enemy": 5, "neutral": 2},
        "stalled": False,
        "oscillating": False,
        "safe_distance": 12,
        "role": "miner",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# _build_analysis_prompt
# ---------------------------------------------------------------------------


class TestBuildAnalysisPrompt:
    """Tests for _build_analysis_prompt."""

    def test_includes_step_info(self):
        prompt = _build_analysis_prompt(_make_context(step=1234))
        assert "1234" in prompt
        assert "10000" in prompt

    def test_includes_agent_id_and_hp(self):
        prompt = _build_analysis_prompt(_make_context(agent_id="a7", hp=42))
        assert "a7" in prompt
        assert "HP=42" in prompt

    def test_includes_hearts(self):
        prompt = _build_analysis_prompt(_make_context(inventory={"heart": 5}))
        assert "Hearts=5" in prompt

    def test_includes_role(self):
        prompt = _build_analysis_prompt(_make_context(role="aligner"))
        assert "Role=aligner" in prompt

    def test_includes_position(self):
        prompt = _build_analysis_prompt(_make_context(position=(10, 20)))
        assert "(10, 20)" in prompt

    def test_includes_gear_flag(self):
        prompt = _build_analysis_prompt(_make_context(has_gear=True))
        assert "Has role gear: True" in prompt
        prompt2 = _build_analysis_prompt(_make_context(has_gear=False))
        assert "Has role gear: False" in prompt2

    def test_includes_resources(self):
        res = {"carbon": 100, "oxygen": 50, "germanium": 0, "silicon": 25}
        prompt = _build_analysis_prompt(_make_context(team_resources=res))
        assert "carbon=100" in prompt

    def test_includes_team_roles(self):
        prompt = _build_analysis_prompt(_make_context(roles="miner=4, aligner=2, scrambler=2"))
        assert "miner=4" in prompt

    def test_includes_junction_counts(self):
        prompt = _build_analysis_prompt(_make_context(junctions={"friendly": 7, "enemy": 3, "neutral": 0}))
        assert "friendly=7" in prompt
        assert "enemy=3" in prompt
        assert "neutral=0" in prompt

    def test_includes_stalled_and_oscillating(self):
        prompt = _build_analysis_prompt(_make_context(stalled=True, oscillating=True))
        assert "Stalled: True" in prompt
        assert "Oscillating: True" in prompt

    def test_includes_safe_distance(self):
        prompt = _build_analysis_prompt(_make_context(safe_distance=30))
        assert "30" in prompt

    def test_includes_json_schema(self):
        prompt = _build_analysis_prompt(_make_context())
        assert "resource_bias" in prompt
        assert "role" in prompt
        assert "objective" in prompt
        assert "analysis" in prompt

    def test_includes_valid_resource_bias_options(self):
        prompt = _build_analysis_prompt(_make_context())
        for element in ("carbon", "oxygen", "germanium", "silicon"):
            assert element in prompt

    def test_includes_valid_role_options(self):
        prompt = _build_analysis_prompt(_make_context())
        for role in ("miner", "aligner", "scrambler"):
            assert role in prompt

    def test_includes_valid_objective_options(self):
        prompt = _build_analysis_prompt(_make_context())
        for obj in ("expand", "defend", "economy_bootstrap"):
            assert obj in prompt

    def test_returns_string(self):
        result = _build_analysis_prompt(_make_context())
        assert isinstance(result, str)

    def test_missing_optional_keys_default_gracefully(self):
        """Context missing optional keys uses defaults."""
        ctx = _make_context()
        del ctx["role"]
        del ctx["position"]
        del ctx["stalled"]
        del ctx["oscillating"]
        del ctx["safe_distance"]
        del ctx["has_gear"]
        del ctx["inventory"]
        del ctx["team_resources"]
        prompt = _build_analysis_prompt(ctx)
        assert "unknown" in prompt
        assert isinstance(prompt, str)


# ---------------------------------------------------------------------------
# _parse_analysis
# ---------------------------------------------------------------------------


class TestParseAnalysis:
    """Tests for _parse_analysis."""

    def test_valid_json_all_fields(self):
        text = json.dumps(
            {
                "resource_bias": "carbon",
                "role": "aligner",
                "objective": "expand",
                "analysis": "We need more junctions.",
            }
        )
        result = _parse_analysis(text)
        assert result["resource_bias"] == "carbon"
        assert result["role"] == "aligner"
        assert result["objective"] == "expand"
        assert result["analysis"] == "We need more junctions."

    @pytest.mark.parametrize("element", ["carbon", "oxygen", "germanium", "silicon"])
    def test_valid_resource_bias_values(self, element):
        text = json.dumps({"resource_bias": element, "analysis": "ok"})
        result = _parse_analysis(text)
        assert result["resource_bias"] == element

    def test_invalid_resource_bias_excluded(self):
        text = json.dumps({"resource_bias": "gold", "analysis": "ok"})
        result = _parse_analysis(text)
        assert "resource_bias" not in result

    @pytest.mark.parametrize("role", ["miner", "aligner", "scrambler"])
    def test_valid_role_values(self, role):
        text = json.dumps({"role": role, "analysis": "ok"})
        result = _parse_analysis(text)
        assert result["role"] == role

    def test_null_role_not_included(self):
        """role=null in JSON means 'keep current', should not appear in result."""
        text = json.dumps({"role": None, "analysis": "ok"})
        result = _parse_analysis(text)
        assert "role" not in result

    def test_invalid_role_excluded(self):
        text = json.dumps({"role": "healer", "analysis": "ok"})
        result = _parse_analysis(text)
        assert "role" not in result

    @pytest.mark.parametrize("objective", ["expand", "defend", "economy_bootstrap"])
    def test_valid_objective_values(self, objective):
        text = json.dumps({"objective": objective, "analysis": "ok"})
        result = _parse_analysis(text)
        assert result["objective"] == objective

    def test_null_objective_not_included(self):
        text = json.dumps({"objective": None, "analysis": "ok"})
        result = _parse_analysis(text)
        assert "objective" not in result

    def test_invalid_objective_excluded(self):
        text = json.dumps({"objective": "attack", "analysis": "ok"})
        result = _parse_analysis(text)
        assert "objective" not in result

    def test_invalid_json_returns_truncated_text(self):
        text = "This is not JSON at all, just plain text analysis."
        result = _parse_analysis(text)
        assert "analysis" in result
        assert result["analysis"] == text[:100]
        assert "resource_bias" not in result
        assert "role" not in result
        assert "objective" not in result

    def test_invalid_json_truncates_long_text(self):
        text = "x" * 200
        result = _parse_analysis(text)
        assert len(result["analysis"]) == 100

    def test_empty_string(self):
        result = _parse_analysis("")
        assert result["analysis"] == ""
        assert "resource_bias" not in result

    def test_partial_valid_fields(self):
        """Only valid fields are extracted; invalid ones are ignored."""
        text = json.dumps(
            {
                "resource_bias": "carbon",
                "role": "invalid_role",
                "objective": "expand",
                "analysis": "partial test",
            }
        )
        result = _parse_analysis(text)
        assert result["resource_bias"] == "carbon"
        assert "role" not in result
        assert result["objective"] == "expand"
        assert result["analysis"] == "partial test"

    def test_json_missing_analysis_field(self):
        """When 'analysis' key is absent from JSON, falls back to text[:100]."""
        text = json.dumps({"resource_bias": "oxygen"})
        result = _parse_analysis(text)
        assert result["resource_bias"] == "oxygen"
        assert result["analysis"] == text[:100]

    def test_json_array_instead_of_object(self):
        """A JSON array is valid JSON but not a dict -- treated as parse failure."""
        text = json.dumps([1, 2, 3])
        result = _parse_analysis(text)
        # json.loads succeeds but isinstance check fails, so only truncated text
        assert result["analysis"] == text[:100]
        assert "resource_bias" not in result

    def test_extra_fields_ignored(self):
        """Extra unexpected fields in JSON don't cause errors."""
        text = json.dumps(
            {
                "resource_bias": "silicon",
                "role": "miner",
                "objective": "defend",
                "analysis": "all good",
                "extra_field": 42,
                "another": "value",
            }
        )
        result = _parse_analysis(text)
        assert result["resource_bias"] == "silicon"
        assert result["role"] == "miner"
        assert result["objective"] == "defend"
        assert result["analysis"] == "all good"
        assert "extra_field" not in result
        assert "another" not in result

    def test_empty_json_object(self):
        text = json.dumps({})
        result = _parse_analysis(text)
        assert "analysis" in result
        assert result["analysis"] == text[:100]
        assert "resource_bias" not in result

    def test_resource_bias_empty_string(self):
        text = json.dumps({"resource_bias": "", "analysis": "ok"})
        result = _parse_analysis(text)
        assert "resource_bias" not in result

    def test_returns_dict(self):
        result = _parse_analysis("anything")
        assert isinstance(result, dict)

    def test_fenced_json(self):
        """JSON wrapped in ```json ... ``` fences is extracted."""
        text = '```json\n{"resource_bias": "germanium", "role": null, "objective": "expand", "analysis": "Need more junctions."}\n```'
        result = _parse_analysis(text)
        assert result["resource_bias"] == "germanium"
        assert result["objective"] == "expand"
        assert "role" not in result

    def test_fenced_json_with_leading_text(self):
        """Text before fenced JSON block is ignored."""
        text = 'Looking at the game state:\n\n- Resources are low\n\n```json\n{"resource_bias": "silicon", "role": "miner", "objective": "economy_bootstrap", "analysis": "Need miners."}\n```'
        result = _parse_analysis(text)
        assert result["resource_bias"] == "silicon"
        assert result["role"] == "miner"
        assert result["objective"] == "economy_bootstrap"

    def test_fenced_json_pretty_printed(self):
        """Pretty-printed JSON inside fences is extracted."""
        text = '```json\n{\n  "resource_bias": "oxygen",\n  "role": null,\n  "objective": "defend",\n  "analysis": "Hold junctions."\n}\n```'
        result = _parse_analysis(text)
        assert result["resource_bias"] == "oxygen"
        assert result["objective"] == "defend"

    def test_json_embedded_in_text(self):
        """JSON object embedded in prose (no fences) is extracted."""
        text = 'The best strategy is: {"resource_bias": "carbon", "role": "aligner", "objective": "expand", "analysis": "Go expand."} based on the data.'
        result = _parse_analysis(text)
        assert result["resource_bias"] == "carbon"
        assert result["role"] == "aligner"

    def test_truncated_fenced_json(self):
        """Truncated response with incomplete JSON fails gracefully."""
        text = '```json\n{"resource_bias": "silicon", "role": null, "objective": "defend", "analysis": "Junction dominance requires'
        result = _parse_analysis(text)
        assert isinstance(result, dict)
        assert "resource_bias" not in result
