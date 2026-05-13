from __future__ import annotations

import json
import re
from pathlib import Path

from .artifacts import write_text
from .framework import AgentFrameworkRef, REQUIRED_CYBORG_SYMBOLS
from .guide_index import ActionCandidate, ActionWireContract, GuideBundle, ObservationSurface


def generate_symbolic_agent(
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
        agent_dir / "run_agent.py",
        test_dir / f"test_{test_prefix}_protocol.py",
        test_dir / f"test_{test_prefix}_policy.py",
        test_dir / f"test_{test_prefix}_cyborg_agent.py",
    )

    action_ids = tuple(action.action_id for action in actions)
    write_text(files[0], _render_agent_readme(bundle, surface, wire_contract, agent_framework))
    write_text(files[1], _render_framework_bootstrap(agent_framework))
    write_text(files[2], _render_cyborg_agent(action_ids, wire_contract))
    write_text(files[3], _render_protocol(action_ids, wire_contract))
    write_text(files[4], _render_policy(action_ids, wire_contract))
    write_text(files[5], _render_runner())
    write_text(files[6], _render_protocol_tests(action_ids, wire_contract))
    write_text(files[7], _render_policy_tests())
    write_text(files[8], _render_cyborg_agent_tests())
    return files


def _render_agent_readme(
    bundle: GuideBundle,
    surface: ObservationSurface,
    wire_contract: ActionWireContract,
    agent_framework: AgentFrameworkRef,
) -> str:
    return f"""# {bundle.game_slug} Generated Symbolic Agent

This is a generated `maker_v1` Phase 2 symbolic baseline.

It is intentionally small:

- `run_agent.py` connects to the player WebSocket URL from
  `COGAMES_ENGINE_WS_URL` or the first CLI argument.
- `framework_bootstrap.py` points the artifact at the Cyborg framework source
  tree and imports `{agent_framework.package}`.
- `cyborg_agent.py` adapts the generated starter policy into the Cyborg
  runtime: percept, belief, mode, strategy directive, and action resolver.
- `protocol.py` serializes selected action ids into the guide-derived wire
  format.
- `policy.py` contains a conservative starter policy helper for unit tests and
  iterative refinement.
- `tests/` contains game-scoped action serialization and starter policy tests.

Observation surface: `{surface.category}`.
Action wire style: `{wire_contract.style}`.
Agent framework: `{agent_framework.framework_dir}`
Framework package: `{agent_framework.package}`

## Run

```bash
python run_agent.py
```

This scaffold is an artifact, not toolkit code. Regenerate it from
`testbed/maker_v1` after changing the generator.
"""


def _test_module_prefix(game_slug: str, output_dir: Path) -> str:
    slug = re.sub(r"[^0-9A-Za-z_]+", "_", game_slug).strip("_").lower() or "game"
    output_name = re.sub(r"[^0-9A-Za-z_]+", "_", output_dir.name).strip("_").lower()
    if not output_name or output_name == slug:
        return slug
    return f"{slug}_{output_name}"


def _remove_legacy_generated_tests(test_dir: Path) -> None:
    paths = [
        *test_dir.glob("test_*_protocol.py"),
        *test_dir.glob("test_*_policy.py"),
        *test_dir.glob("test_*_cyborg_agent.py"),
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
        "from protocol import" in text
        or "from policy import" in text
        or "from cyborg_agent import" in text
    )
    uses_generated_importlib_loader = (
        "def _load_agent_module(module_name: str)" in text
        and 'Path(__file__).resolve().parents[1] / (module_name + ".py")' in text
    )
    loads_generated_agent = (
        '_load_agent_module("protocol")' in text or '_load_agent_module("policy")' in text
        or '_load_agent_module("cyborg_agent")' in text
    )
    return (uses_old_path_setup and imports_generated_agent) or (
        uses_generated_importlib_loader and loads_generated_agent
    )


