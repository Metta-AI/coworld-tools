from __future__ import annotations

import json
import re
from pathlib import Path

from .artifacts import write_text
from .framework import AgentFrameworkRef
from .guide_index import ActionCandidate, ActionWireContract, GuideBundle, ObservationSurface
from .protocol_render import render_protocol, render_protocol_tests
from .symbolic_agent import _render_framework_bootstrap


def generate_visual_agent_shell(
    *,
    bundle: GuideBundle,
    output_dir: Path,
    surface: ObservationSurface,
    actions: tuple[ActionCandidate, ...],
    wire_contract: ActionWireContract,
    agent_framework: AgentFrameworkRef,
) -> tuple[Path, ...]:
    agent_dir = output_dir / "agent"
    test_dir = agent_dir / "tests"
    test_prefix = _test_module_prefix(bundle.game_slug, output_dir)
    _remove_legacy_generated_tests(test_dir)
    files = (
        agent_dir / "README.md",
        agent_dir / "framework_bootstrap.py",
        agent_dir / "cyborg_agent.py",
        agent_dir / "protocol.py",
        agent_dir / "policy.py",
        agent_dir / "action_controller.py",
        agent_dir / "frame_store.py",
        agent_dir / "vlm_client.py",
        agent_dir / "run_agent.py",
        agent_dir / "run_visual_shell.py",
        test_dir / f"test_{test_prefix}_protocol.py",
        test_dir / f"test_{test_prefix}_policy.py",
        test_dir / f"test_{test_prefix}_cyborg_agent.py",
        test_dir / f"test_{test_prefix}_action_controller.py",
        test_dir / f"test_{test_prefix}_frame_store.py",
        test_dir / f"test_{test_prefix}_vlm_client.py",
    )

    action_ids = tuple(action.action_id for action in actions)
    write_text(files[0], _render_readme(bundle, surface, wire_contract, agent_framework))
    write_text(files[1], _render_framework_bootstrap(agent_framework))
    write_text(files[2], _render_cyborg_agent(action_ids, wire_contract))
    write_text(files[3], render_protocol(action_ids, wire_contract))
    write_text(files[4], _render_policy(action_ids, wire_contract))
    write_text(files[5], _render_action_controller(action_ids))
    write_text(files[6], _render_frame_store())
    write_text(files[7], _render_vlm_client(bundle.bundle_hash, action_ids))
    write_text(files[8], _render_live_runner())
    write_text(files[9], _render_capture_runner())
    write_text(files[10], render_protocol_tests(wire_contract))
    write_text(files[11], _render_policy_tests(action_ids, wire_contract))
    write_text(files[12], _render_cyborg_agent_tests())
    write_text(files[13], _render_action_controller_tests(action_ids))
    write_text(files[14], _render_frame_store_tests())
    write_text(files[15], _render_vlm_client_tests(action_ids))
    return files


