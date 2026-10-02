from __future__ import annotations

import builtins
from typing import Any

import pytest

import types

from players.player_sdk import (
    DEFAULT_BEDROCK_MODEL,
    DEFAULT_DIRECT_MODEL,
    bedrock_base_url,
    bedrock_enabled,
    call_json,
    extract_json_object,
    resolve_model,
    response_text,
    select_client,
    usage_dict,
)


def _fake_anthropic_import(monkeypatch: pytest.MonkeyPatch, captured: dict[str, Any]) -> None:
    """Make ``from anthropic import AnthropicBedrock`` yield a recorder of init kwargs."""

    class FakeAnthropicBedrock:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    fake_module = types.ModuleType("anthropic")
    fake_module.AnthropicBedrock = FakeAnthropicBedrock  # type: ignore[attr-defined]
    real_import = builtins.__import__

    def fake_import(
        name: str,
        globals_: dict[str, Any] | None = None,
        locals_: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        if name == "anthropic" and "AnthropicBedrock" in fromlist:
            return fake_module
        return real_import(name, globals_, locals_, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)


class TextBlock:
    def __init__(self, text: Any) -> None:
        self.text = text


class FakeResponse:
    def __init__(self, *, content: Any = None, usage: Any = None) -> None:
        self.content = content
        self.usage = usage


def test_bedrock_enabled_reads_standard_and_extra_flags() -> None:
    assert bedrock_enabled({"USE_BEDROCK": "true"})
    assert bedrock_enabled({"CLAUDE_CODE_USE_BEDROCK": "YES"})
    assert bedrock_enabled({"CREWBORG_USE_BEDROCK": "on"}, extra_names=("CREWBORG_USE_BEDROCK",))
    assert not bedrock_enabled({})
    assert not bedrock_enabled({"USE_BEDROCK": "0", "CLAUDE_CODE_USE_BEDROCK": "false"})


def test_resolve_model_prefers_explicit_then_backend_default() -> None:
    assert (
        resolve_model(
            use_bedrock=True,
            direct_model=DEFAULT_DIRECT_MODEL,
            bedrock_model=DEFAULT_BEDROCK_MODEL,
            explicit="custom-model",
        )
        == "custom-model"
    )
    assert (
        resolve_model(
            use_bedrock=True,
            direct_model=DEFAULT_DIRECT_MODEL,
            bedrock_model=DEFAULT_BEDROCK_MODEL,
        )
        == DEFAULT_BEDROCK_MODEL
    )
    assert (
        resolve_model(
            use_bedrock=False,
            direct_model=DEFAULT_DIRECT_MODEL,
            bedrock_model=DEFAULT_BEDROCK_MODEL,
        )
        == DEFAULT_DIRECT_MODEL
    )


def test_extract_json_object_slices_surrounding_prose() -> None:
    assert extract_json_object('before {"action":"wait","confidence":0.2} after') == (
        '{"action":"wait","confidence":0.2}'
    )


def test_extract_json_object_raises_when_missing() -> None:
    with pytest.raises(ValueError, match="LLM response did not contain a JSON object"):
        extract_json_object("there is no object here")


def test_response_text_collects_supported_block_shapes() -> None:
    response = FakeResponse(
        content=[
            TextBlock(" object "),
            {"text": "dict"},
            " str ",
            TextBlock(None),
            {"text": 123},
        ]
    )

    assert response_text(response) == "object dict str"


def test_response_text_handles_empty_or_none_content() -> None:
    assert response_text(FakeResponse(content=None)) == ""
    assert response_text(FakeResponse(content=[])) == ""
    assert response_text(object()) == ""


def test_usage_dict_handles_none_and_dict() -> None:
    assert usage_dict(FakeResponse()) is None

    raw = {"input_tokens": 3, "output_tokens": 5}
    result = usage_dict(FakeResponse(usage=raw))

    assert result == raw
    assert result is not raw


def test_usage_dict_handles_model_dump() -> None:
    class DumpUsage:
        def model_dump(self, *, mode: str) -> dict[str, Any]:
            assert mode == "json"
            return {"input_tokens": 7}

    assert usage_dict(FakeResponse(usage=DumpUsage())) == {"input_tokens": 7}


def test_usage_dict_handles_token_attrs() -> None:
    class AttrUsage:
        input_tokens = 11
        output_tokens = 13
        ignored = 17

    assert usage_dict(FakeResponse(usage=AttrUsage())) == {
        "input_tokens": 11,
        "output_tokens": 13,
    }


def test_call_json_forwards_messages_create_args_and_returns_metadata() -> None:
    class FakeMessages:
        def __init__(self, response: FakeResponse) -> None:
            self.response = response
            self.calls: list[dict[str, Any]] = []

        def create(
            self,
            *,
            model: str,
            max_tokens: int,
            system: str,
            messages: list[dict[str, str]],
            extra_body: dict[str, Any],
        ) -> FakeResponse:
            self.calls.append(
                {
                    "model": model,
                    "max_tokens": max_tokens,
                    "system": system,
                    "messages": messages,
                    "metadata": extra_body["metadata"],
                }
            )
            return self.response

    class FakeClient:
        def __init__(self, response: FakeResponse) -> None:
            self.messages = FakeMessages(response)

    response = FakeResponse(content=[{"text": '{"ok":true}'}], usage={"input_tokens": 1})
    client = FakeClient(response)

    result = call_json(
        client,
        model="model-id",
        system="system prompt",
        user="user payload",
        max_tokens=123,
        metadata={"source": "test"},
    )

    assert client.messages.calls == [
        {
            "model": "model-id",
            "max_tokens": 123,
            "system": "system prompt",
            "messages": [{"role": "user", "content": "user payload"}],
            "metadata": {"source": "test"},
        }
    ]
    assert result.text == '{"ok":true}'
    assert result.usage == {"input_tokens": 1}
    assert result.model == "model-id"
    assert isinstance(result.latency_ms, float)
    assert result.latency_ms >= 0.0


def test_bedrock_base_url_uses_only_local_override() -> None:
    assert bedrock_base_url({}) is None
    assert bedrock_base_url({"AWS_ENDPOINT_URL_BEDROCK_RUNTIME": "http://retired.invalid"}) is None
    assert bedrock_base_url({"ANTHROPIC_BEDROCK_BASE_URL": "https://local.example"}) == "https://local.example"


def test_hosted_client_and_model_override_local_configuration(monkeypatch):
    import anthropic

    captured = {}
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kwargs: captured.update(kwargs))
    monkeypatch.setenv("COWORLD_LLM_ENDPOINT", "http://127.0.0.1:9100/")
    monkeypatch.setenv("COWORLD_LLM_MODEL", "anthropic/claude-sonnet-4.6")
    monkeypatch.setenv("AWS_ENDPOINT_URL_BEDROCK_RUNTIME", "http://retired.invalid")
    select_client(use_bedrock=True, timeout=2.0)
    assert captured == {"base_url": "http://127.0.0.1:9100", "api_key": "sidecar", "timeout": 2.0, "max_retries": 0}
    assert resolve_model(use_bedrock=True, direct_model="direct", bedrock_model="bedrock", explicit="local") == "anthropic/claude-sonnet-4.6"