def _render_framework_bootstrap(agent_framework: AgentFrameworkRef) -> str:
    required_symbols = json.dumps(list(REQUIRED_CYBORG_SYMBOLS), indent=4)
    return f'''from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import ModuleType


FRAMEWORK_DIR = Path({str(agent_framework.framework_dir)!r})
PACKAGE_SOURCE_ROOT = Path({str(agent_framework.package_source_root)!r})
PACKAGE_NAME = {agent_framework.package!r}
REQUIRED_SYMBOLS: list[str] = {required_symbols}


def load_cyborg_framework() -> ModuleType:
    for source_root in reversed(_candidate_source_roots()):
        if source_root.exists() and str(source_root) not in sys.path:
            sys.path.insert(0, str(source_root))
    try:
        module = importlib.import_module(PACKAGE_NAME)
    except ModuleNotFoundError as exc:
        missing = exc.name or ""
        framework_missing = (
            missing == PACKAGE_NAME
            or PACKAGE_NAME.startswith(missing + ".")
            or missing.startswith(PACKAGE_NAME + ".")
        )
        if not framework_missing:
            raise
        raise RuntimeError(
            "Generated agent requires the Cyborg framework package "
            f"{{PACKAGE_NAME!r}}. Set COGAMES_AGENTS_ROOT to the cogames-agents "
            f"checkout or COGBASE_AGENT_FRAMEWORK_DIR to the coborg_framework "
            f"directory. Tried framework_dir={{FRAMEWORK_DIR}} and "
            f"package_source_root={{PACKAGE_SOURCE_ROOT}}."
        ) from exc
    _validate_cyborg_api(module)
    return module


def _candidate_source_roots() -> list[Path]:
    roots: list[Path] = []
    cogames_root = os.environ.get("COGAMES_AGENTS_ROOT")
    if cogames_root:
        roots.append(Path(cogames_root).expanduser() / "src")
    framework_dir = os.environ.get("COGBASE_AGENT_FRAMEWORK_DIR")
    if framework_dir:
        roots.append(Path(framework_dir).expanduser().parent / "src")
    roots.append(PACKAGE_SOURCE_ROOT)
    return roots


def _validate_cyborg_api(module: ModuleType) -> None:
    missing = [symbol for symbol in REQUIRED_SYMBOLS if not hasattr(module, symbol)]
    if not missing:
        return
    raise RuntimeError(
        "Generated agent requires the Cyborg framework API exported by "
        f"{{PACKAGE_NAME!r}}, but the imported module is missing: "
        f"{{', '.join(missing)}}. Verify COGAMES_AGENTS_ROOT or "
        "COGBASE_AGENT_FRAMEWORK_DIR points at a complete cogames-agents checkout."
    )
'''


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
    observation: dict[str, Any]
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Percept:
    observation: dict[str, Any]
    config: dict[str, Any]
    tick: int


@dataclass
class Belief:
    observation: dict[str, Any] = field(default_factory=dict)
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
        action = choose_policy_action(belief.observation, belief.config)
        return ActionIntent(semantic=action, reason="guide-derived starter policy")


class StarterStrategy:
    def decide(self, snapshot: Any) -> Any:
        del snapshot
        return ModeDirective(
            mode="heuristic",
            source="generated_rule_strategy",
            ttl_ticks=120,
            reason="run the generated conservative starter mode",
        )


def perceive(envelope: ObservationEnvelope, tick: int) -> Percept:
    return Percept(observation=envelope.observation, config=envelope.config, tick=tick)


def update_belief(belief: Belief, percept: Percept) -> None:
    belief.observation = percept.observation
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
        observation: dict[str, Any],
        config: dict[str, Any] | None = None,
    ) -> str:
        command = self.runtime.step(ObservationEnvelope(observation, config or {{}}))
        return str(getattr(command, "action", DEFAULT_ACTION))

    def close(self) -> None:
        self.runtime.close()


