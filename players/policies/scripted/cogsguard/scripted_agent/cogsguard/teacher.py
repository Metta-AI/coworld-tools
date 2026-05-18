from __future__ import annotations

from typing import Optional, Sequence

import numpy as np

from policies.scripted.cogsguard.nim_agents.agents import CogsguardAgentsMultiPolicy
from policies.scripted.cogsguard.scripted_agent.cogsguard.types import Role as CogsguardRole
from policies.scripted.cogsguard.scripted_agent.common.roles import ROLE_VIBES
from mettagrid.policy.policy import AgentPolicy, MultiAgentPolicy
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.simulator import Action, AgentObservation

DEFAULT_ROLE_VIBES = tuple(ROLE_VIBES)


class CogsguardTeacherPolicy(MultiAgentPolicy):
    """Teacher wrapper that forces an initial vibe, then delegates to the Nim policy."""

    short_names = ["teacher"]

    def __init__(
        self,
        policy_env_info: PolicyEnvInterface,
        device: str = "cpu",
        role_vibes: Optional[Sequence[str | CogsguardRole] | str] = None,
    ) -> None:
        super().__init__(policy_env_info, device=device)
        self._delegate = CogsguardAgentsMultiPolicy(policy_env_info)
        self._num_agents = policy_env_info.num_agents
        self._action_names = policy_env_info.all_action_names
        self._action_name_to_index = policy_env_info.action_name_to_flat_index
        self._delegate_agents = [self._delegate.agent_policy(i) for i in range(self._num_agents)]

        self._episode_feature_id = self._find_feature_id("episode_completion_pct")
        self._last_action_feature_id = self._find_feature_id("last_action")

        self._role_action_ids = self._resolve_role_actions(role_vibes)
        self._reset_episode_state()

    def agent_policy(self, agent_id: int) -> AgentPolicy:
        return _CogsguardTeacherAgentPolicy(self, agent_id)

    def reset(self) -> None:
        self._delegate.reset()
        self._reset_episode_state()

    def step_batch(self, raw_observations: np.ndarray, raw_actions: np.ndarray) -> None:
        self._delegate.step_batch(raw_observations, raw_actions)
        if not self._role_action_ids:
            return
        if raw_observations.shape[0] != self._num_agents:
            return
        for agent_id in range(self._num_agents):
            episode_pct = self._extract_episode_pct_raw(raw_observations[agent_id])
            last_action = self._extract_last_action_raw(raw_observations[agent_id])
            forced_action = self._maybe_force_action(agent_id, episode_pct, last_action)
            if forced_action is not None:
                raw_actions[agent_id] = forced_action

    def _step_single(self, agent_id: int, obs: AgentObservation) -> Action:
        base_action = self._delegate_agents[agent_id].step(obs)
        if not self._role_action_ids:
            return base_action
        episode_pct = self._extract_episode_pct_obs(obs)
        last_action = self._extract_last_action_obs(obs)
        forced_action = self._maybe_force_action(agent_id, episode_pct, last_action)
        if forced_action is None:
            return base_action
        action_name = self._action_names[forced_action]
        return Action(name=action_name)

    def _extract_episode_pct_raw(self, raw_obs: np.ndarray) -> Optional[int]:
        if self._episode_feature_id is None:
            return None
        for token in raw_obs:
            if token[0] == 255 and token[1] == 255 and token[2] == 255:
                break
            if token[1] == self._episode_feature_id:
                return int(token[2])
        return 0

    def _extract_episode_pct_obs(self, obs: AgentObservation) -> Optional[int]:
        if self._episode_feature_id is None:
            return None
        for token in obs.tokens:
            if token.feature.name == "episode_completion_pct":
                return token.value
        return 0

    def _extract_last_action_raw(self, raw_obs: np.ndarray) -> Optional[int]:
        if self._last_action_feature_id is None:
            return None
        for token in raw_obs:
            if token[0] == 255 and token[1] == 255 and token[2] == 255:
                break
            if token[1] == self._last_action_feature_id:
                return int(token[2])
        return 0

    def _extract_last_action_obs(self, obs: AgentObservation) -> Optional[int]:
        if self._last_action_feature_id is None:
            return None
        for token in obs.tokens:
            if token.feature.name == "last_action":
                return token.value
        return 0

    def _find_feature_id(self, feature_name: str) -> Optional[int]:
        for feature in self.policy_env_info.obs_features:
            if feature.name == feature_name:
                return feature.id
        return None

    def _resolve_role_actions(self, role_vibes: Optional[Sequence[str | CogsguardRole] | str]) -> list[int]:
        change_vibe_actions = [name for name in self._action_names if name.startswith("change_vibe_")]
        if len(change_vibe_actions) <= 1:
            return []

        available_vibes = [name[len("change_vibe_") :] for name in change_vibe_actions]
        if role_vibes is None:
            role_vibes = [vibe for vibe in DEFAULT_ROLE_VIBES if vibe in available_vibes]
            if not role_vibes:
                role_vibes = [vibe for vibe in available_vibes if vibe != "default"]
            if not role_vibes:
                role_vibes = available_vibes
        else:
            if isinstance(role_vibes, str):
                normalized_vibes = [vibe.strip() for vibe in role_vibes.split(",") if vibe.strip()]
            else:
                normalized_vibes = [vibe.value if isinstance(vibe, CogsguardRole) else str(vibe) for vibe in role_vibes]
            role_vibes = [vibe for vibe in normalized_vibes if vibe in available_vibes]
            if not role_vibes:
                role_vibes = available_vibes

        role_action_ids = []
        for vibe_name in role_vibes:
            action_name = f"change_vibe_{vibe_name}"
            role_action_ids.append(self._action_name_to_index[action_name])
        return role_action_ids

    def _reset_episode_state(self) -> None:
        self._episode_index = [0] * self._num_agents
        self._forced_vibe = [False] * self._num_agents
        self._last_episode_pct = [-1] * self._num_agents
        self._step_in_episode = [0] * self._num_agents
        self._last_action_value: list[Optional[int]] = [None] * self._num_agents

    def _maybe_force_action(
        self,
        agent_id: int,
        episode_pct: Optional[int],
        last_action: Optional[int],
    ) -> Optional[int]:
        self._update_episode_state(agent_id, episode_pct, last_action)
        if self._forced_vibe[agent_id] or self._step_in_episode[agent_id] != 0:
            return None
        self._forced_vibe[agent_id] = True
        role_index = (self._episode_index[agent_id] + agent_id) % len(self._role_action_ids)
        return self._role_action_ids[role_index]

    def _update_episode_state(
        self,
        agent_id: int,
        episode_pct: Optional[int],
        last_action: Optional[int],
    ) -> None:
        last_pct = self._last_episode_pct[agent_id]
        if episode_pct is None:
            last_action_seen = self._last_action_value[agent_id]
            if (
                last_action is not None
                and last_action_seen is not None
                and last_action == 0
                and last_action_seen != 0
                and self._step_in_episode[agent_id] > 0
            ):
                self._episode_index[agent_id] += 1
                self._step_in_episode[agent_id] = 0
                self._forced_vibe[agent_id] = False
                self._last_episode_pct[agent_id] = 0
                self._last_action_value[agent_id] = last_action
                return

            if last_pct == -1:
                self._step_in_episode[agent_id] = 0
            else:
                self._step_in_episode[agent_id] += 1
            self._last_episode_pct[agent_id] = 0
            if last_action is not None:
                self._last_action_value[agent_id] = last_action
            return

        new_episode = False
        if last_pct == -1:
            new_episode = True
        elif episode_pct < last_pct:
            new_episode = True
        elif last_pct > 0 and episode_pct == 0:
            new_episode = True

        if new_episode:
            if last_pct != -1:
                self._episode_index[agent_id] += 1
            self._step_in_episode[agent_id] = 0
            self._forced_vibe[agent_id] = False
        else:
            self._step_in_episode[agent_id] += 1

        self._last_episode_pct[agent_id] = episode_pct
        if last_action is not None:
            self._last_action_value[agent_id] = last_action


class _CogsguardTeacherAgentPolicy(AgentPolicy):
    def __init__(self, parent: CogsguardTeacherPolicy, agent_id: int) -> None:
        super().__init__(parent.policy_env_info)
        self._parent = parent
        self._agent_id = agent_id

    def step(self, obs: AgentObservation) -> Action:
        return self._parent._step_single(self._agent_id, obs)
