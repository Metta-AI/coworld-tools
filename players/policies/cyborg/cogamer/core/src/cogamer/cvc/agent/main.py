"""CvcEngine: per-agent heuristic decision tree for CvC.

Handles role selection, target acquisition, pathfinding, retreat logic,
resource management, and junction alignment/scrambling. Each agent runs
its own independent engine instance with its own world model.
"""

from __future__ import annotations

from collections import deque
from typing import Any

from cogamer.cvc.agent import (
    _ELEMENTS,
    absolute_position,
    format_position,
    heart_batch_target,
    inventory_signature,
    phase_name,
)
from cogamer.cvc.agent.decisions import run_pipeline
from cogamer.cvc.agent.junctions import JunctionMixin
from cogamer.cvc.agent.navigation import MoveAttempt, NavigationMixin, NavigationObservation
from cogamer.cvc.agent.pressure import PressureMixin
from cogamer.cvc.agent.roles import RolesMixin
from cogamer.cvc.agent.targeting import TargetingMixin
from cogamer.cvc.agent.tick_context import TickContext, build_tick_context
from cogamer.cvc.agent.world_model import WorldModel
from cogames.sdk.cogsguard import CogsguardSemanticSurface
from mettagrid.policy.policy import AgentPolicy
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.sdk.agent import MacroDirective, MettagridState
from mettagrid.simulator import Action
from mettagrid.simulator.interface import AgentObservation

_COGSGUARD_SURFACE = CogsguardSemanticSurface()


