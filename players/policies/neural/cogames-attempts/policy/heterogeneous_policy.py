"""Heterogeneous team policy: routes agents to different role checkpoints.

Loads 3 separate LSTM checkpoints (miner, aligner, scrambler) and assigns
roles based on agent_id:
  - agents 0-1: miner
  - agents 2-4: aligner
  - agents 5-7: scrambler

Upload example:
    cogames upload \
      -p 'class=heterogeneous_policy.HeterogeneousTeamPolicy,kw.miner_data=checkpoints/miner.pt,kw.aligner_data=checkpoints/aligner.pt,kw.scrambler_data=checkpoints/scrambler.pt' \
      -f heterogeneous_policy.py -f checkpoints \
      -n kickstarted_team_v1
"""

from __future__ import annotations

from typing import Optional

from mettagrid.policy.lstm import LSTMPolicy
from mettagrid.policy.policy import AgentPolicy, MultiAgentPolicy
from mettagrid.policy.policy_env_interface import PolicyEnvInterface


# Agent-to-role mapping: 2 miners, 3 aligners, 3 scramblers
ROLE_ASSIGNMENTS = {
    0: "miner",
    1: "miner",
    2: "aligner",
    3: "aligner",
    4: "aligner",
    5: "scrambler",
    6: "scrambler",
    7: "scrambler",
}


class HeterogeneousTeamPolicy(MultiAgentPolicy):
    short_names = ["heterogeneous"]

    def __init__(
        self,
        policy_env_info: PolicyEnvInterface,
        device: str = "cpu",
        miner_data: Optional[str] = None,
        aligner_data: Optional[str] = None,
        scrambler_data: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(policy_env_info, device=device)

        self._policies = {}
        for role, data_path in [
            ("miner", miner_data),
            ("aligner", aligner_data),
            ("scrambler", scrambler_data),
        ]:
            policy = LSTMPolicy(policy_env_info, device=device)
            if data_path:
                policy.load_policy_data(data_path)
            self._policies[role] = policy

    def agent_policy(self, agent_id: int) -> AgentPolicy:
        role = ROLE_ASSIGNMENTS.get(agent_id, "aligner")
        return self._policies[role].agent_policy(agent_id)

    def reset(self) -> None:
        for policy in self._policies.values():
            policy.reset()
