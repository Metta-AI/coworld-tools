from __future__ import annotations

import gymnasium as gym

from amongcogs.agent.amongcogs_cyborg.policy import (
    AmongUsAnthropicCyborgAgent,
    AmongUsAnthropicCyborgPolicy,
    AmongUsMeetingDecision,
    _action_vote_label,
    _apply_discussion_decision,
    _ballot_talk_for_action,
    _build_meeting_prompt,
    _normalize_stance,
)
from amongcogs.game import VIBE_VOTE_SKIP, vote_target_vibe
from mettagrid.policy.loader import discover_and_register_policies, resolve_policy_class_path
from mettagrid.policy.policy import AgentPolicy
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.simulator import Action, Location, VisibleTalk
from mettagrid.simulator.interface import AgentObservation


class _FakeTextBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeMessages:
    def __init__(self, texts: str | list[str]) -> None:
        self._texts = [texts] if isinstance(texts, str) else list(texts)
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        assert self._texts
        text = self._texts[0] if len(self._texts) == 1 else self._texts.pop(0)
        return type("FakeResponse", (), {"content": [_FakeTextBlock(text)]})()


class _FakeClient:
    def __init__(self, texts: str | list[str]) -> None:
        self.messages = _FakeMessages(texts)


class _StubBaseAgent(AgentPolicy):
    def __init__(self, policy_env_info: PolicyEnvInterface, *, action: Action, infos: dict[str, object]) -> None:
        super().__init__(policy_env_info)
        self._action = action
        self._infos = infos
        self.steps = 0

    def step(self, obs: AgentObservation) -> Action:
        self.steps += 1
        return self._action


def _policy_env_info() -> PolicyEnvInterface:
    return PolicyEnvInterface.from_spaces(
        observation_space=gym.spaces.Box(low=0.0, high=1.0, shape=(4, 4), dtype=float),
        action_space=gym.spaces.Discrete(5),
        num_agents=4,
        action_names=["noop", "move_north", "move_south", "move_west", "move_east"],
        vibe_action_names=[f"change_vibe_{vote_target_vibe(1)}", "change_vibe_vote_skip"],
    ).model_copy(update={"game_label": "amongcogs_ship.basic"})


def _meeting_obs() -> AgentObservation:
    return AgentObservation(
        agent_id=0,
        tokens=[],
        talk=[VisibleTalk(agent_id=1, text="I found the body", location=Location(1, 1), remaining_steps=3)],
    )


def test_amongcogs_anthropic_cyborg_short_name_resolves() -> None:
    discover_and_register_policies("amongcogs.agent.amongcogs_cyborg")

    assert (
        resolve_policy_class_path("amongcogs-anthropic-cyborg")
        == "amongcogs.agent.amongcogs_cyborg.policy.AmongUsAnthropicCyborgPolicy"
    )


def test_amongcogs_anthropic_cyborg_discussion_overrides_talk_and_keeps_vote() -> None:
    policy_env_info = _policy_env_info()
    base_agent = _StubBaseAgent(
        policy_env_info,
        action=Action(
            name="noop",
            vibe=f"change_vibe_{VIBE_VOTE_SKIP}",
            talk="skip for now",
        ),
        infos={
            "alive": 1,
            "role": "crew",
            "meeting_active": 1,
            "meeting_discussion": 1,
            "meeting_ballot": 0,
            "meeting_reported_body": 1,
            "meeting_speakers": 1,
            "heard_talk": 1,
            "voted": 0,
        },
    )
    client = _FakeClient('{"talk":"body report points to agent-1","stance":"accuse"}')
    agent = AmongUsAnthropicCyborgAgent(
        policy_env_info,
        agent_id=0,
        desired_role="crew",
        client=client,
        model="fake-model",
        max_tokens=120,
        temperature=0.0,
        static_known={},
        spawn_pos=(0, 0),
        base_agent=base_agent,
    )

    action = agent.step(_meeting_obs())

    assert action.name == "noop"
    assert action.vibe == f"change_vibe_{VIBE_VOTE_SKIP}"
    assert action.talk == "body report points to agent-1"
    assert len(client.messages.calls) == 1