class CvcEngine(RolesMixin, NavigationMixin, TargetingMixin, PressureMixin, JunctionMixin, AgentPolicy):
    """Per-agent heuristic decision engine.

    Each tick: update world model → pick role → pick action via priority-based
    decision tree (retreat > unstick > gear > role action > explore).
    """

    def __init__(
        self,
        policy_env_info: PolicyEnvInterface,
        *,
        agent_id: int,
        world_model: WorldModel,
        shared_junctions: dict[tuple[int, int], tuple[str | None, int]] | None = None,
        shared_claims: dict[tuple[int, int], tuple[int, int]] | None = None,
    ) -> None:
        super().__init__(policy_env_info)
        self._agent_id = agent_id
        # Normalized ID (0-7) for role assignment and team-relative lookups.
        # In tournament/run mode, agent IDs may be 8-15 for the second team.
        self._role_id = agent_id % 8
        self._world_model = world_model
        self._claims: dict[tuple[int, int], tuple[int, int]] = shared_claims if shared_claims is not None else {}
        self._junctions: dict[tuple[int, int], tuple[str | None, int]] = (
            shared_junctions if shared_junctions is not None else {}
        )
        self._events: list[Any] = []
        self._previous_state: MettagridState | None = None
        self._last_global_pos: tuple[int, int] | None = None
        self._last_attempt: MoveAttempt | None = None
        self._temp_blocks: dict[tuple[int, int], int] = {}
        self._step_index = 0
        self._action_names = set(policy_env_info.action_names)
        self._vibe_actions = set(policy_env_info.vibe_action_names)
        self._fallback_action = "noop" if "noop" in self._action_names else policy_env_info.action_names[0]
        self._explore_index = 0
        self._default_resource_bias = _ELEMENTS[self._role_id % len(_ELEMENTS)]
        self._resource_bias = self._default_resource_bias
        self._last_inventory_signature: tuple[tuple[str, int], ...] | None = None
        self._stalled_steps = 0
        self._oscillation_steps = 0
        self._recent_navigation: deque[NavigationObservation] = deque(maxlen=6)
        self._current_target_position: tuple[int, int] | None = None
        self._current_target_kind: str | None = None
        self._claimed_target: tuple[int, int] | None = None
        self._sticky_target_position: tuple[int, int] | None = None
        self._sticky_target_kind: str | None = None
        self._hotspots: dict[tuple[int, int], int] = {}
        self._current_directive = MacroDirective()

    def step(self, obs: AgentObservation) -> Action:
        self._step_index += 1
        state = _COGSGUARD_SURFACE.build_state_with_events(
            obs,
            policy_env_info=self.policy_env_info,
            step=self._step_index,
            previous_state=self._previous_state,
        )
        return self.evaluate_state(state)

    def evaluate_state(self, state: MettagridState) -> Action:
        self._step_index = self._step_index + 1 if state.step is None else state.step
        self._current_target_position = None
        self._current_target_kind = None
        self._events.extend(state.recent_events)

        self._world_model.update(state)
        self._update_junctions(state)
        self._world_model.prune_missing_extractors(
            current_position=absolute_position(state),
            visible_entities=state.visible_entities,
            obs_width=self.policy_env_info.obs_width,
            obs_height=self.policy_env_info.obs_height,
        )
        current_pos = absolute_position(state)
        self._update_temp_blocks(current_pos)
        self._update_stall_counter(state, current_pos)

        directive = self._sanitize_macro_directive(self._macro_directive(state))
        self._current_directive = directive
        self._resource_bias = (
            self._default_resource_bias if directive.resource_bias is None else directive.resource_bias
        )
        role = directive.role or self._desired_role(state, objective=directive.objective)
        action, summary = self._choose_action(state, role)
        self._record_navigation_observation(current_pos, summary)
        macro_snapshot = self._macro_snapshot(state, role)
        self._infos = {
            "role": role,
            "subtask": summary,
            "summary": summary,
            "oscillation_steps": self._oscillation_steps,
            "phase": phase_name(state, role),
            "heart": int(state.self_state.inventory.get("heart", 0)),
            "heart_batch_target": heart_batch_target(state, role),
            "target_kind": self._current_target_kind or "",
            "target_position": (
                "" if self._current_target_position is None else format_position(self._current_target_position)
            ),
            "directive_role": directive.role or "",
            "directive_resource_bias": directive.resource_bias or "",
            "directive_objective": directive.objective or "",
            "directive_note": directive.note,
            "directive_target_entity_id": directive.target_entity_id or "",
            "directive_target_region": directive.target_region or "",
            **macro_snapshot,
        }
        self._previous_state = state
        self._last_global_pos = current_pos
        self._last_inventory_signature = inventory_signature(state)
        return action

    def reset(self, simulation=None) -> None:
        self._events: list[Any] = []
        self._previous_state = None
        self._world_model.reset()
        self._last_global_pos = None
        self._last_attempt = None
        self._temp_blocks.clear()
        self._step_index = 0
        self._explore_index = 0
        self._resource_bias = self._default_resource_bias
        self._last_inventory_signature = None
        self._stalled_steps = 0
        self._oscillation_steps = 0
        self._recent_navigation.clear()
        self._clear_target_claim()
        self._clear_sticky_target()
        self._hotspots.clear()
        self._current_directive = MacroDirective()
        self._infos = {}

    def _macro_directive(self, state: MettagridState) -> MacroDirective:
        del state
        return MacroDirective()

    def render_skill_library(self) -> str:
        return _COGSGUARD_SURFACE.render_skill_library()

    def _sanitize_macro_directive(self, directive: MacroDirective) -> MacroDirective:
        role = directive.role if directive.role in {"miner", "aligner", "scrambler", "scout"} else None
        resource_bias = directive.resource_bias if directive.resource_bias in _ELEMENTS else None
        note = directive.note.strip()
        objective = directive.objective.strip() if directive.objective is not None else None
        target_entity_id = directive.target_entity_id.strip() if directive.target_entity_id is not None else None
        target_region = directive.target_region.strip() if directive.target_region is not None else None
        return MacroDirective(
            role=role,
            target_entity_id=target_entity_id or None,
            target_region=target_region or None,
            resource_bias=resource_bias,
            objective=objective or None,
            note=note,
        )

    # ── Main decision tree ──────────────────────────────────────────

    def _choose_action(self, state: MettagridState, role: str) -> tuple[Action, str]:
        self._clear_targets_for_role(role)
        ctx = self._build_tick_context(state)
        return run_pipeline(ctx, role, self)

    def _clear_targets_for_role(self, role: str) -> None:
        """Reset target claims when switching to an incompatible role."""
        if role not in {"aligner", "miner"}:
            self._clear_target_claim()
            self._clear_sticky_target()
        elif role == "aligner" and self._sticky_target_kind not in {None, "junction"}:
            self._clear_sticky_target()
        elif role == "miner" and (
            self._sticky_target_kind is not None and not self._sticky_target_kind.endswith("_extractor")
        ):
            self._clear_sticky_target()

    def _build_tick_context(self, state: MettagridState) -> TickContext:
        return build_tick_context(
            state,
            world_model=self._world_model,
            nearest_hub_fn=self._nearest_hub,
            known_junctions_fn=self._known_junctions,
            stalled_steps=self._stalled_steps,
            oscillation_steps=self._oscillation_steps,
            resource_bias=self._resource_bias,
            step_index=self._step_index,
        )
