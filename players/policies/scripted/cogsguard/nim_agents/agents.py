import importlib
import json
import os
import sys
from typing import Sequence

from mettagrid.policy.policy import NimMultiAgentPolicy
from mettagrid.policy.policy_env_interface import PolicyEnvInterface

current_dir = os.path.dirname(os.path.abspath(__file__))
bindings_dir = os.path.join(current_dir, "bindings/generated")
if bindings_dir not in sys.path:
    sys.path.append(bindings_dir)

_na = None


def _nim_agents():
    global _na
    if _na is None:
        try:
            _na = importlib.import_module("nim_agents")
        except (ImportError, OSError):
            # Build the Nim bindings on demand rather than requiring them at import time.
            # This keeps policy discovery cheap while still making `metta://policy/*nim*`
            # URIs usable anywhere the build toolchain is available.
            from policies.scripted.cogsguard.nim_agents.build import build_nim  # noqa: PLC0415

            build_nim()
            _na = importlib.import_module("nim_agents")
    return _na


class _NimAgentsProxy:
    def __getattr__(self, name: str):
        return getattr(_nim_agents(), name)


# Kept for callers/tests that expect `agents.na.<binding>`, but loaded lazily so importing
# this module doesn't require Nim bindings to be present.
na = _NimAgentsProxy()


def start_measure():
    _nim_agents().start_measure()


def end_measure():
    _nim_agents().end_measure()


class ThinkyAgentsMultiPolicy(NimMultiAgentPolicy):
    short_names = ["thinky"]

    def __init__(self, policy_env_info: PolicyEnvInterface, agent_ids: Sequence[int] | None = None):
        super().__init__(
            policy_env_info,
            nim_policy_factory=_nim_agents().ThinkyPolicy,
            agent_ids=agent_ids,
        )


class RandomAgentsMultiPolicy(NimMultiAgentPolicy):
    short_names = ["nim_random"]

    def __init__(self, policy_env_info: PolicyEnvInterface, agent_ids: Sequence[int] | None = None):
        super().__init__(
            policy_env_info,
            nim_policy_factory=_nim_agents().RandomPolicy,
            agent_ids=agent_ids,
        )


class RaceCarAgentsMultiPolicy(NimMultiAgentPolicy):
    short_names = ["race_car"]

    def __init__(self, policy_env_info: PolicyEnvInterface, agent_ids: Sequence[int] | None = None):
        super().__init__(
            policy_env_info,
            nim_policy_factory=_nim_agents().RaceCarPolicy,
            agent_ids=agent_ids,
        )


class CogsguardAgentsMultiPolicy(NimMultiAgentPolicy):
    short_names = ["role_nim"]

    def __init__(
        self,
        policy_env_info: PolicyEnvInterface,
        agent_ids: Sequence[int] | None = None,
        **_: object,
    ):
        super().__init__(
            policy_env_info,
            nim_policy_factory=_nim_agents().CogsguardPolicy,
            agent_ids=agent_ids,
        )


class CogsguardAlignAllAgentsMultiPolicy(NimMultiAgentPolicy):
    short_names = ["alignall"]

    def __init__(
        self,
        policy_env_info: PolicyEnvInterface,
        agent_ids: Sequence[int] | None = None,
        **_: object,
    ):
        super().__init__(
            policy_env_info,
            nim_policy_factory=_nim_agents().CogsguardAlignAllPolicy,
            agent_ids=agent_ids,
        )


class NlankyAgentsMultiPolicy(NimMultiAgentPolicy):
    short_names = ["nlanky"]

    def __init__(
        self,
        policy_env_info: PolicyEnvInterface,
        device: str = "cpu",
        agent_ids: Sequence[int] | None = None,
        miner: int | str = -1,
        scout: int | str = 0,
        aligner: int | str = -1,
        scrambler: int | str = -1,
        stem: int | str = 0,
        trace: int | str = 0,
        trace_level: int | str = 1,
        trace_agent: int | str = -1,
        bio: int | str = 0,
        stats: int | str = 0,
        disable_role_switching: bool | int | str = 0,
        **_: object,
    ):
        # `cogames play -p "... kw.foo=1"` passes strings; be robust and coerce.
        int(bio)
        int(stats)
        if isinstance(disable_role_switching, str):
            value = disable_role_switching.strip().lower()
            if value in {"1", "true", "t", "yes", "y", "on"}:
                disable_role_switching = True
            elif value in {"0", "false", "f", "no", "n", "off", ""}:
                disable_role_switching = False
        nlanky_config = {
            "miner": int(miner),
            "scout": int(scout),
            "aligner": int(aligner),
            "scrambler": int(scrambler),
            "stem": int(stem),
            "trace": int(trace),
            "traceLevel": int(trace_level),
            "traceAgent": int(trace_agent),
            "disableRoleSwitching": bool(disable_role_switching),
        }

        super().__init__(
            policy_env_info,
            nim_policy_factory=lambda env_json: _nim_agents().NlankyPolicy(
                json.dumps({"env": json.loads(env_json), "nlanky": nlanky_config})
            ),
            agent_ids=agent_ids,
            device=device,
        )
