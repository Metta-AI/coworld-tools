from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


GUIDE_ROOT = Path(__file__).resolve().parents[1] / "testbed" / "guide_v1"
sys.path.insert(0, str(GUIDE_ROOT))

from guide_v1.contracts import GUIDE_CONTRACT_SCHEMA_VERSION, write_guide_contract  # noqa: E402
from guide_v1.framework import AgentFrameworkRef  # noqa: E402
from guide_v1 import pipeline as guide_pipeline  # noqa: E402


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
        name="cyborg",
        framework_dir=framework_dir,
        package="cogames_agents.cyborg",
        package_source_root=package_source_root,
    )
