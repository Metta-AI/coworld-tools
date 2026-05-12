from __future__ import annotations

from pathlib import Path

import gymnasium as gym
import numpy as np
import pytest
from agent_policies.policies.cyborg.bitworld import among_them
from agent_policies.policies.cyborg.bitworld.among_them import (
    SCOUT_TASK_HOLD_TICKS,
    TASK_ICON_TARGET_X_OFFSET,
    TASK_ICON_TARGET_Y_OFFSET,
    TASK_ICON_TEMPLATE,
    BitWorldAmongThemBeaconPolicy,
    BitWorldAmongThemChampionPolicy,
    BitWorldAmongThemCircuitSentinelPolicy,
    BitWorldAmongThemCyborgPolicy,
    BitWorldAmongThemNativeAcePolicy,
    BitWorldAmongThemNotTooDumbPolicy,
    BitWorldAmongThemPathfinderPolicy,
    BitWorldAmongThemScoutPolicy,
    BitWorldAmongThemSignalRunnerPolicy,
    BitWorldAmongThemSleuthPolicy,
    BitWorldAmongThemTaskMarshalPolicy,
)
from pytest import MonkeyPatch

from mettagrid.bitworld import (
    BITWORLD_ACTION_COUNT,
    PACKED_FRAME_SHAPE,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    bitworld_action_index,
    bitworld_action_names,
    encode_buttons,
)
from mettagrid.policy.loader import resolve_policy_class_path
from mettagrid.policy.policy_env_interface import PolicyEnvInterface


class _FakeChoice:
    def __init__(self, text: str) -> None:
        self.message = type("FakeMessage", (), {"content": text})()


class _FakeCompletionResponse:
    def __init__(self, text: str) -> None:
        self.choices = [_FakeChoice(text)]


class _FakeChatCompletions:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs) -> _FakeCompletionResponse:
        self.calls.append(kwargs)
        return _FakeCompletionResponse(self.text)


class _FakeOpenAIClient:
    def __init__(self, text: str) -> None:
        self.chat = type("FakeChat", (), {})()
        self.chat.completions = _FakeChatCompletions(text)


class _FakeTextBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeAnthropicMessages:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs) -> object:
        self.calls.append(kwargs)
        return type("FakeResponse", (), {"content": [_FakeTextBlock(self.text)]})()


class _FakeAnthropicClient:
    def __init__(self, text: str) -> None:
        self.messages = _FakeAnthropicMessages(text)


class _FakeNimCore:
    def __init__(self, *, chat: str, role: int) -> None:
        self.chat = chat
        self.role_value = role

    def step_batch(self, raw_observations, raw_actions) -> None:
        del raw_observations
        raw_actions[:] = bitworld_action_index(encode_buttons(("a",)))

    def take_chat(self, agent_id: int) -> str:
        del agent_id
        chat = self.chat
        self.chat = ""
        return chat

    def role(self, agent_id: int) -> int:
        del agent_id
        return self.role_value

    def debug_stats(self, agent_id: int) -> dict[str, float]:
        del agent_id
        return {"interstitial": 1.0}


