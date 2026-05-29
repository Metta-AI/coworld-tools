from __future__ import annotations

from dataclasses import dataclass, field

from cogsguard.semantic import CogsguardSemanticSurface
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.sdk.agent import (
    LogSink,
    MemoryView,
    MettagridActions,
    MettagridSDK,
    MettagridState,
    PlanView,
    SemanticEvent,
)
from mettagrid.sdk.agent.runtime.observation import ObservationEnvelope
from mettagrid.simulator import AgentObservation

from players.cogsguard._shared.semantic.prompt_adapter import CogsguardPromptAdapter


@dataclass(slots=True)
class CogsguardPolicySurface:
    """Player-owned composition of game semantics and policy prompt helpers."""

    semantic_surface: CogsguardSemanticSurface = field(default_factory=CogsguardSemanticSurface)
    prompt_adapter: CogsguardPromptAdapter = field(default_factory=CogsguardPromptAdapter)

    def build_state(
        self,
        raw_observation: AgentObservation,
        *,
        policy_env_info: PolicyEnvInterface,
        step: int | None = None,
    ) -> MettagridState:
        return self.semantic_surface.state_adapter.build_state(
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
        state.recent_events = self.extract_events(previous_state, state)
        return state

    def extract_events(
        self,
        previous_state: MettagridState | None,
        current_state: MettagridState,
    ) -> list[SemanticEvent]:
        return self.semantic_surface.extract_events(previous_state, current_state)

    def render_state(self, state: MettagridState) -> str:
        return self.prompt_adapter.render_state(state)

    def render_skill_library(self) -> str:
        return self.prompt_adapter.render_skill_library()

    def build_sdk(
        self,
        state: MettagridState,
        *,
        actions: MettagridActions,
        memory: MemoryView,
        log: LogSink,
        plan: PlanView | None = None,
        shared_objectives: list[str] | None = None,
    ) -> MettagridSDK:
        return self.semantic_surface.build_sdk(
            state,
            actions=actions,
            memory=memory,
            log=log,
            plan=plan,
            shared_objectives=shared_objectives,
        )
