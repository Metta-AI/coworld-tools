"""
Buggy Policy — goal-tree scripted agent.

Buggy is a fork of Planky used for experimentation/tuning without changing the
baseline `planky` policy.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from mettagrid.mettagrid_c import dtype_actions
from mettagrid.policy.policy import MultiAgentPolicy, StatefulAgentPolicy, StatefulPolicyImpl
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.simulator import Action, ObservationToken
from mettagrid.simulator.interface import AgentObservation

from .context import PlankyContext, StateSnapshot
from .entity_map import EntityMap
from .goal import Goal, evaluate_goals
from .goals.aligner import AlignJunctionGoal, GetAlignerGearGoal
from .goals.miner import DepositCargoGoal, ExploreHubGoal, GetMinerGearGoal, MineResourceGoal, PickResourceGoal
from .goals.scout import ExploreGoal, GetScoutGearGoal
from .goals.scrambler import GetScramblerGearGoal, ScrambleJunctionGoal
from .goals.shared import FallbackMineGoal, GetHeartsGoal
from .goals.stem import SelectRoleGoal
from .goals.survive import SurviveGoal
from .navigator import Navigator
from .obs_parser import ObsParser
from .trace import TraceLog

# Role vibes that map to roles
VIBE_TO_ROLE = {"miner", "scout", "aligner", "scrambler"}

# Default spawn position (center of 200x200 grid)
SPAWN_POS = (100, 100)


def _make_goal_list(role: str) -> list[Goal]:
    """Create goal list for a role."""
    if role == "miner":
        return [
            SurviveGoal(hp_threshold=15),
            ExploreHubGoal(),
            GetMinerGearGoal(),
            PickResourceGoal(),
            DepositCargoGoal(),
            MineResourceGoal(),
        ]
    elif role == "scout":
        return [
            SurviveGoal(hp_threshold=50),
            GetScoutGearGoal(),
            ExploreGoal(),
        ]
    elif role == "aligner":
        # Aligners NEED gear + heart to align junctions.
        # Hearts require gear first — don't waste resources on hearts without gear.
        # FallbackMine at end: mine resources when can't get gear/hearts.
        return [
            SurviveGoal(hp_threshold=50),
            GetAlignerGearGoal(),
            GetHeartsGoal(min_hearts=1),
            AlignJunctionGoal(),
            FallbackMineGoal(),
        ]
    elif role == "scrambler":
        # Scramblers NEED gear + heart to scramble junctions.
        # FallbackMine at end: mine resources when can't get gear/hearts.
        return [
            SurviveGoal(hp_threshold=30),
            GetScramblerGearGoal(),
            GetHeartsGoal(min_hearts=1),
            ScrambleJunctionGoal(),
            FallbackMineGoal(),
        ]
    elif role == "stem":
        return [
            SurviveGoal(hp_threshold=20),
            SelectRoleGoal(),
        ]
    else:
        # Default/inactive
        return []


class PlankyAgentState:
    """Persistent state for a Planky agent across ticks."""

    def __init__(self, agent_id: int, role: str, goals: list[Goal], entity_map: EntityMap | None = None) -> None:
        self.agent_id = agent_id
        self.role = role
        self.goals = goals
        self.entity_map = entity_map or EntityMap()
        self.navigator = Navigator()
        self.blackboard: dict[str, Any] = {}
        self.step = 0


class PlankyBrain(StatefulPolicyImpl[PlankyAgentState]):
    """Per-agent coordinator that owns state and evaluates the goal tree."""

    def __init__(
        self,
        policy_env_info: PolicyEnvInterface,
        agent_id: int,
        role: str,
        shared_map: EntityMap | None = None,
        trace_enabled: bool = False,
        trace_level: int = 1,
        trace_agent: int = -1,
    ) -> None:
        self._agent_id = agent_id
        self._policy_env_info = policy_env_info
        self._role = role
        self._shared_map = shared_map
        self._obs_parser = ObsParser(policy_env_info)
        self._action_names = policy_env_info.all_action_names

        # Tracing
        self._trace_enabled = trace_enabled
        self._trace_level = trace_level
        self._trace_agent = trace_agent  # -1 = trace all

    def initial_agent_state(self) -> PlankyAgentState:
        goals = _make_goal_list(self._role)
        return PlankyAgentState(
            agent_id=self._agent_id,
            role=self._role,
            goals=goals,
            entity_map=self._shared_map,
        )

    def step_with_state(self, obs: AgentObservation, agent_state: PlankyAgentState) -> tuple[Action, PlankyAgentState]:
        agent_state.step += 1

        # Parse observation
        state, visible_entities = self._obs_parser.parse(obs, agent_state.step, SPAWN_POS)

        # Update entity map
        agent_state.entity_map.update_from_observation(
            agent_pos=state.position,
            obs_half_height=self._obs_parser.obs_half_height,
            obs_half_width=self._obs_parser.obs_half_width,
            visible_entities=visible_entities,
            step=agent_state.step,
        )

        # Detect useful actions by comparing state changes
        # Useful = mined resources, deposited to team hub, aligned/scrambled junction
        self._detect_useful_action(state, agent_state)

        # Detect failed moves: if last action was a move but position didn't change
        last_pos = agent_state.blackboard.get("_last_pos")
        last_action = agent_state.blackboard.get("_last_action", "")
        if last_pos is not None and last_action.startswith("move_") and state.position == last_pos:
            # Move failed - track consecutive failures
            fail_count = agent_state.blackboard.get("_move_fail_count", 0) + 1
            agent_state.blackboard["_move_fail_count"] = fail_count

            # After 3 consecutive failed moves, clear navigation cache and targets
            if fail_count >= 3:
                agent_state.navigator._cached_path = None
                agent_state.navigator._cached_target = None
                # Clear any target resource selection to force re-evaluation
                if fail_count >= 6:
                    agent_state.blackboard.pop("target_resource", None)
                    agent_state.blackboard["_move_fail_count"] = 0
        else:
            agent_state.blackboard["_move_fail_count"] = 0

        agent_state.blackboard["_last_pos"] = state.position

        # Vibe-driven role system: agent's role IS their vibe
        # "default" → set initial role vibe
        # "gear" → stem mode (role selection)
        # any valid role → run that role's goals

        # Check if goals want to change role (via blackboard)
        if "change_role" in agent_state.blackboard:
            new_role = agent_state.blackboard.pop("change_role")
            if new_role in VIBE_TO_ROLE:
                return Action(name=f"change_vibe_{new_role}"), agent_state

        # Map vibe to role
        current_vibe = state.vibe
        if current_vibe == "default":
            if self._role in VIBE_TO_ROLE:
                # Non-stem agent: set initial role vibe
                return Action(name=f"change_vibe_{self._role}"), agent_state
            else:
                # Stem agent: default vibe = stem mode
                effective_role = "stem"
        elif current_vibe == "gear":
            # Gear vibe = stem mode (role selection)
            effective_role = "stem"
        elif current_vibe in VIBE_TO_ROLE:
            effective_role = current_vibe
        else:
            if self._role in VIBE_TO_ROLE:
                return Action(name=f"change_vibe_{self._role}"), agent_state
            effective_role = "stem"

        # Update goals if role changed
        if effective_role != agent_state.role:
            if self._should_trace(agent_state):
                print(f"[buggy][t={agent_state.step} a={self._agent_id}] role: {agent_state.role}→{effective_role}")
            agent_state.role = effective_role
            agent_state.goals = _make_goal_list(effective_role)

        # Build context
        should_trace = self._should_trace(agent_state)
        trace = TraceLog() if should_trace else None

        # Calculate steps since last useful action
        last_useful = agent_state.blackboard.get("_last_useful_step", 0)
        steps_since_useful = agent_state.step - last_useful
        if trace:
            trace.steps_since_useful = steps_since_useful

        # If we've been idle too long (100+ steps), force a reset of cached state
        # This helps break out of stuck loops
        if steps_since_useful >= 100 and steps_since_useful % 50 == 0:
            # Clear cached navigation and target selections
            agent_state.navigator._cached_path = None
            agent_state.navigator._cached_target = None
            agent_state.blackboard.pop("target_resource", None)
            if trace:
                trace.activate("IdleReset", f"clearing cache after {steps_since_useful} idle steps")

        ctx = PlankyContext(
            state=state,
            map=agent_state.entity_map,
            blackboard=agent_state.blackboard,
            navigator=agent_state.navigator,
            trace=trace,
            action_names=self._action_names,
            agent_id=self._agent_id,
            step=agent_state.step,
        )

        # If we're stuck (many failed moves), force exploration to discover terrain
        fail_count = agent_state.blackboard.get("_move_fail_count", 0)
        if fail_count >= 6:
            action = agent_state.navigator.explore(
                state.position,
                agent_state.entity_map,
                direction_bias=["north", "east", "south", "west"][self._agent_id % 4],
            )
            if trace:
                trace.active_goal_chain = f"ForceExplore(stuck={fail_count})"
                trace.action_name = action.name
        else:
            # Evaluate goals normally
            action = evaluate_goals(agent_state.goals, ctx)

        # Emit trace
        if trace:
            line = trace.format_line(
                step=agent_state.step,
                agent_id=self._agent_id,
                role=agent_state.role,
                pos=state.position,
                hp=state.hp,
                level=self._trace_level,
            )
            print(f"[buggy] {line}")
            if agent_state.step % 25 == 0 or agent_state.step == 3:
                print(
                    f"[buggy][t={agent_state.step} a={self._agent_id}] "
                    f"team: C={state.team_carbon} O={state.team_oxygen} "
                    f"G={state.team_germanium} S={state.team_silicon} "
                    f"cargo={state.cargo_total}/{state.cargo_capacity} "
                    f"energy={state.energy}"
                )

        # Track action for failed-move detection
        agent_state.blackboard["_last_action"] = action.name

        return action, agent_state

    def _should_trace(self, agent_state: PlankyAgentState) -> bool:
        if not self._trace_enabled:
            return False
        return not (self._trace_agent >= 0 and self._agent_id != self._trace_agent)

    def _detect_useful_action(self, state: StateSnapshot, agent_state: PlankyAgentState) -> None:
        """Detect if a useful action occurred by comparing state changes.

        Useful actions:
        - Mine: cargo increased
        - Deposit: cargo decreased AND team hub total increased
        - Align/Scramble: heart decreased (spent on junction action)
        - Got gear: gear flag changed
        - Got heart: heart count increased
        """
        bb = agent_state.blackboard

        # Get previous state values
        prev_cargo = bb.get("_prev_cargo", 0)
        prev_heart = bb.get("_prev_heart", 0)
        prev_team_total = bb.get("_prev_team_total", 0)

        current_cargo = state.cargo_total
        current_heart = state.heart
        current_team_total = state.team_carbon + state.team_oxygen + state.team_germanium + state.team_silicon

        # Detect useful actions
        useful = False

        # Mined resources (cargo increased)
        if current_cargo > prev_cargo:
            useful = True

        if current_cargo < prev_cargo and current_team_total > prev_team_total:
            useful = True

        # Got a heart (heart increased)
        if current_heart > prev_heart:
            useful = True

        # Spent a heart on align/scramble (heart decreased)
        if current_heart < prev_heart:
            useful = True

        # Update tracking
        if useful:
            bb["_last_useful_step"] = agent_state.step

        # Store current values for next tick comparison
        bb["_prev_cargo"] = current_cargo
        bb["_prev_heart"] = current_heart
        bb["_prev_team_total"] = current_team_total


class BuggyPolicy(MultiAgentPolicy):
    """Multi-agent goal-tree policy with URI-based role distribution.

    URI parameters:
        ?miner=4&scout=0&aligner=2&scrambler=4  — role counts
        ?trace=1&trace_level=2&trace_agent=0     — tracing
    """

    short_names = ["buggy"]

    def __init__(
        self,
        policy_env_info: PolicyEnvInterface,
        device: str = "cpu",
        # Role counts — if stem > 0, defaults to all-stem unless explicit roles given
        miner: int = -1,
        scout: int = 0,
        aligner: int = -1,
        scrambler: int = -1,
        stem: int = 0,
        # Tracing
        trace: int = 0,
        trace_level: int = 1,
        trace_agent: int = -1,
        # Accept any extra kwargs
        **kwargs: object,
    ) -> None:
        super().__init__(policy_env_info, device=device)
        self._feature_by_id = {f.id: f for f in policy_env_info.obs_features}
        self._action_name_to_index = policy_env_info.action_name_to_flat_index
        self._noop_action_value = dtype_actions.type(self._action_name_to_index["noop"])

        # Tracing
        self._trace_enabled = bool(trace)
        self._trace_level = trace_level
        self._trace_agent = trace_agent

        # Resolve defaults: if stem > 0 and miner/aligner/scrambler not explicitly set, zero them
        if stem > 0:
            if miner == -1:
                miner = 0
            if aligner == -1:
                aligner = 0
            if scrambler == -1:
                scrambler = 0
        else:
            # Default to using the full team with a simple split:
            # - miners generate elements for heart crafting
            # - a small number of scramblers contain Clips expansion
            # - the rest are aligners (capture junctions)
            num_agents = int(policy_env_info.num_agents)
            if miner == -1:
                miner = max(1, round(num_agents * 0.4))
            if scrambler == -1:
                scrambler = 1 if num_agents >= 6 else 0
            if aligner == -1:
                aligner = max(0, num_agents - (miner + scout + scrambler + stem))
                if aligner == 0 and miner > 1:
                    miner -= 1
                    aligner = 1

        # Build role distribution
        self._role_distribution: list[str] = []
        self._role_distribution.extend(["miner"] * miner)
        self._role_distribution.extend(["scout"] * scout)
        self._role_distribution.extend(["aligner"] * aligner)
        self._role_distribution.extend(["scrambler"] * scrambler)
        self._role_distribution.extend(["stem"] * stem)

        if self._trace_enabled:
            print(f"[buggy] Role distribution: {self._role_distribution}")

        self._agent_policies: dict[int, StatefulAgentPolicy[PlankyAgentState]] = {}
        self._shared_map = EntityMap()

    def agent_policy(self, agent_id: int) -> StatefulAgentPolicy[PlankyAgentState]:
        if agent_id not in self._agent_policies:
            role = self._role_distribution[agent_id] if agent_id < len(self._role_distribution) else "default"

            brain = PlankyBrain(
                policy_env_info=self._policy_env_info,
                agent_id=agent_id,
                role=role,
                shared_map=self._shared_map,
                trace_enabled=self._trace_enabled,
                trace_level=self._trace_level,
                trace_agent=self._trace_agent,
            )

            self._agent_policies[agent_id] = StatefulAgentPolicy(
                brain,
                self._policy_env_info,
                agent_id=agent_id,
            )

        return self._agent_policies[agent_id]

    def step_batch(self, raw_observations: np.ndarray, raw_actions: np.ndarray) -> None:
        raw_actions[...] = self._noop_action_value
        num_agents = min(raw_observations.shape[0], self._policy_env_info.num_agents)
        active_agents = min(num_agents, len(self._role_distribution))
        for agent_id in range(active_agents):
            obs = self._raw_obs_to_agent_obs(agent_id, raw_observations[agent_id])
            action = self.agent_policy(agent_id).step(obs)
            action_index = self._action_name_to_index[action.name]
            raw_actions[agent_id] = dtype_actions.type(action_index)

    def _raw_obs_to_agent_obs(self, agent_id: int, raw_obs: np.ndarray) -> AgentObservation:
        tokens: list[ObservationToken] = []
        for token in raw_obs:
            feature_id = int(token[1])
            if feature_id == 0xFF:
                break
            feature = self._feature_by_id.get(feature_id)
            if feature is None:
                continue
            location_packed = int(token[0])
            value = int(token[2])
            tokens.append(
                ObservationToken(
                    feature=feature,
                    value=value,
                    raw_token=(location_packed, feature_id, value),
                )
            )
        return AgentObservation(agent_id=agent_id, tokens=tokens)