def test_bitworld_among_them_scout_moves_to_visible_task_icon() -> None:
    policy = BitWorldAmongThemScoutPolicy(_bitworld_policy_env_info())
    observations = np.zeros((1, 4, SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
    actions = np.full(1, -1, dtype=np.int32)

    observations[0, -1, SCREEN_HEIGHT // 2, -1] = 8
    policy.step_batch(observations, actions)

    observations[...] = 0
    _stamp_task_icon(
        observations[0, -1],
        SCREEN_WIDTH // 2 + 20 - TASK_ICON_TARGET_X_OFFSET,
        SCREEN_HEIGHT // 2 - TASK_ICON_TARGET_Y_OFFSET,
    )

    policy.step_batch(observations, actions)

    assert actions[0] == bitworld_action_index(encode_buttons(("right", "a")))


def test_bitworld_among_them_scout_holds_action_on_task() -> None:
    policy = BitWorldAmongThemScoutPolicy(_bitworld_policy_env_info())
    observations = np.zeros((1, 4, SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
    actions = np.full(1, -1, dtype=np.int32)

    observations[0, -1, SCREEN_HEIGHT // 2, -1] = 8
    policy.step_batch(observations, actions)

    observations[...] = 0
    _stamp_task_icon(
        observations[0, -1],
        SCREEN_WIDTH // 2 - TASK_ICON_TARGET_X_OFFSET,
        SCREEN_HEIGHT // 2 - TASK_ICON_TARGET_Y_OFFSET,
    )

    policy.step_batch(observations, actions)
    assert actions[0] == bitworld_action_index(encode_buttons(("a",)))

    observations[...] = 0
    observations[0, -1, SCREEN_HEIGHT // 2, -1] = 8
    for _ in range(SCOUT_TASK_HOLD_TICKS - 1):
        policy.step_batch(observations, actions)
        assert actions[0] == bitworld_action_index(encode_buttons(("a",)))


def test_bitworld_among_them_scout_ignores_unprimed_task_icon() -> None:
    policy = BitWorldAmongThemScoutPolicy(_bitworld_policy_env_info())
    observations = np.zeros((1, 4, SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
    _stamp_task_icon(
        observations[0, -1],
        SCREEN_WIDTH // 2 - TASK_ICON_TARGET_X_OFFSET,
        SCREEN_HEIGHT // 2 - TASK_ICON_TARGET_Y_OFFSET,
    )
    actions = np.full(1, -1, dtype=np.int32)

    policy.step_batch(observations, actions)

    assert actions[0] == bitworld_action_index(encode_buttons(("right", "a")))


def test_bitworld_among_them_scout_chases_task_radar() -> None:
    policy = BitWorldAmongThemScoutPolicy(_bitworld_policy_env_info())
    observations = np.zeros((2, 4, SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
    observations[0, -1, SCREEN_HEIGHT // 2, -1] = 8
    observations[1, -1, 0, SCREEN_WIDTH // 2] = 8
    actions = np.full(2, -1, dtype=np.int32)

    policy.step_batch(observations, actions)

    assert actions.tolist() == [
        bitworld_action_index(encode_buttons(("right", "a"))),
        bitworld_action_index(encode_buttons(("up", "a"))),
    ]


def test_bitworld_among_them_scout_patrols_without_radar() -> None:
    policy = BitWorldAmongThemScoutPolicy(_bitworld_policy_env_info(), seed=36)
    observations = np.zeros((1, 4, SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
    actions = np.full(1, -1, dtype=np.int32)

    policy.step_batch(observations, actions)

    assert actions[0] == bitworld_action_index(encode_buttons(("down", "a")))


def test_bitworld_among_them_scout_accepts_packed_frames() -> None:
    policy = BitWorldAmongThemScoutPolicy(_bitworld_policy_env_info())
    observations = np.zeros((1, *PACKED_FRAME_SHAPE), dtype=np.uint8)
    frame_index = (SCREEN_HEIGHT // 2) * SCREEN_WIDTH + (SCREEN_WIDTH - 1)
    byte_index = frame_index // 2
    observations[0, byte_index] = 8 << 4
    actions = np.full(1, -1, dtype=np.int32)

    policy.step_batch(observations, actions)

    assert actions[0] == bitworld_action_index(encode_buttons(("right", "a")))


def test_bitworld_among_them_scout_short_name_resolves() -> None:
    assert (
        resolve_policy_class_path("bitworld_among_them_scout")
        == "agent_policies.policies.cyborg.bitworld.among_them.BitWorldAmongThemScoutPolicy"
    )


def test_bitworld_among_them_cyborg_chases_state_task_arrow() -> None:
    policy = BitWorldAmongThemCyborgPolicy(_bitworld_policy_env_info())
    observations = _state_observations(1)
    observations[0, 0] = among_them.PHASE_PLAYING
    task_base = among_them.STATE_TASK_FEATURE_OFFSET
    observations[0, task_base] = among_them.KIND_TASK
    observations[0, task_base + 3] = among_them.TASK_INCOMPLETE | among_them.TASK_ARROW_VISIBLE
    observations[0, task_base + 5] = SCREEN_WIDTH - 1
    observations[0, task_base + 6] = SCREEN_HEIGHT // 2
    actions = np.full(1, -1, dtype=np.int32)

    actions[0] = _step_policy_agent(policy, 3, observations)

    assert actions[0] == bitworld_action_index(encode_buttons(("right", "a")))


def test_bitworld_among_them_cyborg_holds_active_state_task() -> None:
    policy = BitWorldAmongThemCyborgPolicy(_bitworld_policy_env_info())
    observations = _state_observations(1)
    observations[0, 0] = among_them.PHASE_PLAYING
    observations[0, among_them.HEADER_TASK_PROGRESS] = 12
    actions = np.full(1, -1, dtype=np.int32)

    policy.step_batch(observations, actions)

    assert actions[0] == bitworld_action_index(encode_buttons(("a",)))


def test_bitworld_among_them_cyborg_imposter_kills_lone_target() -> None:
    policy = BitWorldAmongThemCyborgPolicy(_bitworld_policy_env_info())
    observations = _state_observations(1)
    observations[0, 0] = among_them.PHASE_PLAYING
    observations[0, among_them.HEADER_SELF_ROLE] = among_them.ROLE_IMPOSTER
    observations[0, among_them.HEADER_KILL_COOLDOWN] = among_them.KILL_READY_BYTE
    _write_player(observations[0], 0, SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2, among_them.PLAYER_SELF)
    _write_player(observations[0], 1, SCREEN_WIDTH // 2 + 4, SCREEN_HEIGHT // 2, 0)
    actions = np.full(1, -1, dtype=np.int32)

    policy.step_batch(observations, actions)

    assert actions[0] == bitworld_action_index(encode_buttons(("a",)))


def test_bitworld_among_them_cyborg_declared_imposter_uses_imposter_play() -> None:
    policy = BitWorldAmongThemCyborgPolicy(
        _bitworld_policy_env_info(),
        use_nim_core=False,
        declared_role="imposter",
    )
    observations = _state_observations(1)
    observations[0, 0] = among_them.PHASE_PLAYING
    actions = np.full(1, -1, dtype=np.int32)

    policy.step_batch(observations, actions)

    assert actions[0] == among_them.RIGHT_A_ACTION


def test_bitworld_among_them_cyborg_declared_role_bypasses_nim_core() -> None:
    policy = BitWorldAmongThemCyborgPolicy(
        _bitworld_policy_env_info(),
        use_nim_core=False,
        declared_role="imposter",
    )
    policy._nim_core = _FakeNimCore(chat="", role=0)
    observations = np.zeros((1, 4, SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
    actions = np.full(1, -1, dtype=np.int32)

    policy.step_batch(observations, actions)

    assert actions[0] == among_them.RIGHT_ACTION


def test_bitworld_among_them_cyborg_rejects_unknown_declared_role() -> None:
    with pytest.raises(ValueError, match="declared_role"):
        BitWorldAmongThemCyborgPolicy(_bitworld_policy_env_info(), declared_role="detective")


def test_bitworld_among_them_cyborg_votes_skip_and_talks() -> None:
    policy = BitWorldAmongThemCyborgPolicy(_bitworld_policy_env_info(), vote_listen_ticks=0)
    observations = _state_observations(1)
    observations[0, 0] = among_them.PHASE_VOTING
    observations[0, among_them.HEADER_VOTE_CURSOR] = 6
    for player_index in range(5):
        _write_player(observations[0], player_index, 10 + player_index * 8, 4, 0)
    actions = np.full(1, -1, dtype=np.int32)

    actions[0] = _step_policy_agent(policy, 2, observations)

    assert actions[0] == bitworld_action_index(encode_buttons(("a",)))
    assert policy.bitworld_chat_messages([2]) == ["skip unless sus"]


def test_bitworld_among_them_cyborg_uses_openai_talk_directive() -> None:
    fake_client = _FakeOpenAIClient('{"talk":"I found body near medbay; skip if no counter."}')
    policy = BitWorldAmongThemCyborgPolicy(
        _bitworld_policy_env_info(),
        vote_listen_ticks=0,
        llm_talk=True,
        llm_provider="openai",
        llm_client=fake_client,
        llm_model="fake-model",
    )
    policy._state(4).queued_chat = "body near medbay"
    observations = _state_observations(1)
    observations[0, 0] = among_them.PHASE_VOTING
    observations[0, among_them.HEADER_VOTE_CURSOR] = 1
    actions = np.full(1, -1, dtype=np.int32)

    actions[0] = _step_policy_agent(policy, 4, observations)

    assert policy.bitworld_chat_messages([4]) == ["I found body near medbay; skip if no counter."]
    call = fake_client.chat.completions.calls[0]
    assert call["model"] == "fake-model"
    assert call["response_format"] == {"type": "json_object"}
    assert "role: crewmate" in call["messages"][1]["content"]


def test_bitworld_among_them_cyborg_keeps_no_evidence_talk_local() -> None:
    fake_client = _FakeOpenAIClient('{"talk":"I saw nothing, skip."}')
    policy = BitWorldAmongThemCyborgPolicy(
        _bitworld_policy_env_info(),
        vote_listen_ticks=0,
        llm_talk=True,
        llm_provider="openai",
        llm_client=fake_client,
    )
    observations = _state_observations(1)
    observations[0, 0] = among_them.PHASE_VOTING
    observations[0, among_them.HEADER_VOTE_CURSOR] = 1
    actions = np.full(1, -1, dtype=np.int32)

    actions[0] = _step_policy_agent(policy, 4, observations)

    assert policy.bitworld_chat_messages([4]) == ["skip unless sus"]
    assert fake_client.chat.completions.calls == []


def test_bitworld_among_them_cyborg_routes_accusation_through_openai_talk() -> None:
    fake_client = _FakeOpenAIClient('{"talk":"orange sus near the body; I reported it."}')
    policy = BitWorldAmongThemCyborgPolicy(
        _bitworld_policy_env_info(),
        vote_listen_ticks=0,
        llm_talk=True,
        llm_provider="openai",
        llm_client=fake_client,
    )
    observations = _state_observations(1)
    observations[0, 0] = among_them.PHASE_PLAYING
    _write_player(observations[0], 0, SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2, among_them.PLAYER_SELF, color=0)
    _write_player(observations[0], 1, SCREEN_WIDTH // 2 + 5, SCREEN_HEIGHT // 2, 0, color=1)
    _write_body(observations[0], 0, SCREEN_WIDTH // 2 + 4, SCREEN_HEIGHT // 2, color=2)
    actions = np.full(1, -1, dtype=np.int32)

    policy.step_batch(observations, actions)

    voting = _state_observations(1)
    voting[0, 0] = among_them.PHASE_VOTING
    voting[0, among_them.HEADER_VOTE_CURSOR] = 2
    _write_player(voting[0], 0, 20, 4, among_them.PLAYER_SELF, color=0)
    _write_player(voting[0], 1, 36, 4, 0, color=1)
    policy.step_batch(voting, actions)

    assert actions[0] == bitworld_action_index(encode_buttons(("a",)))
    assert policy.bitworld_chat_messages([0]) == ["orange sus near the body; I reported it."]
    prompt = fake_client.chat.completions.calls[0]["messages"][1]["content"]
    assert "known_event: body reported; orange sus" in prompt
    assert "accusation_target: player_1" in prompt
    assert "accusation_color: orange" in prompt


def test_bitworld_among_them_cyborg_routes_nim_chat_evidence_through_llm() -> None:
    fake_client = _FakeOpenAIClient('{"talk":"orange sus from body report."}')
    policy = BitWorldAmongThemCyborgPolicy(
        _bitworld_policy_env_info(),
        llm_talk=True,
        llm_provider="openai",
        llm_client=fake_client,
        use_nim_core=False,
    )
    policy._nim_core = _FakeNimCore(chat="body in electrical sus orange", role=1)
    observations = np.zeros((1, 4, SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
    actions = np.full(1, -1, dtype=np.int32)

    policy.step_batch(observations, actions)

    assert actions[0] == bitworld_action_index(encode_buttons(("a",)))
    assert policy.bitworld_chat_messages([0]) == ["orange sus from body report."]
    prompt = fake_client.chat.completions.calls[0]["messages"][1]["content"]
    assert "known_event: body in electrical sus orange" in prompt
    assert "accusation_color: orange" in prompt


def test_bitworld_among_them_cyborg_uses_anthropic_talk_directive() -> None:
    fake_client = _FakeAnthropicClient('{"talk":"I was on wires; skip unless new evidence."}')
    policy = BitWorldAmongThemCyborgPolicy(
        _bitworld_policy_env_info(),
        vote_listen_ticks=0,
        llm_talk=True,
        llm_provider="anthropic",
        llm_client=fake_client,
        llm_model="fake-anthropic",
    )
    policy._state(1).queued_chat = "I was on wires"
    observations = _state_observations(1)
    observations[0, 0] = among_them.PHASE_VOTING
    observations[0, among_them.HEADER_VOTE_CURSOR] = 1
    actions = np.full(1, -1, dtype=np.int32)

    actions[0] = _step_policy_agent(policy, 1, observations)

    assert policy.bitworld_chat_messages([1]) == ["I was on wires; skip unless new evidence."]
    call = fake_client.messages.calls[0]
    assert call["model"] == "fake-anthropic"
    assert call["system"] == among_them.AMONGTHEM_LLM_SYSTEM_PROMPT
    assert "role: crewmate" in call["messages"][0]["content"]


def test_bitworld_among_them_cyborg_auto_provider_uses_anthropic_client() -> None:
    fake_client = _FakeAnthropicClient('{"talk":"orange sus from body report."}')
    policy = BitWorldAmongThemCyborgPolicy(
        _bitworld_policy_env_info(),
        vote_listen_ticks=0,
        llm_talk=True,
        llm_client=fake_client,
        llm_model="fake-anthropic",
    )
    policy._state(1).queued_chat = "body report sus orange"
    observations = _state_observations(1)
    observations[0, 0] = among_them.PHASE_VOTING
    observations[0, among_them.HEADER_VOTE_CURSOR] = 1
    actions = np.full(1, -1, dtype=np.int32)

    actions[0] = _step_policy_agent(policy, 1, observations)

    assert policy.bitworld_chat_messages([1]) == ["orange sus from body report."]
    assert fake_client.messages.calls[0]["model"] == "fake-anthropic"


def test_bitworld_among_them_llm_talk_is_clipped_to_chat_limit() -> None:
    directive = among_them.AmongThemMeetingDirective.model_validate(
        {"talk": "I was doing tasks in electrical, didn't see anything suspicious. Anyone find a body?"}
    )

    assert directive.talk == "I was doing tasks in electrical, didn't see anything suspicious. Anyone"


def test_bitworld_among_them_cyborg_short_name_resolves() -> None:
    assert (
        resolve_policy_class_path("bitworld_among_them_cyborg")
        == "agent_policies.policies.cyborg.bitworld.among_them.BitWorldAmongThemCyborgPolicy"
    )


def test_bitworld_among_them_signal_runner_uses_diagonal_radar() -> None:
    policy = BitWorldAmongThemSignalRunnerPolicy(_bitworld_policy_env_info())
    observations = np.zeros((1, 4, SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
    observations[0, -1, 0, 0] = 8
    actions = np.full(1, -1, dtype=np.int32)

    policy.step_batch(observations, actions)

    assert actions[0] == bitworld_action_index(encode_buttons(("up", "left", "a")))


def test_bitworld_among_them_signal_runner_sweeps_without_radar() -> None:
    policy = BitWorldAmongThemSignalRunnerPolicy(_bitworld_policy_env_info(), seed=56)
    observations = np.zeros((1, 4, SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
    actions = np.full(1, -1, dtype=np.int32)

    policy.step_batch(observations, actions)

    assert actions[0] == bitworld_action_index(encode_buttons(("down", "a")))


def test_bitworld_among_them_signal_runner_accepts_packed_frames() -> None:
    policy = BitWorldAmongThemSignalRunnerPolicy(_bitworld_policy_env_info())
    observations = np.zeros((1, *PACKED_FRAME_SHAPE), dtype=np.uint8)
    observations[0, 0] = 8
    actions = np.full(1, -1, dtype=np.int32)

    policy.step_batch(observations, actions)

    assert actions[0] == bitworld_action_index(encode_buttons(("up", "left", "a")))


def test_bitworld_among_them_signal_runner_short_name_resolves() -> None:
    assert (
        resolve_policy_class_path("amongthem_signal_runner")
        == "agent_policies.policies.cyborg.bitworld.among_them.BitWorldAmongThemSignalRunnerPolicy"
    )


def test_bitworld_among_them_beacon_remembers_lost_radar() -> None:
    policy = BitWorldAmongThemBeaconPolicy(_bitworld_policy_env_info())
    observations = np.full((1, 4, SCREEN_HEIGHT, SCREEN_WIDTH), 3, dtype=np.uint8)
    observations[0, -1, 0, 0] = 8
    actions = np.full(1, -1, dtype=np.int32)

    policy.step_batch(observations, actions)
    assert actions[0] == bitworld_action_index(encode_buttons(("up", "left", "a")))

    observations[...] = 3
    policy.step_batch(observations, actions)

    assert actions[0] == bitworld_action_index(encode_buttons(("up", "left", "a")))


def test_bitworld_among_them_beacon_votes_skip_and_chats_on_interstitial() -> None:
    policy = BitWorldAmongThemBeaconPolicy(_bitworld_policy_env_info())
    observations = np.zeros((1, 4, SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
    actions = np.full(1, -1, dtype=np.int32)

    policy.step_batch(observations, actions)

    assert actions[0] == bitworld_action_index(encode_buttons(("right",)))
    assert policy.bitworld_chat_messages([0]) == ["doing tasks; skip unless sus"]


def test_bitworld_among_them_beacon_uses_state_task_arrow() -> None:
    policy = BitWorldAmongThemBeaconPolicy(_bitworld_policy_env_info())
    observations = _state_observations(1)
    observations[0, 0] = among_them.PHASE_PLAYING
    task_base = among_them.STATE_TASK_FEATURE_OFFSET
    observations[0, task_base] = among_them.KIND_TASK
    observations[0, task_base + 3] = among_them.TASK_INCOMPLETE | among_them.TASK_ARROW_VISIBLE
    observations[0, task_base + 5] = SCREEN_WIDTH - 1
    observations[0, task_base + 6] = SCREEN_HEIGHT // 2
    actions = np.full(1, -1, dtype=np.int32)

    policy.step_batch(observations, actions)

    assert actions[0] == bitworld_action_index(encode_buttons(("right", "a")))


def test_bitworld_among_them_beacon_short_name_resolves() -> None:
    assert (
        resolve_policy_class_path("bitworld_among_them_beacon")
        == "agent_policies.policies.cyborg.bitworld.among_them.BitWorldAmongThemBeaconPolicy"
    )


def test_bitworld_among_them_task_marshal_preserves_native_action(monkeypatch: MonkeyPatch) -> None:
    native_action = bitworld_action_index(encode_buttons(("up", "right")))
    _install_fake_nottoodumb_core(monkeypatch, action=native_action)
    policy = BitWorldAmongThemTaskMarshalPolicy(_bitworld_policy_env_info())
    observations = np.full((1, 4, SCREEN_HEIGHT, SCREEN_WIDTH), 7, dtype=np.uint8)
    actions = np.full(1, -1, dtype=np.int32)

    policy.step_batch(observations, actions)

    assert actions[0] == native_action


def test_bitworld_among_them_task_marshal_talks_on_native_interstitial(monkeypatch: MonkeyPatch) -> None:
    _install_fake_nottoodumb_core(monkeypatch, interstitial=True)
    policy = BitWorldAmongThemTaskMarshalPolicy(_bitworld_policy_env_info())
    observations = np.full((1, 4, SCREEN_HEIGHT, SCREEN_WIDTH), 7, dtype=np.uint8)
    actions = np.full(1, -1, dtype=np.int32)

    policy.step_batch(observations, actions)

    assert policy.bitworld_chat_messages([0]) == ["skip unless sus"]


def test_bitworld_among_them_native_ace_leaves_interstitial_noop(monkeypatch: MonkeyPatch) -> None:
    _install_fake_nottoodumb_core(monkeypatch, interstitial=True)
    policy = BitWorldAmongThemNativeAcePolicy(_bitworld_policy_env_info())
    policy._ticks[0] = among_them.NOTTOODUMB_START_ACTION_TICKS + 1
    observations = np.full((1, 4, SCREEN_HEIGHT, SCREEN_WIDTH), 7, dtype=np.uint8)
    actions = np.full(1, -1, dtype=np.int32)

    policy.step_batch(observations, actions)

    assert actions[0] == among_them.NOOP_ACTION


def test_bitworld_among_them_native_ace_does_not_vote_on_sparse_playfield(monkeypatch: MonkeyPatch) -> None:
    _install_fake_nottoodumb_core(monkeypatch)
    policy = BitWorldAmongThemNativeAcePolicy(_bitworld_policy_env_info())
    policy._ticks[0] = among_them.NOTTOODUMB_START_ACTION_TICKS + 1
    observations = np.full((1, 4, SCREEN_HEIGHT, SCREEN_WIDTH), 7, dtype=np.uint8)
    observations[0, -1, :, :70] = 0
    actions = np.full(1, -1, dtype=np.int32)

    policy.step_batch(observations, actions)

    assert actions[0] != among_them.NOOP_ACTION


def test_bitworld_among_them_task_marshal_short_name_resolves() -> None:
    assert (
        resolve_policy_class_path("amongthem_task_marshal")
        == "agent_policies.policies.cyborg.bitworld.among_them.BitWorldAmongThemTaskMarshalPolicy"
    )


def test_bitworld_among_them_nottoodumb_short_name_resolves() -> None:
    assert BitWorldAmongThemNotTooDumbPolicy.short_names == ["bitworld_among_them_nottoodumb"]
    assert (
        resolve_policy_class_path("bitworld_among_them_nottoodumb")
        == "agent_policies.policies.cyborg.bitworld.among_them.BitWorldAmongThemNotTooDumbPolicy"
    )


def test_bitworld_among_them_nottoodumb_accepts_empty_agent_batch(monkeypatch: MonkeyPatch) -> None:
    class _FakeNotTooDumbCore:
        calls = 0

        def __init__(self, policy_env_info: PolicyEnvInterface, library_path: Path) -> None:
            del policy_env_info, library_path

        def step_batch(self, raw_observations, raw_actions) -> None:
            del raw_observations, raw_actions
            type(self).calls += 1

    monkeypatch.setattr(among_them, "_nottoodumb_library_path", lambda: Path("fake-nottoodumb"))
    monkeypatch.setattr(among_them, "_NotTooDumbCore", _FakeNotTooDumbCore)
    policy = BitWorldAmongThemNotTooDumbPolicy(_bitworld_policy_env_info())
    observations = np.zeros((0, 4, SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
    actions = np.full(0, -1, dtype=np.int32)

    policy.step_batch(observations, actions)

    assert _FakeNotTooDumbCore.calls == 0


def test_bitworld_among_them_variant_short_names_resolve() -> None:
    policy_classes = [
        BitWorldAmongThemBeaconPolicy,
        BitWorldAmongThemChampionPolicy,
        BitWorldAmongThemCircuitSentinelPolicy,
        BitWorldAmongThemNativeAcePolicy,
        BitWorldAmongThemPathfinderPolicy,
        BitWorldAmongThemSleuthPolicy,
    ]

    for policy_class in policy_classes:
        assert (
            resolve_policy_class_path(policy_class.short_names[0])
            == f"agent_policies.policies.cyborg.bitworld.among_them.{policy_class.__name__}"
        )


def test_bitworld_among_them_sleuth_votes_for_suspect_color() -> None:
    policy = BitWorldAmongThemSleuthPolicy(_bitworld_policy_env_info(), vote_listen_ticks=0)
    policy._state(0).accusation_target_color = "orange"
    observations = _state_observations(1)
    observations[0, 0] = among_them.PHASE_VOTING
    observations[0, among_them.HEADER_VOTE_CURSOR] = 2
    _write_player(observations[0], 0, 20, 4, among_them.PLAYER_SELF, color=0)
    _write_player(observations[0], 1, 36, 4, 0, color=1)

    actions = np.full(1, -1, dtype=np.int32)
    policy.step_batch(observations, actions)

    assert actions[0] == bitworld_action_index(encode_buttons(("a",)))


def test_bitworld_among_them_sleuth_kills_isolated_target_with_distant_witness() -> None:
    policy = BitWorldAmongThemSleuthPolicy(_bitworld_policy_env_info())
    observations = _state_observations(1)
    observations[0, 0] = among_them.PHASE_PLAYING
    observations[0, among_them.HEADER_SELF_ROLE] = among_them.ROLE_IMPOSTER
    observations[0, among_them.HEADER_KILL_COOLDOWN] = among_them.KILL_READY_BYTE
    _write_player(observations[0], 0, SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2, among_them.PLAYER_SELF)
    _write_player(observations[0], 1, SCREEN_WIDTH // 2 + 4, SCREEN_HEIGHT // 2, 0)
    _write_player(observations[0], 2, 8, 8, 0)

    actions = np.full(1, -1, dtype=np.int32)
    policy.step_batch(observations, actions)

    assert actions[0] == bitworld_action_index(encode_buttons(("a",)))


def test_bitworld_among_them_sleuth_avoids_kill_with_close_witness() -> None:
    policy = BitWorldAmongThemSleuthPolicy(_bitworld_policy_env_info())
    observations = _state_observations(1)
    observations[0, 0] = among_them.PHASE_PLAYING
    observations[0, among_them.HEADER_SELF_ROLE] = among_them.ROLE_IMPOSTER
    observations[0, among_them.HEADER_KILL_COOLDOWN] = among_them.KILL_READY_BYTE
    _write_player(observations[0], 0, SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2, among_them.PLAYER_SELF)
    _write_player(observations[0], 1, SCREEN_WIDTH // 2 + 4, SCREEN_HEIGHT // 2, 0)
    _write_player(observations[0], 2, SCREEN_WIDTH // 2 + 10, SCREEN_HEIGHT // 2, 0)

    actions = np.full(1, -1, dtype=np.int32)
    policy.step_batch(observations, actions)

    assert actions[0] != bitworld_action_index(encode_buttons(("a",)))


def test_bitworld_among_them_circuit_sentinel_ignores_native_core(monkeypatch: MonkeyPatch) -> None:
    class _ForbiddenNotTooDumbCore:
        def __init__(self, policy_env_info: PolicyEnvInterface, library_path: Path) -> None:
            del policy_env_info, library_path
            raise AssertionError("circuit sentinel must not load the native NotTooDumb core")

    monkeypatch.setattr(among_them, "_nottoodumb_library_path", lambda: Path("fake-nottoodumb"))
    monkeypatch.setattr(among_them, "_NotTooDumbCore", _ForbiddenNotTooDumbCore)

    policy = BitWorldAmongThemCircuitSentinelPolicy(_bitworld_policy_env_info())

    assert policy._nim_core is None


def test_bitworld_among_them_circuit_sentinel_moves_to_visible_task_icon() -> None:
    policy = BitWorldAmongThemCircuitSentinelPolicy(_bitworld_policy_env_info())
    observations = np.zeros((1, 4, SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
    _stamp_task_icon(
        observations[0, -1],
        SCREEN_WIDTH // 2 + 20 - TASK_ICON_TARGET_X_OFFSET,
        SCREEN_HEIGHT // 2 - TASK_ICON_TARGET_Y_OFFSET,
    )
    actions = np.full(1, -1, dtype=np.int32)

    policy.step_batch(observations, actions)

    assert actions[0] == bitworld_action_index(encode_buttons(("right", "a")))


def test_bitworld_among_them_circuit_sentinel_holds_centered_task_icon() -> None:
    policy = BitWorldAmongThemCircuitSentinelPolicy(_bitworld_policy_env_info())
    observations = np.zeros((1, 4, SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
    _stamp_task_icon(
        observations[0, -1],
        SCREEN_WIDTH // 2 - TASK_ICON_TARGET_X_OFFSET,
        SCREEN_HEIGHT // 2 - TASK_ICON_TARGET_Y_OFFSET,
    )
    actions = np.full(1, -1, dtype=np.int32)

    policy.step_batch(observations, actions)
    assert actions[0] == bitworld_action_index(encode_buttons(("a",)))

    observations[...] = 0
    policy.step_batch(observations, actions)

    assert actions[0] == bitworld_action_index(encode_buttons(("a",)))


def test_bitworld_among_them_circuit_sentinel_short_name_resolves() -> None:
    assert (
        resolve_policy_class_path("amongthem_circuit_sentinel")
        == "agent_policies.policies.cyborg.bitworld.among_them.BitWorldAmongThemCircuitSentinelPolicy"
    )


def test_bitworld_among_them_cyborg_emits_meeting_chat() -> None:
    policy = BitWorldAmongThemCyborgPolicy(_bitworld_policy_env_info(), use_nim_core=False, llm_talk=False)
    observations = np.zeros((1, 4, SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
    actions = np.full(1, -1, dtype=np.int32)

    actions[0] = _step_policy_agent(policy, 3, observations)

    assert actions[0] == bitworld_action_index(encode_buttons(("right",)))
    assert policy.bitworld_chat_messages([3]) == ["skip unless sus"]
    assert (
        resolve_policy_class_path("bitworld_among_them_cyborg")
        == "agent_policies.policies.cyborg.bitworld.among_them.BitWorldAmongThemCyborgPolicy"
    )


def test_bitworld_among_them_pathfinder_does_not_load_native_core(monkeypatch: MonkeyPatch) -> None:
    def fail_native_lookup() -> Path | None:
        raise AssertionError("pathfinder should not load the native NotTooDumb core")

    monkeypatch.setattr(among_them, "_nottoodumb_library_path", fail_native_lookup)

    policy = BitWorldAmongThemPathfinderPolicy(_bitworld_policy_env_info())
    observations = _state_observations(1)
    observations[0, 0] = among_them.PHASE_PLAYING
    task_base = among_them.STATE_TASK_FEATURE_OFFSET
    observations[0, task_base] = among_them.KIND_TASK
    observations[0, task_base + 3] = among_them.TASK_INCOMPLETE | among_them.TASK_ARROW_VISIBLE
    observations[0, task_base + 5] = SCREEN_WIDTH - 1
    observations[0, task_base + 6] = SCREEN_HEIGHT // 2
    actions = np.full(1, -1, dtype=np.int32)

    policy.step_batch(observations, actions)

    assert actions[0] == bitworld_action_index(encode_buttons(("right", "a")))


def test_bitworld_among_them_pathfinder_holds_visible_task_longer() -> None:
    policy = BitWorldAmongThemPathfinderPolicy(_bitworld_policy_env_info())
    observations = _state_observations(1)
    observations[0, 0] = among_them.PHASE_PLAYING
    task_base = among_them.STATE_TASK_FEATURE_OFFSET
    observations[0, task_base] = among_them.KIND_TASK
    observations[0, task_base + 1] = SCREEN_WIDTH // 2 - 6
    observations[0, task_base + 2] = SCREEN_HEIGHT // 2 - 18
    observations[0, task_base + 3] = among_them.TASK_INCOMPLETE | among_them.TASK_ICON_VISIBLE
    actions = np.full(1, -1, dtype=np.int32)

    policy.step_batch(observations, actions)

    assert actions[0] == bitworld_action_index(encode_buttons(("a",)))
    assert policy._state(0).hold_ticks == among_them.PATHFINDER_TASK_HOLD_TICKS


def test_bitworld_among_them_pathfinder_pixel_holds_visible_task() -> None:
    policy = BitWorldAmongThemPathfinderPolicy(_bitworld_policy_env_info())
    observations = np.full((1, 4, SCREEN_HEIGHT, SCREEN_WIDTH), 6, dtype=np.uint8)
    _stamp_task_icon(
        observations[0, -1],
        SCREEN_WIDTH // 2 - TASK_ICON_TARGET_X_OFFSET,
        SCREEN_HEIGHT // 2 - TASK_ICON_TARGET_Y_OFFSET,
    )
    actions = np.full(1, -1, dtype=np.int32)

    policy.step_batch(observations, actions)

    assert actions[0] == bitworld_action_index(encode_buttons(("a",)))
    assert policy._state(0).hold_ticks == among_them.PATHFINDER_TASK_HOLD_TICKS - 1

    observations[...] = 6
    policy.step_batch(observations, actions)

    assert actions[0] == bitworld_action_index(encode_buttons(("a",)))


def test_bitworld_among_them_pathfinder_pixel_pulses_radar_movement() -> None:
    policy = BitWorldAmongThemPathfinderPolicy(_bitworld_policy_env_info())
    observations = np.full((1, 4, SCREEN_HEIGHT, SCREEN_WIDTH), 6, dtype=np.uint8)
    observations[0, -1, SCREEN_HEIGHT // 2, -1] = among_them.TASK_RADAR_COLOR
    actions = np.full(1, -1, dtype=np.int32)

    policy.step_batch(observations, actions)

    assert actions[0] == bitworld_action_index(encode_buttons(("right", "a")))


def test_bitworld_among_them_pathfinder_imposter_chases_isolated_target() -> None:
    policy = BitWorldAmongThemPathfinderPolicy(_bitworld_policy_env_info())
    observations = _state_observations(1)
    observations[0, 0] = among_them.PHASE_PLAYING
    observations[0, among_them.HEADER_SELF_ROLE] = among_them.ROLE_IMPOSTER
    observations[0, among_them.HEADER_KILL_COOLDOWN] = among_them.KILL_READY_BYTE
    _write_player(observations[0], 0, SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2, among_them.PLAYER_SELF)
    _write_player(observations[0], 1, SCREEN_WIDTH // 2 + 24, SCREEN_HEIGHT // 2, 0)
    actions = np.full(1, -1, dtype=np.int32)

    policy.step_batch(observations, actions)

    assert actions[0] == bitworld_action_index(encode_buttons(("right",)))


def test_bitworld_among_them_pathfinder_imposter_ignores_crowded_target() -> None:
    policy = BitWorldAmongThemPathfinderPolicy(_bitworld_policy_env_info())
    observations = _state_observations(1)
    observations[0, 0] = among_them.PHASE_PLAYING
    observations[0, among_them.HEADER_SELF_ROLE] = among_them.ROLE_IMPOSTER
    observations[0, among_them.HEADER_KILL_COOLDOWN] = among_them.KILL_READY_BYTE
    _write_player(observations[0], 0, SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2, among_them.PLAYER_SELF)
    _write_player(observations[0], 1, SCREEN_WIDTH // 2 + 18, SCREEN_HEIGHT // 2, 0)
    _write_player(observations[0], 2, SCREEN_WIDTH // 2 + 22, SCREEN_HEIGHT // 2 + 2, 0)
    actions = np.full(1, -1, dtype=np.int32)

    policy.step_batch(observations, actions)

    assert actions[0] != bitworld_action_index(encode_buttons(("right",)))


def _bitworld_policy_env_info() -> PolicyEnvInterface:
    return PolicyEnvInterface.from_spaces(
        observation_space=gym.spaces.Box(low=0, high=15, shape=(4, SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8),
        action_space=gym.spaces.Discrete(BITWORLD_ACTION_COUNT),
        num_agents=5,
        action_names=bitworld_action_names(),
    )


def _state_observations(batch_size: int) -> np.ndarray:
    return np.zeros((batch_size, among_them.STATE_FEATURES), dtype=np.uint8)


def _step_policy_agent(policy, agent_id: int, observations: np.ndarray) -> int:
    slot_observations = np.zeros(
        (policy.policy_env_info.num_agents, *observations.shape[1:]),
        dtype=observations.dtype,
    )
    slot_observations[agent_id] = observations[0]
    slot_actions = np.full(policy.policy_env_info.num_agents, -1, dtype=np.int32)
    policy.step_batch(slot_observations, slot_actions)
    return int(slot_actions[agent_id])


def _install_fake_nottoodumb_core(
    monkeypatch: MonkeyPatch,
    action: int = among_them.NOOP_ACTION,
    *,
    interstitial: bool = False,
) -> None:
    class _FakeNotTooDumbCore:
        def __init__(self, policy_env_info: PolicyEnvInterface, library_path: Path) -> None:
            del policy_env_info, library_path

        def step_batch(self, raw_observations, raw_actions) -> None:
            del raw_observations
            raw_actions[:] = action

        def _normalize_observations(self, raw_observations):
            return raw_observations

        def debug_stats(self, agent_id: int) -> dict[str, float]:
            del agent_id
            return {"interstitial": float(interstitial)}

        def role(self, agent_id: int) -> int:
            del agent_id
            return 0

        def take_chat(self, agent_id: int) -> str:
            del agent_id
            return ""

    monkeypatch.setattr(among_them, "_nottoodumb_library_path", lambda: Path("fake-nottoodumb"))
    monkeypatch.setattr(among_them, "_NotTooDumbCore", _FakeNotTooDumbCore)


def _write_player(
    frame: np.ndarray,
    player_index: int,
    x: int,
    y: int,
    extra_flags: int,
    *,
    color: int = 0,
) -> None:
    base = among_them.STATE_PLAYER_FEATURE_OFFSET + player_index * among_them.STATE_PLAYER_FEATURES
    frame[base] = among_them.KIND_PLAYER
    frame[base + 1] = x
    frame[base + 2] = y
    frame[base + 3] = color
    frame[base + 4] = among_them.PLAYER_ALIVE | extra_flags


def _write_body(frame: np.ndarray, body_index: int, x: int, y: int, *, color: int) -> None:
    base = among_them.STATE_BODY_FEATURE_OFFSET + body_index * among_them.STATE_BODY_FEATURES
    frame[base] = among_them.KIND_BODY
    frame[base + 1] = x
    frame[base + 2] = y
    frame[base + 3] = color


def _stamp_task_icon(frame: np.ndarray, x: int, y: int) -> None:
    for row in range(TASK_ICON_TEMPLATE.shape[0]):
        for col in range(TASK_ICON_TEMPLATE.shape[1]):
            value = int(TASK_ICON_TEMPLATE[row, col])
            if value >= 0:
                frame[y + row, x + col] = value
