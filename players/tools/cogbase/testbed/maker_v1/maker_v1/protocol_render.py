"""Shared renderers for the generated ``protocol.py`` and its tests.

Single source of truth for protocol serialization output. Both
:mod:`symbolic_agent` and :mod:`visual_agent` call into this module so the
``binary_button_mask`` / ``move_json`` / ``action_name_json`` /
``action_index_json`` branches stay in lockstep. New wire styles get
added here, not in either agent generator.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from .guide_index import ActionWireContract


_JSON_ASSERTION_RENDERERS: dict[str, Callable[[str], str]] = {
    "move_json": lambda default: f'assert serialize_action({default!r}) == {{"move": {default!r}}}',
    "action_name_json": lambda default: f'assert serialize_action({default!r}) == {{"type": "action", "action_name": {default!r}}}',
    "action_index_json": lambda default: f'assert serialize_action({default!r}) == {{"type": "action", "action_index": 0}}',
}


def render_protocol(
    action_ids: tuple[str, ...],
    wire_contract: ActionWireContract,
) -> str:
    actions_json = json.dumps(list(action_ids), indent=4)
    payloads_json = json.dumps(wire_contract.action_payloads, indent=4, sort_keys=True)
    return f'''from __future__ import annotations

from typing import Any


ACTIONS: list[str] = {actions_json}
ACTION_WIRE_STYLE = {wire_contract.style!r}
DEFAULT_ACTION = {wire_contract.default_action!r}
ACTION_PAYLOADS: dict[str, int] = {payloads_json}


def normalize_action(action_id: str | None, config: dict[str, Any] | None = None) -> str:
    if ACTION_WIRE_STYLE == "binary_button_mask":
        return _normalize_with_names(action_id, list(ACTION_PAYLOADS))
    return _normalize_with_names(action_id, _action_names(config))


def _normalize_with_names(action_id: str | None, action_names: list[str]) -> str:
    if action_id in action_names:
        return str(action_id)
    if DEFAULT_ACTION in action_names:
        return DEFAULT_ACTION
    if "noop" in action_names:
        return "noop"
    return action_names[0] if action_names else DEFAULT_ACTION


def serialize_action(action_id: str | None, config: dict[str, Any] | None = None) -> bytes | dict[str, Any] | None:
    if ACTION_WIRE_STYLE == "binary_button_mask":
        action = _normalize_with_names(action_id, list(ACTION_PAYLOADS))
        if action not in ACTION_PAYLOADS:
            return None
        mask = ACTION_PAYLOADS[action] & 0x7F
        return bytes((0x00, mask))
    action_names = _action_names(config)
    action = _normalize_with_names(action_id, action_names)
    if ACTION_WIRE_STYLE == "move_json":
        return {{"move": action}}
    if ACTION_WIRE_STYLE == "action_name_json":
        return {{"type": "action", "action_name": action}}
    if ACTION_WIRE_STYLE == "action_index_json":
        try:
            action_index = action_names.index(action)
        except ValueError:
            action_index = 0
        return {{"type": "action", "action_index": action_index}}
    return None


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


def render_protocol_tests(wire_contract: ActionWireContract) -> str:
    assertion, fallback_assertion = _render_test_assertions(wire_contract)
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


_protocol = _load_agent_module("protocol")
DEFAULT_ACTION = _protocol.DEFAULT_ACTION
is_terminal_message = _protocol.is_terminal_message
serialize_action = _protocol.serialize_action


def test_serialize_supported_action() -> None:
    {assertion}


def test_invalid_action_falls_back() -> None:
    {fallback_assertion}


def test_terminal_message_detection() -> None:
    assert is_terminal_message({{"type": "final"}})
    assert is_terminal_message({{"done": True}})
    assert not is_terminal_message({{"type": "observation"}})
'''


def _render_test_assertions(wire_contract: ActionWireContract) -> tuple[str, str]:
    default = wire_contract.default_action
    fallback = f"assert serialize_action('__invalid__') == serialize_action({default!r})"

    if wire_contract.style == "binary_button_mask" and wire_contract.action_payloads:
        preferred = next(
            (action for action in ("right", "down", "left", "up") if action in wire_contract.action_payloads),
            default,
        )
        expected = bytes((0x00, wire_contract.action_payloads.get(preferred, 0) & 0x7F))
        return f"assert serialize_action({preferred!r}) == {expected!r}", fallback

    json_renderer = _JSON_ASSERTION_RENDERERS.get(wire_contract.style)
    if json_renderer is not None:
        return json_renderer(default), fallback

    return (
        "assert serialize_action(DEFAULT_ACTION) is None",
        "assert serialize_action('__invalid__') is None",
    )
