"""PufferLib policy wrapper for the Tribal Village environment."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Sequence

import torch
from gymnasium import spaces

import pufferlib.models  # type: ignore[import-untyped]
import pufferlib.pytorch  # type: ignore[import-untyped]
from mettagrid.policy.policy import AgentPolicy, MultiAgentPolicy
from mettagrid.simulator import Action, Simulation

from tribal_village_env.config import (
    DEFAULT_HIDDEN_SIZE,
    OBS_NORMALIZATION_FACTOR,
)


@dataclass
class TribalPolicyEnvInfo:
    """Minimal environment metadata required by MultiAgentPolicy."""

    observation_space: spaces.Box
    action_space: spaces.Discrete
    num_agents: int

    @property
    def actions(self) -> list[SimpleNamespace]:
        """Adapter expected by MultiAgentPolicy/PolicyEnvInterface."""

        return [
            SimpleNamespace(name=f"action_{idx}")
            for idx in range(self.action_space.n)
        ]


class TribalVillagePufferPolicy(MultiAgentPolicy, AgentPolicy):
    """Trainable policy using PufferLib's default model for Tribal Village."""

    short_names = ["tribal", "tribal_default", "tribal_puffer"]

    def __init__(
        self,
        policy_env_info: TribalPolicyEnvInfo,
        *,
        hidden_size: int = DEFAULT_HIDDEN_SIZE,
        device: str | torch.device | None = None,
    ) -> None:
        MultiAgentPolicy.__init__(self, policy_env_info)
        AgentPolicy.__init__(self, policy_env_info)

        shim_env = SimpleNamespace(
            single_observation_space=policy_env_info.observation_space,
            single_action_space=policy_env_info.action_space,
            observation_space=policy_env_info.observation_space,
            action_space=policy_env_info.action_space,
            num_agents=policy_env_info.num_agents,
        )
        shim_env.env = shim_env

        self._net = pufferlib.models.Default(shim_env, hidden_size=hidden_size)  # type: ignore[arg-type]
        if device is not None:
            self._net = self._net.to(torch.device(device))

        self._action_names = [
            f"action_{idx}" for idx in range(policy_env_info.action_space.n)
        ]
        self._num_actions = len(self._action_names)
        self._device = next(self._net.parameters()).device

    def network(self) -> torch.nn.Module:  # type: ignore[override]
        return self._net

    def agent_policy(self, agent_id: int) -> AgentPolicy:  # type: ignore[override]
        return self

    def is_recurrent(self) -> bool:
        return False

    def reset(self, simulation: Simulation | None = None) -> None:  # type: ignore[override]
        return None

    def load_policy_data(self, policy_data_path: str) -> None:
        state = torch.load(policy_data_path, map_location=self._device)
        self._net.load_state_dict(state)
        self._net = self._net.to(self._device)

    def save_policy_data(self, policy_data_path: str) -> None:
        torch.save(self._net.state_dict(), policy_data_path)

    def step(self, obs: torch.Tensor | Sequence[Any]) -> Action:  # type: ignore[override]
        obs_tensor = torch.as_tensor(obs, device=self._device, dtype=torch.float32)

        if obs_tensor.ndim == len(self.policy_env_info.observation_space.shape):
            obs_tensor = obs_tensor.unsqueeze(0)

        obs_tensor = obs_tensor * OBS_NORMALIZATION_FACTOR

        with torch.no_grad():
            self._net.eval()
            logits, _ = self._net.forward_eval(obs_tensor)
            sampled, _, _ = pufferlib.pytorch.sample_logits(logits)

        action_idx = int(sampled.item()) % max(1, self._num_actions)
        return Action(name=self._action_names[action_idx])
