"""GameState: thin adapter wrapping CogletAgentPolicy engine.

Wraps the engine internally for its A* pathfinder, world model, stall
detection, targeting, and all role-specific action logic.  Programs call
GameState methods which delegate to the engine's working infrastructure.
"""

from __future__ import annotations

from typing import Any, Callable

from cvc_policy.agent import (
    ELEMENTS,
    KnownEntity,
    absolute_position,
    gear_signature,
    has_role_gear,
    inventory_signature,
    is_usable_extractor,
    needs_emergency_mining,
    resource_priority,
    resource_total,
    team_can_afford_gear,
    team_id,
)
from cvc_policy.agent.coglet_policy import CogletAgentPolicy
from cvc_policy.agent.world_model import WorldModel
from cogames.sdk.cogsguard import CogsguardSemanticSurface
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.sdk.agent import MettagridState
from mettagrid.simulator import Action
from mettagrid.simulator.interface import AgentObservation

_COGSGUARD_SURFACE = CogsguardSemanticSurface()


class GameState:
    """Thin adapter over CogletAgentPolicy — one per agent per episode.

    Programs read properties and call action methods here; everything
    delegates to the engine's proven A* pathfinding and role logic.
    """

    def __init__(
        self,
        policy_env_info: PolicyEnvInterface,
        *,
        agent_id: int,
        on_cargo_cap_discovery: Callable[[tuple[str, ...], int], None] | None = None,
        on_heart_cap_discovery: Callable[[tuple[str, ...], int], None] | None = None,
    ) -> None:
        self.engine = CogletAgentPolicy(
            policy_env_info,
            agent_id=agent_id,
            world_model=WorldModel(),
            on_cargo_cap_discovery=on_cargo_cap_discovery,
            on_heart_cap_discovery=on_heart_cap_discovery,
        )
        self.agent_id = agent_id
        self.role: str = "miner"
        self.mg_state: MettagridState | None = None

        # Expose action validation info for backward compat
        self.action_names: set[str] = set(policy_env_info.action_names)
        self.vibe_actions: set[str] = set(policy_env_info.vibe_action_names)
        self.fallback: str = "noop" if "noop" in self.action_names else policy_env_info.action_names[0]

    # ── Observation processing ────────────────────────────────────────

    def process_obs(self, obs: AgentObservation) -> MettagridState:
        """Process observation using engine internals, but skip _choose_action.

        Mirrors the first half of CvcEngine.evaluate_state():
        build state, update world model, update junctions, navigation
        counters, stall detection, directive setup.
        """
        engine = self.engine

        engine._step_index += 1
        state = _COGSGUARD_SURFACE.build_state_with_events(
            obs,
            policy_env_info=engine.policy_env_info,
            step=engine._step_index,
            previous_state=engine._previous_state,
        )

        # World model update
        engine._world_model.update(state)
        engine._update_junctions(state)
        current_pos = absolute_position(state)
        engine._world_model.prune_missing_extractors(
            current_position=current_pos,
            visible_entities=state.visible_entities,
            obs_width=engine.policy_env_info.obs_width,
            obs_height=engine.policy_env_info.obs_height,
        )

        # Navigation infrastructure
        engine._update_temp_blocks(current_pos)
        engine._update_stall_counter(state, current_pos)

        # Reset per-tick targeting
        engine._current_target_position = None
        engine._current_target_kind = None

        # Collect events
        engine._events.extend(state.recent_events)

        # Set up directive (resource bias, etc.) — mirrors evaluate_state
        directive = engine._sanitize_macro_directive(engine._macro_directive(state))
        engine._current_directive = directive
        engine._resource_bias = (
            engine._default_resource_bias if directive.resource_bias is None else directive.resource_bias
        )

        # Cargo-cap discovery: at this point `state` reflects the outcome of
        # last tick's action. If that action was a mine attempt, compare cargo
        # to the snapshot taken at end of last tick.
        sig = gear_signature(state)
        engine._cargo_cap.observe(
            gear_sig=sig,
            cargo=resource_total(state),
            mined_last_tick=engine._prev_summary_was_mine,
        )
        # Heart-cap discovery: same plateau logic, keyed on the single `heart`
        # inventory slot. Fires when last tick's action was a heart-pickup.
        engine._heart_cap.observe(
            gear_sig=sig,
            hearts=int(state.self_state.inventory.get("heart", 0)),
            tried_pickup_last_tick=engine._prev_summary_was_heart_pickup,
        )

        # Store for bookkeeping at end of step
        self.mg_state = state
        return state

    def finalize_step(self, summary: str) -> None:
        """Bookkeep after action selection — mirrors end of evaluate_state."""
        engine = self.engine
        state = self.mg_state
        if state is None:
            return
        current_pos = absolute_position(state)
        engine._record_navigation_observation(current_pos, summary)
        engine._previous_state = state
        engine._last_global_pos = current_pos
        engine._last_inventory_signature = inventory_signature(state)
        engine._prev_summary_was_mine = summary.startswith("mine_") or "_mine_" in summary
        # Heart-pickup attempts: aligner/scrambler actions at or toward the hub
        # intending to take a heart. Match the summaries emitted by roles.py.
        engine._prev_summary_was_heart_pickup = (
            summary == "acquire_heart" or summary == "batch_hearts"
        )

    # ── Properties delegating to engine/state ─────────────────────────

    @property
    def step_index(self) -> int:
        return self.engine._step_index

    @step_index.setter
    def step_index(self, value: int) -> None:
        self.engine._step_index = value

    @property
    def hp(self) -> int:
        if self.mg_state is None:
            return 0
        return int(self.mg_state.self_state.inventory.get("hp", 0))

    @property
    def position(self) -> tuple[int, int]:
        if self.mg_state is None:
            return (0, 0)
        return absolute_position(self.mg_state)

    @property
    def resource_bias(self) -> str:
        return self.engine._resource_bias

    @resource_bias.setter
    def resource_bias(self, value: str) -> None:
        self.engine._resource_bias = value

    @property
    def world_model(self) -> WorldModel:
        return self.engine._world_model

    @property
    def stalled_steps(self) -> int:
        return self.engine._stalled_steps

    @stalled_steps.setter
    def stalled_steps(self, value: int) -> None:
        self.engine._stalled_steps = value

    @property
    def oscillation_steps(self) -> int:
        return self.engine._oscillation_steps

    @oscillation_steps.setter
    def oscillation_steps(self, value: int) -> None:
        self.engine._oscillation_steps = value

    @property
    def explore_index(self) -> int:
        return self.engine._explore_index

    @explore_index.setter
    def explore_index(self, value: int) -> None:
        self.engine._explore_index = value

    # ── Delegate infrastructure methods to engine ─────────────────────

    def move_to_known(
        self, entity: KnownEntity, *, summary: str = "move", vibe: str | None = None
    ) -> tuple[Action, str]:
        """A* pathfinding to a known entity."""
        assert self.mg_state is not None
        return self.engine._move_to_known(self.mg_state, entity, summary=summary, vibe=vibe)

    def move_to_position(
        self, target: tuple[int, int], *, summary: str = "move", vibe: str | None = None
    ) -> tuple[Action, str]:
        """A* pathfinding to a position."""
        assert self.mg_state is not None
        return self.engine._move_to_position(self.mg_state, target, summary=summary, vibe=vibe)

    def hold(self, *, summary: str = "hold", vibe: str | None = None) -> tuple[Action, str]:
        return self.engine._hold(summary=summary, vibe=vibe)

    def nearest_hub(self) -> KnownEntity | None:
        assert self.mg_state is not None
        return self.engine._nearest_hub(self.mg_state)

    def nearest_friendly_depot(self) -> KnownEntity | None:
        assert self.mg_state is not None
        return self.engine._nearest_friendly_depot(self.mg_state)

    def explore(self, role: str = "miner") -> tuple[Action, str]:
        assert self.mg_state is not None
        return self.engine._explore_action(self.mg_state, role=role, summary="explore")

    def unstick(self, role: str = "miner") -> tuple[Action, str]:
        assert self.mg_state is not None
        return self.engine._unstick_action(self.mg_state, role)

    def should_retreat(self) -> bool:
        assert self.mg_state is not None
        safe_target = self.nearest_hub()
        return self.engine._should_retreat(self.mg_state, self.role, safe_target)

    def desired_role(self, objective: str | None = None) -> str:
        assert self.mg_state is not None
        return self.engine._desired_role(self.mg_state, objective=objective)

    def miner_action(self, summary_prefix: str = "") -> tuple[Action, str]:
        assert self.mg_state is not None
        return self.engine._miner_action(self.mg_state, summary_prefix=summary_prefix)

    def aligner_action(self) -> tuple[Action, str]:
        assert self.mg_state is not None
        return self.engine._aligner_action(self.mg_state)

    def scrambler_action(self) -> tuple[Action, str]:
        assert self.mg_state is not None
        return self.engine._scrambler_action(self.mg_state)

    def acquire_role_gear(self, role: str) -> tuple[Action, str]:
        assert self.mg_state is not None
        return self.engine._acquire_role_gear(self.mg_state, role)

    def choose_action(self, role: str) -> tuple[Action, str]:
        """Full engine decision tree — delegates to engine._choose_action."""
        assert self.mg_state is not None
        return self.engine._choose_action(self.mg_state, role)

    # ── Helper delegates ──────────────────────────────────────────────

    def has_role_gear(self, role: str) -> bool:
        assert self.mg_state is not None
        return has_role_gear(self.mg_state, role)

    def team_can_afford_gear(self, role: str) -> bool:
        assert self.mg_state is not None
        return team_can_afford_gear(self.mg_state, role)

    def needs_emergency_mining(self) -> bool:
        assert self.mg_state is not None
        return needs_emergency_mining(self.mg_state)

    def resource_priority(self) -> list[str]:
        assert self.mg_state is not None
        return resource_priority(self.mg_state, resource_bias=self.resource_bias)

    def nearest_extractor(self, resource: str) -> KnownEntity | None:
        assert self.mg_state is not None
        current_pos = absolute_position(self.mg_state)
        return self.world_model.nearest(
            position=current_pos,
            entity_type=f"{resource}_extractor",
            predicate=lambda e: is_usable_extractor(e),
        )

    def known_junctions(self, predicate: Any = None) -> list[KnownEntity]:
        assert self.mg_state is not None
        if predicate is None:
            predicate = lambda e: True  # noqa: E731
        return self.engine._known_junctions(self.mg_state, predicate=predicate)

    def team_id(self) -> str:
        assert self.mg_state is not None
        return team_id(self.mg_state)

    # ── Reset ─────────────────────────────────────────────────────────

    def reset(self) -> None:
        """Clear all state between episodes."""
        self.engine.reset()
        self.mg_state = None
        self.role = "miner"