def choose_runtime_action(
    observation: dict[str, Any],
    config: dict[str, Any] | None = None,
) -> str:
    agent = StarterAgent()
    try:
        return agent.choose_action(observation, config)
    finally:
        agent.close()
'''


def _render_protocol(
    action_ids: tuple[str, ...],
    wire_contract: ActionWireContract,
) -> str:
    actions_json = json.dumps(list(action_ids), indent=4)
    return f'''from __future__ import annotations

from typing import Any


ACTIONS: list[str] = {actions_json}
ACTION_WIRE_STYLE = {wire_contract.style!r}
DEFAULT_ACTION = {wire_contract.default_action!r}


def normalize_action(action_id: str | None, config: dict[str, Any] | None = None) -> str:
    action_names = _action_names(config)
    if action_id in action_names:
        return str(action_id)
    if DEFAULT_ACTION in action_names:
        return DEFAULT_ACTION
    if "noop" in action_names:
        return "noop"
    return action_names[0] if action_names else DEFAULT_ACTION


def serialize_action(action_id: str | None, config: dict[str, Any] | None = None) -> dict[str, Any]:
    action = normalize_action(action_id, config)
    if ACTION_WIRE_STYLE == "move_json":
        return {{"move": action}}
    if ACTION_WIRE_STYLE == "action_name_json":
        return {{"type": "action", "action_name": action}}
    if ACTION_WIRE_STYLE == "action_index_json":
        action_names = _action_names(config)
        try:
            action_index = action_names.index(action)
        except ValueError:
            action_index = 0
        return {{"type": "action", "action_index": action_index}}
    return {{}}


def is_terminal_message(message: Any) -> bool:
    return isinstance(message, dict) and (message.get("type") == "final" or message.get("done") is True)


def _action_names(config: dict[str, Any] | None) -> list[str]:
    if isinstance(config, dict):
        names = config.get("action_names")
        if _is_string_list(names):
            return list(names)
        policy_env = config.get("policy_env")
        if isinstance(policy_env, dict):
            names = policy_env.get("action_names")
            if _is_string_list(names):
                return list(names)
    return list(ACTIONS)


def _is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)
'''


def _render_policy(
    action_ids: tuple[str, ...],
    wire_contract: ActionWireContract,
) -> str:
    actions_json = json.dumps(list(action_ids), indent=4)
    return f'''from __future__ import annotations

from typing import Any


ACTIONS: list[str] = {actions_json}
DEFAULT_ACTION = {wire_contract.default_action!r}


def choose_action(observation: dict[str, Any], config: dict[str, Any] | None = None) -> str:
    if not isinstance(observation, dict):
        return DEFAULT_ACTION
    if _looks_like_paint_arena(observation):
        return _paint_arena_sweep(observation)
    if "noop" in ACTIONS:
        return "noop"
    if DEFAULT_ACTION in ACTIONS:
        return DEFAULT_ACTION
    return ACTIONS[0] if ACTIONS else "noop"


def _looks_like_paint_arena(observation: dict[str, Any]) -> bool:
    required = {{"slot", "width", "height", "positions", "tile_owners"}}
    return required.issubset(observation)


def _paint_arena_sweep(observation: dict[str, Any]) -> str:
    if not {{"up", "down", "left", "right", "stay"}}.issubset(ACTIONS):
        return DEFAULT_ACTION

    slot = observation.get("slot")
    positions = observation.get("positions")
    width = observation.get("width")
    height = observation.get("height")
    if not isinstance(slot, int) or not isinstance(positions, list):
        return "stay"
    if not isinstance(width, int) or not isinstance(height, int) or width < 1 or height < 1:
        return "stay"
    if slot < 0 or slot >= len(positions) or not isinstance(positions[slot], list):
        return "stay"
    if len(positions[slot]) < 2:
        return "stay"

    x, y = positions[slot][0], positions[slot][1]
    if not isinstance(x, int) or not isinstance(y, int):
        return "stay"

    if slot == 0:
        if y % 2 == 0:
            return "right" if x < width - 1 else ("down" if y < height - 1 else "stay")
        return "left" if x > 0 else ("down" if y < height - 1 else "stay")

    if y % 2 == 0:
        return "left" if x > 0 else ("up" if y > 0 else "stay")
    return "right" if x < width - 1 else ("up" if y > 0 else "stay")
