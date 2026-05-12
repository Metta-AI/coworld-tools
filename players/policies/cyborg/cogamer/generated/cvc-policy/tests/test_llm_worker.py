"""Tests for LLMWorker recorder emissions, using a fake Anthropic client."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from cvc_policy.cogamer_policy import CvCAgentState
from cvc_policy.llm_worker import LLMWorker, _build_status
from cvc_policy.recorder import EventRecorder


class _ToolUseBlock(SimpleNamespace):
    type = "tool_use"


class _TextBlock(SimpleNamespace):
    type = "text"


class _Response(SimpleNamespace):
    pass


class FakeAnthropicClient:
    """Scripts a sequence of responses returned by messages.create()."""

    def __init__(self) -> None:
        self._scripted: list[_Response] = []
        self._calls: list[dict[str, Any]] = []
        self.messages = SimpleNamespace(create=self._create)

    def queue_tool_use(self, tool: str, inp: dict[str, Any], block_id: str = "b1") -> None:
        block = _ToolUseBlock(id=block_id, name=tool, input=dict(inp))
        self._scripted.append(_Response(content=[block], stop_reason="tool_use"))

    def queue_end_turn(self, text: str = "done") -> None:
        block = _TextBlock(text=text)
        self._scripted.append(_Response(content=[block], stop_reason="end_turn"))

    def _create(self, **kwargs: Any) -> _Response:
        self._calls.append(kwargs)
        if not self._scripted:
            return _Response(
                content=[_TextBlock(text="stop")], stop_reason="end_turn"
            )
        return self._scripted.pop(0)


def _run_worker(client: FakeAnthropicClient, max_iters: int = 10, recorder: EventRecorder | None = None) -> LLMWorker:
    if recorder is None:
        recorder = EventRecorder()
    state = CvCAgentState()
    worker = LLMWorker(client, agent_id=0, state=state, recorder=recorder)
    from cvc_policy import llm_worker as lw
    orig = lw._STATUS_COOLDOWN_S
    lw._STATUS_COOLDOWN_S = 0.0
    try:
        for _ in range(max_iters):
            if worker._step_once():
                break
    finally:
        lw._STATUS_COOLDOWN_S = orig
    return worker


def test_get_status_emits_llm_turn():
    client = FakeAnthropicClient()
    client.queue_tool_use("get_status", {})
    client.queue_end_turn()
    worker = _run_worker(client)
    turn_events = [e for e in worker._recorder.events if e["type"] == "llm_turn"]
    assert len(turn_events) >= 1
    first = turn_events[0]
    assert first["stream"] == "llm"
    assert first["agent"] == 0
    assert "latency_ms" in first["payload"]
    assert any(tc["tool"] == "get_status" for tc in first["payload"]["tool_calls"])


def test_get_status_returns_dashboard():
    recorder = EventRecorder()
    # Seed some inventory events.
    recorder.emit(type="inventory", agent=0, stream="py", payload={
        "inventory": {"hp": 80, "heart": 2, "miner": 1},
        "role": "miner", "pos": [10, 20],
        "team_resources": {"carbon": 100, "oxygen": 50},
        "junctions": {"friendly": 3, "enemy": 1, "neutral": 40},
    })
    recorder.emit(type="action", agent=0, stream="py", payload={
        "summary": "mine_carbon", "role": "miner",
    })
    status = _build_status(recorder, agent_id=0)
    assert status["hp"] == 80
    assert status["role"] == "miner"
    assert status["position"] == [10, 20]
    assert status["gear"] == {"heart": 2, "miner": 1}
    assert status["team_resources"]["carbon"] == 100
    assert status["junctions"]["friendly"] == 3
    assert len(status["recent_actions"]) == 1


def test_trim_history_never_starts_with_assistant():
    client = FakeAnthropicClient()
    state = CvCAgentState()
    worker = LLMWorker(client, agent_id=0, state=state)
    initial = [{"role": "user", "content": "grounding"}]
    msgs = list(initial)
    for i in range(200):
        if i % 2 == 0:
            msgs.append(
                {
                    "role": "assistant",
                    "content": [_ToolUseBlock(id=f"t{i}", name="x", input={})],
                }
            )
        else:
            msgs.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": f"t{i - 1}",
                            "content": "ok",
                        }
                    ],
                }
            )
    trimmed = worker._trim_history(msgs)
    assert trimmed[0] is msgs[0]
    assert trimmed[0]["role"] == "user"
    if len(trimmed) > 1:
        assert trimmed[1]["role"] == "user"


def test_patch_tool_role_and_objective():
    client = FakeAnthropicClient()
    state = CvCAgentState()
    worker = LLMWorker(client, agent_id=0, state=state)
    out = worker._tool_patch(
        {"role": "scrambler", "objective": "expand", "rationale": "push"}
    )
    assert out["ok"] is True
    assert out["applied"]["role"] == "scrambler"
    assert out["applied"]["objective"] == "expand"
    assert state.llm_role_override == "scrambler"
    assert state.llm_objective == "expand"


def test_dispatch_unknown_tool():
    client = FakeAnthropicClient()
    state = CvCAgentState()
    worker = LLMWorker(client, agent_id=0, state=state)
    out = worker._dispatch_tool("nope", {})
    assert "error" in out


def test_stop_joins_thread():
    client = FakeAnthropicClient()
    client.queue_end_turn()
    state = CvCAgentState()
    worker = LLMWorker(client, agent_id=0, state=state)
    worker.start()
    worker.stop(timeout=2.0)
    assert worker._shutdown.is_set()


def test_trim_history_short_messages_unchanged():
    client = FakeAnthropicClient()
    state = CvCAgentState()
    worker = LLMWorker(client, agent_id=0, state=state)
    msgs = [{"role": "user", "content": "g"}, {"role": "assistant", "content": "a"}]
    out = worker._trim_history(msgs)
    assert out == msgs


def test_patch_tool_emits_patch_applied_event():
    client = FakeAnthropicClient()
    client.queue_tool_use(
        "patch",
        {"resource_bias": "carbon", "rationale": "low carbon supply"},
    )
    client.queue_end_turn()
    recorder = EventRecorder()
    _run_worker(client, recorder=recorder)
    patch_events = [e for e in recorder.events if e["type"] == "patch_applied"]
    assert len(patch_events) == 1
    assert patch_events[0]["payload"]["applied"] == {"resource_bias": "carbon"}
    assert patch_events[0]["payload"]["rationale"] == "low carbon supply"
    assert patch_events[0]["stream"] == "llm"


def test_world_model_skips_territory_observation_attrs():
    client = FakeAnthropicClient()
    entity = SimpleNamespace(
        entity_type="agent",
        position=(10, 20),
        last_seen_step=7,
        owner="team_0",
        team="team_0",
        attributes={
            "global_x": 10,
            "global_y": 20,
            "territory:here": 1,
            "territory:east": 1,
            "energy": 80,
        },
    )
    state = CvCAgentState(
        game_state=SimpleNamespace(
            world_model=SimpleNamespace(entities=lambda: [entity])
        )
    )
    worker = LLMWorker(client, agent_id=0, state=state)
    world_model = worker._tool_get_world_model({})

    assert world_model["count"] == 1
    assert world_model["entities"] == [
        {
            "type": "agent",
            "pos": [10, 20],
            "last_seen": 7,
            "owner": "team_0",
            "team": "team_0",
            "energy": 80,
        }
    ]