def _render_readme(
    bundle: GuideBundle,
    surface: ObservationSurface,
    wire_contract: ActionWireContract,
    agent_framework: AgentFrameworkRef,
) -> str:
    return f"""# {bundle.game_slug} Visual Shell

This is a generated `maker_v1` visual starter agent, shaped to ship as a
Coworld player image. The live starter reads `COGAMES_ENGINE_WS_URL` from
the runner's env, connects to the player websocket, captures binary or
JSON observations, decodes raw observations when
`agent/perception/decoder.py` can do so, chooses a simple guide-derived
movement action, sends only actions that serialize through the generated
protocol layer, and exits at episode end.

Observation surface: `{surface.category}`.
Action wire style: `{wire_contract.style}`.

Generated files:

- `protocol.py`: serializes guide-derived action ids into the live wire format
- `framework_bootstrap.py`: points this artifact at `{agent_framework.package}`
  from `{agent_framework.framework_dir}` (host-absolute path recorded at
  generation time; update before building the Docker image)
- `cyborg_agent.py`: adapts the starter policy into Cyborg percept, belief,
  mode, strategy directive, and action resolution boundaries
- `policy.py`: conservative movement/exploration starter policy helper
- `action_controller.py`: validates VLM action recommendations
- `frame_store.py`: frame/message hashing and fixture storage
- `vlm_client.py`: request builder and deterministic mock VLM response
- `run_agent.py`: live Coworld entrypoint (WebSocket runner)
- `run_visual_shell.py`: budgeted capture and mock-label WebSocket runner
- `tests/`: local tests for the generated shell

## Coworld workflow

```bash
# Pull the target Coworld and read its protocol contract.
uv run coworld download {bundle.game_slug} --output-dir ./coworld

# Resolve the Cyborg framework dependency in the bundle's Dockerfile, then
# build the player image.
docker build --platform=linux/amd64 -t {bundle.game_slug}-player:latest .

# Local episode (one image fills every slot).
uv run coworld run-episode ./coworld/coworld_manifest.json {bundle.game_slug}-player:latest

# Upload + submit to a league.
uv run coworld upload-policy {bundle.game_slug}-player:latest --name {bundle.game_slug}-player
uv run coworld submit {bundle.game_slug}-player --league league_...
```

Use this scaffold as the first live policy surface. It is meant to run
safely, not to be competitive before parser and policy refinement.
"""


def _test_module_prefix(game_slug: str, output_dir: Path) -> str:
    slug = re.sub(r"[^0-9A-Za-z_]+", "_", game_slug).strip("_").lower() or "game"
    output_name = re.sub(r"[^0-9A-Za-z_]+", "_", output_dir.name).strip("_").lower()
    if not output_name or output_name == slug:
        return slug
    return f"{slug}_{output_name}"


def _remove_legacy_generated_tests(test_dir: Path) -> None:
    paths = [
        *test_dir.glob("test_*_action_controller.py"),
        *test_dir.glob("test_*_frame_store.py"),
        *test_dir.glob("test_*_vlm_client.py"),
        *test_dir.glob("test_*_protocol.py"),
        *test_dir.glob("test_*_policy.py"),
        *test_dir.glob("test_*_cyborg_agent.py"),
        test_dir / "test_action_controller.py",
        test_dir / "test_frame_store.py",
        test_dir / "test_vlm_client.py",
        test_dir / "test_protocol.py",
        test_dir / "test_policy.py",
        test_dir / "test_cyborg_agent.py",
    ]
    for path in paths:
        if path.exists() and _looks_like_legacy_generated_test(path):
            path.unlink()


