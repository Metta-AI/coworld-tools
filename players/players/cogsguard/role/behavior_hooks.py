from __future__ import annotations

from typing import Callable

from mettagrid.simulator import Action

from .policy import CogsguardMultiRoleImpl
from .types import CogsguardAgentState, Role

BehaviorHook = Callable[[CogsguardAgentState], Action]


def build_cogsguard_behavior_hooks(policy: CogsguardMultiRoleImpl) -> dict[str, BehaviorHook]:
    """Bind evolutionary behavior names to existing role implementations.

    These hooks are not wired into the live policy yet, but they allow the
    evolutionary coordinator to execute real behavior logic when integrated.
    """
    miner = policy._get_role_impl(Role.MINER)
    scout = policy._get_role_impl(Role.SCOUT)
    aligner = policy._get_role_impl(Role.ALIGNER)
    scrambler = policy._get_role_impl(Role.SCRAMBLER)

    def _discover_with_scout(s: CogsguardAgentState) -> Action:
        return scout.execute_role(s)

    def _get_influence(s: CogsguardAgentState) -> Action:
        return aligner._get_resources(s, need_heart=False)

    return {
        "explore": policy._explore,
        "recharge": policy._do_recharge,
        "mine_resource": miner._do_gather,
        "deposit_resource": miner._do_deposit,
        "find_extractor": miner._do_gather,
        "discover_stations": _discover_with_scout,
        "discover_extractors": _discover_with_scout,
        "discover_junctions": _discover_with_scout,
        "get_hearts": scrambler._get_hearts,
        "get_influence": _get_influence,
        "align_junction": aligner.execute_role,
        "scramble_junction": scrambler.execute_role,
        "find_enemy_junction": scrambler.execute_role,
    }