def test_amongcogs_anthropic_cyborg_caches_one_call_per_meeting() -> None:
    policy_env_info = _policy_env_info()
    base_agent = _StubBaseAgent(
        policy_env_info,
        action=Action(name="noop", vibe=f"change_vibe_{VIBE_VOTE_SKIP}", talk="skip for now"),
        infos={
            "alive": 1,
            "role": "crew",
            "meeting_active": 1,
            "meeting_discussion": 1,
            "meeting_ballot": 0,
            "meeting_reported_body": 1,
            "meeting_speakers": 1,
            "heard_talk": 1,
            "voted": 0,
        },
    )
    client = _FakeClient('{"talk":"agent-1 is suspicious","stance":"accuse"}')
    agent = AmongUsAnthropicCyborgAgent(
        policy_env_info,
        agent_id=0,
        desired_role="crew",
        client=client,
        model="fake-model",
        max_tokens=120,
        temperature=0.0,
        static_known={},
        spawn_pos=(0, 0),
        base_agent=base_agent,
    )

    first = agent.step(_meeting_obs())
    second = agent.step(_meeting_obs())

    assert first.vibe == f"change_vibe_{VIBE_VOTE_SKIP}"
    assert second.vibe == f"change_vibe_{VIBE_VOTE_SKIP}"
    assert len(client.messages.calls) == 1


def test_amongcogs_anthropic_cyborg_reuses_discussion_decision_in_ballot() -> None:
    policy_env_info = _policy_env_info()
    base_agent = _StubBaseAgent(
        policy_env_info,
        action=Action(name="noop", vibe=f"change_vibe_{VIBE_VOTE_SKIP}", talk="need a named suspect"),
        infos={
            "alive": 1,
            "role": "crew",
            "meeting_active": 1,
            "meeting_discussion": 1,
            "meeting_ballot": 0,
            "meeting_reported_body": 1,
            "meeting_speakers": 1,
            "heard_talk": 1,
            "voted": 0,
        },
    )
    client = _FakeClient('{"talk":"vote them out","stance":"accuse"}')
    agent = AmongUsAnthropicCyborgAgent(
        policy_env_info,
        agent_id=0,
        desired_role="crew",
        client=client,
        model="fake-model",
        max_tokens=120,
        temperature=0.0,
        static_known={},
        spawn_pos=(0, 0),
        base_agent=base_agent,
    )

    discussion_action = agent.step(_meeting_obs())
    base_agent._infos.update({"meeting_discussion": 0, "meeting_ballot": 1})
    ballot_action = agent.step(_meeting_obs())

    assert discussion_action.talk == "vote them out"
    assert discussion_action.vibe == f"change_vibe_{VIBE_VOTE_SKIP}"
    assert ballot_action.vibe == f"change_vibe_{VIBE_VOTE_SKIP}"
    assert ballot_action.talk == "ballot: skip."
    assert len(client.messages.calls) == 1


def test_amongcogs_anthropic_cyborg_does_not_weaken_report_accuse_vote() -> None:
    policy_env_info = _policy_env_info()
    base_agent = _StubBaseAgent(
        policy_env_info,
        action=Action(name="noop", vibe=f"change_vibe_{vote_target_vibe(1)}", talk="I found the body near Agent 1"),
        infos={
            "alive": 1,
            "role": "crew",
            "meeting_active": 1,
            "meeting_discussion": 1,
            "meeting_ballot": 0,
            "meeting_reported_body": 1,
            "meeting_speakers": 1,
            "heard_talk": 1,
            "voted": 0,
        },
    )
    client = _FakeClient('{"talk":"skip for now","stance":"skip"}')
    agent = AmongUsAnthropicCyborgAgent(
        policy_env_info,
        agent_id=0,
        desired_role="crew",
        client=client,
        model="fake-model",
        max_tokens=120,
        temperature=0.0,
        static_known={},
        spawn_pos=(0, 0),
        base_agent=base_agent,
    )

    action = agent.step(_meeting_obs())
    base_agent._infos.update({"meeting_discussion": 0, "meeting_ballot": 1})
    ballot_action = agent.step(_meeting_obs())

    assert action.vibe == f"change_vibe_{vote_target_vibe(1)}"
    assert action.talk == "I found the body near Agent 1"
    assert ballot_action.vibe == f"change_vibe_{vote_target_vibe(1)}"
    assert ballot_action.talk == "ballot: Agent 1."


def test_amongcogs_anthropic_cyborg_policy_builds_agent() -> None:
    policy = AmongUsAnthropicCyborgPolicy(
        _policy_env_info(),
        client=_FakeClient('{"talk":"","stance":"question"}'),
        model="fake-model",
        max_tokens=120,
    )

    agent = policy.agent_policy(0)

    assert isinstance(agent, AgentPolicy)