def _looks_like_legacy_generated_test(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    uses_old_path_setup = 'sys.path.insert(0, str(Path(__file__).resolve().parents[1]))' in text
    imports_generated_agent = (
        "from action_controller import" in text
        or "from frame_store import" in text
        or "from vlm_client import" in text
        or "from protocol import" in text
        or "from policy import" in text
        or "from cyborg_agent import" in text
    )
    uses_generated_importlib_loader = (
        "def _load_agent_module(module_name: str)" in text
        and 'Path(__file__).resolve().parents[1] / (module_name + ".py")' in text
    )
    loads_generated_agent = (
        '_load_agent_module("action_controller")' in text
        or '_load_agent_module("frame_store")' in text
        or '_load_agent_module("vlm_client")' in text
        or '_load_agent_module("protocol")' in text
        or '_load_agent_module("policy")' in text
        or '_load_agent_module("cyborg_agent")' in text
    )
    return (uses_old_path_setup and imports_generated_agent) or (
        uses_generated_importlib_loader and loads_generated_agent
    )


def _render_cyborg_agent(
    action_ids: tuple[str, ...],
    wire_contract: ActionWireContract,
) -> str:
    actions_json = json.dumps(list(action_ids), indent=4)
    return f'''from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from framework_bootstrap import load_cyborg_framework
from policy import choose_action as choose_policy_action


cyborg = load_cyborg_framework()
ActionCommand = cyborg.ActionCommand
ActionIntent = cyborg.ActionIntent
AgentRuntime = cyborg.AgentRuntime
EmptyModeParams = cyborg.EmptyModeParams
Mode = cyborg.Mode
ModeDirective = cyborg.ModeDirective
ModeRegistry = cyborg.ModeRegistry
SynchronousStrategyRunner = cyborg.SynchronousStrategyRunner

ACTIONS: list[str] = {actions_json}
DEFAULT_ACTION = {wire_contract.default_action!r}


@dataclass(frozen=True)
class ObservationEnvelope:
    observation: bytes | dict[str, Any] | None
    frame_index: int = 0
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Percept:
    observation: bytes | dict[str, Any] | None
    frame_index: int
    config: dict[str, Any]
    tick: int


@dataclass
class Belief:
    observation: bytes | dict[str, Any] | None = None
    frame_index: int = 0
    config: dict[str, Any] = field(default_factory=dict)
    tick: int = 0


@dataclass
class ActionState:
    last_action: str = DEFAULT_ACTION


class IdleMode(Mode):
    name = "idle"
    params_type = EmptyModeParams

    def decide(self, belief: Belief, action_state: ActionState) -> Any:
        del belief, action_state
        return ActionIntent(semantic=DEFAULT_ACTION, reason="default idle mode")


class HeuristicMode(Mode):
    name = "heuristic"
    params_type = EmptyModeParams

    def decide(self, belief: Belief, action_state: ActionState) -> Any:
        del action_state
        action = choose_policy_action(
            belief.observation,
            frame_index=belief.frame_index,
            config=belief.config,
        )
        return ActionIntent(semantic=action, reason="guide-derived visual starter policy")


class StarterStrategy:
    def decide(self, snapshot: Any) -> Any:
        del snapshot
        return ModeDirective(
            mode="heuristic",
            source="generated_rule_strategy",
            ttl_ticks=120,
            reason="run the generated conservative visual mode",
        )


def perceive(envelope: ObservationEnvelope, tick: int) -> Percept:
    return Percept(
        observation=envelope.observation,
        frame_index=envelope.frame_index,
        config=envelope.config,
        tick=tick,
    )


def update_belief(belief: Belief, percept: Percept) -> None:
    belief.observation = percept.observation
    belief.frame_index = percept.frame_index
    belief.config = percept.config
    belief.tick = percept.tick


def resolve_action(intent: Any, belief: Belief, action_state: ActionState) -> Any:
    del belief
    action = getattr(intent, "semantic", None)
    if action not in ACTIONS:
        action = DEFAULT_ACTION if DEFAULT_ACTION in ACTIONS else (ACTIONS[0] if ACTIONS else "noop")
    action_state.last_action = action
    return ActionCommand(action=action)


def build_mode_registry() -> Any:
    registry = ModeRegistry()
    registry.register(IdleMode)
    registry.register(HeuristicMode)
    return registry


def build_runtime() -> Any:
    return AgentRuntime(
        belief=Belief(),
        action_state=ActionState(),
        perceive=perceive,
        update_belief=update_belief,
        resolve_action=resolve_action,
        mode_registry=build_mode_registry(),
        default_directive=ModeDirective(mode="idle", source="default"),
        strategy_runner=SynchronousStrategyRunner(StarterStrategy()),
    )


class StarterAgent:
    def __init__(self) -> None:
        self.runtime = build_runtime()

    def choose_action(
        self,
        observation: bytes | dict[str, Any] | None,
        *,
        frame_index: int = 0,
        config: dict[str, Any] | None = None,
    ) -> str:
        command = self.runtime.step(ObservationEnvelope(observation, frame_index, config or {{}}))
        return str(getattr(command, "action", DEFAULT_ACTION))

    def close(self) -> None:
        self.runtime.close()


def choose_runtime_action(
    observation: bytes | dict[str, Any] | None,
    *,
    frame_index: int = 0,
    config: dict[str, Any] | None = None,
) -> str:
    agent = StarterAgent()
    try:
        return agent.choose_action(observation, frame_index=frame_index, config=config)
    finally:
        agent.close()
'''


def _render_policy(
    action_ids: tuple[str, ...],
    wire_contract: ActionWireContract,
) -> str:
    actions_json = json.dumps(list(action_ids), indent=4)
    movement = [action for action in ("right", "down", "left", "up") if action in action_ids]
    movement_json = json.dumps(movement, indent=4)
    return f'''from __future__ import annotations

from typing import Any


ACTIONS: list[str] = {actions_json}
DEFAULT_ACTION = {wire_contract.default_action!r}
MOVEMENT_SEQUENCE: list[str] = {movement_json}
HOLD_FRAMES = 18


def choose_action(
    observation: bytes | dict[str, Any] | None,
    *,
    frame_index: int = 0,
    config: dict[str, Any] | None = None,
) -> str:
    if isinstance(observation, dict) and observation.get("recommended_action") in ACTIONS:
        return str(observation["recommended_action"])
    if isinstance(observation, bytes) and _looks_like_interstitial_packed_frame(observation):
        return _fallback_action()
    if MOVEMENT_SEQUENCE:
        return MOVEMENT_SEQUENCE[(max(0, frame_index) // HOLD_FRAMES) % len(MOVEMENT_SEQUENCE)]
    return _fallback_action()


def _fallback_action() -> str:
    if DEFAULT_ACTION in ACTIONS:
        return DEFAULT_ACTION
    if DEFAULT_ACTION == "noop":
        return DEFAULT_ACTION
    if "noop" in ACTIONS:
        return "noop"
    if "stay" in ACTIONS:
        return "stay"
    return ACTIONS[0] if ACTIONS else "noop"


def _looks_like_interstitial_packed_frame(payload: bytes) -> bool:
    if len(payload) != 8192:
        return False
    black_pixels = 0
    for value in payload:
        if value & 0x0F == 0:
            black_pixels += 1
        if (value >> 4) & 0x0F == 0:
            black_pixels += 1
    return black_pixels >= (128 * 128 * 30) // 100
'''


def _render_action_controller(action_ids: tuple[str, ...]) -> str:
    actions_json = json.dumps(list(action_ids), indent=4)
    return f'''from __future__ import annotations

from typing import Any


ALLOWED_ACTIONS: list[str] = {actions_json}


def validate_recommended_action(response: dict[str, Any]) -> dict[str, Any]:
    fallback = _fallback_action()
    recommended = response.get("recommended_action")
    if not isinstance(recommended, dict):
        return {{"action_id": fallback, "valid": False, "fallback_action_id": fallback, "reason": "missing recommended_action"}}
    action_id = recommended.get("action_id")
    if action_id not in ALLOWED_ACTIONS:
        return {{"action_id": fallback, "valid": False, "fallback_action_id": fallback, "reason": f"action not allowed: {{action_id}}"}}
    return {{"action_id": action_id, "valid": True, "fallback_action_id": fallback, "reason": "recommended action allowed"}}


def _fallback_action() -> str:
    for candidate in ("noop", "stay", "wait"):
        if candidate in ALLOWED_ACTIONS:
            return candidate
    return ALLOWED_ACTIONS[0] if ALLOWED_ACTIONS else "unknown"
'''


def _render_frame_store() -> str:
    return '''from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def hash_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def save_frame(payload: bytes, root: Path, *, suffix: str = ".bin") -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    digest = hash_bytes(payload)
    path = root / f"{digest}{suffix}"
    path.write_bytes(payload)
    return {
        "frame_id": digest,
        "frame_hash": digest,
        "path": str(path),
        "size_bytes": len(payload),
    }


def save_json_message(message: dict[str, Any], root: Path) -> dict[str, Any]:
    payload = json.dumps(message, sort_keys=True, separators=(",", ":")).encode("utf-8")
    record = save_frame(payload, root, suffix=".json")
    Path(record["path"]).write_text(json.dumps(message, indent=2, sort_keys=True) + "\\n", encoding="utf-8")
    return record


def write_label(label: dict[str, Any], root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    request_id = str(label.get("request_id", "unknown"))
    path = root / f"{request_id}.json"
    path.write_text(json.dumps(label, indent=2, sort_keys=True) + "\\n", encoding="utf-8")
    return path
'''


def _render_vlm_client(bundle_hash: str, action_ids: tuple[str, ...]) -> str:
    actions_json = json.dumps(list(action_ids), indent=4)
    return f'''from __future__ import annotations

import hashlib
from typing import Any


GUIDE_BUNDLE_HASH = {bundle_hash!r}
ALLOWED_ACTIONS: list[str] = {actions_json}


def build_vlm_request(
    *,
    frame_id: str,
    frame_hash: str,
    play_card_hash: str,
    run_id: str = "manual",
    objective: str = "classify_current_frame",
    allowed_views: list[str] | None = None,
    parser_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    seed = f"{{GUIDE_BUNDLE_HASH}}:{{play_card_hash}}:{{frame_id}}:{{objective}}"
    request_id = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return {{
        "schema_version": "maker.vlm_request.v1",
        "request_id": request_id,
        "guide_bundle_hash": GUIDE_BUNDLE_HASH,
        "play_card_hash": play_card_hash,
        "frame_id": frame_id,
        "frame_hash": frame_hash,
        "run_id": run_id,
        "objective": objective,
        "allowed_views": allowed_views or ["unknown"],
        "allowed_actions": list(ALLOWED_ACTIONS),
        "recent_history": [],
        "parser_summary": parser_summary or {{}},
        "retrieved_context_ids": [],
    }}


def mock_vlm_response(request: dict[str, Any]) -> dict[str, Any]:
    fallback = _fallback_action(request.get("allowed_actions", []))
    return {{
        "schema_version": "maker.vlm_frame.v1",
        "request_id": request["request_id"],
        "frame_id": request["frame_id"],
        "view": {{"id": "unknown", "confidence": 0.0, "evidence": ["generated mock"]}},
        "phase": {{"id": "unknown", "confidence": 0.0, "evidence": ["generated mock"]}},
        "visible_text": [],
        "ui_elements": [],
        "entities": [],
        "state_observations": [],
        "available_actions": [
            {{"action_id": action_id, "confidence": 0.0, "evidence": ["guide action registry"]}}
            for action_id in request.get("allowed_actions", [])
        ],
        "recommended_action": {{
            "action_id": fallback,
            "parameters": {{}},
            "confidence": 0.0,
            "rationale": "Generated mock VLM does not inspect frames.",
            "fallback_action_id": fallback,
        }},
        "novelty": {{
            "status": "uncertain",
            "save_frame": True,
            "reason": "No real VLM adapter was called.",
        }},
        "parser_targets": [
            {{
                "target": "view_classifier",
                "why": "Frame needs a deterministic parser fixture.",
                "suggested_test": "Save this frame and add expected view/phase labels.",
            }}
        ],
        "memory_updates": [],
        "uncertainty": [
            {{
                "field": "view",
                "reason": "Mock VLM cannot classify visual state.",
                "needed_next": "Run a real VLM adapter or add a human label.",
            }}
        ],
    }}


def _fallback_action(actions: list[str]) -> str:
    for candidate in ("noop", "stay", "wait"):
        if candidate in actions:
            return candidate
    return actions[0] if actions else "unknown"
'''


def _render_live_runner() -> str:
    return '''from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from cyborg_agent import StarterAgent
from frame_store import save_frame, save_json_message
from protocol import is_terminal_message, serialize_action

try:
    from perception.decoder import DecodeError, decode_observation
except Exception:  # pragma: no cover - generated fallback for partial artifacts
    DecodeError = Exception
    decode_observation = None


DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parents[1] / "visual_bootstrap" / "live_run"


async def run(
    url: str,
    *,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    max_frames: int | None = None,
) -> None:
    frames_dir = output_root / "frames"
    decoded_dir = output_root / "decoded"
    messages_dir = output_root / "messages"
    config: dict[str, Any] = {}
    frame_index = 0
    last_payload: bytes | str | None = None
    agent = StarterAgent()

    try:
        import websockets
    except ModuleNotFoundError as exc:
        raise RuntimeError("Install the 'websockets' package to run this generated agent.") from exc

    try:
        async with websockets.connect(url, max_size=None) as websocket:
            initial = serialize_action("noop", config)
            if initial is not None:
                await _send_serialized(websocket, initial)
                last_payload = _payload_key(initial)

            async for raw_message in websocket:
                observation: bytes | dict[str, Any] | None
                if isinstance(raw_message, bytes):
                    observation = raw_message
                    save_frame(raw_message, frames_dir)
                    _try_write_decoded(raw_message, decoded_dir)
                    frame_index += 1
                else:
                    message = _decode_json(raw_message)
                    if isinstance(message, dict) and message.get("type") == "player_config":
                        config = message
                        continue
                    if is_terminal_message(message):
                        break
                    observation = message if isinstance(message, dict) else None
                    if isinstance(message, dict):
                        save_json_message(message, messages_dir)

                action_id = agent.choose_action(observation, frame_index=frame_index, config=config)
                payload = serialize_action(action_id, config)
                payload_key = _payload_key(payload)
                if payload is not None and payload_key != last_payload:
                    await _send_serialized(websocket, payload)
                    last_payload = payload_key
                if max_frames is not None and frame_index >= max_frames:
                    break
    finally:
        agent.close()


def _try_write_decoded(payload: bytes, output_dir: Path) -> None:
    if decode_observation is None:
        return
    try:
        decoded = decode_observation(payload)
    except DecodeError:
        return
    if decoded.image_bytes is None or decoded.image_format is None:
        return
    save_frame(decoded.image_bytes, output_dir, suffix=f".{decoded.image_format}")


async def _send_serialized(websocket: Any, payload: bytes | dict[str, Any]) -> None:
    if isinstance(payload, bytes):
        await websocket.send(payload)
        return
    await websocket.send(json.dumps(payload))


def _payload_key(payload: bytes | dict[str, Any] | None) -> bytes | str | None:
    if payload is None:
        return None
    if isinstance(payload, bytes):
        return payload
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _decode_json(payload: Any) -> Any:
    if not isinstance(payload, str):
        return payload
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return {"raw": payload}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the generated visual starter agent.")
    parser.add_argument("url", nargs="?", default=os.environ.get("COGAMES_ENGINE_WS_URL"))
    parser.add_argument("--max-frames", type=int)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    url = args.url
    if not url:
        print("Set COGAMES_ENGINE_WS_URL or pass a WebSocket URL.", file=sys.stderr)
        return 2
    asyncio.run(run(url, output_root=args.output_root, max_frames=args.max_frames))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def _render_capture_runner() -> str:
    return '''from __future__ import annotations

import asyncio
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from action_controller import validate_recommended_action
from frame_store import save_frame, save_json_message, write_label
from vlm_client import build_vlm_request, mock_vlm_response


DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parents[1] / "visual_bootstrap"


async def run(url: str, *, output_root: Path = DEFAULT_OUTPUT_ROOT, frame_limit: int = 25) -> None:
    frames_dir = output_root / "frames"
    labels_dir = output_root / "labels"
    play_card = output_root / "play_card.md"
    play_card_hash = hashlib.sha256(play_card.read_bytes()).hexdigest() if play_card.exists() else "missing"

    captured = 0
    try:
        import websockets
    except ModuleNotFoundError as exc:
        raise RuntimeError("Install the 'websockets' package to run this generated capture shell.") from exc

    async with websockets.connect(url) as websocket:
        async for raw_message in websocket:
            if isinstance(raw_message, bytes):
                record = save_frame(raw_message, frames_dir)
            else:
                message = _decode_json(raw_message)
                if isinstance(message, dict) and (message.get("type") == "final" or message.get("done") is True):
                    break
                record = save_json_message(message if isinstance(message, dict) else {"raw": str(raw_message)}, frames_dir)

            request = build_vlm_request(
                frame_id=record["frame_id"],
                frame_hash=record["frame_hash"],
                play_card_hash=play_card_hash,
            )
            response = mock_vlm_response(request)
            label = {
                "schema_version": "maker.visual_label.v1",
                "request": request,
                "response": response,
                "action_validation": validate_recommended_action(response),
                "stored_frame": record["path"],
            }
            write_label(label, labels_dir)
            captured += 1
            if captured >= frame_limit:
                break


def _decode_json(payload: Any) -> Any:
    if not isinstance(payload, str):
        return payload
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return {"raw": payload}


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture observations and write mock VLM labels.")
    parser.add_argument("url", nargs="?", default=os.environ.get("COGAMES_ENGINE_WS_URL"))
    parser.add_argument("--frame-limit", type=int, default=25)
    args = parser.parse_args()
    url = args.url
    if not url:
        print("Set COGAMES_ENGINE_WS_URL or pass a WebSocket URL.", file=sys.stderr)
        return 2
    asyncio.run(run(url, frame_limit=max(1, args.frame_limit)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def _render_policy_tests(
    action_ids: tuple[str, ...],
    wire_contract: ActionWireContract,
) -> str:
    movement = [action for action in ("right", "down", "left", "up") if action in action_ids]
    expected = movement[0] if movement else wire_contract.default_action
    return f'''from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def _load_agent_module(module_name: str) -> ModuleType:
    path = Path(__file__).resolve().parents[1] / (module_name + ".py")
    unique_name = "_generated_" + Path(__file__).resolve().parents[2].name + "_" + module_name
    spec = importlib.util.spec_from_file_location(unique_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[unique_name] = module
    spec.loader.exec_module(module)
    return module


_policy = _load_agent_module("policy")
choose_action = _policy.choose_action
MOVEMENT_SEQUENCE = _policy.MOVEMENT_SEQUENCE


def test_policy_returns_known_action() -> None:
    assert choose_action(b"\\xff" * 8192, frame_index=0) == {expected!r}


def test_policy_uses_fallback_for_black_interstitial_frame() -> None:
    assert choose_action(b"\\x00" * 8192, frame_index=0) == _policy.DEFAULT_ACTION
'''


def _render_cyborg_agent_tests() -> str:
    return '''from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def _load_agent_module(module_name: str) -> ModuleType:
    path = Path(__file__).resolve().parents[1] / (module_name + ".py")
    unique_name = "_generated_" + Path(__file__).resolve().parents[2].name + "_" + module_name
    old_path = list(sys.path)
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(unique_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[unique_name] = module
    try:
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path[:] = old_path


_cyborg_agent = _load_agent_module("cyborg_agent")
StarterAgent = _cyborg_agent.StarterAgent
choose_runtime_action = _cyborg_agent.choose_runtime_action


def test_runtime_returns_known_action() -> None:
    action = choose_runtime_action(b"\\xff" * 8192, frame_index=0)
    assert action in {*_cyborg_agent.ACTIONS, "noop"}


def test_runtime_preserves_instance_between_steps() -> None:
    agent = StarterAgent()
    try:
        first = agent.choose_action(b"\\xff" * 8192, frame_index=0)
        second = agent.choose_action(b"\\xff" * 8192, frame_index=1)
    finally:
        agent.close()
    assert first in {*_cyborg_agent.ACTIONS, "noop"}
    assert second in {*_cyborg_agent.ACTIONS, "noop"}
'''


def _render_action_controller_tests(action_ids: tuple[str, ...]) -> str:
    fallback = (
        "noop"
        if "noop" in action_ids
        else ("stay" if "stay" in action_ids else (action_ids[0] if action_ids else "unknown"))
    )
    valid = fallback if fallback != "unknown" else (action_ids[0] if action_ids else "unknown")
    return f'''from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def _load_agent_module(module_name: str) -> ModuleType:
    path = Path(__file__).resolve().parents[1] / (module_name + ".py")
    unique_name = "_generated_" + Path(__file__).resolve().parents[2].name + "_" + module_name
    spec = importlib.util.spec_from_file_location(unique_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[unique_name] = module
    spec.loader.exec_module(module)
    return module


_action_controller = _load_agent_module("action_controller")
validate_recommended_action = _action_controller.validate_recommended_action


def test_valid_action_is_allowed() -> None:
    result = validate_recommended_action({{"recommended_action": {{"action_id": {valid!r}}}}})
    assert result["valid"] is True


def test_invalid_action_uses_fallback() -> None:
    result = validate_recommended_action({{"recommended_action": {{"action_id": "__bad__"}}}})
    assert result["valid"] is False
    assert result["action_id"] == {fallback!r}
'''


def _render_frame_store_tests() -> str:
    return '''from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType


def _load_agent_module(module_name: str) -> ModuleType:
    path = Path(__file__).resolve().parents[1] / (module_name + ".py")
    unique_name = "_generated_" + Path(__file__).resolve().parents[2].name + "_" + module_name
    spec = importlib.util.spec_from_file_location(unique_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[unique_name] = module
    spec.loader.exec_module(module)
    return module


_frame_store = _load_agent_module("frame_store")
save_frame = _frame_store.save_frame
save_json_message = _frame_store.save_json_message
write_label = _frame_store.write_label


def test_save_frame_hashes_and_writes_bytes(tmp_path: Path) -> None:
    record = save_frame(b"abc", tmp_path)
    assert record["size_bytes"] == 3
    assert Path(record["path"]).read_bytes() == b"abc"
    assert len(record["frame_hash"]) == 64


def test_save_json_message_and_label(tmp_path: Path) -> None:
    record = save_json_message({"type": "observation"}, tmp_path / "frames")
    assert json.loads(Path(record["path"]).read_text(encoding="utf-8"))["type"] == "observation"
    label_path = write_label({"request_id": "r1", "value": 1}, tmp_path / "labels")
    assert json.loads(label_path.read_text(encoding="utf-8"))["request_id"] == "r1"
'''


def _render_vlm_client_tests(action_ids: tuple[str, ...]) -> str:
    fallback = (
        "noop"
        if "noop" in action_ids
        else ("stay" if "stay" in action_ids else (action_ids[0] if action_ids else "unknown"))
    )
    return f'''from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def _load_agent_module(module_name: str) -> ModuleType:
    path = Path(__file__).resolve().parents[1] / (module_name + ".py")
    unique_name = "_generated_" + Path(__file__).resolve().parents[2].name + "_" + module_name
    spec = importlib.util.spec_from_file_location(unique_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[unique_name] = module
    spec.loader.exec_module(module)
    return module


_vlm_client = _load_agent_module("vlm_client")
build_vlm_request = _vlm_client.build_vlm_request
mock_vlm_response = _vlm_client.mock_vlm_response


def test_build_vlm_request() -> None:
    request = build_vlm_request(frame_id="f1", frame_hash="h1", play_card_hash="p1")
    assert request["schema_version"] == "maker.vlm_request.v1"
    assert request["frame_id"] == "f1"
    assert request["allowed_actions"] == {list(action_ids)!r}


def test_mock_vlm_response_shape() -> None:
    request = build_vlm_request(frame_id="f1", frame_hash="h1", play_card_hash="p1")
    response = mock_vlm_response(request)
    assert response["schema_version"] == "maker.vlm_frame.v1"
    assert response["request_id"] == request["request_id"]
    assert response["recommended_action"]["action_id"] == {fallback!r}
'''