def test_select_client_bedrock_direct_when_no_sidecar_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    _fake_anthropic_import(monkeypatch, captured)
    monkeypatch.delenv("ANTHROPIC_BEDROCK_BASE_URL", raising=False)
    monkeypatch.delenv("AWS_ENDPOINT_URL_BEDROCK_RUNTIME", raising=False)

    select_client(use_bedrock=True, timeout=2.0)

    # No endpoint override -> AnthropicBedrock targets real AWS (no base_url passed).
    assert captured == {"timeout": 2.0}


def test_select_client_bedrock_missing_extra_raises_actionable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def fake_import(
        name: str,
        globals_: dict[str, Any] | None = None,
        locals_: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        if name == "anthropic" and "AnthropicBedrock" in fromlist:
            raise ImportError("No module named boto3")
        return real_import(name, globals_, locals_, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(RuntimeError, match=r"players\[bedrock\]"):
        select_client(use_bedrock=True, timeout=1.0)


def test_native_messages_sends_sampling_in_supported_sdk_body(monkeypatch) -> None:
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append((self.path, body))
            response = json.dumps({
                'id': 'msg_native', 'type': 'message', 'role': 'assistant',
                'model': body['model'], 'stop_reason': 'end_turn', 'stop_sequence': None,
                'content': [{'type': 'text', 'text': '{"ok":true}'}],
                'usage': {'input_tokens': 10, 'output_tokens': 3},
            }).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv('COWORLD_LLM_ENDPOINT', f'http://127.0.0.1:{server.server_port}')
    try:
        client = select_client(use_bedrock=True, timeout=3)
        response = call_json(client, model='anthropic/claude-haiku-4.5',
                             system='rules', user='state', max_tokens=32, temperature=0.2)
        assert response.text == '{"ok":true}'
        assert response.usage['input_tokens'] == 10
        client.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert requests == [('/v1/messages', {
        'model': 'anthropic/claude-haiku-4.5', 'system': 'rules', 'max_tokens': 32,
        'messages': [{'role': 'user', 'content': 'state'}], 'temperature': 0.2,
    })]
