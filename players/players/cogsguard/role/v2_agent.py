"""CogsGuard scripted policy with a tuned default role mix."""

from __future__ import annotations

from typing import Any

from mettagrid.policy.policy_env_interface import PolicyEnvInterface

from .policy import CogsguardPolicy
from .role_mix import default_role_counts as _default_role_counts


class CogsguardV2Agent(CogsguardPolicy):
    """Scripted cogsguard policy with better default role allocation."""

    short_names = ["cogsguard_v2"]

    def __init__(
        self,
        policy_env_info: PolicyEnvInterface,
        device: str = "cpu",
        **vibe_counts: Any,
    ):
        if not any(isinstance(v, int) for v in vibe_counts.values()):
            vibe_counts = {**vibe_counts, **_default_role_counts(policy_env_info.num_agents)}
        super().__init__(policy_env_info, device=device, **vibe_counts)
