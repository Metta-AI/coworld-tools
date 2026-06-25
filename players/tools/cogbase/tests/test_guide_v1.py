from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


GUIDE_ROOT = Path(__file__).resolve().parents[1] / "testbed" / "guide_v1"
sys.path.insert(0, str(GUIDE_ROOT))

from guide_v1.claude_env import bedrock_subprocess_env  # noqa: E402
from guide_v1.contracts import GUIDE_CONTRACT_SCHEMA_VERSION, write_guide_contract  # noqa: E402
from guide_v1.framework import AgentFrameworkRef  # noqa: E402
from guide_v1 import pipeline as guide_pipeline  # noqa: E402
from guide_v1 import prompts as guide_prompts  # noqa: E402
from guide_v1.documents import get_document  # noqa: E402
from guide_v1.sidecar import DOC_CONTRACT_SCHEMA_VERSION  # noqa: E402


def test_bedrock_subprocess_env_forces_bedrock_and_strips_conflicting_auth() -> None:
    base = {
        "PATH": "/usr/bin",
        "AWS_REGION": "us-east-1",
        "ANTHROPIC_API_KEY": "sk-leak",
        "ANTHROPIC_AUTH_TOKEN": "leak-token",
        "CLAUDE_CODE_USE_VERTEX": "1",
    }

    env = bedrock_subprocess_env(base)

    assert env["CLAUDE_CODE_USE_BEDROCK"] == "1"
    assert env["AWS_REGION"] == "us-east-1"
    assert env["PATH"] == "/usr/bin"
    assert "ANTHROPIC_API_KEY" not in env
    assert "ANTHROPIC_AUTH_TOKEN" not in env
    assert "CLAUDE_CODE_USE_VERTEX" not in env
    # The cmux claude wrapper strips provider-selection vars unless these
    # opt-outs are present; the env must keep CLAUDE_CODE_USE_BEDROCK alive
    # through the wrapper so the child process actually routes to Bedrock.
    assert env["CMUX_PRESERVE_CLAUDE_AUTH_SELECTION_ENV"] == "1"
    preserved = set(env["CMUX_PRESERVE_CLAUDE_AUTH_SELECTION_ENV_KEYS"].split(","))
    assert "CLAUDE_CODE_USE_BEDROCK" in preserved
    # The input mapping must not be mutated.
    assert base["ANTHROPIC_API_KEY"] == "sk-leak"