def test_build_meeting_prompt_includes_moderator_guidance_and_ballot_contract() -> None:
    prompt = _build_meeting_prompt(
        agent_id=0,
        phase="discussion",
        base_action=Action(name="noop", vibe=f"change_vibe_{VIBE_VOTE_SKIP}", talk=""),
        base_infos={
            "role": "crew",
            "meeting_reported_body": 1,
            "meeting_speakers": 2,
            "heard_talk": 2,
        },
        talk=_meeting_obs().talk,
        talk_max_length=140,
    )

    assert "Moderator prompt:" in prompt
    assert "A body was reported. Say what you saw or who you suspect." in prompt
    assert "every agent will announce their vote aloud" in prompt
    assert '{"talk":"short message or empty string","stance":"accuse|skip|question"}' in prompt
    assert '"baseline_vote": "skip"' in prompt
    assert '"allowed_agent_labels": ["agent-1"]' in prompt
    assert "Never use color names." in prompt
    assert "Keep the tone blunt." in prompt


def test_ballot_talk_for_action_matches_structured_vote() -> None:
    accuse = Action(name="noop", vibe=f"change_vibe_{vote_target_vibe(1)}")
    accuse_name = Action(name=f"change_vibe_{vote_target_vibe(1)}")
    skip = Action(name="noop", vibe=f"change_vibe_{VIBE_VOTE_SKIP}")
    plain = Action(name="noop", talk="already talking")

    assert _ballot_talk_for_action(accuse) == "ballot: Agent 1."
    assert _ballot_talk_for_action(accuse_name) == "ballot: Agent 1."
    assert _ballot_talk_for_action(skip) == "ballot: skip."
    assert _ballot_talk_for_action(plain) == "already talking"


def test_normalize_stance_defaults_unknown_values_to_question() -> None:
    assert _normalize_stance("ACCUSE") == "accuse"
    assert _normalize_stance("skip") == "skip"
    assert _normalize_stance("maybe") == "question"


def test_apply_discussion_decision_keeps_accuse_talk_when_model_softens() -> None:
    base_action = Action(
        name="noop",
        vibe=f"change_vibe_{vote_target_vibe(1)}",
        talk="body was reported. vote Agent 1.",
    )
    softened = _apply_discussion_decision(
        base_action,
        decision=AmongUsMeetingDecision(talk="I did not see enough yet.", stance="skip"),
    )

    assert softened.talk == "body was reported. vote Agent 1."
    assert softened.vibe == f"change_vibe_{vote_target_vibe(1)}"


def test_action_vote_label_handles_name_and_vibe_vote_intents() -> None:
    assert _action_vote_label(Action(name=f"change_vibe_{vote_target_vibe(1)}")) == "accuse"
    assert _action_vote_label(Action(name="noop", vibe=f"change_vibe_{vote_target_vibe(1)}")) == "accuse"
    assert _action_vote_label(Action(name=f"change_vibe_{VIBE_VOTE_SKIP}")) == "skip"
    assert _action_vote_label(Action(name="noop")) == "question"


def test_amongcogs_anthropic_cyborg_rewrites_color_hallucination_into_grounded_talk() -> None:
    policy_env_info = _policy_env_info()
    base_agent = _StubBaseAgent(
        policy_env_info,
        action=Action(name="noop", vibe=f"change_vibe_{VIBE_VOTE_SKIP}", talk="body was reported. who was nearby?"),
        infos={
            "alive": 1,
            "role": "crew",
            "meeting_active": 1,
            "meeting_discussion": 1,
            "meeting_ballot": 0,
            "meeting_reported_body": 1,
            "meeting_speakers": 1,
            "heard_talk": 1,
            "voted": 0,
        },
    )
    client = _FakeClient('{"talk":"Red is suspicious here.","stance":"accuse"}')
    agent = AmongUsAnthropicCyborgAgent(
        policy_env_info,
        agent_id=0,
        desired_role="crew",
        client=client,
        model="fake-model",
        max_tokens=120,
        temperature=0.0,
        static_known={},
        spawn_pos=(0, 0),
        base_agent=base_agent,
    )

    action = agent.step(_meeting_obs())

    assert "Red" not in action.talk
    assert action.talk == "agent-1, give me the room and timing."
