from __future__ import annotations

import asyncio
import base64
import importlib.util
import json
import struct
import sys
import types
from pathlib import Path

import pytest
import websockets


MAKER_ROOT = Path(__file__).resolve().parents[1] / "testbed" / "maker_v1"
sys.path.insert(0, str(MAKER_ROOT))

ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADgwGJ"
    "lK3Q6wAAAABJRU5ErkJggg=="
)

from maker_v1.build_plan import MakerError, generate_plan  # noqa: E402
from maker_v1.bootstrap import BootstrapError, run_visual_bootstrap  # noqa: E402
from maker_v1.cli import main as maker_main  # noqa: E402
from maker_v1.framework import AgentFrameworkRef  # noqa: E402
from maker_v1 import framework as maker_framework  # noqa: E402
from maker_v1.policy_builder import build_policy_from_labels  # noqa: E402
from maker_v1.smoke import run_smoke_test  # noqa: E402
from maker_v1.vlm import (  # noqa: E402
    BedrockClaudeAdapter,
    MockVlmAdapter,
    VlmProviderError,
    VlmValidationError,
    build_mock_vlm_frame_response,
    validate_vlm_frame_response,
    validate_vlm_request,
)


@pytest.fixture(autouse=True)
def _default_cyborg_framework(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_cyborg_stub(tmp_path, monkeypatch)


def test_generate_symbolic_plan(tmp_path: Path) -> None:
    guide_dir = _write_guide(
        tmp_path,
        "paint_like",
        interface="""
# Interface Contract

Transport is WebSocket JSON. The server sends observation objects with fields
`slot`, `positions`, `tile_owners`, `scores`, `tick`, and `done`.

| Field | Type | Required | Valid values |
|---|---|---:|---|
| `move` | string | yes | `"up"`, `"down"`, `"left"`, `"right"`, `"stay"` |
""",
        observation="""
# Observation Decoding

Decode the JSON fields directly. There is no framebuffer, screenshot, or
pixel payload in the player observation.
""",
    )

    result = generate_plan(guide_dir, output_dir=tmp_path / "maker_out")
    manifest = json.loads(result.manifest_file.read_text(encoding="utf-8"))

    assert manifest["observation_surface"]["category"] == "symbolic_primary"
    assert {item["action_id"] for item in manifest["candidate_actions"]} == {
        "down",
        "left",
        "right",
        "stay",
        "up",
    }
    assert manifest["action_wire_contract"]["style"] == "move_json"
    assert result.plan_file.exists()
    assert result.play_card_file.exists()
    assert result.vlm_request_schema_file.exists()
    assert result.vlm_schema_file.exists()
    decoder_spec = json.loads(
        (result.output_dir / "agent" / "perception" / "decoder_spec.json").read_text(encoding="utf-8")
    )
    assert decoder_spec["input_kind"] == "structured_symbolic"
    assert decoder_spec["decoder_strategy"] == "generate_symbolic_decoder"
    assert decoder_spec["vlm_ready_without_decoder"] is True
    assert (result.output_dir / "agent" / "run_agent.py").exists()
    assert (result.output_dir / "agent" / "framework_bootstrap.py").exists()
    assert (result.output_dir / "agent" / "cyborg_agent.py").exists()
    assert "cyborg_framework_handoff" in manifest["implemented_capabilities"]
    assert "symbolic_cyborg_runtime_generation" in manifest["implemented_capabilities"]
    assert _has_test_file(result.output_dir, "*policy.py")
    protocol = _load_generated_module(result.output_dir / "agent" / "protocol.py")
    assert protocol.serialize_action("right") == {"move": "right"}
    assert protocol.serialize_action("__bad__") == {"move": "stay"}
    policy = _load_generated_module(result.output_dir / "agent" / "policy.py")
    assert policy.choose_action(
        {
            "slot": 0,
            "width": 3,
            "height": 2,
            "positions": [[0, 0], [2, 1]],
            "tile_owners": [-1, -1, -1, -1, -1, -1],
        }
    ) == "right"
    assert "No VLM should be required" in result.plan_file.read_text(encoding="utf-8")


def test_generate_mixed_visual_plan(tmp_path: Path) -> None:
    guide_dir = _write_guide(
        tmp_path,
        "among_like",
        interface="""
# Interface Contract

The primary `/player` endpoint sends a BinaryMessage of 8192 bytes. It is a
packed 4-bit framebuffer for a 128x128 pixel view. The alternative
`/sprite_player` endpoint is an alternate playable channel with structured
observations.
The agent sends 2-byte binary input packets `[0x00, mask]`.

| Bit | Hex | Constant | Decoded Field |
|---:|---:|---|---|
| 0 | `0x01` | `ButtonUp` | `up` |
| 1 | `0x02` | `ButtonDown` | `down` |
| 2 | `0x04` | `ButtonLeft` | `left` |
| 3 | `0x08` | `ButtonRight` | `right` |
| 4 | `0x10` | `ButtonSelect` | `select` |
| 5 | `0x20` | `ButtonA` | `attack` |
""",
        observation="""
# Observation Decoding

Unpack pixels from the packed framebuffer before classifying the current view.
Use the structured alternate channel only when it is admissible for the agent.
""",
    )

    result = generate_plan(guide_dir, output_dir=tmp_path / "maker_out")
    manifest = json.loads(result.manifest_file.read_text(encoding="utf-8"))

    assert manifest["observation_surface"]["category"] == "mixed_or_alternate"
    assert manifest["action_wire_contract"]["style"] == "binary_button_mask"
    assert manifest["action_wire_contract"]["action_payloads"]["right"] == 0x08
    assert {"up", "down", "left", "right", "select", "attack"}.issubset(
        {item["action_id"] for item in manifest["candidate_actions"]}
    )
    assert (result.output_dir / "agent" / "run_agent.py").exists()
    assert (result.output_dir / "agent" / "framework_bootstrap.py").exists()
    assert (result.output_dir / "agent" / "cyborg_agent.py").exists()
    assert (result.output_dir / "agent" / "protocol.py").exists()
    assert (result.output_dir / "agent" / "policy.py").exists()
    decoder_spec_path = result.output_dir / "agent" / "perception" / "decoder_spec.json"
    decoder_spec = json.loads(decoder_spec_path.read_text(encoding="utf-8"))
    assert decoder_spec["input_kind"] == "raw_visual_observation"
    assert decoder_spec["decoder_strategy"] == "generate_visual_decoder"
    assert decoder_spec["needs_generated_decoder"] is True
    assert "observation_decoder_impl_generation" in manifest["implemented_capabilities"]
    assert "cyborg_framework_handoff" in manifest["implemented_capabilities"]
    assert "visual_cyborg_runtime_generation" in manifest["implemented_capabilities"]
    assert "decoder_code_generation" not in manifest["not_implemented"]
    assert "128x128" in {item.replace(" ", "") for item in decoder_spec["extracted_hints"]["dimensions"]}
    assert "8192 bytes" in decoder_spec["extracted_hints"]["byte_lengths"]
    decoder = _load_generated_module(result.output_dir / "agent" / "perception" / "decoder.py")
    decoded = decoder.decode_observation(bytes([0x0F]) * 8192)
    assert decoded.image_format == "png"
    assert _png_size(decoded.image_bytes) == (128, 128)
    task_text = (result.output_dir / "agent" / "perception" / "DECODER_GENERATION_TASK.md").read_text(
        encoding="utf-8"
    )
    assert "Do not reuse assumptions from another game's framebuffer" in task_text
    assert (result.output_dir / "agent" / "run_visual_shell.py").exists()
    assert (result.output_dir / "agent" / "action_controller.py").exists()
    assert (result.output_dir / "agent" / "frame_store.py").exists()
    assert (result.output_dir / "agent" / "vlm_client.py").exists()
    assert _has_test_file(result.output_dir, "*vlm_client.py")
    protocol = _load_generated_module(result.output_dir / "agent" / "protocol.py")
    assert protocol.serialize_action("right") == b"\x00\x08"
    assert protocol.serialize_action("__bad__") == b"\x00\x00"
    starter_policy = _load_generated_module(result.output_dir / "agent" / "policy.py")
    assert starter_policy.choose_action(b"\xff" * 8192, frame_index=0) == "right"
    visual_client = _load_generated_module(result.output_dir / "agent" / "vlm_client.py")
    request = visual_client.build_vlm_request(frame_id="f1", frame_hash="h1", play_card_hash="p1")
    response = visual_client.mock_vlm_response(request)
    assert response["schema_version"] == "maker.vlm_frame.v1"
    assert "Use the VLM as a schema-bound observation labeler" in result.plan_file.read_text(
        encoding="utf-8"
    )


def test_generate_plan_rejects_incomplete_cyborg_framework_before_writing(
    tmp_path: Path,
) -> None:
    guide_dir = _write_guide(
        tmp_path,
        "broken_framework_like",
        interface="""
# Interface Contract

Transport is WebSocket JSON. Observations are JSON fields. Valid actions are
`"up"`, `"down"`, `"left"`, `"right"`, and `"stay"` sent as `{"move": "up"}`.
""",
        observation="""
# Observation Decoding

Decode JSON fields directly. There is no framebuffer or pixel payload.
""",
    )
    bad_root = tmp_path / "bad_framework_root"
    bad_framework_dir = bad_root / "src" / "agent_policies" / "frameworks" / "coborg"
    bad_package_dir = bad_framework_dir
    bad_framework_dir.mkdir(parents=True)
    (bad_root / "src" / "agent_policies" / "__init__.py").write_text("", encoding="utf-8")
    (bad_root / "src" / "agent_policies" / "frameworks" / "__init__.py").write_text(
        "",
        encoding="utf-8",
    )
    (bad_package_dir / "__init__.py").write_text("BROKEN = True\n", encoding="utf-8")
    bad_ref = AgentFrameworkRef(
        name="coborg",
        framework_dir=bad_framework_dir,
        package="agent_policies.frameworks.coborg",
        package_source_root=bad_root / "src",
    )
    output_dir = tmp_path / "maker_out"

    with pytest.raises(MakerError, match="missing required API symbol"):
        generate_plan(guide_dir, output_dir=output_dir, agent_framework=bad_ref)

    assert not output_dir.exists()


def test_generate_binary_button_masks_from_bit_only_table(tmp_path: Path) -> None:
    guide_dir = _write_guide(
        tmp_path,
        "among_bit_table_like",
        interface="""
# Interface Contract

The primary `/player` endpoint sends a binary packed framebuffer. Agents send
a 2-byte binary WebSocket message:

```
[0x00, mask]
```

The `mask` byte encodes 7 buttons:

| Bit | Constant | Name | Playing Phase | Voting Phase |
|-----|----------|------|---------------|--------------|
| 0 | `ButtonUp` | Up | Move up | Cursor up |
| 1 | `ButtonDown` | Down | Move down | Cursor down |
| 2 | `ButtonLeft` | Left | Move left | Cursor up |
| 3 | `ButtonRight` | Right | Move right | Cursor down |
| 4 | `ButtonSelect` | Select | unused | unused |
| 5 | `ButtonA` | A (attack) | Report / Kill / Task | Confirm vote |
| 6 | `ButtonB` | B | Vent | unused |
""",
        observation="Packed framebuffer bytes must be decoded before perception.",
    )

    result = generate_plan(guide_dir, output_dir=tmp_path / "maker_out")
    manifest = json.loads(result.manifest_file.read_text(encoding="utf-8"))
    payloads = manifest["action_wire_contract"]["action_payloads"]

    assert manifest["action_wire_contract"]["style"] == "binary_button_mask"
    assert payloads["noop"] == 0x00
    assert payloads["up"] == 0x01
    assert payloads["down"] == 0x02
    assert payloads["left"] == 0x04
    assert payloads["right"] == 0x08
    assert payloads["select"] == 0x10
    assert payloads["attack"] == 0x20
    assert payloads["vent"] == 0x40


def test_generate_plan_prefers_guide_contract_over_markdown_heuristics(tmp_path: Path) -> None:
    guide_dir = _write_guide(
        tmp_path,
        "contract_first_like",
        interface="""
# Interface Contract

This stale prose says actions are JSON moves: `"move"` with valid values
`"up"`, `"down"`, `"left"`, `"right"`, and `"stay"`.
""",
        observation="This stale prose says observations are JSON fields.",
    )
    (guide_dir / "guide_contract.json").write_text(
        json.dumps(
            {
                "schema_version": "guide.contract.v1",
                "observation": {
                    "surface_category": "mixed_or_alternate",
                    "confidence": 0.9,
                    "visual_score": 12,
                    "symbolic_score": 3,
                    "primary": {
                        "input_kind": "raw_visual_observation",
                        "encoding": "packed_4bit_framebuffer",
                        "width": 128,
                        "height": 128,
                        "byte_length": 8192,
                        "bit_depth": 4,
                        "evidence": [
                            {
                                "document": "INTERFACE_CONTRACT.md",
                                "line": 1,
                                "text": "contract evidence",
                            }
                        ],
                    },
                },
                "actions": {
                    "style": "binary_button_mask",
                    "default_action": "noop",
                    "requires_message_type": True,
                    "payload_prefix": [0],
                    "payloads": {"noop": 0, "right": 8, "up": 1},
                    "candidates": [
                        {"action_id": "noop", "source": "guide_contract", "evidence": []},
                        {"action_id": "right", "source": "guide_contract", "evidence": []},
                        {"action_id": "up", "source": "guide_contract", "evidence": []},
                    ],
                    "evidence": [
                        {
                            "document": "INTERFACE_CONTRACT.md",
                            "line": 1,
                            "text": "contract action evidence",
                        }
                    ],
                },
                "runtime": {"notes": []},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    result = generate_plan(guide_dir, output_dir=tmp_path / "maker_out")
    manifest = json.loads(result.manifest_file.read_text(encoding="utf-8"))

    assert manifest["guide_contract_schema_version"] == "guide.contract.v1"
    assert "guide_contract_ingestion" in manifest["implemented_capabilities"]
    assert manifest["observation_surface"]["category"] == "mixed_or_alternate"
    assert manifest["action_wire_contract"]["style"] == "binary_button_mask"
    assert manifest["action_wire_contract"]["action_payloads"]["right"] == 0x08
    protocol = _load_generated_module(result.output_dir / "agent" / "protocol.py")
    assert protocol.serialize_action("right") == b"\x00\x08"


def test_generate_plan_rejects_unsupported_guide_contract_schema(tmp_path: Path) -> None:
    guide_dir = _write_guide(
        tmp_path,
        "bad_contract_like",
        interface="JSON observations with `move` actions.",
        observation="Structured observation fields.",
    )
    (guide_dir / "guide_contract.json").write_text(
        json.dumps({"schema_version": "guide.contract.v999"}) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unsupported guide contract schema"):
        generate_plan(guide_dir, output_dir=tmp_path / "maker_out")


def test_cli_writes_plan_only_artifacts(tmp_path: Path) -> None:
    guide_dir = _write_guide(
        tmp_path,
        "cogs_like",
        interface="""
# Interface Contract

The `player_config` message is JSON and includes
`"action_names": ["noop", "move_north", "move_south", "move_west", "move_east"]`.
The observation kind is token and the observation_shape is `[500, 3]`.
The agent may send `{ "type": "action", "action_name": "noop" }`.
""",
        observation="""
# Observation Decoding

Decode the token array as symbolic feature triples.
""",
    )
    output_dir = tmp_path / "cli_out"
    legacy_tests = output_dir / "agent" / "tests"
    legacy_tests.mkdir(parents=True)
    (legacy_tests / "test_policy.py").write_text(
        'from pathlib import Path\n'
        'import sys\n'
        'sys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n'
        'from policy import choose_action\n',
        encoding="utf-8",
    )

    assert maker_main([str(guide_dir), "--output-dir", str(output_dir), "--plan-only"]) == 0

    manifest = json.loads((output_dir / "maker_manifest.json").read_text(encoding="utf-8"))
    assert manifest["observation_surface"]["category"] == "symbolic_primary"
    assert [item["action_id"] for item in manifest["candidate_actions"]] == [
        "noop",
        "move_north",
        "move_south",
        "move_west",
        "move_east",
    ]
    assert {item["action_id"] for item in manifest["candidate_actions"]} == {
        "move_east",
        "move_north",
        "move_south",
        "move_west",
        "noop",
    }
    assert manifest["action_wire_contract"]["style"] == "action_name_json"
    assert (output_dir / "AGENT_BUILD_PLAN.md").exists()
    assert (output_dir / "agent" / "run_agent.py").exists()
    assert not (output_dir / "agent" / "tests" / "test_policy.py").exists()
    assert _has_test_file(output_dir, "*policy.py")
    assert (output_dir / "visual_bootstrap" / "vlm_request_schema.json").exists()
    assert (output_dir / "visual_bootstrap" / "vlm_schema.json").exists()
    assert (output_dir / "agent" / "perception" / "decoder_spec.json").exists()

    protocol = _load_generated_module(output_dir / "agent" / "protocol.py")
    assert protocol.serialize_action("move_north") == {
        "type": "action",
        "action_name": "move_north",
    }
    assert protocol.serialize_action("__bad__") == {
        "type": "action",
        "action_name": "noop",
    }


def test_vlm_mock_adapter_validates_and_caches(tmp_path: Path) -> None:
    request = {
        "schema_version": "maker.vlm_request.v1",
        "request_id": "req-1",
        "guide_bundle_hash": "guide",
        "play_card_hash": "play",
        "frame_id": "frame-1",
        "frame_hash": "hash",
        "run_id": "run-1",
        "objective": "classify_current_frame",
        "allowed_views": ["unknown"],
        "allowed_actions": ["noop", "move_north"],
        "recent_history": [],
        "parser_summary": {},
        "retrieved_context_ids": [],
    }

    validate_vlm_request(request)
    adapter = MockVlmAdapter(tmp_path / "cache")
    response = adapter.label_frame(request, image_bytes=b"frame")
    validate_vlm_frame_response(response, allowed_actions=["noop", "move_north"])
    assert response["recommended_action"]["action_id"] == "noop"
    assert adapter.label_frame(request, image_bytes=b"frame") == response

    bad_response = dict(response)
    bad_response["recommended_action"] = dict(response["recommended_action"])
    bad_response["recommended_action"]["action_id"] = "not_allowed"
    try:
        validate_vlm_frame_response(bad_response, allowed_actions=["noop"])
    except VlmValidationError:
        pass
    else:
        raise AssertionError("invalid VLM action should be rejected")


def test_bedrock_adapter_calls_converse_and_caches(tmp_path: Path) -> None:
    request = {
        "schema_version": "maker.vlm_request.v1",
        "request_id": "req-bedrock",
        "guide_bundle_hash": "guide",
        "play_card_hash": "play",
        "frame_id": "frame-1",
        "frame_hash": "hash",
        "run_id": "run-1",
        "objective": "classify_current_frame",
        "allowed_views": ["unknown"],
        "allowed_actions": ["noop", "move_north"],
        "recent_history": [],
        "parser_summary": {},
        "retrieved_context_ids": [],
    }
    fake_client = _FakeBedrockClient(build_mock_vlm_frame_response(request))
    adapter = BedrockClaudeAdapter(
        tmp_path / "cache",
        client=fake_client,
        model_id="anthropic.test-model",
        play_card_text="Use the guide action registry.",
    )

    first = adapter.label_frame(request, image_bytes=ONE_PIXEL_PNG)
    second = adapter.label_frame(request, image_bytes=ONE_PIXEL_PNG)
    rerun_request = dict(request)
    rerun_request["run_id"] = "run-2"
    third = adapter.label_frame(rerun_request, image_bytes=ONE_PIXEL_PNG)

    assert first == second
    assert first == third
    assert fake_client.calls == 1
    call = fake_client.last_call
    assert call["modelId"] == "anthropic.test-model"
    assert call["messages"][0]["content"][1]["image"]["format"] == "png"
    assert call["inferenceConfig"]["temperature"] == 0.0


def test_bedrock_adapter_rejects_raw_framebuffer_bytes(tmp_path: Path) -> None:
    request = {
        "schema_version": "maker.vlm_request.v1",
        "request_id": "req-bedrock",
        "guide_bundle_hash": "guide",
        "play_card_hash": "play",
        "frame_id": "frame-1",
        "frame_hash": "hash",
        "run_id": "run-1",
        "objective": "classify_current_frame",
        "allowed_views": ["unknown"],
        "allowed_actions": ["noop"],
        "recent_history": [],
        "parser_summary": {},
        "retrieved_context_ids": [],
    }
    adapter = BedrockClaudeAdapter(tmp_path / "cache", client=_FakeBedrockClient({}))

    try:
        adapter.label_frame(request, image_bytes=b"raw-framebuffer")
    except VlmProviderError as exc:
        assert "game-specific decoder" in str(exc)
    else:
        raise AssertionError("raw framebuffer bytes should be rejected for Bedrock VLM calls")


def test_visual_bootstrap_labels_frame_dir_with_budget(tmp_path: Path) -> None:
    guide_dir = _write_guide(
        tmp_path,
        "among_like",
        interface="""
# Interface Contract

The primary `/player` endpoint sends a BinaryMessage of 8192 bytes. It is a
packed 4-bit framebuffer for a 128x128 pixel view.

| Bit | Hex | Constant | Decoded Field |
|---:|---:|---|---|
| 0 | `0x01` | `ButtonUp` | `up` |
| 1 | `0x02` | `ButtonDown` | `down` |
""",
        observation="""
# Observation Decoding

Unpack pixels from the packed framebuffer before classifying the current view.
""",
    )
    output_dir = tmp_path / "maker_out"
    result = generate_plan(guide_dir, output_dir=output_dir)
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    (frames_dir / "a.bin").write_bytes(bytes([0x0F]) * 8192)
    (frames_dir / "b.bin").write_bytes(bytes([0xF0]) * 8192)

    bootstrap = run_visual_bootstrap(
        output_dir=result.output_dir,
        frames_dir=frames_dir,
        budget=1,
        provider="mock",
        decode_observations=True,
    )

    assert bootstrap.labels_written == 1
    report = json.loads(bootstrap.report_file.read_text(encoding="utf-8"))
    assert report["budget"] == 1
    assert report["decode_observations"] is True
    assert report["labels_written"] == 1
    assert report["records"][0]["decoded_observation"] is True
    assert len(list((output_dir / "visual_bootstrap" / "labels").glob("*.json"))) == 1
    assert len(list((output_dir / "visual_bootstrap" / "decoded_frames").glob("*.png"))) == 1

    policy_result = build_policy_from_labels(output_dir)
    assert policy_result.labels_read == 1
    assert policy_result.rules_written == 1
    policy = _load_generated_module(output_dir / "agent" / "policy_from_labels.py")
    action = policy.choose_action({"response": {"view": {"id": "unknown"}, "phase": {"id": "unknown"}}})
    assert action in policy.ALLOWED_ACTIONS


@pytest.mark.asyncio
async def test_generated_visual_starter_sends_live_actions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_cyborg_stub(tmp_path, monkeypatch)
    guide_dir = _write_guide(
        tmp_path,
        "among_live_like",
        interface="""
# Interface Contract

The primary `/player` endpoint sends a BinaryMessage of 8192 bytes. It is a
packed 4-bit framebuffer for a 128x128 pixel view.
The agent sends 2-byte binary input packets `[0x00, mask]`.

| Bit | Hex | Constant | Decoded Field |
|---:|---:|---|---|
| 0 | `0x01` | `ButtonUp` | `up` |
| 1 | `0x02` | `ButtonDown` | `down` |
| 2 | `0x04` | `ButtonLeft` | `left` |
| 3 | `0x08` | `ButtonRight` | `right` |
""",
        observation="""
# Observation Decoding

Unpack pixels from the packed framebuffer before classifying the current view.
""",
    )
    result = generate_plan(guide_dir, output_dir=tmp_path / "maker_out")
    runner = _load_generated_agent_module(result.output_dir / "agent" / "run_agent.py")
    received: list[bytes | str] = []

    async def handler(websocket: object) -> None:
        recv = getattr(websocket, "recv")
        send = getattr(websocket, "send")
        received.append(await asyncio.wait_for(recv(), timeout=1))
        await send(b"\xff" * 8192)
        received.append(await asyncio.wait_for(recv(), timeout=1))

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        assert server.sockets is not None
        port = server.sockets[0].getsockname()[1]
        await runner.run(
            f"ws://127.0.0.1:{port}",
            output_root=tmp_path / "live_run",
            max_frames=1,
        )

    assert received == [b"\x00\x00", b"\x00\x08"]
    assert len(list((tmp_path / "live_run" / "frames").glob("*.bin"))) == 1


@pytest.mark.asyncio
async def test_smoke_test_runs_generated_visual_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_cyborg_stub(tmp_path, monkeypatch)
    guide_dir = _write_guide(
        tmp_path,
        "among_smoke_like",
        interface="""
# Interface Contract

The primary `/player` endpoint sends a BinaryMessage of 8192 bytes. It is a
packed 4-bit framebuffer for a 128x128 pixel view.
The agent sends 2-byte binary input packets `[0x00, mask]`.

| Bit | Hex | Constant | Decoded Field |
|---:|---:|---|---|
| 0 | `0x01` | `ButtonUp` | `up` |
| 3 | `0x08` | `ButtonRight` | `right` |
""",
        observation="""
# Observation Decoding

Unpack pixels from the packed framebuffer before classifying the current view.
""",
    )
    result = generate_plan(guide_dir, output_dir=tmp_path / "maker_out")
    received: list[bytes | str] = []

    async def handler(websocket: object) -> None:
        recv = getattr(websocket, "recv")
        send = getattr(websocket, "send")
        received.append(await asyncio.wait_for(recv(), timeout=1))
        await send(b"\xff" * 8192)
        received.append(await asyncio.wait_for(recv(), timeout=1))

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        assert server.sockets is not None
        port = server.sockets[0].getsockname()[1]
        smoke = await asyncio.to_thread(
            run_smoke_test,
            output_dir=result.output_dir,
            agent_url=f"ws://127.0.0.1:{port}",
            run_timeout=5,
            agent_max_frames=1,
        )

    assert smoke.passed is True
    assert smoke.frames_saved == 1
    assert received == [b"\x00\x00", b"\x00\x08"]
    report = json.loads(smoke.report_file.read_text(encoding="utf-8"))
    assert report["status"] == "passed"
    assert report["frames_saved"] == 1
    assert report["agent_returncode"] == 0


def test_visual_bootstrap_rejects_symbolic_and_unimplemented_provider(tmp_path: Path) -> None:
    guide_dir = _write_guide(
        tmp_path,
        "paint_like",
        interface="""
# Interface Contract

Transport is WebSocket JSON. The action field is `move` with valid values
`"up"`, `"down"`, `"left"`, `"right"`, and `"stay"`.
""",
        observation="Decode JSON fields directly.",
    )
    result = generate_plan(guide_dir, output_dir=tmp_path / "maker_out")
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    (frames_dir / "a.bin").write_bytes(b"a")

    try:
        run_visual_bootstrap(output_dir=result.output_dir, frames_dir=frames_dir, budget=1)
    except BootstrapError as exc:
        assert "only for visual_primary" in str(exc)
    else:
        raise AssertionError("symbolic outputs should not run visual bootstrap")

    mixed = _write_guide(
        tmp_path,
        "among_provider_like",
        interface="BinaryMessage packed framebuffer, pixels, 8192 bytes. Action `up`.",
        observation="Unpack pixels from the packed framebuffer.",
    )
    mixed_result = generate_plan(mixed, output_dir=tmp_path / "mixed_out")
    try:
        run_visual_bootstrap(
            output_dir=mixed_result.output_dir,
            frames_dir=frames_dir,
            budget=1,
            provider="openai",
        )
    except BootstrapError as exc:
        assert "OPENAI_API_KEY" in str(exc)
    else:
        raise AssertionError("openai provider should fail clearly until implemented")


def _write_guide(
    tmp_path: Path,
    name: str,
    *,
    interface: str,
    observation: str,
) -> Path:
    guide_dir = tmp_path / name
    guide_dir.mkdir()
    docs = {
        "README.md": f"# {name}\n",
        "GAME_OVERVIEW.md": f"# {name} Overview\n",
        "INTERFACE_CONTRACT.md": interface,
        "OBSERVATION_DECODING.md": observation,
        "ACTION_SEMANTICS_AND_CONTROL.md": "# Action Semantics\n",
        "STATE_AND_VIEW_MODEL.md": "# State And View Model\n",
        "CONNECTION_AND_EPISODE_LIFECYCLE.md": "# Lifecycle\nWebSocket endpoint notes.\n",
        "MINIMUM_VIABLE_AGENT.md": "# Minimum Viable Agent\n",
    }
    for filename, content in docs.items():
        (guide_dir / filename).write_text(content.strip() + "\n", encoding="utf-8")
    return guide_dir


def _load_generated_module(path: Path) -> types.ModuleType:
    module_name = f"_generated_{path.parent.parent.name}_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _load_generated_agent_module(path: Path) -> types.ModuleType:
    module_name = f"_generated_agent_{path.parent.parent.name}_{path.stem}"
    old_path = list(sys.path)
    previous = {
        name: sys.modules.get(name)
        for name in (
            "cyborg_agent",
            "agent_policies",
            "agent_policies.frameworks",
            "agent_policies.frameworks.coborg",
            "framework_bootstrap",
            "frame_store",
            "policy",
            "protocol",
        )
    }
    for name in previous:
        sys.modules.pop(name, None)
    sys.path.insert(0, str(path.parent))
    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path[:] = old_path
        for name, module in previous.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def _png_size(payload: bytes) -> tuple[int, int]:
    assert payload.startswith(b"\x89PNG\r\n\x1a\n")
    return struct.unpack(">II", payload[16:24])


def _has_test_file(output_dir: Path, pattern: str) -> bool:
    return any((output_dir / "agent" / "tests").glob(f"test_{pattern}"))


def _install_cyborg_stub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "agent_policies_stub"
    framework_dir = root / "src" / "agent_policies" / "frameworks" / "coborg"
    package_dir = framework_dir
    framework_dir.mkdir(parents=True, exist_ok=True)
    package_dir.mkdir(parents=True, exist_ok=True)
    (framework_dir / "README.md").write_text("# Cyborg test framework\n", encoding="utf-8")
    (root / "src" / "agent_policies" / "__init__.py").write_text("", encoding="utf-8")
    (root / "src" / "agent_policies" / "frameworks" / "__init__.py").write_text(
        "",
        encoding="utf-8",
    )
    (package_dir / "__init__.py").write_text(
        '''
from __future__ import annotations


class EmptyModeParams:
    pass


class ModeDirective:
    def __init__(
        self,
        *,
        mode: str,
        params=None,
        source: str = "strategy",
        issued_at_tick: int = 0,
        ttl_ticks: int = 0,
        reason: str = "",
        metadata=None,
    ) -> None:
        self.mode = mode
        self.params = params if params is not None else EmptyModeParams()
        self.source = source
        self.issued_at_tick = issued_at_tick
        self.ttl_ticks = ttl_ticks
        self.reason = reason
        self.metadata = metadata or {}

    def issued(self, tick: int):
        return ModeDirective(
            mode=self.mode,
            params=self.params,
            source=self.source,
            issued_at_tick=tick,
            ttl_ticks=self.ttl_ticks,
            reason=self.reason,
            metadata=self.metadata,
        )

    def expired_at(self, tick: int) -> bool:
        return self.ttl_ticks > 0 and self.issued_at_tick > 0 and tick - self.issued_at_tick >= self.ttl_ticks


class ActionIntent:
    def __init__(self, semantic: str = "noop", target=None, text=None, reason: str = "", metadata=None) -> None:
        self.semantic = semantic
        self.target = target
        self.text = text
        self.reason = reason
        self.metadata = metadata or {}


class ActionCommand:
    def __init__(self, action: str = "noop", text=None, metadata=None) -> None:
        self.action = action
        self.text = text
        self.metadata = metadata or {}


class Mode:
    name = ""
    params_type = EmptyModeParams

    def __init__(self, params=None) -> None:
        self.params = params if params is not None else self.params_type()

    def matches_directive(self, directive: ModeDirective) -> bool:
        return directive.mode == self.name and type(directive.params) is type(self.params)

    def on_enter(self, belief, action_state) -> None:
        pass

    def on_exit(self, belief, action_state, next_directive: ModeDirective) -> None:
        pass

    def is_legal(self, belief) -> bool:
        return True


class ModeRegistry:
    def __init__(self) -> None:
        self._modes = {}

    def register(self, mode_cls):
        self._modes[mode_cls.name] = mode_cls
        return mode_cls

    def validation_error(self, directive: ModeDirective):
        if directive.mode not in self._modes:
            return f"unknown mode {directive.mode!r}"
        return None

    def validate(self, directive: ModeDirective):
        error = self.validation_error(directive)
        if error is not None:
            raise ValueError(error)
        return directive

    def create(self, directive: ModeDirective):
        self.validate(directive)
        return self._modes[directive.mode](directive.params)


class SynchronousStrategyRunner:
    def __init__(self, strategy, *, cadence_ticks: int = 1) -> None:
        self.strategy = strategy
        self.pending = None

    def observe(self, snapshot) -> None:
        del snapshot
        self.pending = self.strategy.decide(None)

    def poll(self):
        result = self.pending
        self.pending = None
        return result

    def close(self) -> None:
        self.pending = None


class AgentRuntime:
    def __init__(
        self,
        *,
        belief,
        action_state,
        perceive,
        update_belief,
        resolve_action,
        mode_registry,
        default_directive,
        strategy_runner=None,
        **kwargs,
    ) -> None:
        del kwargs
        self.belief = belief
        self.action_state = action_state
        self.perceive = perceive
        self.update_belief = update_belief
        self.resolve_action = resolve_action
        self.mode_registry = mode_registry
        self.strategy_runner = strategy_runner
        self.tick = 0
        self.active_directive = default_directive.issued(0)
        self.active_mode = mode_registry.create(self.active_directive)

    def step(self, observation):
        self.tick += 1
        percept = self.perceive(observation, self.tick)
        self.update_belief(self.belief, percept)
        if self.strategy_runner is not None:
            self.strategy_runner.observe(None)
            directive = self.strategy_runner.poll()
            if directive is not None:
                self.active_directive = directive.issued(self.tick)
                self.active_mode = self.mode_registry.create(self.active_directive)
        intent = self.active_mode.decide(self.belief, self.action_state)
        return self.resolve_action(intent, self.belief, self.action_state)

    def close(self) -> None:
        if self.strategy_runner is not None:
            self.strategy_runner.close()
'''.strip()
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(maker_framework, "DEFAULT_FRAMEWORK_DIR", framework_dir)
    return root


class _FakeBedrockClient:
    def __init__(self, response_payload: dict[str, object]) -> None:
        self.response_payload = response_payload
        self.calls = 0
        self.last_call: dict[str, object] = {}

    def converse(self, **kwargs: object) -> dict[str, object]:
        self.calls += 1
        self.last_call = kwargs
        return {
            "output": {
                "message": {
                    "content": [
                        {
                            "text": json.dumps(self.response_payload),
                        }
                    ]
                }
            }
        }
