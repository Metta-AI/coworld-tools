from __future__ import annotations

from dataclasses import dataclass, field

from mettagrid_sdk.runtime.observation import ObservationEnvelope
from mettagrid_sdk.sdk import GridPosition, MettagridState, SemanticEvent

from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.simulator import AgentObservation
from mettagrid.simulator.interface import Location, VisibleTalk
from werecog.sdk.prompt_adapter import WerewolfMafiaPromptAdapter
from werecog.sdk.state import WerewolfMafiaStateAdapter


@dataclass(slots=True)
class WerewolfMafiaSemanticSurface:
    state_adapter: WerewolfMafiaStateAdapter = field(default_factory=WerewolfMafiaStateAdapter)
    prompt_adapter: WerewolfMafiaPromptAdapter = field(default_factory=WerewolfMafiaPromptAdapter)

    def build_state(
        self,
        raw_observation: AgentObservation,
        *,
        policy_env_info: PolicyEnvInterface,
        step: int | None = None,
    ) -> MettagridState:
        return self.state_adapter.build_state(
            ObservationEnvelope(raw_observation=raw_observation, policy_env_info=policy_env_info, step=step)
        )

    def build_state_with_events(
        self,
        raw_observation: AgentObservation,
        *,
        policy_env_info: PolicyEnvInterface,
        step: int | None = None,
        previous_state: MettagridState | None = None,
    ) -> MettagridState:
        state = self.build_state(raw_observation, policy_env_info=policy_env_info, step=step)
        state.recent_events = _phase_events(previous_state, state) + _talk_events(
            raw_observation,
            step=state.step or 0,
            previous_state=previous_state,
        )
        return state

    def render_state(self, state: MettagridState) -> str:
        return self.prompt_adapter.render_state(state)

    def render_skill_library(self) -> str:
        return self.prompt_adapter.render_skill_library()


def _phase_events(
    previous_state: MettagridState | None,
    current_state: MettagridState,
) -> list[SemanticEvent]:
    if previous_state is None:
        return []
    previous_phase = "day" if "day" in previous_state.self_state.status else "night"
    current_phase = "day" if "day" in current_state.self_state.status else "night"
    if previous_phase == current_phase:
        return []
    step = current_state.step or 0
    return [
        SemanticEvent(
            event_id=f"phase:{step}",
            event_type="phase_shift",
            step=step,
            importance=0.7,
            summary=f"phase changed from {previous_phase} to {current_phase}",
        )
    ]


def _talk_events(
    raw_observation: AgentObservation,
    *,
    step: int,
    previous_state: MettagridState | None,
) -> list[SemanticEvent]:
    seen_event_ids = (
        set()
        if previous_state is None
        else {event.event_id for event in previous_state.recent_events if event.event_type == "heard_speech"}
        | _active_talk_event_ids(previous_state)
    )
    events: list[SemanticEvent] = []
    for utterance in raw_observation.talk:
        text = " ".join(utterance.text.split()).strip()
        if not text:
            continue
        event_id = _talk_event_id(utterance=utterance, step=step, text=text)
        if event_id in seen_event_ids:
            continue
        events.append(
            SemanticEvent(
                event_id=event_id,
                event_type="heard_speech",
                step=step,
                location=GridPosition(x=utterance.location.x, y=utterance.location.y),
                importance=0.8,
                summary=f'agent-{utterance.agent_id} said "{text}"',
                evidence=[text],
            )
        )
    return events


def _active_talk_event_ids(state: MettagridState) -> set[str]:
    active_event_ids: set[str] = set()
    for entity in [state.self_state, *state.visible_entities]:
        talk_text = entity.attributes.get("talk_text")
        if not isinstance(talk_text, str) or not talk_text:
            continue
        remaining_steps = entity.attributes.get("talk_remaining_steps")
        if not isinstance(remaining_steps, int) or remaining_steps <= 0:
            continue
        agent_id = entity.attributes.get("agent_id")
        if not isinstance(agent_id, int):
            continue
        active_event_ids.add(
            _talk_event_id(
                utterance=VisibleTalk(
                    agent_id=agent_id,
                    text=talk_text,
                    location=Location(
                        entity.attributes.get("talk_row", entity.position.y),
                        entity.attributes.get("talk_col", entity.position.x),
                    ),
                    remaining_steps=remaining_steps,
                ),
                step=state.step or 0,
                text=" ".join(talk_text.split()).strip(),
            )
        )
    return active_event_ids


def _talk_event_id(*, utterance: VisibleTalk, step: int, text: str) -> str:
    expires_at = step + max(0, utterance.remaining_steps)
    return f"talk:{utterance.agent_id}:{utterance.location.row}:{utterance.location.col}:{expires_at}:{text}"