def test_write_guide_contract_extracts_machine_readable_action_and_observation_contract(
    tmp_path: Path,
) -> None:
    guide_dir = tmp_path / "among_like"
    guide_dir.mkdir()
    (guide_dir / "INTERFACE_CONTRACT.md").write_text(
        """
# Interface Contract

The `/player` WebSocket sends a binary packed 128x128 4-bit framebuffer of
8192 bytes. Agents send a 2-byte binary WebSocket message:

```
[0x00, mask]
```

| Bit | Constant | Name | Playing Phase | Voting Phase |
|-----|----------|------|---------------|--------------|
| 0 | `ButtonUp` | Up | Move up | Cursor up |
| 1 | `ButtonDown` | Down | Move down | Cursor down |
| 2 | `ButtonLeft` | Left | Move left | Cursor up |
| 3 | `ButtonRight` | Right | Move right | Cursor down |
| 5 | `ButtonA` | A (attack) | Report / Kill | Confirm vote |
| 6 | `ButtonB` | B | Vent | unused |
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (guide_dir / "OBSERVATION_DECODING.md").write_text(
        "Decode packed framebuffer pixels before image labeling.\n",
        encoding="utf-8",
    )

    contract_file = write_guide_contract(guide_dir)
    contract = json.loads(contract_file.read_text(encoding="utf-8"))

    assert contract["schema_version"] == GUIDE_CONTRACT_SCHEMA_VERSION
    assert contract["observation"]["surface_category"] == "visual_primary"
    assert contract["observation"]["primary"]["input_kind"] == "raw_visual_observation"
    assert contract["observation"]["primary"]["width"] == 128
    assert contract["observation"]["primary"]["height"] == 128
    assert contract["observation"]["primary"]["byte_length"] == 8192
    assert contract["observation"]["primary"]["bit_depth"] == 4
    assert contract["actions"]["style"] == "binary_button_mask"
    assert contract["actions"]["payload_prefix"] == [0]
    assert contract["actions"]["payloads"]["right"] == 0x08
    assert contract["actions"]["payloads"]["attack"] == 0x20
    assert contract["actions"]["payloads"]["vent"] == 0x40


def test_guide_contract_treats_negated_visual_terms_as_symbolic_evidence(
    tmp_path: Path,
) -> None:
    guide_dir = tmp_path / "paint_like"
    guide_dir.mkdir()
    (guide_dir / "INTERFACE_CONTRACT.md").write_text(
        """
# Interface Contract

The `/player` WebSocket sends JSON observation objects with fields `slot`,
`positions`, `tile_owners`, and `scores`. There is no framebuffer, screenshot,
canvas, image, or pixel payload in the player observation.

The agent sends JSON actions as `{"move": "up"}`. Valid move values are
`"up"`, `"down"`, `"left"`, `"right"`, and `"stay"`.

The `/results` path is an HTTP result file destination, not a player websocket.
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (guide_dir / "OBSERVATION_DECODING.md").write_text(
        "Decode the JSON fields directly. Do not use visual frame decoding.\n",
        encoding="utf-8",
    )
    (guide_dir / "CONNECTION_AND_EPISODE_LIFECYCLE.md").write_text(
        "Connect each player to `/player?slot=<slot>&token=<token>` over WebSocket. "
        "The `/results` URI is written as HTTP/file output after the match.\n",
        encoding="utf-8",
    )

    contract_file = write_guide_contract(guide_dir)
    contract = json.loads(contract_file.read_text(encoding="utf-8"))

    assert contract["observation"]["surface_category"] == "symbolic_primary"
    assert contract["observation"]["primary"]["input_kind"] == "structured_symbolic"
    assert {item["action_id"] for item in contract["actions"]["candidates"]} == {
        "down",
        "left",
        "right",
        "stay",
        "up",
    }
    endpoint_transports = {
        endpoint["path"]: endpoint["transport"]
        for endpoint in contract["runtime"]["endpoints"]
    }
    assert endpoint_transports["/player"] == "websocket"
    assert endpoint_transports["/results"] == "http"


def test_normalize_runner_names_accepts_aliases_and_preserves_selection_order() -> None:
    assert guide_pipeline.normalize_runner_names(None) == ("claude", "codex")
    assert guide_pipeline.normalize_runner_names(["clod"]) == ("claude",)
    assert guide_pipeline.normalize_runner_names(["codec,claude"]) == ("codex", "claude")

    with pytest.raises(ValueError, match="unknown runner"):
        guide_pipeline.normalize_runner_names(["llama"])


def test_single_runner_generation_promotes_draft_and_skips_codex_and_synthesis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    output_dir = tmp_path / "guide"
    framework = _framework_ref(tmp_path)
    calls: list[str] = []

    def fake_claude(*_args: object, output_dir: Path, **_kwargs: object) -> str:
        calls.append("claude")
        draft = output_dir / ".drafts" / "GAME_OVERVIEW" / "claude_draft.md"
        draft.write_text("# Claude overview\n", encoding="utf-8")
        return ""

    def fail_codex(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("Codex should not run when only Claude is selected")

    def fail_synthesizer(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("Synthesizer should not run with one selected runner")

    monkeypatch.setattr(guide_pipeline, "run_claude", fake_claude)
    monkeypatch.setattr(guide_pipeline, "run_codex", fail_codex)
    monkeypatch.setattr(guide_pipeline, "run_synthesizer", fail_synthesizer)

    result = guide_pipeline.run_pipeline(
        source,
        output_dir=output_dir,
        through_stage=1,
        agent_framework=framework,
        runners=("clod",),
        max_parallel=1,
    )

    assert result.ok
    assert calls == ["claude"]
    assert (output_dir / "GAME_OVERVIEW.md").read_text(encoding="utf-8") == "# Claude overview\n"
    assert not (output_dir / ".drafts" / "GAME_OVERVIEW" / "codex_draft.md").exists()


def test_two_runner_generation_runs_synthesizer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    output_dir = tmp_path / "guide"
    framework = _framework_ref(tmp_path)
    calls: list[str] = []

    def fake_claude(*_args: object, output_dir: Path, **_kwargs: object) -> str:
        calls.append("claude")
        draft = output_dir / ".drafts" / "GAME_OVERVIEW" / "claude_draft.md"
        draft.write_text("# Claude draft\n", encoding="utf-8")
        return ""

    def fake_codex(
        *_args: object,
        draft_output_file: Path,
        **_kwargs: object,
    ) -> str:
        calls.append("codex")
        draft_output_file.write_text("# Codex draft\n", encoding="utf-8")
        return ""

    def fake_synthesizer(
        *_args: object,
        output_file: Path,
        **_kwargs: object,
    ) -> str:
        calls.append("synthesizer")
        output_file.write_text("# Synthesized overview\n", encoding="utf-8")
        return ""

    monkeypatch.setattr(guide_pipeline, "run_claude", fake_claude)
    monkeypatch.setattr(guide_pipeline, "run_codex", fake_codex)
    monkeypatch.setattr(guide_pipeline, "run_synthesizer", fake_synthesizer)

    result = guide_pipeline.run_pipeline(
        source,
        output_dir=output_dir,
        through_stage=1,
        agent_framework=framework,
        runners=("claude", "codex"),
        max_parallel=1,
    )

    assert result.ok
    assert calls == ["claude", "codex", "synthesizer"]
    assert (output_dir / "GAME_OVERVIEW.md").read_text(encoding="utf-8") == "# Synthesized overview\n"


def _framework_ref(tmp_path: Path) -> AgentFrameworkRef:
    framework_dir = tmp_path / "framework"
    package_source_root = tmp_path / "src"
    framework_dir.mkdir()
    package_source_root.mkdir()
    return AgentFrameworkRef(
        name="player_sdk",
        framework_dir=framework_dir,
        package="players.player_sdk",
        package_source_root=package_source_root,
    )


def test_summarize_prior_doc_returns_title_and_opening_paragraph(tmp_path: Path) -> None:
    doc = tmp_path / "GAME_OVERVIEW.md"
    doc.write_text(
        "# Sample Game: Overview\n"
        "\n"
        "Sample is a real-time 8-player social deduction game.\n"
        "Players are split into roles and act each tick.\n"
        "\n"
        "## Classification\n"
        "\n"
        "| Dimension | Value |\n"
        "| --- | --- |\n"
        "| Genre | Social deduction |\n",
        encoding="utf-8",
    )

    summary = guide_prompts.summarize_prior_doc(doc)

    assert summary.startswith("# Sample Game: Overview")
    assert "real-time 8-player social deduction" in summary
    # Stops at the next heading — Classification table must not leak in.
    assert "Classification" not in summary
    assert "Genre" not in summary


def test_format_prior_docs_inlines_summary_blocks(tmp_path: Path) -> None:
    output_dir = tmp_path / "guide"
    output_dir.mkdir()
    (output_dir / "GAME_OVERVIEW.md").write_text(
        "# Sample Overview\n\nA tiny social deduction game.\n",
        encoding="utf-8",
    )

    rules_doc = get_document("RULES_AND_MECHANICS")
    formatted = guide_prompts.format_prior_docs(
        rules_doc,
        output_dir,
        frozenset({"GAME_OVERVIEW"}),
    )

    assert "### GAME_OVERVIEW.md" in formatted
    assert f"Path: `{output_dir / 'GAME_OVERVIEW.md'}`" in formatted
    assert "# Sample Overview" in formatted
    assert "A tiny social deduction game." in formatted


def test_guide_contract_prefers_sidecar_actions_over_prose_extraction(tmp_path: Path) -> None:
    guide_dir = tmp_path / "sidecar_game"
    guide_dir.mkdir()
    # Prose alone would extract the wrong action_id table. The sidecar carries
    # the ground-truth wire payloads and must win.
    (guide_dir / "INTERFACE_CONTRACT.md").write_text(
        "# Interface Contract\n"
        "\n"
        "Actions are sent as a 2-byte binary websocket message of the form\n"
        "`[0x00, mask]`.\n"
        "\n"
        "| Index | Name | Input Mask (hex) | Buttons |\n"
        "| --- | --- | --- | --- |\n"
        "| 0 | `noop` | `0x00` | None |\n"
        "| 1 | `a` | `0x20` | A |\n"
        "| 2 | `b` | `0x40` | B |\n"
        "| 6 | `down` | `0x02` | Down |\n",
        encoding="utf-8",
    )
    (guide_dir / "INTERFACE_CONTRACT.contract.json").write_text(
        json.dumps(
            {
                "schema_version": DOC_CONTRACT_SCHEMA_VERSION,
                "document": "INTERFACE_CONTRACT.md",
                "actions": {
                    "style": "binary_button_mask",
                    "default_action": "noop",
                    "requires_message_type": True,
                    "payload_prefix": [0],
                    "payloads": {
                        "noop": 0,
                        "up": 0x01,
                        "down": 0x02,
                        "left": 0x04,
                        "right": 0x08,
                        "attack": 0x20,
                        "b": 0x40,
                    },
                    "candidates": [
                        {
                            "action_id": "attack",
                            "description": "Imposter kill / Crewmate report / vote confirm.",
                            "evidence": [
                                {
                                    "document": "INTERFACE_CONTRACT.md",
                                    "line": 8,
                                    "text": "| 1 | `a` | `0x20` | A |",
                                }
                            ],
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    contract_file = write_guide_contract(guide_dir)
    contract = json.loads(contract_file.read_text(encoding="utf-8"))

    assert contract["actions"]["payloads"]["attack"] == 0x20
    assert contract["actions"]["payloads"]["down"] == 0x02
    assert contract["actions"]["payloads"]["up"] == 0x01
    candidate_ids = {item["action_id"] for item in contract["actions"]["candidates"]}
    assert candidate_ids == {"attack"}
    assert contract["sidecar_sources"]["actions"] == "INTERFACE_CONTRACT.contract.json"


def test_guide_contract_falls_back_when_sidecar_is_missing_or_malformed(tmp_path: Path) -> None:
    guide_dir = tmp_path / "no_sidecar"
    guide_dir.mkdir()
    (guide_dir / "INTERFACE_CONTRACT.md").write_text(
        "# Interface Contract\n"
        "\n"
        "Players send JSON actions `{\"move\": \"up\"}`. Valid values are\n"
        "`\"up\"`, `\"down\"`, `\"left\"`, `\"right\"`, `\"stay\"`.\n",
        encoding="utf-8",
    )
    # Wrong schema version: must be ignored, prose extraction wins.
    (guide_dir / "INTERFACE_CONTRACT.contract.json").write_text(
        json.dumps({"schema_version": "not-a-real-version", "actions": {"style": "broken"}}),
        encoding="utf-8",
    )

    contract = json.loads(write_guide_contract(guide_dir).read_text(encoding="utf-8"))

    assert contract["actions"]["style"] != "broken"
    assert "sidecar_sources" not in contract
