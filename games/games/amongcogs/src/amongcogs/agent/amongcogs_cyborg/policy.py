"""Anthropic-backed meeting policy layered on top of the scripted Among Us agent."""

from __future__ import annotations

import importlib
import json
import os
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from amongcogs.agent.amongcogs_agent.policy import (
    AmongUsAgent,
    _build_static_known,
)
from amongcogs.constants import VIBE_VOTE_AGENT_PREFIX
from amongcogs.game import VIBE_VOTE_SKIP
from mettagrid.policy.policy import AgentPolicy, MultiAgentPolicy
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.simulator import Action
from mettagrid.simulator.interface import AgentObservation, VisibleTalk

__all__ = ["AmongUsAnthropicCyborgPolicy"]

_DEFAULT_MAX_TOKENS = 160
_DEFAULT_TEMPERATURE = 0.0
_DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-5"
_DEFAULT_BEDROCK_MODEL = "global.anthropic.claude-sonnet-4-5-20250929-v1:0"
_AGENT_REF_RE = re.compile(r"\bagent-\d+\b")
_COLOR_REF_RE = re.compile(
    r"\b(?:red|blue|green|pink|orange|yellow|black|white|purple|brown|cyan|lime|maroon)\b",
    re.IGNORECASE,
)
_SPEAKER_STYLES = ("blunt", "calm", "skeptical", "procedural", "sharp", "measured")


def _resolve_api_key(*, direct_value: str | None, file_path: str | Path | None, env_var: str) -> str | None:
    if direct_value:
        stripped = direct_value.strip()
        if stripped:
            return stripped

    if file_path:
        path = Path(file_path)
        if path.is_file():
            return path.read_text().strip()

    value = os.getenv(env_var)
    if value:
        return value.strip()

    return None


def _env_flag_enabled(name: str) -> bool:
    return os.getenv(name, "").lower() in {"1", "true", "yes", "on"}


def _should_use_anthropic_bedrock(api_key: str | None) -> bool:
    return _env_flag_enabled("CLAUDE_CODE_USE_BEDROCK") or not api_key


def _get_default_anthropic_model(*, api_key: str | None) -> str:
    if _should_use_anthropic_bedrock(api_key):
        model = os.getenv("ANTHROPIC_MODEL")
        if model:
            stripped = model.strip()
            if stripped:
                return stripped
        return _DEFAULT_BEDROCK_MODEL
    return _DEFAULT_ANTHROPIC_MODEL


def _build_anthropic_client(*, api_key: str | None) -> object:
    anthropic = importlib.import_module("anthropic")

    if _should_use_anthropic_bedrock(api_key):
        return anthropic.AnthropicBedrock(
            aws_profile=os.getenv("AWS_PROFILE"),
            aws_region=os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION")),
        )

    if api_key is None:
        raise ValueError("Anthropic API key is required when Bedrock is disabled")

    return anthropic.Anthropic(api_key=api_key)


class AmongUsMeetingDecision(BaseModel):
    talk: str = ""
    stance: str = "question"


def _response_text(response: Any) -> str:
    for block in getattr(response, "content", []):
        text = getattr(block, "text", None)
        if isinstance(text, str):
            return text
    raise ValueError("Anthropic response did not include a text block")


def _extract_json_object(raw_text: str) -> str:
    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("Anthropic meeting response did not include a JSON object")
    return raw_text[start : end + 1]