'''


def _render_runner() -> str:
    return '''from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

from cyborg_agent import StarterAgent
from protocol import is_terminal_message, serialize_action


async def run(url: str) -> None:
    config: dict[str, Any] = {}
    agent = StarterAgent()
    try:
        import websockets
    except ModuleNotFoundError as exc:
        raise RuntimeError("Install the 'websockets' package to run this generated agent.") from exc

    try:
        async with websockets.connect(url) as websocket:
            async for raw_message in websocket:
                message = json.loads(raw_message)
                if not isinstance(message, dict):
                    continue
                if message.get("type") == "player_config":
                    config = message
                    continue
                if is_terminal_message(message):
                    break
                if message.get("type") != "observation":
                    continue
                action_id = agent.choose_action(message, config)
                await websocket.send(json.dumps(serialize_action(action_id, config)))
    finally:
        agent.close()


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("COGAMES_ENGINE_WS_URL")
    if not url:
        print("Set COGAMES_ENGINE_WS_URL or pass a WebSocket URL.", file=sys.stderr)
        return 2
    asyncio.run(run(url))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def _render_protocol_tests(
    action_ids: tuple[str, ...],
    wire_contract: ActionWireContract,
) -> str:
    default = wire_contract.default_action
    if wire_contract.style == "move_json":
        assertion = f'assert serialize_action({default!r}) == {{"move": {default!r}}}'
    elif wire_contract.style == "action_name_json":
        assertion = f'assert serialize_action({default!r}) == {{"type": "action", "action_name": {default!r}}}'
    elif wire_contract.style == "action_index_json":
        assertion = f'assert serialize_action({default!r}) == {{"type": "action", "action_index": 0}}'
    else:
        assertion = "assert serialize_action(DEFAULT_ACTION) == {}"

    return f'''from __future__ import annotations

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


_protocol = _load_agent_module("protocol")
DEFAULT_ACTION = _protocol.DEFAULT_ACTION
is_terminal_message = _protocol.is_terminal_message
serialize_action = _protocol.serialize_action


def test_serialize_default_action() -> None:
    {assertion}


def test_invalid_action_falls_back() -> None:
    assert serialize_action("__invalid__") == serialize_action(DEFAULT_ACTION)


def test_terminal_message_detection() -> None:
    assert is_terminal_message({{"type": "final"}})
    assert is_terminal_message({{"done": True}})
    assert not is_terminal_message({{"type": "observation"}})
'''


def _render_policy_tests() -> str:
    return '''from __future__ import annotations

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
ACTIONS = _policy.ACTIONS
choose_action = _policy.choose_action


def test_choose_action_returns_known_action() -> None:
    assert choose_action({}) in {*ACTIONS, "noop"}


def test_paint_arena_sweep_when_supported() -> None:
    if not {"up", "down", "left", "right", "stay"}.issubset(ACTIONS):
        return

    action = choose_action(
        {
            "slot": 0,
            "width": 3,
            "height": 2,
            "positions": [[0, 0], [2, 1]],
            "tile_owners": [-1, -1, -1, -1, -1, -1],
        }
    )
    assert action == "right"
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
    action = choose_runtime_action({})
    assert action in {*_cyborg_agent.ACTIONS, "noop"}


def test_runtime_preserves_instance_between_steps() -> None:
    agent = StarterAgent()
    try:
        first = agent.choose_action({})
        second = agent.choose_action({})
    finally:
        agent.close()
    assert first in {*_cyborg_agent.ACTIONS, "noop"}
    assert second in {*_cyborg_agent.ACTIONS, "noop"}
'''
