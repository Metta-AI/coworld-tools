"""Test policy to debug territory/HP mechanics."""
from __future__ import annotations
import sys
from mettagrid.policy.policy import MultiAgentPolicy, AgentPolicy
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.simulator import Action
from mettagrid.simulator.interface import AgentObservation

class NoopTestPolicy(MultiAgentPolicy):
    short_names = ["nooptest"]
    def __init__(self, policy_env_info: PolicyEnvInterface, device: str = "cpu", **kw):
        super().__init__(policy_env_info, device=device, **kw)
        self._agents: dict[int, _TestAgent] = {}
    def agent_policy(self, aid: int) -> AgentPolicy:
        if aid not in self._agents:
            self._agents[aid] = _TestAgent(self._policy_env_info, aid)
        return self._agents[aid]

class _TestAgent(AgentPolicy):
    def __init__(self, pei: PolicyEnvInterface, aid: int):
        self._pei = pei
        self._aid = aid
        self._c = (pei.obs_height // 2, pei.obs_width // 2)
        self._step = 0
        self._infos: dict = {}

    def _inv(self, obs: AgentObservation) -> dict[str, int]:
        items: dict[str, int] = {}
        for t in obs.tokens:
            if t.location != self._c:
                continue
            if t.feature.name.startswith("inv:"):
                suf = t.feature.name[4:]
                name, sep, pstr = suf.rpartition(":p")
                if not sep:
                    name = suf
                    p = 0
                else:
                    p = int(pstr) if pstr.isdigit() else 0
                v = int(t.value)
                if v > 0:
                    b = max(int(t.feature.normalization), 1)
                    items[name] = items.get(name, 0) + v * (b ** p)
        return items

    def step(self, obs: AgentObservation) -> Action:
        self._step += 1
        items = self._inv(obs)
        hp = items.get("hp", 0)
        energy = items.get("energy", 0)

        # Agent 0: noop always (stays on hub)
        # Agent 1: move south once then noop
        # Agent 2: move south twice then noop
        # Agent 3: move south 5 times then noop
        # Agent 4: move south 10 times then noop
        # Agent 5: move south 15 times then noop
        # Agent 6: move south 20 times then noop
        # Agent 7: move south 25 times then noop
        move_steps = [0, 1, 2, 5, 10, 15, 20, 25][self._aid]

        if self._step <= 60 and self._step % 5 == 0:
            print(f"[TEST] a={self._aid} s={self._step} hp={hp} energy={energy} moved={min(self._step-1, move_steps)}", file=sys.stderr)

        if self._step <= move_steps:
            return Action(name="move_south")
        return Action(name="noop")

    def reset(self) -> None:
        self._step = 0