class AmongUsAnthropicCyborgAgent(AgentPolicy):
    def __init__(
        self,
        policy_env_info: PolicyEnvInterface,
        *,
        agent_id: int,
        desired_role: str,
        client: Any,
        model: str,
        max_tokens: int,
        temperature: float,
        static_known,
        spawn_pos,
        base_agent: AgentPolicy | None = None,
    ) -> None:
        super().__init__(policy_env_info)
        self._agent_id = agent_id
        self._client = client
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._talk_max_length = policy_env_info.talk.max_length
        self._base_agent = (
            base_agent
            if base_agent is not None
            else AmongUsAgent(
                policy_env_info,
                agent_id=agent_id,
                desired_role=desired_role,
                static_known=static_known,
                spawn_pos=spawn_pos,
            )
        )
        self._in_meeting = False
        self._meeting_index = 0
        self._cached_decision: AmongUsMeetingDecision | None = None

    def reset(self, simulation=None) -> None:  # type: ignore[override]
        self._base_agent.reset(simulation=simulation)
        self._in_meeting = False
        self._meeting_index = 0
        self._cached_decision = None

    def step(self, obs: AgentObservation) -> Action:
        base_action = self._base_agent.step(obs)
        base_infos = dict(self._base_agent.infos)
        meeting_active = bool(int(base_infos.get("meeting_active", 0)))
        if meeting_active and not self._in_meeting:
            self._meeting_index += 1
            self._cached_decision = None
        if not meeting_active and self._in_meeting:
            self._cached_decision = None
        self._in_meeting = meeting_active

        phase = _meeting_phase(base_infos)
        decision_used = False
        if int(base_infos.get("alive", 0)) > 0 and phase == "discussion":
            decision = self._decision_for_phase(
                phase=phase,
                base_action=base_action,
                base_infos=base_infos,
                talk=obs.talk,
            )
            base_action = _apply_discussion_decision(base_action, decision=decision)
            decision_used = True
        elif int(base_infos.get("alive", 0)) > 0 and phase == "ballot":
            base_action = _apply_ballot_decision(base_action, decision=self._cached_decision)

        self._infos = {
            **base_infos,
            "cyborg_policy": "anthropic",
            "cyborg_meeting_phase": phase,
            "cyborg_decision_used": int(decision_used),
            "cyborg_meeting_index": self._meeting_index,
        }
        if self._cached_decision is not None and phase == "discussion":
            self._infos["cyborg_talk"] = self._cached_decision.talk
            self._infos["cyborg_stance"] = self._cached_decision.stance
        if phase == "ballot":
            self._infos["cyborg_ballot_talk"] = base_action.talk or ""
        return base_action

    def _decision_for_phase(
        self,
        *,
        phase: str,
        base_action: Action,
        base_infos: dict[str, Any],
        talk: tuple[VisibleTalk, ...] | list[VisibleTalk],
    ) -> AmongUsMeetingDecision:
        if self._cached_decision is not None:
            return self._cached_decision
        prompt = _build_meeting_prompt(
            agent_id=self._agent_id,
            phase=phase,
            base_action=base_action,
            base_infos=base_infos,
            talk=talk,
            talk_max_length=self._talk_max_length,
        )
        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        decision = AmongUsMeetingDecision.model_validate_json(_extract_json_object(_response_text(response)))
        decision = decision.model_copy(update={"stance": _normalize_stance(decision.stance)})
        decision = decision.model_copy(
            update={
                "talk": _finalize_discussion_talk(
                    agent_id=self._agent_id,
                    decision=decision,
                    base_action=base_action,
                    base_infos=base_infos,
                    talk=talk,
                    talk_max_length=self._talk_max_length,
                )
            }
        )
        self._cached_decision = decision
        return decision


