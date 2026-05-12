"""CogletAgentPolicy: optimized heuristic overrides for CvcEngine.

Extends CvcEngine with:
- Resource-aware macro directives (mine least-available resource, LLM override)
- Phase-based pressure budgets (aligner/scrambler allocation over time)
- Miner safety retreat logic
"""

from __future__ import annotations

from cogamer.cvc.agent import KnownEntity, absolute_position, manhattan
from cogamer.cvc.agent.main import CvcEngine
from mettagrid.sdk.agent import MacroDirective, MettagridState

_ELEMENTS = ("carbon", "oxygen", "germanium", "silicon")
_MINER_MAX_HUB_DISTANCE = 15


def _shared_resources(state: MettagridState) -> dict[str, int]:
    if state.team_summary is None:
        return {r: 0 for r in _ELEMENTS}
    return {r: int(state.team_summary.shared_inventory.get(r, 0)) for r in _ELEMENTS}


def _least_resource(resources: dict[str, int]) -> str:
    return min(_ELEMENTS, key=lambda r: resources[r])


class CogletAgentPolicy(CvcEngine):
    """Per-agent policy with optimized heuristics.

    Key improvements over base CvcEngine:
    - Resource-aware macro directives (mine least-available resource)
    - LLM resource_bias override via _llm_resource_bias attribute
    - Implicit teammate coordination via team_summary positions
    - Extra retreat safety for miners far from hub
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Set by CogletPolicyImpl when LLM provides guidance
        self._llm_resource_bias: str | None = None

    def _macro_directive(self, state: MettagridState) -> MacroDirective:
        # LLM override takes priority
        if self._llm_resource_bias and self._llm_resource_bias in _ELEMENTS:
            return MacroDirective(resource_bias=self._llm_resource_bias)
        # Fallback: mine least-available resource
        resources = _shared_resources(state)
        least = _least_resource(resources)
        return MacroDirective(resource_bias=least)

    def _pressure_budgets(self, state: MettagridState, *, objective: str | None = None) -> tuple[int, int]:
        step = state.step or self._step_index
        if objective == "resource_coverage":
            return 0, 0
        if objective == "economy_bootstrap":
            return 2, 0
        # Base budgets (tuned for 8 agents)
        if step < 10:
            return 2, 0
        if step < 300:
            return 5, 0
        return 4, 1

    def _should_retreat(self, state: MettagridState, role: str, safe_target: KnownEntity | None) -> bool:
        if super()._should_retreat(state, role, safe_target):
            return True
        if role == "miner" and safe_target is not None:
            pos = absolute_position(state)
            dist = manhattan(pos, safe_target.position)
            hp = int(state.self_state.inventory.get("hp", 0))
            if dist > _MINER_MAX_HUB_DISTANCE and hp < dist + 10:
                return True
        return False
