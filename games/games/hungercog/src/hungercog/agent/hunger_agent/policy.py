"""Hunger Agent policy — goal-tree scripted agent for the Hunger game.

Agents randomly choose carnivore or herbivore role (can be overridden with
`carnivore_prob` in the policy URI):
  - Herbivore: harvest plant objects, flee from carnivores
  - Carnivore: hunt herbivores, avoid other carnivores (to protect egg)
"""

from __future__ import annotations

import random
from typing import Any

import numpy as np

from mettagrid.mettagrid_c import dtype_actions
from mettagrid.policy.policy import MultiAgentPolicy, StatefulAgentPolicy, StatefulPolicyImpl
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.simulator import Action, ObservationToken
from mettagrid.simulator.interface import AgentObservation

from .entity_map import EntityMap
from .goals import (
    AvoidPredatorGoal,
    ExploreGoal,
    FleeGoal,
    GetGearGoal,
    Goal,
    HarvestGoal,
    HungerContext,
    HuntGoal,
    evaluate_goals,
)
from .navigator import Navigator
from .obs_parser import ObsParser

SPAWN_POS = (100, 100)


def _herbivore_goals() -> list[Goal]:
    return [
        GetGearGoal("herbivore_station", "herbivore"),
        FleeGoal(),
        HarvestGoal(),
        ExploreGoal(),
    ]


def _carnivore_goals() -> list[Goal]:
    return [
        GetGearGoal("carnivore_station", "carnivore"),
        AvoidPredatorGoal(),
        HuntGoal(),
        ExploreGoal(),
    ]


class HungerAgentState:
    def __init__(self, agent_id: int, role: str, goals: list[Goal]) -> None:
        self.agent_id = agent_id
        self.role = role
        self.goals = goals
        self.entity_map = EntityMap()
        self.navigator = Navigator()
        self.blackboard: dict[str, Any] = {}
        self.step = 0


class HungerBrain(StatefulPolicyImpl[HungerAgentState]):
    def __init__(
        self,
        pei: PolicyEnvInterface,
        agent_id: int,
        role: str,
    ) -> None:
        self._agent_id = agent_id
        self._role = role
        self._obs_parser = ObsParser(pei)

    def initial_agent_state(self) -> HungerAgentState:
        goals = _herbivore_goals() if self._role == "herbivore" else _carnivore_goals()
        return HungerAgentState(self._agent_id, self._role, goals)

    def step_with_state(self, obs: AgentObservation, s: HungerAgentState) -> tuple[Action, HungerAgentState]:
        s.step += 1

        state, visible = self._obs_parser.parse(obs, s.step, SPAWN_POS)
        s.entity_map.update_from_observation(
            state.position,
            self._obs_parser.obs_half_h,
            self._obs_parser.obs_half_w,
            visible,
            s.step,
        )

        # Failed move detection
        last_pos = s.blackboard.get("_last_pos")
        last_act = s.blackboard.get("_last_action", "")
        if last_pos and last_act.startswith("move_") and state.position == last_pos:
            fails = s.blackboard.get("_fails", 0) + 1
            s.blackboard["_fails"] = fails
            if fails >= 3:
                s.navigator._cached_path = None
                s.navigator._cached_target = None
            if fails >= 6:
                s.blackboard["_fails"] = 0
        else:
            s.blackboard["_fails"] = 0
        s.blackboard["_last_pos"] = state.position

        ctx = HungerContext(
            state=state,
            map=s.entity_map,
            blackboard=s.blackboard,
            navigator=s.navigator,
            agent_id=self._agent_id,
            step=s.step,
        )

        # Stuck recovery
        fails = s.blackboard.get("_fails", 0)
        if fails >= 6:
            action = s.navigator.explore(
                state.position,
                s.entity_map,
                bias=["north", "east", "south", "west"][self._agent_id % 4],
            )
        else:
            action = evaluate_goals(s.goals, ctx)

        s.blackboard["_last_action"] = action.name
        return action, s


class HungerPolicy(MultiAgentPolicy):
    """Scripted agent for the Hunger game.

    Each agent randomly chooses carnivore or herbivore role based on carnivore_prob.
    URI: metta://policy/hunger_agent?carnivore_prob=0.5
    """

    short_names = ["hunger_agent"]

    def __init__(
        self,
        policy_env_info: PolicyEnvInterface,
        device: str = "cpu",
        carnivore_prob: float = 0.5,
        **kwargs: object,
    ) -> None:
        super().__init__(policy_env_info, device=device)
        self._carnivore_prob = float(carnivore_prob)
        self._feature_by_id = {f.id: f for f in policy_env_info.obs_features}
        self._action_map = policy_env_info.action_name_to_flat_index
        self._noop = dtype_actions.type(self._action_map["noop"])
        self._agents: dict[int, StatefulAgentPolicy[HungerAgentState]] = {}

    def agent_policy(self, agent_id: int) -> StatefulAgentPolicy[HungerAgentState]:
        if agent_id not in self._agents:
            role = "carnivore" if random.random() < self._carnivore_prob else "herbivore"
            brain = HungerBrain(self._policy_env_info, agent_id, role)
            self._agents[agent_id] = StatefulAgentPolicy(brain, self._policy_env_info, agent_id=agent_id)
        return self._agents[agent_id]

    def step_batch(self, raw_obs: np.ndarray, raw_actions: np.ndarray) -> None:
        raw_actions[...] = self._noop
        n = min(raw_obs.shape[0], self._policy_env_info.num_agents)
        for aid in range(n):
            obs = self._raw_to_obs(aid, raw_obs[aid])
            action = self.agent_policy(aid).step(obs)
            raw_actions[aid] = dtype_actions.type(self._action_map[action.name])

    def _raw_to_obs(self, aid: int, raw: np.ndarray) -> AgentObservation:
        tokens: list[ObservationToken] = []
        for tok in raw:
            fid = int(tok[1])
            if fid == 0xFF:
                break
            feat = self._feature_by_id.get(fid)
            if feat is None:
                continue
            tokens.append(
                ObservationToken(
                    feature=feat,
                    value=int(tok[2]),
                    raw_token=(int(tok[0]), fid, int(tok[2])),
                )
            )
        return AgentObservation(agent_id=aid, tokens=tokens)