class AmongUsAnthropicCyborgPolicy(MultiAgentPolicy):
    """Anthropic-backed Among Us meeting policy layered over scripted movement/mechanics."""

    short_names = [
        "among_us_anthropic_cyborg",
        "amongcogs_anthropic_cyborg",
        "among-us-anthropic-cyborg",
        "amongcogs-anthropic-cyborg",
        "anthropic-cyborg-among-us",
        "anthropic-cyborg-amongcogs",
    ]

    def __init__(
        self,
        policy_env_info: PolicyEnvInterface,
        device: str = "cpu",
        impostor_ratio: float = 0.25,
        model: str | None = None,
        client: Any | None = None,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        temperature: float = _DEFAULT_TEMPERATURE,
        api_key: str | None = None,
        api_key_file: str | None = None,
        anthropic_api_key: str | None = None,
        anthropic_api_key_file: str | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(policy_env_info, device=device)
        ratio = max(0.05, min(float(impostor_ratio), 0.5))
        num_agents = policy_env_info.num_agents
        impostor_count = max(1, int(round(num_agents * ratio)))
        resolved_api_key = _resolve_api_key(
            direct_value=anthropic_api_key or api_key,
            file_path=anthropic_api_key_file or api_key_file,
            env_var="ANTHROPIC_API_KEY",
        )
        resolved_model = (
            model or os.getenv("ANTHROPIC_SMALL_FAST_MODEL") or _get_default_anthropic_model(api_key=resolved_api_key)
        )
        self._client = client if client is not None else _build_anthropic_client(api_key=resolved_api_key)
        self._model = resolved_model
        self._max_tokens = int(max_tokens)
        self._temperature = float(temperature)
        self._impostor_ids = set(range(impostor_count))
        self._agents: dict[int, AmongUsAnthropicCyborgAgent] = {}
        self._static_known, self._spawn_positions = _build_static_known(num_agents)

    def agent_policy(self, agent_id: int) -> AgentPolicy:
        if agent_id not in self._agents:
            desired_role = "impostor" if agent_id in self._impostor_ids else "crew"
            self._agents[agent_id] = AmongUsAnthropicCyborgAgent(
                self._policy_env_info,
                agent_id=agent_id,
                desired_role=desired_role,
                client=self._client,
                model=self._model,
                max_tokens=self._max_tokens,
                temperature=self._temperature,
                static_known=self._static_known,
                spawn_pos=self._spawn_positions[agent_id],
            )
        return self._agents[agent_id]


def _meeting_phase(base_infos: dict[str, Any]) -> str:
    if int(base_infos.get("meeting_discussion", 0)) > 0:
        return "discussion"
    if int(base_infos.get("meeting_ballot", 0)) > 0 and int(base_infos.get("voted", 0)) == 0:
        return "ballot"
    return "none"


def _apply_discussion_decision(action: Action, *, decision: AmongUsMeetingDecision) -> Action:
    talk = action.talk if not decision.talk else decision.talk
    if _action_vote_label(action) == "accuse" and decision.stance != "accuse":
        talk = action.talk or talk
    return Action(name=action.name, vibe=action.vibe, talk=talk)


def _apply_ballot_decision(action: Action, *, decision: AmongUsMeetingDecision | None) -> Action:
    action = _apply_accuse_stance(action, decision=decision)
    ballot_talk = _ballot_talk_for_action(action)
    if not ballot_talk:
        return action
    return Action(name=action.name, vibe=action.vibe, talk=ballot_talk)


def _apply_accuse_stance(action: Action, *, decision: AmongUsMeetingDecision | None) -> Action:
    if decision is None or decision.stance != "accuse":
        return action
    return action


def _apply_ballot_talk(action: Action) -> Action:
    ballot_talk = _ballot_talk_for_action(action)
    if not ballot_talk:
        return action
    return Action(name=action.name, vibe=action.vibe, talk=ballot_talk)


def _build_meeting_prompt(
    *,
    agent_id: int,
    phase: str,
    base_action: Action,
    base_infos: dict[str, Any],
    talk: tuple[VisibleTalk, ...] | list[VisibleTalk],
    talk_max_length: int,
) -> str:
    role = str(base_infos.get("role", "crew") or "crew")
    speaker_style = _speaker_style(agent_id=agent_id, role=role)
    allowed_agent_labels = _visible_agent_labels(talk=talk, self_agent_id=agent_id)
    heard_lines = _talk_lines(talk=talk, self_agent_id=agent_id)
    heard_text = "\n".join(f"- {line}" for line in heard_lines) if heard_lines else "- none"
    moderator_text = "\n".join(f"- {line}" for line in _meeting_moderator_lines(base_infos))
    role_guidance = (
        "- You are crew. Give one short evidence-based suspicion, observation, or reason to skip.\n"
        "- Do not invent facts not present in the moderator prompt or transcript."
    )
    if role == "impostor":
        role_guidance = (
            "- You are impostor. Give one short plausible line that creates doubt or pushes skip.\n"
            "- Do not confess and do not invent impossible map facts."
        )
    payload = {
        "role": role,
        "phase": phase,
        "meeting_reported_body": bool(int(base_infos.get("meeting_reported_body", 0))),
        "meeting_speakers": int(base_infos.get("meeting_speakers", 0)),
        "heard_talk": int(base_infos.get("heard_talk", 0)),
        "baseline_talk": base_action.talk or "",
        "baseline_vote": _action_vote_label(base_action),
        "speaker_style": speaker_style,
        "allowed_agent_labels": list(allowed_agent_labels),
    }
    return "\n".join(
        [
            "You are controlling one Among Us agent during a live meeting.",
            "This is the discussion phase only.",
            "Return JSON only with this schema:",
            '{"talk":"short message or empty string","stance":"accuse|skip|question"}',
            f"Talk must be at most {talk_max_length} characters.",
            "Use only the provided moderator prompt and visible transcript.",
            (
                'Use "accuse" when discussion should push a named suspect vote, '
                '"skip" when discussion should avoid an accuse vote, '
                'and "question" for neutral information-gathering.'
            ),
            'If baseline_vote is "accuse", keep your stance on "accuse" and name the same target.',
            f"Keep the tone {speaker_style}.",
            "Refer to other agents only as agent-<id> from allowed_agent_labels. Never use color names.",
            "If you do not have an allowed agent label, talk about routes, rooms, witnesses, or pressure to vote.",
            "Do not repeat baseline_talk verbatim unless it is the only grounded thing you can say.",
            "Moderator prompt:",
            moderator_text,
            role_guidance,
            "Meeting state:",
            json.dumps(payload, sort_keys=True),
            "Visible transcript:",
            heard_text,
        ]
    )


def _talk_lines(*, talk: tuple[VisibleTalk, ...] | list[VisibleTalk], self_agent_id: int) -> list[str]:
    return [
        f"agent-{item.agent_id}: {json.dumps(item.text)}"
        for item in talk
        if item.agent_id != self_agent_id and item.text
    ]


def _visible_agent_labels(*, talk: tuple[VisibleTalk, ...] | list[VisibleTalk], self_agent_id: int) -> tuple[str, ...]:
    labels = sorted({f"agent-{item.agent_id}" for item in talk if item.agent_id != self_agent_id and item.text})
    return tuple(labels)


def _meeting_moderator_lines(base_infos: dict[str, Any]) -> list[str]:
    lines = []
    if bool(int(base_infos.get("meeting_reported_body", 0))):
        lines.append("A body was reported. Say what you saw or who you suspect.")
    else:
        lines.append("Emergency meeting. Say one short suspicion or reason to skip.")
    lines.append("Keep discussion brief and concrete.")
    lines.append("When ballot opens, every agent will announce their vote aloud.")
    return lines


def _ballot_talk_for_action(action: Action) -> str:
    if _action_vote_label(action) == "accuse":
        target_id = _target_vote_agent_id(action)
        if target_id is not None:
            return f"ballot: Agent {target_id}."
        return "ballot: named suspect."
    if _action_vote_label(action) == "skip":
        return "ballot: skip."
    return action.talk or ""


def _action_vote_label(action: Action) -> str:
    vote_action = action.vibe or action.name
    if vote_action.startswith(f"change_vibe_{VIBE_VOTE_AGENT_PREFIX}"):
        return "accuse"
    if vote_action == f"change_vibe_{VIBE_VOTE_SKIP}":
        return "skip"
    return "question"


def _target_vote_agent_id(action: Action) -> int | None:
    vote_action = action.vibe or action.name
    prefix = f"change_vibe_{VIBE_VOTE_AGENT_PREFIX}"
    if not vote_action.startswith(prefix):
        return None
    suffix = vote_action[len(prefix) :]
    if not suffix.isdecimal():
        return None
    return int(suffix)


def _speaker_style(*, agent_id: int, role: str) -> str:
    offset = 1 if role == "impostor" else 0
    return _SPEAKER_STYLES[(agent_id + offset) % len(_SPEAKER_STYLES)]


def _finalize_discussion_talk(
    *,
    agent_id: int,
    decision: AmongUsMeetingDecision,
    base_action: Action,
    base_infos: dict[str, Any],
    talk: tuple[VisibleTalk, ...] | list[VisibleTalk],
    talk_max_length: int,
) -> str:
    fallback = _discussion_fallback_talk(
        agent_id=agent_id,
        base_action=base_action,
        base_infos=base_infos,
        talk=talk,
    )
    text = " ".join(decision.talk.split()).strip()
    if not text:
        return fallback[:talk_max_length]
    allowed_agent_labels = set(_visible_agent_labels(talk=talk, self_agent_id=agent_id))
    mentioned_agent_labels = set(_AGENT_REF_RE.findall(text.lower()))
    if _COLOR_REF_RE.search(text):
        return fallback[:talk_max_length]
    if mentioned_agent_labels and not mentioned_agent_labels.issubset(allowed_agent_labels):
        return fallback[:talk_max_length]
    if _too_generic_discussion_talk(text=text, fallback=fallback):
        return fallback[:talk_max_length]
    return text[:talk_max_length]


def _too_generic_discussion_talk(*, text: str, fallback: str) -> bool:
    normalized = text.lower().strip(". ")
    fallback_normalized = fallback.lower().strip(". ")
    generic_phrases = {
        "could be anyone",
        "i did not see enough yet",
        "i didn't see anything",
        "skip for now",
    }
    return normalized in generic_phrases or normalized == fallback_normalized


def _discussion_fallback_talk(
    *,
    agent_id: int,
    base_action: Action,
    base_infos: dict[str, Any],
    talk: tuple[VisibleTalk, ...] | list[VisibleTalk],
) -> str:
    role = str(base_infos.get("role", "crew") or "crew")
    baseline_vote = _action_vote_label(base_action)
    report_meeting = bool(int(base_infos.get("meeting_reported_body", 0)))
    allowed_agent_labels = _visible_agent_labels(talk=talk, self_agent_id=agent_id)
    if role == "impostor":
        return _pick_template(
            agent_id,
            _impostor_discussion_templates(report_meeting=report_meeting, allowed_agent_labels=allowed_agent_labels),
        )
    if baseline_vote == "accuse":
        return _pick_template(
            agent_id,
            _crew_accuse_templates(base_action=base_action, allowed_agent_labels=allowed_agent_labels),
        )
    return _pick_template(
        agent_id,
        _crew_question_templates(report_meeting=report_meeting, allowed_agent_labels=allowed_agent_labels),
    )


def _crew_accuse_templates(
    *,
    base_action: Action,
    allowed_agent_labels: tuple[str, ...],
) -> tuple[str, ...]:
    if (base_action.talk or "").lower().startswith("i found the body"):
        target_id = _target_vote_agent_id(base_action)
        if target_id is not None:
            return (
                f"I found the body near agent-{target_id}. Vote agent-{target_id}.",
                f"I found the body near agent-{target_id}. Do not skip this.",
                f"My report names agent-{target_id}. Vote agent-{target_id}.",
            )
        return (
            "I found the body. I do not have a named suspect.",
            "I found the body. Do not let this turn into a skip.",
            "I found the body. Ask who was nearby.",
        )
    if allowed_agent_labels:
        speaker = allowed_agent_labels[0]
        return (
            f"{speaker} is naming details. Pressure that named suspect.",
            f"{speaker} is giving the strongest claim. Follow the named vote.",
            f"We have a claim from {speaker}. Keep pressure on that suspect.",
        )
    return (
        "A body was reported. I need a named suspect.",
        "Body on the floor. Do not turn this into a skip.",
        "We have a report. Name who was nearby.",
    )


def _crew_question_templates(
    *,
    report_meeting: bool,
    allowed_agent_labels: tuple[str, ...],
) -> tuple[str, ...]:
    if allowed_agent_labels:
        speaker = allowed_agent_labels[0]
        return (
            f"{speaker}, give me the room and timing.",
            f"{speaker}, who crossed your path before the report?",
            f"{speaker}, give one witness and one route.",
        )
    if report_meeting:
        return (
            "Body report. Who was near the room right before it?",
            "Give me the room and the last path you took.",
            "I want one witness and one route before I skip.",
        )
    return (
        "Give me one room, one route, and one witness.",
        "I want a concrete path before I vote.",
        "Name the room and who you crossed there.",
    )


def _impostor_discussion_templates(
    *,
    report_meeting: bool,
    allowed_agent_labels: tuple[str, ...],
) -> tuple[str, ...]:
    if allowed_agent_labels:
        speaker = allowed_agent_labels[0]
        return (
            f"Right now I only have {speaker}'s claim. That is too thin for a vote.",
            f"{speaker} has one story, but I still want timing and a witness.",
            f"I need more than {speaker}'s claim before we eject.",
        )
    if report_meeting:
        return (
            "One report is not enough. I want timing and a witness.",
            "Too thin for a vote. Give me a route and a witness first.",
            "We need a room, timing, and one solid witness before we eject.",
        )
    return (
        "This is still too thin for a vote.",
        "I want one concrete witness before we eject.",
        "Give me timing and a route before we vote.",
    )


def _pick_template(agent_id: int, templates: tuple[str, ...]) -> str:
    return templates[agent_id % len(templates)]


def _normalize_stance(raw_stance: str) -> str:
    stance = raw_stance.strip().lower()
    if stance in {"accuse", "skip", "question"}:
        return stance
    return "question"
